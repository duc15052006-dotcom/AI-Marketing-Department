"""Adversarial RED regressions for Commitment model_copy authority.

Invariant: model_copy(update=...) must not bypass immutable Commitment authority.
Differing protected updates require the explicit revision boundary, while plain
copies and same-value protected updates remain valid copy operations.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from runtime.mission import CommitmentMutationError, CommitmentRecord


class CommitmentModelCopyAuthorityV1Tests(unittest.TestCase):
    def _commitment(self) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id="COMMIT-COPY-001",
            mission_id="MISSION-COPY-001",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            authority_mode="OPERATOR_APPROVED",
            active=True,
            deadline_at=datetime.now(timezone.utc) + timedelta(days=7),
            budget_limits={"spend_usd": 100.0},
            stop_conditions=["OPERATOR_CANCEL"],
            revision=1,
        )

    def _assert_copy_revision_error(self, commitment: CommitmentRecord, update: dict) -> None:
        with self.assertRaises(CommitmentMutationError) as caught:
            commitment.model_copy(update=update)
        self.assertEqual(str(caught.exception), "COMMITMENT_COPY_UPDATE_REQUIRES_REVISION")

    def test_commitment_id_change_requires_revision(self):
        commitment = self._commitment()
        self._assert_copy_revision_error(
            commitment,
            {"commitment_id": "COMMIT-COPY-OTHER"},
        )
        self.assertEqual(commitment.commitment_id, "COMMIT-COPY-001")

    def test_mission_id_change_requires_revision_and_plain_copy_preserves_runtime_types(self):
        commitment = self._commitment()
        self._assert_copy_revision_error(
            commitment,
            {"mission_id": "MISSION-COPY-OTHER"},
        )

        copied = commitment.model_copy()
        self.assertIsInstance(copied.deadline_at, datetime)
        self.assertIsInstance(copied.created_at, datetime)
        self.assertIsNot(copied, commitment)

    def test_authority_mode_change_requires_revision(self):
        commitment = self._commitment()
        self._assert_copy_revision_error(
            commitment,
            {"authority_mode": "SUPERVISED"},
        )
        self.assertEqual(commitment.authority_mode, "OPERATOR_APPROVED")

    def test_active_change_requires_revision_and_revise_remains_authoritative(self):
        commitment = self._commitment()
        self._assert_copy_revision_error(commitment, {"active": False})

        revised = commitment.revise(
            new_commitment_id="COMMIT-COPY-002",
            active=False,
        )
        self.assertTrue(commitment.active)
        self.assertFalse(revised.active)
        self.assertEqual(revised.revision, commitment.revision + 1)
        self.assertEqual(revised.supersedes_commitment_id, commitment.commitment_id)

    def test_budget_limits_change_requires_revision(self):
        commitment = self._commitment()
        self._assert_copy_revision_error(
            commitment,
            {"budget_limits": {"spend_usd": 25.0}},
        )
        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})

    def test_plain_model_copy_is_allowed_control(self):
        commitment = self._commitment()
        copied = commitment.model_copy()

        self.assertIsInstance(copied, CommitmentRecord)
        self.assertIsNot(copied, commitment)
        self.assertEqual(copied.commitment_id, commitment.commitment_id)
        self.assertEqual(copied.mission_id, commitment.mission_id)
        self.assertEqual(copied.authority_mode, commitment.authority_mode)
        self.assertEqual(copied.revision, commitment.revision)

    def test_same_value_protected_update_is_allowed_control(self):
        commitment = self._commitment()
        copied = commitment.model_copy(
            update={"commitment_id": commitment.commitment_id}
        )

        self.assertIsInstance(copied, CommitmentRecord)
        self.assertIsNot(copied, commitment)
        self.assertEqual(copied.commitment_id, commitment.commitment_id)
        self.assertEqual(commitment.commitment_id, "COMMIT-COPY-001")


if __name__ == "__main__":
    unittest.main()
