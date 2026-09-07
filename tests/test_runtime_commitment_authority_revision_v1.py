"""Adversarial RED regressions for Commitment authority revision semantics.

Invariant: authority-envelope changes must not mutate an existing Commitment
snapshot in place. They must create a new revision with a distinct Commitment
identity while preserving authoritative Mission scope.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from runtime.mission import CommitmentRecord


class CommitmentAuthorityRevisionV1Tests(unittest.TestCase):
    def _commitment(self) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id="COMMIT-REV-001",
            mission_id="MISSION-001",
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

    def test_authority_mode_cannot_be_reassigned_in_place(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.authority_mode = "SUPERVISED"

    def test_active_flag_cannot_be_reassigned_in_place(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.active = False

    def test_deadline_cannot_be_reassigned_in_place(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.deadline_at = None

    def test_budget_limits_cannot_be_replaced_in_place(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.budget_limits = {"spend_usd": 50.0}

    def test_stop_conditions_cannot_be_replaced_in_place(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.stop_conditions = ["BUDGET_EXHAUSTED"]

    def test_revision_number_cannot_be_reassigned_in_place(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.revision = 2

    def test_authorized_change_creates_distinct_revision_snapshot(self):
        commitment = self._commitment()
        old_deadline = commitment.deadline_at

        revised = commitment.revise(
            new_commitment_id="COMMIT-REV-002",
            authority_mode="SUPERVISED",
            active=False,
            deadline_at=None,
            budget_limits={"spend_usd": 25.0},
            stop_conditions=["BUDGET_EXHAUSTED"],
        )

        self.assertEqual(commitment.commitment_id, "COMMIT-REV-001")
        self.assertEqual(commitment.revision, 1)
        self.assertEqual(commitment.authority_mode, "OPERATOR_APPROVED")
        self.assertTrue(commitment.active)
        self.assertEqual(commitment.deadline_at, old_deadline)
        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})
        self.assertEqual(commitment.stop_conditions, ["OPERATOR_CANCEL"])

        self.assertEqual(revised.commitment_id, "COMMIT-REV-002")
        self.assertEqual(revised.revision, 2)
        self.assertEqual(revised.supersedes_commitment_id, "COMMIT-REV-001")
        self.assertEqual(revised.mission_id, commitment.mission_id)
        self.assertEqual(revised.business_id, commitment.business_id)
        self.assertEqual(revised.project_id, commitment.project_id)
        self.assertEqual(revised.user_id, commitment.user_id)
        self.assertEqual(revised.authority_mode, "SUPERVISED")
        self.assertFalse(revised.active)
        self.assertIsNone(revised.deadline_at)
        self.assertEqual(revised.budget_limits, {"spend_usd": 25.0})
        self.assertEqual(revised.stop_conditions, ["BUDGET_EXHAUSTED"])

    def test_revision_requires_new_distinct_commitment_id(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.revise(new_commitment_id=commitment.commitment_id)


if __name__ == "__main__":
    unittest.main()
