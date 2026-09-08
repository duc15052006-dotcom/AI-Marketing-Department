"""Adversarial RED regressions for Mission model_copy authority.

Invariant: MissionRecord.model_copy(update=...) must not create a copied Mission
that bypasses authority rules already enforced for direct initialized mutation.
CREATED scope correction remains a compatibility control; lifecycle changes and
commitment binding still require their canonical authority boundaries.
"""

from __future__ import annotations

import unittest

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus


class MissionModelCopyAuthorityV1Tests(unittest.TestCase):
    def _created_mission(self) -> MissionRecord:
        return MissionRecord(
            mission_id="MISSION-COPY-001",
            objective="Protect Mission copy authority",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
        )

    def _ready_mission(self) -> MissionRecord:
        mission = self._created_mission()
        commitment = CommitmentRecord(
            commitment_id="COMMIT-COPY-001",
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            user_id=mission.user_id,
            authority_mode="SUPERVISED",
        )
        mission.mark_ready(commitment)
        self.assertEqual(mission.status, MissionStatus.READY)
        self.assertEqual(mission.commitment_id, commitment.commitment_id)
        return mission

    def test_ready_copy_cannot_rebind_authoritative_scope(self) -> None:
        mission = self._ready_mission()
        attacks = {
            "mission_id": "MISSION-OTHER",
            "business_id": "BIZ-OTHER",
            "project_id": "PROJECT-OTHER",
            "user_id": "USER-OTHER",
        }
        for field_name, forged_value in attacks.items():
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    mission.model_copy(update={field_name: forged_value})

    def test_created_copy_cannot_bypass_lifecycle_authority(self) -> None:
        mission = self._created_mission()
        with self.assertRaises(ValueError):
            mission.model_copy(update={"status": MissionStatus.ACTIVE})

    def test_ready_copy_cannot_bypass_lifecycle_authority(self) -> None:
        mission = self._ready_mission()
        with self.assertRaises(ValueError):
            mission.model_copy(update={"status": MissionStatus.ACTIVE})

    def test_created_copy_cannot_forge_commitment_binding(self) -> None:
        mission = self._created_mission()
        with self.assertRaises(ValueError):
            mission.model_copy(update={"commitment_id": "COMMIT-FAKE"})

    def test_ready_copy_cannot_replace_commitment_binding(self) -> None:
        mission = self._ready_mission()
        with self.assertRaises(ValueError):
            mission.model_copy(update={"commitment_id": "COMMIT-OTHER"})

    def test_plain_copy_preserves_current_authority_control(self) -> None:
        mission = self._ready_mission()
        copied = mission.model_copy()
        self.assertIsNot(copied, mission)
        self.assertEqual(copied.mission_id, mission.mission_id)
        self.assertEqual(copied.business_id, mission.business_id)
        self.assertEqual(copied.project_id, mission.project_id)
        self.assertEqual(copied.user_id, mission.user_id)
        self.assertEqual(copied.status, MissionStatus.READY)
        self.assertEqual(copied.commitment_id, mission.commitment_id)

    def test_same_value_protected_updates_remain_idempotent_control(self) -> None:
        mission = self._ready_mission()
        copied = mission.model_copy(
            update={
                "mission_id": mission.mission_id,
                "business_id": mission.business_id,
                "project_id": mission.project_id,
                "user_id": mission.user_id,
                "status": mission.status,
                "commitment_id": mission.commitment_id,
            }
        )
        self.assertEqual(copied.status, MissionStatus.READY)
        self.assertEqual(copied.commitment_id, mission.commitment_id)

    def test_created_scope_correction_remains_allowed_control(self) -> None:
        mission = self._created_mission()
        copied = mission.model_copy(
            update={
                "mission_id": "MISSION-COPY-CORRECTED",
                "business_id": "BIZ-CORRECTED",
                "project_id": "PROJECT-CORRECTED",
                "user_id": "USER-CORRECTED",
            }
        )
        self.assertEqual(copied.status, MissionStatus.CREATED)
        self.assertIsNone(copied.commitment_id)
        self.assertEqual(copied.mission_id, "MISSION-COPY-CORRECTED")
        self.assertEqual(copied.business_id, "BIZ-CORRECTED")
        self.assertEqual(copied.project_id, "PROJECT-CORRECTED")
        self.assertEqual(copied.user_id, "USER-CORRECTED")


if __name__ == "__main__":
    unittest.main()
