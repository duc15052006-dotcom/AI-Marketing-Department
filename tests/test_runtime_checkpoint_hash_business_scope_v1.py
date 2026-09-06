"""Adversarial RED for checkpoint hash coverage of authoritative business scope.

RuntimeContext freezes business_id as part of AuthoritativeScope and copies it
into every ExecutionCheckpoint. The checkpoint integrity digest must therefore
change when the captured business boundary changes.
"""

from __future__ import annotations

import unittest

from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeStage, RuntimeStatus


class RuntimeCheckpointHashBusinessScopeV1Tests(unittest.TestCase):
    @staticmethod
    def _checkpoint(business_id):
        return ExecutionCheckpoint(
            checkpoint_id="CHKPT-HASH-BUSINESS-V1",
            run_id="RUN-HASH-BUSINESS-V1",
            business_id=business_id,
            project_id="PROJ-HASH-BUSINESS-V1",
            chat_id="CHAT-HASH-BUSINESS-V1",
            stage=RuntimeStage.STRATEGIST,
            status=RuntimeStatus.RUNNING,
            completed_stages=["cmo_initial", "intelligence"],
            receipt_ids=["EXEC-HASH-BUSINESS-V1"],
            approval_state=ApprovalState.NOT_REQUIRED,
            pending_approval_id=None,
            working_state_snapshot={"plan": {"mode": "ADAPTIVE_DAG"}},
        )

    def test_different_business_ids_change_checkpoint_hash(self) -> None:
        business_a = self._checkpoint("BIZ-A")
        business_b = self._checkpoint("BIZ-B")

        self.assertNotEqual(
            business_a.calculate_checkpoint_hash(),
            business_b.calculate_checkpoint_hash(),
            "checkpoint integrity hash must bind the authoritative business scope",
        )

    def test_missing_vs_present_business_id_changes_checkpoint_hash(self) -> None:
        missing = self._checkpoint(None)
        present = self._checkpoint("BIZ-A")

        self.assertNotEqual(
            missing.calculate_checkpoint_hash(),
            present.calculate_checkpoint_hash(),
            "adding/removing captured business scope must change checkpoint integrity",
        )

    def test_same_business_id_has_same_checkpoint_hash_control(self) -> None:
        left = self._checkpoint("BIZ-A")
        right = self._checkpoint("BIZ-A")

        self.assertEqual(
            left.calculate_checkpoint_hash(),
            right.calculate_checkpoint_hash(),
            "equivalent business-scoped checkpoints must remain hash-equivalent",
        )


if __name__ == "__main__":
    unittest.main()
