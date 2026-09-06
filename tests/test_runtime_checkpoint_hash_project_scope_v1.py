"""Adversarial RED for checkpoint hash coverage of authoritative project scope.

RuntimeContext freezes project_id as part of AuthoritativeScope and copies it
into every ExecutionCheckpoint. The checkpoint integrity digest must therefore
change when the captured project boundary changes.
"""

from __future__ import annotations

import unittest

from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeStage, RuntimeStatus


class RuntimeCheckpointHashProjectScopeV1Tests(unittest.TestCase):
    @staticmethod
    def _checkpoint(project_id):
        return ExecutionCheckpoint(
            checkpoint_id="CHKPT-HASH-PROJECT-V1",
            run_id="RUN-HASH-PROJECT-V1",
            business_id="BIZ-HASH-PROJECT-V1",
            project_id=project_id,
            chat_id="CHAT-HASH-PROJECT-V1",
            stage=RuntimeStage.STRATEGIST,
            status=RuntimeStatus.RUNNING,
            completed_stages=["cmo_initial", "intelligence"],
            receipt_ids=["EXEC-HASH-PROJECT-V1"],
            approval_state=ApprovalState.NOT_REQUIRED,
            pending_approval_id=None,
            working_state_snapshot={"plan": {"mode": "ADAPTIVE_DAG"}},
        )

    def test_different_project_ids_change_checkpoint_hash(self) -> None:
        project_a = self._checkpoint("PROJ-A")
        project_b = self._checkpoint("PROJ-B")

        self.assertNotEqual(
            project_a.calculate_checkpoint_hash(),
            project_b.calculate_checkpoint_hash(),
            "checkpoint integrity hash must bind the authoritative project scope",
        )

    def test_missing_vs_present_project_id_changes_checkpoint_hash(self) -> None:
        missing = self._checkpoint(None)
        present = self._checkpoint("PROJ-A")

        self.assertNotEqual(
            missing.calculate_checkpoint_hash(),
            present.calculate_checkpoint_hash(),
            "adding/removing captured project scope must change checkpoint integrity",
        )

    def test_same_project_id_has_same_checkpoint_hash_control(self) -> None:
        left = self._checkpoint("PROJ-A")
        right = self._checkpoint("PROJ-A")

        self.assertEqual(
            left.calculate_checkpoint_hash(),
            right.calculate_checkpoint_hash(),
            "equivalent project-scoped checkpoints must remain hash-equivalent",
        )


if __name__ == "__main__":
    unittest.main()
