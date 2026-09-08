"""Adversarial regressions for Commitment model_copy authority.

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

    def test_remaining_protected_fields_require_revision(self):
        commitment = self._commitment()
        differing_updates = {
            "business_id": "BIZ-OTHER",
            "project_id": "PROJECT-OTHER",
            "user_id": "USER-OTHER",
            "deadline_at": commitment.deadline_at + timedelta(days=1),
            "stop_conditions": ["BUDGET_EXHAUSTED"],
            "revision": commitment.revision + 1,
            "supersedes_commitment_id": "COMMIT-COPY-PREVIOUS",
        }

        for field_name, value in differing_updates.items():
            with self.subTest(field=field_name):
                self._assert_copy_revision_error(commitment, {field_name: value})

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
            update={
                "commitment_id": commitment.commitment_id,
                "mission_id": commitment.mission_id,
                "business_id": commitment.business_id,
                "project_id": commitment.project_id,
                "user_id": commitment.user_id,
                "authority_mode": commitment.authority_mode,
                "active": commitment.active,
                "deadline_at": commitment.deadline_at,
                "budget_limits": commitment.budget_limits,
                "stop_conditions": commitment.stop_conditions,
                "revision": commitment.revision,
                "supersedes_commitment_id": commitment.supersedes_commitment_id,
            }
        )

        self.assertIsInstance(copied, CommitmentRecord)
        self.assertIsNot(copied, commitment)
        self.assertEqual(copied.commitment_id, commitment.commitment_id)
        self.assertEqual(copied.mission_id, commitment.mission_id)
        self.assertEqual(copied.business_id, commitment.business_id)
        self.assertEqual(copied.project_id, commitment.project_id)
        self.assertEqual(copied.user_id, commitment.user_id)
        self.assertEqual(copied.authority_mode, commitment.authority_mode)
        self.assertEqual(copied.active, commitment.active)
        self.assertEqual(copied.deadline_at, commitment.deadline_at)
        self.assertEqual(copied.budget_limits, commitment.budget_limits)
        self.assertEqual(copied.stop_conditions, commitment.stop_conditions)
        self.assertEqual(copied.revision, commitment.revision)
        self.assertEqual(copied.supersedes_commitment_id, commitment.supersedes_commitment_id)


if __name__ == "__main__":
    unittest.main()
