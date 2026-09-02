"""Adversarial regression for durable job artifact-hash restart contract."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.job_store import DurableJobRecord, SQLiteJobRepository
from runtime.queue import RunManager, RunQueueStatus


class _RestoreOnlyRuntime:
    """Runtime stub: this test exercises durable restore only, never dispatch."""


class TestJobArtifactHashRestartContractV1(unittest.TestCase):
    def test_completed_job_artifact_hash_survives_fresh_manager_restart(self) -> None:
        expected_hash = "a" * 64
        run_id = "RUN-ARTIFACT-HASH-RESTART-001"
        now = datetime.now(timezone.utc).isoformat()

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite3"

            repo = SQLiteJobRepository(db_path)
            repo.create_job(
                DurableJobRecord(
                    run_id=run_id,
                    objective="preserve durable artifact identity",
                    business_id="BIZ-ARTIFACT-HASH",
                    status=RunQueueStatus.COMPLETED.value,
                    created_at=now,
                    started_at=now,
                    completed_at=now,
                    artifact_hash=expected_hash,
                    attempt_count=1,
                )
            )
            persisted_before_restart = repo.get_job(run_id)
            self.assertIsNotNone(persisted_before_restart)
            self.assertEqual(persisted_before_restart.artifact_hash, expected_hash)
            repo.close()

            reopened_repo = SQLiteJobRepository(db_path)
            manager = RunManager(
                _RestoreOnlyRuntime(),
                max_workers=0,
                job_repository=reopened_repo,
            )
            try:
                restored = manager.get_run(run_id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.status, RunQueueStatus.COMPLETED)

                # This is the same public QueueItem wire representation consumed by
                # the queue run/list API endpoints. Durable identity must not vanish
                # merely because the in-memory DepartmentRunArtifact died with the
                # previous process.
                self.assertEqual(
                    restored.model_dump()["artifact_hash"],
                    expected_hash,
                    "completed durable job must preserve artifact_hash across a fresh manager restart",
                )

                listed = {item.run_id: item.model_dump() for item in manager.list_runs()}
                self.assertEqual(listed[run_id]["artifact_hash"], expected_hash)

                persisted_after_restart = reopened_repo.get_job(run_id)
                self.assertIsNotNone(persisted_after_restart)
                self.assertEqual(persisted_after_restart.artifact_hash, expected_hash)
            finally:
                manager.shutdown()
                reopened_repo.close()


if __name__ == "__main__":
    unittest.main()
