"""Adversarial RED regressions for Mission authoritative scope immutability.

Invariant: once a Mission becomes executable (READY or later), its authoritative
identity/scope fields cannot be rebound by ordinary field assignment.
"""

from __future__ import annotations

import unittest

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus


class MissionAuthoritativeScopeImmutabilityV1Tests(unittest.TestCase):
    def _ready_mission(self) -> MissionRecord:
        mission = MissionRecord(
            mission_id="MISSION-SCOPE-001",
            objective="Protect authoritative mission scope",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
        )
        commitment = CommitmentRecord(
            commitment_id="COMMIT-SCOPE-001",
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            user_id=mission.user_id,
            authority_mode="OPERATOR_APPROVED",
        )
        mission.mark_ready(commitment)
        self.assertEqual(mission.status, MissionStatus.READY)
        return mission

    def test_ready_mission_id_cannot_be_rebound(self):
        mission = self._ready_mission()
        with self.assertRaises(ValueError):
            mission.mission_id = "MISSION-OTHER"
        self.assertEqual(mission.mission_id, "MISSION-SCOPE-001")

    def test_ready_business_scope_cannot_be_rebound(self):
        mission = self._ready_mission()
        with self.assertRaises(ValueError):
            mission.business_id = "BIZ-OTHER"
        self.assertEqual(mission.business_id, "BIZ-001")

    def test_ready_project_scope_cannot_be_rebound(self):
        mission = self._ready_mission()
        with self.assertRaises(ValueError):
            mission.project_id = "PROJECT-OTHER"
        self.assertEqual(mission.project_id, "PROJECT-001")

    def test_ready_user_scope_cannot_be_rebound(self):
        mission = self._ready_mission()
        with self.assertRaises(ValueError):
            mission.user_id = "USER-OTHER"
        self.assertEqual(mission.user_id, "USER-001")

    def test_same_scope_assignment_is_idempotent_control(self):
        mission = self._ready_mission()
        mission.mission_id = "MISSION-SCOPE-001"
        mission.business_id = "BIZ-001"
        mission.project_id = "PROJECT-001"
        mission.user_id = "USER-001"
        self.assertEqual(mission.status, MissionStatus.READY)

    def test_created_mission_scope_can_be_corrected_before_commitment_binding_control(self):
        mission = MissionRecord(
            mission_id="MISSION-DRAFT-001",
            objective="Draft mission",
            business_id="BIZ-DRAFT",
            project_id=None,
            user_id="USER-DRAFT",
        )
        mission.business_id = "BIZ-CORRECTED"
        mission.project_id = "PROJECT-CORRECTED"
        self.assertEqual(mission.business_id, "BIZ-CORRECTED")
        self.assertEqual(mission.project_id, "PROJECT-CORRECTED")
        self.assertEqual(mission.status, MissionStatus.CREATED)


if __name__ == "__main__":
    unittest.main()
