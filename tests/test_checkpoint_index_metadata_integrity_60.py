"""Adversarial regressions for durable checkpoint row metadata integrity."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeStage, RuntimeStatus
from runtime.job_store import DurableJobRecord, JobStoreIntegrityError, SQLiteJobRepository


class TestCheckpointIndexMetadataIntegrity60(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "jobs.sqlite3"
        self.repo = SQLiteJobRepository(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        for run_id in ("RUN-CHK-META-A", "RUN-CHK-META-B"):
            self.repo.create_job(
                DurableJobRecord(
                    run_id=run_id,
                    objective="checkpoint metadata integrity",
                    business_id="BIZ-CHK-META",
                    status="RUNNING",
                    created_at=now,
                    started_at=now,
                )
            )

    def tearDown(self) -> None:
        self.repo.close()
        self.tmp.cleanup()

    def _append_checkpoint(self, suffix: str) -> ExecutionCheckpoint:
        checkpoint = ExecutionCheckpoint(
            checkpoint_id=f"CHKPT-META-{suffix}",
            run_id="RUN-CHK-META-A",
            business_id="BIZ-CHK-META",
            stage=RuntimeStage.PERFORMANCE,
            status=RuntimeStatus.WAITING_FOR_APPROVAL,
            completed_stages=["cmo_initial", "intelligence"],
            receipt_ids=[f"EXEC-{suffix}"],
            approval_state=ApprovalState.PENDING_APPROVAL,
            pending_approval_id=f"APPROVAL-{suffix}",
            working_state_snapshot={"safe": "value"},
        )
        checkpoint.checkpoint_hash = checkpoint.calculate_checkpoint_hash()
        self.assertTrue(self.repo.append_checkpoint(checkpoint))
        return checkpoint

    def _tamper(self, sql: str, params: tuple[object, ...]) -> None:
        raw = sqlite3.connect(str(self.db_path))
        raw.execute("PRAGMA foreign_keys=ON")
        raw.execute(sql, params)
        raw.commit()
        raw.close()

    def _clear_checkpoints(self) -> None:
        raw = sqlite3.connect(str(self.db_path))
        raw.execute("DELETE FROM job_checkpoints")
        raw.commit()
        raw.close()

    def test_tampered_redundant_metadata_cannot_be_trusted_over_hashed_payload(self) -> None:
        cases = (
            (
                "run_id",
                "RUN",
                "UPDATE job_checkpoints SET run_id=? WHERE checkpoint_id=?",
                lambda checkpoint: ("RUN-CHK-META-B", checkpoint.checkpoint_id),
                "RUN-CHK-META-B",
            ),
            (
                "checkpoint_id",
                "ID",
                "UPDATE job_checkpoints SET checkpoint_id=? WHERE checkpoint_id=?",
                lambda checkpoint: (f"{checkpoint.checkpoint_id}-TAMPERED", checkpoint.checkpoint_id),
                "RUN-CHK-META-A",
            ),
            (
                "checkpoint_hash",
                "HASH",
                "UPDATE job_checkpoints SET checkpoint_hash=? WHERE checkpoint_id=?",
                lambda checkpoint: ("0" * 64, checkpoint.checkpoint_id),
                "RUN-CHK-META-A",
            ),
            (
                "created_at",
                "TIME",
                "UPDATE job_checkpoints SET created_at=? WHERE checkpoint_id=?",
                lambda checkpoint: ("1970-01-01T00:00:00+00:00", checkpoint.checkpoint_id),
                "RUN-CHK-META-A",
            ),
        )

        for field, suffix, sql, params_for, query_run_id in cases:
            with self.subTest(field=field):
                checkpoint = self._append_checkpoint(suffix)
                self._tamper(sql, params_for(checkpoint))
                try:
                    with self.assertRaisesRegex(
                        JobStoreIntegrityError,
                        rf"CHECKPOINT_METADATA_INTEGRITY_MISMATCH: .*field={field}",
                    ):
                        self.repo.list_checkpoints(query_run_id)
                finally:
                    self._clear_checkpoints()


if __name__ == "__main__":
    unittest.main()
