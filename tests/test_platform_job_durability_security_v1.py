"""Security regressions for Platform Batch #8 durable job storage."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.job_store import DurableJobRecord, JobStoreError, SQLiteJobRepository
from runtime.queue import RunManager, RunQueueStatus


class TestPlatformJobDurabilitySecurityV1(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "jobs.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _record(
        objective: str,
        *,
        run_id: str = "RUN-DURABILITY-SECURITY-001",
        status: str = "QUEUED",
    ) -> DurableJobRecord:
        now = datetime.now(timezone.utc).isoformat()
        return DurableJobRecord(
            run_id=run_id,
            objective=objective,
            business_id="BIZ-SECURITY",
            status=status,
            created_at=now,
            started_at=now if status != "QUEUED" else None,
        )

    def test_objective_secrets_are_redacted_before_hash_and_persistence(self) -> None:
        bearer = "objective-bearer-secret-123456"
        api_key = "objective-api-key-654321"
        repo = SQLiteJobRepository(self.db_path)
        saved = repo.create_job(
            self._record(f"Audit Authorization: Bearer {bearer} api_key={api_key}")
        )

        self.assertNotIn(bearer, saved.objective)
        self.assertNotIn(api_key, saved.objective)
        self.assertTrue(saved.verify_integrity())
        repo.close()

        raw = sqlite3.connect(str(self.db_path))
        objective = raw.execute(
            "SELECT objective FROM jobs WHERE run_id=?",
            ("RUN-DURABILITY-SECURITY-001",),
        ).fetchone()[0]
        raw.close()
        self.assertNotIn(bearer, objective)
        self.assertNotIn(api_key, objective)

    def test_closed_database_write_is_translated_to_job_store_error(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        saved = repo.create_job(self._record("safe objective"))
        repo.close()

        with self.assertRaisesRegex(JobStoreError, "JOB_STORE_SAVE_FAILED"):
            repo.save_job(saved)

    def test_failed_recovery_persistence_rolls_back_in_memory_resolution(self) -> None:
        run_id = "RUN-RECOVERY-PERSIST-FAIL-001"
        repo = SQLiteJobRepository(self.db_path)
        repo.create_job(
            self._record(
                "recovery objective",
                run_id=run_id,
                status="RUNNING",
            )
        )
        manager = RunManager(object(), max_workers=0, job_repository=repo)
        item = manager.get_run(run_id)
        self.assertIsNotNone(item)
        self.assertEqual(item.status, RunQueueStatus.RECOVERY_REQUIRED)
        original_reason = item.recovery_reason

        repo.close()
        with self.assertRaisesRegex(JobStoreError, "JOB_STORE_SAVE_FAILED"):
            manager.resolve_recovery(
                run_id,
                RunQueueStatus.FAILED,
                note="operator decision must not appear committed",
            )

        restored_in_memory = manager.get_run(run_id)
        self.assertEqual(restored_in_memory.status, RunQueueStatus.RECOVERY_REQUIRED)
        self.assertIsNone(restored_in_memory.completed_at)
        self.assertEqual(restored_in_memory.recovery_reason, original_reason)
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
