"""Adversarial RED for checkpoint hash coverage of nested working state.

A checkpoint hash is only useful as an integrity fingerprint if changing the
captured working_state_snapshot changes the digest. Canonical key ordering must
not make semantically identical dictionaries hash differently.
"""

from __future__ import annotations

import unittest

from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeStage, RuntimeStatus


class RuntimeCheckpointHashWorkingStateV1Tests(unittest.TestCase):
    @staticmethod
    def _checkpoint(working_state_snapshot):
        return ExecutionCheckpoint(
            checkpoint_id="CHKPT-HASH-WORKING-STATE-V1",
            run_id="RUN-HASH-WORKING-STATE-V1",
            business_id="BIZ-HASH-WORKING-STATE-V1",
            project_id="PROJ-HASH-WORKING-STATE-V1",
            chat_id="CHAT-HASH-WORKING-STATE-V1",
            stage=RuntimeStage.INTELLIGENCE,
            status=RuntimeStatus.RUNNING,
            completed_stages=["cmo_initial"],
            receipt_ids=["EXEC-HASH-WORKING-STATE-V1"],
            approval_state=ApprovalState.NOT_REQUIRED,
            pending_approval_id=None,
            working_state_snapshot=working_state_snapshot,
        )

    def test_nested_working_state_value_change_changes_checkpoint_hash(self) -> None:
        before = self._checkpoint(
            {
                "intelligence_adaptive_task_plan": {
                    "mode": "ADAPTIVE_CMO_PROPOSAL",
                    "waves": [["intelligence-market", "intelligence-customers"]],
                    "metadata": {"selected_count": 2},
                }
            }
        )
        after = self._checkpoint(
            {
                "intelligence_adaptive_task_plan": {
                    "mode": "ADAPTIVE_CMO_PROPOSAL",
                    "waves": [["intelligence-market", "intelligence-customers"]],
                    "metadata": {"selected_count": 999},
                }
            }
        )

        self.assertNotEqual(
            before.calculate_checkpoint_hash(),
            after.calculate_checkpoint_hash(),
            "checkpoint integrity hash must bind nested working_state_snapshot values",
        )

    def test_nested_working_state_list_change_changes_checkpoint_hash(self) -> None:
        before = self._checkpoint(
            {"plan": {"waves": [["task-a", "task-b"]], "rejected_kinds": []}}
        )
        after = self._checkpoint(
            {"plan": {"waves": [["task-a", "task-b", "task-c"]], "rejected_kinds": []}}
        )

        self.assertNotEqual(
            before.calculate_checkpoint_hash(),
            after.calculate_checkpoint_hash(),
            "checkpoint hash must detect nested list tampering in captured runtime state",
        )

    def test_equivalent_mapping_key_order_has_same_checkpoint_hash_control(self) -> None:
        left = self._checkpoint(
            {
                "plan": {
                    "mode": "ADAPTIVE_DAG",
                    "metadata": {"selected_count": 2, "fallback": False},
                    "waves": [["task-a", "task-b"]],
                }
            }
        )
        right = self._checkpoint(
            {
                "plan": {
                    "waves": [["task-a", "task-b"]],
                    "metadata": {"fallback": False, "selected_count": 2},
                    "mode": "ADAPTIVE_DAG",
                }
            }
        )

        self.assertEqual(
            left.calculate_checkpoint_hash(),
            right.calculate_checkpoint_hash(),
            "canonical checkpoint hashing must ignore dictionary insertion order",
        )


if __name__ == "__main__":
    unittest.main()
