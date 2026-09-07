"""Adversarial RED regressions for canonical Mission lifecycle authority.

Invariant: after construction, lifecycle changes must go through the canonical
Mission transition API. Direct status reassignment may remain idempotent only
when assigning the already-current state.
"""

from __future__ import annotations

import unittest

from runtime.mission import (
    CommitmentRecord,
    MissionRecord,
    MissionStatus,
    MissionTransitionError,
)


class MissionStateMachineAuthorityV1Tests(unittest.TestCase):
    def _commitment(self) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id="COMMIT-FSM-001",
            mission_id="MISSION-FSM-001",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            authority_mode="OPERATOR_APPROVED",
        )

    def _ready_mission(self) -> MissionRecord:
        mission = MissionRecord(
            mission_id="MISSION-FSM-001",
            objective="Prove canonical lifecycle authority",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
        )
        mission.mark_ready(self._commitment())
        return mission

    def test_direct_created_to_active_assignment_is_rejected(self):
        mission = MissionRecord(
            mission_id="MISSION-FSM-001",
            objective="Prove canonical lifecycle authority",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
        )

        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.ACTIVE

        self.assertEqual(mission.status, MissionStatus.CREATED)

    def test_direct_ready_to_active_assignment_is_rejected(self):
        mission = self._ready_mission()

        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.ACTIVE

        self.assertEqual(mission.status, MissionStatus.READY)

    def test_direct_active_to_created_assignment_is_rejected(self):
        mission = self._ready_mission()
        mission.transition_to(MissionStatus.ACTIVE)

        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.CREATED

        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_same_status_assignment_is_idempotent_control(self):
        mission = self._ready_mission()
        mission.status = MissionStatus.READY
        self.assertEqual(mission.status, MissionStatus.READY)

    def test_ready_to_active_is_allowed_through_canonical_api(self):
        mission = self._ready_mission()
        mission.transition_to(MissionStatus.ACTIVE)
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_active_wait_resume_path_is_allowed_through_canonical_api(self):
        mission = self._ready_mission()
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_TIME)
        mission.transition_to(MissionStatus.ACTIVE)
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_waiting_state_cannot_jump_back_to_ready(self):
        mission = self._ready_mission()
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_EVENT)

        with self.assertRaises(MissionTransitionError):
            mission.transition_to(MissionStatus.READY)

        self.assertEqual(mission.status, MissionStatus.WAITING_FOR_EVENT)

    def test_created_to_ready_remains_commitment_gated(self):
        mission = MissionRecord(
            mission_id="MISSION-FSM-001",
            objective="Prove canonical lifecycle authority",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
        )

        with self.assertRaises(MissionTransitionError):
            mission.transition_to(MissionStatus.READY)

        self.assertEqual(mission.status, MissionStatus.CREATED)
        self.assertIsNone(mission.commitment_id)

        mission.mark_ready(self._commitment())
        self.assertEqual(mission.status, MissionStatus.READY)
        self.assertEqual(mission.commitment_id, "COMMIT-FSM-001")

    def test_active_can_cancel_but_cancelled_cannot_revive(self):
        mission = self._ready_mission()
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.CANCELLED)
        self.assertEqual(mission.status, MissionStatus.CANCELLED)

        with self.assertRaises(MissionTransitionError):
            mission.transition_to(MissionStatus.ACTIVE)

        self.assertEqual(mission.status, MissionStatus.CANCELLED)


if __name__ == "__main__":
    unittest.main()
