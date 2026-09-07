"""Adversarial regressions for Commitment identity/scope immutability.

Invariant: a Commitment record is an authority snapshot. Once constructed, its
identity and authoritative scope cannot be rebound by ordinary field assignment.
Authority-envelope changes must use the revision boundary.
"""

from __future__ import annotations

import unittest

from runtime.mission import CommitmentRecord


class CommitmentIdentityScopeImmutabilityV1Tests(unittest.TestCase):
    def _commitment(self) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id="COMMIT-SCOPE-001",
            mission_id="MISSION-SCOPE-001",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            authority_mode="OPERATOR_APPROVED",
        )

    def test_commitment_id_cannot_be_rebound(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.commitment_id = "COMMIT-OTHER"
        self.assertEqual(commitment.commitment_id, "COMMIT-SCOPE-001")

    def test_mission_id_cannot_be_rebound(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.mission_id = "MISSION-OTHER"
        self.assertEqual(commitment.mission_id, "MISSION-SCOPE-001")

    def test_business_scope_cannot_be_rebound(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.business_id = "BIZ-OTHER"
        self.assertEqual(commitment.business_id, "BIZ-001")

    def test_project_scope_cannot_be_rebound(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.project_id = "PROJECT-OTHER"
        self.assertEqual(commitment.project_id, "PROJECT-001")

    def test_user_scope_cannot_be_rebound(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.user_id = "USER-OTHER"
        self.assertEqual(commitment.user_id, "USER-001")

    def test_same_identity_and_scope_assignment_is_idempotent_control(self):
        commitment = self._commitment()
        commitment.commitment_id = "COMMIT-SCOPE-001"
        commitment.mission_id = "MISSION-SCOPE-001"
        commitment.business_id = "BIZ-001"
        commitment.project_id = "PROJECT-001"
        commitment.user_id = "USER-001"
        self.assertEqual(commitment.commitment_id, "COMMIT-SCOPE-001")

    def test_authority_envelope_change_uses_revision_boundary(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.authority_mode = "SUPERVISED"

        revised = commitment.revise(
            new_commitment_id="COMMIT-SCOPE-002",
            authority_mode="SUPERVISED",
        )
        self.assertEqual(commitment.authority_mode, "OPERATOR_APPROVED")
        self.assertEqual(revised.authority_mode, "SUPERVISED")
        self.assertEqual(revised.revision, commitment.revision + 1)


if __name__ == "__main__":
    unittest.main()
