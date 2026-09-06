"""Adversarial RED for checkpoint hash coverage of authoritative chat scope.

RuntimeContext freezes chat_id as part of AuthoritativeScope and copies it into
every ExecutionCheckpoint. The checkpoint integrity digest must therefore change
when the captured chat boundary changes.
"""

from __future__ import annotations

import unittest

from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeStage, RuntimeStatus


class RuntimeCheckpointHashChatScopeV1Tests(unittest.TestCase):
    @staticmethod
    def _checkpoint(chat_id):
        return ExecutionCheckpoint(
            checkpoint_id="CHKPT-HASH-CHAT-V1",
            run_id="RUN-HASH-CHAT-V1",
            business_id="BIZ-HASH-CHAT-V1",
            project_id="PROJ-HASH-CHAT-V1",
            chat_id=chat_id,
            stage=RuntimeStage.STRATEGIST,
            status=RuntimeStatus.RUNNING,
            completed_stages=["cmo_initial", "intelligence"],
            receipt_ids=["EXEC-HASH-CHAT-V1"],
            approval_state=ApprovalState.NOT_REQUIRED,
            pending_approval_id=None,
            working_state_snapshot={"plan": {"mode": "ADAPTIVE_DAG"}},
        )

    def test_different_chat_ids_change_checkpoint_hash(self) -> None:
        chat_a = self._checkpoint("CHAT-A")
        chat_b = self._checkpoint("CHAT-B")

        self.assertNotEqual(
            chat_a.calculate_checkpoint_hash(),
            chat_b.calculate_checkpoint_hash(),
            "checkpoint integrity hash must bind the authoritative chat scope",
        )

    def test_missing_vs_present_chat_id_changes_checkpoint_hash(self) -> None:
        missing = self._checkpoint(None)
        present = self._checkpoint("CHAT-A")

        self.assertNotEqual(
            missing.calculate_checkpoint_hash(),
            present.calculate_checkpoint_hash(),
            "adding/removing captured chat scope must change checkpoint integrity",
        )

    def test_same_chat_id_has_same_checkpoint_hash_control(self) -> None:
        left = self._checkpoint("CHAT-A")
        right = self._checkpoint("CHAT-A")

        self.assertEqual(
            left.calculate_checkpoint_hash(),
            right.calculate_checkpoint_hash(),
            "equivalent chat-scoped checkpoints must remain hash-equivalent",
        )


if __name__ == "__main__":
    unittest.main()
