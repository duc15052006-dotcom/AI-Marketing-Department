"""Adversarial regression for checkpoint semantic hash coverage.

A durable checkpoint hash must bind the semantic runtime snapshot that is later
persisted. Mutating that snapshot after hash creation must fail closed at the
SQLite repository boundary instead of being accepted and re-hashed only at the
serialized-payload layer.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.context import RuntimeContext
from runtime.job_store import DurableJobRecord, JobStoreIntegrityError, SQLiteJobRepository


class CheckpointSemanticHashIntegrityAdversarialV1Tests(unittest.TestCase):
    def test_mutated_working_state_snapshot_is_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteJobRepository(Path(tmpdir) / "jobs.sqlite3")
            try:
                context = RuntimeContext(
                    objective="Verify checkpoint semantic integrity",
                    business_id="BIZ-CHECKPOINT-HASH",
                )
                context.working_state["budget"] = 100
                checkpoint = context.create_checkpoint()
                original_hash = checkpoint.checkpoint_hash

                repository.create_job(
                    DurableJobRecord(
                        run_id=context.run_id,
                        objective=context.objective,
                        business_id=context.business_id,
                        project_id=context.project_id,
                        chat_id=context.chat_id,
                        status="QUEUED",
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                )

                # Adversarial mutation after the checkpoint hash has already been
                # sealed. The stale hash must not authenticate a different runtime
                # state snapshot at the durable persistence boundary.
                checkpoint.working_state_snapshot["budget"] = 999999
                self.assertEqual(original_hash, checkpoint.checkpoint_hash)

                with self.assertRaises(JobStoreIntegrityError):
                    repository.append_checkpoint(checkpoint)

                self.assertEqual([], repository.list_checkpoints(context.run_id))
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
