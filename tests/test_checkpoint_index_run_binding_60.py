"""Adversarial regression for durable checkpoint row/payload binding."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.context import ExecutionCheckpoint, RuntimeStage, RuntimeStatus
from runtime.job_store import DurableJobRecord, JobStoreIntegrityError, SQLiteJobRepository


class TestCheckpointIndexRunBinding60(unittest.TestCase):
    @staticmethod
    def _job(run_id: str, business_id: str) -> DurableJobRecord:
        now = datetime.now(timezone.utc).isoformat()
        return DurableJobRecord(
            run_id=run_id,
            objective=f"objective for {run_id}",
            business_id=business_id,
            status="COMPLETED",
            created_at=now,
            completed_at=now,
        )

    @staticmethod
    def _checkpoint(run_id: str, business_id: str) -> ExecutionCheckpoint:
        checkpoint = ExecutionCheckpoint(
            run_id=run_id,
            business_id=business_id,
            stage=RuntimeStage.PERFORMANCE,
            status=RuntimeStatus.COMPLETED,
            completed_stages=["cmo_initial", "intelligence", "strategist", "creative", "performance"],
            working_state_snapshot={"marker": f"ONLY-{business_id}"},
        )
        checkpoint.checkpoint_hash = checkpoint.calculate_checkpoint_hash()
        return checkpoint

    def test_checkpoint_run_index_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite3"
            repo = SQLiteJobRepository(db_path)
            repo.create_job(self._job("RUN-A", "BIZ-A"))
            repo.create_job(self._job("RUN-B", "BIZ-B"))
            checkpoint = self._checkpoint("RUN-A", "BIZ-A")
            repo.append_checkpoint(checkpoint)
            repo.close()

            raw = sqlite3.connect(str(db_path))
            raw.execute(
                "UPDATE job_checkpoints SET run_id=? WHERE checkpoint_id=?",
                ("RUN-B", checkpoint.checkpoint_id),
            )
            raw.commit()
            raw.close()

            reopened = SQLiteJobRepository(db_path)
            with self.assertRaisesRegex(JobStoreIntegrityError, "CHECKPOINT_INDEX_METADATA_MISMATCH"):
                reopened.list_checkpoints("RUN-B")
            reopened.close()

    def test_untampered_checkpoint_roundtrip_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite3"
            repo = SQLiteJobRepository(db_path)
            repo.create_job(self._job("RUN-A", "BIZ-A"))
            checkpoint = self._checkpoint("RUN-A", "BIZ-A")
            repo.append_checkpoint(checkpoint)

            payloads = repo.list_checkpoints("RUN-A")
            self.assertEqual(len(payloads), 1)
            self.assertEqual(payloads[0]["run_id"], "RUN-A")
            self.assertEqual(payloads[0]["business_id"], "BIZ-A")
            self.assertEqual(payloads[0]["working_state_snapshot"]["marker"], "ONLY-BIZ-A")
            repo.close()


if __name__ == "__main__":
    unittest.main()
