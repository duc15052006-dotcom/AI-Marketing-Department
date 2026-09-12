"""Platform Batch #8 tests for durable job state and safe restart recovery."""

from __future__ import annotations

import itertools
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from runtime.context import (
    ApprovalState,
    ExecutionCheckpoint,
    RunIdAlreadyExistsError,
    RuntimeStage,
    RuntimeStatus,
)
from runtime.job_store import (
    DurableJobRecord,
    JobStoreIntegrityError,
    SQLiteJobRepository,
)
from runtime.queue import RunManager, RunQueueStatus


class DurableStubRuntime:
    def __init__(
        self,
        *,
        execute_status: RuntimeStatus = RuntimeStatus.COMPLETED,
        execute_error: Optional[str] = None,
    ) -> None:
        self._counter = itertools.count(1)
        self._reserved = set()
        self._active_contexts = {}
        self.started = []
        self.cancelled = []
        self.execute_status = execute_status
        self.execute_error = execute_error

    def is_reserved_run_id(self, run_id: str) -> bool:
        return run_id in self._reserved

    def reserve_run_id(self, custom_id: Optional[str] = None, trusted: bool = False) -> str:
        del trusted
        run_id = custom_id or f"RUN-DURABLE-{next(self._counter):04d}"
        if run_id in self._reserved:
            raise RunIdAlreadyExistsError(f"RUN_ID_ALREADY_EXISTS: {run_id}")
        self._reserved.add(run_id)
        return run_id

    def get_active_context(self, run_id: str):
        return self._active_contexts.get(run_id)

    def start_run(
        self,
        *,
        objective: str,
        business_id: str,
        project_id=None,
        chat_id=None,
        reserved_run_id: str,
    ):
        del objective, business_id, project_id, chat_id
        ctx = SimpleNamespace(status=RuntimeStatus.RUNNING, checkpoints=[])
        self._active_contexts[reserved_run_id] = ctx
        self.started.append(reserved_run_id)
        return ctx

    def execute_run(self, ctx):
        if self.execute_error:
            raise RuntimeError(self.execute_error)
        ctx.status = self.execute_status
        return ctx, {"status": self.execute_status.value}, None

    def cancel_run(self, run_id: str) -> bool:
        self.cancelled.append(run_id)
        ctx = self._active_contexts.get(run_id)
        if ctx is not None:
            ctx.status = RuntimeStatus.CANCELLED
        return True


class TestPlatformJobDurabilityRecoveryV1(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "jobs.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _wait_for_status(manager: RunManager, run_id: str, status: RunQueueStatus, timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = manager.get_run(run_id)
            if item is not None and item.status == status:
                return item
            time.sleep(0.01)
        item = manager.get_run(run_id)
        raise AssertionError(f"run {run_id} did not reach {status}; final={getattr(item, 'status', None)}")

    @staticmethod
    def _record(run_id: str, status: str = "QUEUED", *, error: Optional[str] = None) -> DurableJobRecord:
        now = datetime.now(timezone.utc).isoformat()
        return DurableJobRecord(
            run_id=run_id,
            objective="durable objective",
            business_id="BIZ-DURABLE",
            status=status,
            created_at=now,
            started_at=now if status not in {"QUEUED"} else None,
            error=error,
        )

    def test_repository_survives_reopen_and_detects_record_tampering(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        saved = repo.create_job(self._record("RUN-STORE-001"))
        self.assertTrue(saved.verify_integrity())
        repo.close()

        reopened = SQLiteJobRepository(self.db_path)
        loaded = reopened.get_job("RUN-STORE-001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.objective, "durable objective")
        reopened.close()

        raw = sqlite3.connect(str(self.db_path))
        raw.execute("UPDATE jobs SET objective='tampered objective' WHERE run_id='RUN-STORE-001'")
        raw.commit()
        raw.close()

        tampered = SQLiteJobRepository(self.db_path)
        with self.assertRaisesRegex(JobStoreIntegrityError, "JOB_RECORD_INTEGRITY_MISMATCH"):
            tampered.get_job("RUN-STORE-001")
        tampered.close()

    def test_checkpoint_is_immutable_integrity_checked_and_secret_sanitized(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        repo.create_job(self._record("RUN-CHK-001"))
        checkpoint = ExecutionCheckpoint(
            run_id="RUN-CHK-001",
            business_id="BIZ-DURABLE",
            stage=RuntimeStage.PERFORMANCE,
            status=RuntimeStatus.WAITING_FOR_APPROVAL,
            completed_stages=["cmo_initial", "intelligence"],
            receipt_ids=["EXEC-001"],
            approval_state=ApprovalState.PENDING_APPROVAL,
            pending_approval_id="PENDING-APPROVAL-001",
            working_state_snapshot={
                "safe": "keep",
                "api_key": "must-not-persist",
                "diagnostic": "Authorization: Bearer checkpoint-secret-123456",
            },
        )
        checkpoint.checkpoint_hash = checkpoint.calculate_checkpoint_hash()

        self.assertTrue(repo.append_checkpoint(checkpoint))
        self.assertFalse(repo.append_checkpoint(checkpoint))
        payloads = repo.list_checkpoints("RUN-CHK-001")
        self.assertEqual(len(payloads), 1)
        payload_text = str(payloads[0])
        self.assertNotIn("must-not-persist", payload_text)
        self.assertNotIn("checkpoint-secret-123456", payload_text)
        self.assertEqual(payloads[0]["working_state_snapshot"]["safe"], "keep")
        repo.close()

    def test_completed_job_persists_and_restores_as_history_without_dispatch(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        runtime = DurableStubRuntime(execute_status=RuntimeStatus.COMPLETED)
        manager = RunManager(runtime, max_workers=1, job_repository=repo)
        item = manager.enqueue_run("complete once", run_id="RUN-COMPLETE-001", business_id="BIZ-DURABLE")
        completed = self._wait_for_status(manager, item.run_id, RunQueueStatus.COMPLETED)
        self.assertEqual(completed.attempt_count, 1)
        persisted = repo.get_job(item.run_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, "COMPLETED")
        self.assertEqual(persisted.attempt_count, 1)
        manager.shutdown()
        repo.close()

        repo2 = SQLiteJobRepository(self.db_path)
        runtime2 = DurableStubRuntime()
        manager2 = RunManager(runtime2, max_workers=1, job_repository=repo2)
        restored = manager2.get_run(item.run_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, RunQueueStatus.COMPLETED)
        self.assertEqual(runtime2.started, [])
        manager2.shutdown()
        repo2.close()

    def test_interrupted_running_job_becomes_recovery_required_not_auto_retried(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        repo.create_job(self._record("RUN-CRASH-001", "RUNNING"))
        repo.close()

        repo2 = SQLiteJobRepository(self.db_path)
        runtime = DurableStubRuntime()
        manager = RunManager(runtime, max_workers=1, job_repository=repo2)
        recovered = manager.get_run("RUN-CRASH-001")
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.status, RunQueueStatus.RECOVERY_REQUIRED)
        self.assertIn("previous_status=RUNNING", recovered.recovery_reason or "")
        self.assertEqual(runtime.started, [])
        self.assertEqual(manager.get_queue_stats()["recovery_required_runs"], 1)
        self.assertEqual(repo2.get_job("RUN-CRASH-001").status, "RECOVERY_REQUIRED")
        manager.shutdown()
        repo2.close()

    def test_even_previously_queued_job_is_not_blindly_replayed_after_restart(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        repo.create_job(self._record("RUN-QUEUED-CRASH-001", "QUEUED"))
        repo.close()

        repo2 = SQLiteJobRepository(self.db_path)
        runtime = DurableStubRuntime()
        manager = RunManager(runtime, max_workers=1, job_repository=repo2)
        recovered = manager.get_run("RUN-QUEUED-CRASH-001")
        self.assertEqual(recovered.status, RunQueueStatus.RECOVERY_REQUIRED)
        time.sleep(0.05)
        self.assertEqual(runtime.started, [])
        manager.shutdown()
        repo2.close()

    def test_recovery_resolution_closes_old_run_but_never_reuses_same_run_id(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        repo.create_job(self._record("RUN-RECOVERY-001", "RUNNING"))
        repo.close()

        repo2 = SQLiteJobRepository(self.db_path)
        manager = RunManager(DurableStubRuntime(), max_workers=0, job_repository=repo2)
        self.assertTrue(
            manager.resolve_recovery(
                "RUN-RECOVERY-001",
                RunQueueStatus.FAILED,
                note="Operator reconciled external state; retry requires a new run.",
            )
        )
        item = manager.get_run("RUN-RECOVERY-001")
        self.assertEqual(item.status, RunQueueStatus.FAILED)
        self.assertIsNotNone(item.completed_at)
        self.assertEqual(repo2.get_job("RUN-RECOVERY-001").status, "FAILED")

        with self.assertRaises(RunIdAlreadyExistsError):
            manager.enqueue_run("do not reuse", run_id="RUN-RECOVERY-001")
        manager.shutdown()
        repo2.close()

    def test_waiting_approval_is_persisted_but_requires_reconciliation_after_restart(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        runtime = DurableStubRuntime(execute_status=RuntimeStatus.WAITING_FOR_APPROVAL)
        manager = RunManager(runtime, max_workers=1, job_repository=repo)
        item = manager.enqueue_run("approval workflow", run_id="RUN-APPROVAL-001")
        waiting = self._wait_for_status(manager, item.run_id, RunQueueStatus.WAITING_APPROVAL)
        self.assertIsNone(waiting.completed_at)
        self.assertEqual(repo.get_job(item.run_id).status, "WAITING_APPROVAL")
        manager.shutdown(cancel_pending=False)
        repo.close()

        repo2 = SQLiteJobRepository(self.db_path)
        runtime2 = DurableStubRuntime()
        manager2 = RunManager(runtime2, max_workers=1, job_repository=repo2)
        recovered = manager2.get_run(item.run_id)
        self.assertEqual(recovered.status, RunQueueStatus.RECOVERY_REQUIRED)
        self.assertIn("previous_status=WAITING_APPROVAL", recovered.recovery_reason or "")
        self.assertEqual(runtime2.started, [])
        manager2.shutdown()
        repo2.close()

    def test_persisted_worker_error_is_secret_safe(self) -> None:
        secret = "durability-secret-token-123456"
        key = "durability-key-999999"
        repo = SQLiteJobRepository(self.db_path)
        runtime = DurableStubRuntime(
            execute_error=f"Authorization: Bearer {secret} api_key={key}"
        )
        manager = RunManager(runtime, max_workers=1, job_repository=repo)
        item = manager.enqueue_run("safe failure", run_id="RUN-SECRET-DURABLE-001")
        failed = self._wait_for_status(manager, item.run_id, RunQueueStatus.FAILED)
        persisted = repo.get_job(item.run_id)
        self.assertNotIn(secret, failed.error or "")
        self.assertNotIn(key, failed.error or "")
        self.assertNotIn(secret, persisted.error or "")
        self.assertNotIn(key, persisted.error or "")
        manager.shutdown()
        repo.close()

    def test_durable_duplicate_history_blocks_explicit_run_id_before_dispatch(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        repo.create_job(self._record("RUN-HISTORY-001", "COMPLETED"))
        runtime = DurableStubRuntime()
        manager = RunManager(runtime, max_workers=0, job_repository=repo)

        with self.assertRaises(RunIdAlreadyExistsError):
            manager.enqueue_run("duplicate", run_id="RUN-HISTORY-001")
        self.assertEqual(runtime.started, [])
        manager.shutdown()
        repo.close()


if __name__ == "__main__":
    unittest.main()
