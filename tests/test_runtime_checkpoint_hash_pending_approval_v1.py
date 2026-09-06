"""Adversarial RED for checkpoint hash coverage of pending approval identity.

A WAITING_FOR_APPROVAL checkpoint must cryptographically bind the exact approval
request it is waiting on. Otherwise two materially different approval gates can
share one integrity digest.
"""

from __future__ import annotations

import unittest

from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeStage, RuntimeStatus


class RuntimeCheckpointHashPendingApprovalV1Tests(unittest.TestCase):
    @staticmethod
    def _checkpoint(pending_approval_id):
        return ExecutionCheckpoint(
            checkpoint_id="CHKPT-HASH-APPROVAL-V1",
            run_id="RUN-HASH-APPROVAL-V1",
            business_id="BIZ-HASH-APPROVAL-V1",
            project_id="PROJ-HASH-APPROVAL-V1",
            chat_id="CHAT-HASH-APPROVAL-V1",
            stage=RuntimeStage.FINAL_CMO,
            status=RuntimeStatus.WAITING_FOR_APPROVAL,
            completed_stages=["cmo_initial", "intelligence", "strategist", "creative", "performance", "final_cmo"],
            receipt_ids=["EXEC-HASH-APPROVAL-V1"],
            approval_state=ApprovalState.PENDING_APPROVAL,
            pending_approval_id=pending_approval_id,
            working_state_snapshot={
                "authorization": {"status": "APPROVED_WITH_CONDITIONS"},
            },
        )

    def test_different_pending_approval_ids_change_checkpoint_hash(self) -> None:
        approval_a = self._checkpoint("EXEC-APPROVAL-A")
        approval_b = self._checkpoint("EXEC-APPROVAL-B")

        self.assertNotEqual(
            approval_a.calculate_checkpoint_hash(),
            approval_b.calculate_checkpoint_hash(),
            "checkpoint integrity hash must bind the exact pending approval request id",
        )

    def test_missing_vs_present_pending_approval_id_changes_checkpoint_hash(self) -> None:
        missing = self._checkpoint(None)
        present = self._checkpoint("EXEC-APPROVAL-A")

        self.assertNotEqual(
            missing.calculate_checkpoint_hash(),
            present.calculate_checkpoint_hash(),
            "adding/removing the pending approval identity must change checkpoint integrity",
        )

    def test_same_pending_approval_id_has_same_checkpoint_hash_control(self) -> None:
        left = self._checkpoint("EXEC-APPROVAL-A")
        right = self._checkpoint("EXEC-APPROVAL-A")

        self.assertEqual(
            left.calculate_checkpoint_hash(),
            right.calculate_checkpoint_hash(),
            "equivalent pending approval checkpoints must remain deterministically hash-equivalent",
        )


if __name__ == "__main__":
    unittest.main()
