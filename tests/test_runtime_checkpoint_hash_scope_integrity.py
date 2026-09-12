"""Regression locks for authoritative scope and approval data in checkpoint hashes."""

import tempfile
import unittest
from pathlib import Path

from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeStage, RuntimeStatus
from runtime.job_store import DurableJobRecord, JobStoreIntegrityError, SQLiteJobRepository


class TestRuntimeCheckpointHashScopeIntegrity(unittest.TestCase):
    @staticmethod
    def _checkpoint(**overrides) -> ExecutionCheckpoint:
        values = {
            "checkpoint_id": "CHKPT-SCOPE-HASH-001",
            "run_id": "RUN-SCOPE-HASH-001",
            "business_id": "BIZ-SCOPE-A",
            "project_id": "PROJ-SCOPE-A",
            "chat_id": "CHAT-SCOPE-A",
            "stage": RuntimeStage.FINAL_CMO,
            "status": RuntimeStatus.WAITING_FOR_APPROVAL,
            "completed_stages": ["CMO_INITIAL", "INTELLIGENCE", "CONTENT"],
            "receipt_ids": ["EXEC-SCOPE-HASH-001"],
            "approval_state": ApprovalState.PENDING_APPROVAL,
            "pending_approval_id": "APPR-SERVER-A",
            "working_state_snapshot": {"final_cmo_deployment_binding": {"binding_id": "BIND-A"}},
        }
        values.update(overrides)
        return ExecutionCheckpoint(**values)

    def test_each_scope_or_pending_approval_field_changes_checkpoint_hash(self):
        base = self._checkpoint()
        base_hash = base.calculate_checkpoint_hash()
        mutations = {
            "business_id": "BIZ-SCOPE-B",
            "project_id": "PROJ-SCOPE-B",
            "chat_id": "CHAT-SCOPE-B",
            "pending_approval_id": "APPR-SERVER-B",
        }

        for field_name, mutated_value in mutations.items():
            with self.subTest(field=field_name):
                mutated = self._checkpoint(**{field_name: mutated_value})
                self.assertNotEqual(base_hash, mutated.calculate_checkpoint_hash())

    def test_post_creation_tampering_is_detectable_for_all_bound_fields(self):
        mutations = {
            "business_id": "BIZ-TAMPERED",
            "project_id": "PROJ-TAMPERED",
            "chat_id": "CHAT-TAMPERED",
            "pending_approval_id": "APPR-TAMPERED",
        }

        for field_name, mutated_value in mutations.items():
            with self.subTest(field=field_name):
                checkpoint = self._checkpoint()
                checkpoint.checkpoint_hash = checkpoint.calculate_checkpoint_hash()
                original_hash = checkpoint.checkpoint_hash
                setattr(checkpoint, field_name, mutated_value)
                self.assertNotEqual(original_hash, checkpoint.calculate_checkpoint_hash())

    def test_equivalent_typed_checkpoints_recompute_same_bound_hash(self):
        first = self._checkpoint()
        second = self._checkpoint()
        self.assertEqual(first.calculate_checkpoint_hash(), second.calculate_checkpoint_hash())

    def test_job_store_rejects_tampered_bound_checkpoint_fields(self):
        mutations = {
            "business_id": "BIZ-TAMPERED",
            "project_id": "PROJ-TAMPERED",
            "chat_id": "CHAT-TAMPERED",
            "pending_approval_id": "APPR-TAMPERED",
        }

        for field_name, mutated_value in mutations.items():
            with self.subTest(field=field_name), tempfile.TemporaryDirectory() as tmp:
                repository = SQLiteJobRepository(Path(tmp) / "jobs.sqlite3")
                try:
                    repository.create_job(
                        DurableJobRecord(
                            run_id="RUN-SCOPE-HASH-001",
                            objective="Checkpoint integrity regression",
                            business_id="BIZ-SCOPE-A",
                            project_id="PROJ-SCOPE-A",
                            chat_id="CHAT-SCOPE-A",
                            status="WAITING_APPROVAL",
                            created_at="2026-09-12T00:00:00+00:00",
                        )
                    )
                    checkpoint = self._checkpoint()
                    checkpoint.checkpoint_hash = checkpoint.calculate_checkpoint_hash()
                    setattr(checkpoint, field_name, mutated_value)
                    with self.assertRaises(JobStoreIntegrityError):
                        repository.append_checkpoint(checkpoint)
                finally:
                    repository.close()


if __name__ == "__main__":
    unittest.main()
