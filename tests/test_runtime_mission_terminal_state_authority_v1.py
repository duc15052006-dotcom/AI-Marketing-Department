"""Adversarial regressions for terminal Mission lifecycle authority.

RED invariant: once a Mission reaches a terminal state, ordinary field mutation
must not be able to revive it into an executable or waiting state.
"""

from __future__ import annotations

import unittest

from runtime.mission import MissionRecord, MissionStatus


class MissionTerminalStateAuthorityV1Tests(unittest.TestCase):
    def _mission(self, status: MissionStatus) -> MissionRecord:
        return MissionRecord(
            mission_id="MISSION-TERMINAL-001",
            objective="Protect terminal lifecycle authority",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            status=status,
            commitment_id="COMMIT-001",
        )

    def test_cancelled_mission_cannot_be_revived_by_direct_assignment(self):
        mission = self._mission(MissionStatus.CANCELLED)

        with self.assertRaises(ValueError):
            mission.status = MissionStatus.ACTIVE

        self.assertEqual(mission.status, MissionStatus.CANCELLED)

    def test_completed_mission_cannot_be_revived_by_direct_assignment(self):
        mission = self._mission(MissionStatus.COMPLETED)

        with self.assertRaises(ValueError):
            mission.status = MissionStatus.READY

        self.assertEqual(mission.status, MissionStatus.COMPLETED)

    def test_failed_mission_cannot_be_revived_by_direct_assignment(self):
        mission = self._mission(MissionStatus.FAILED)

        with self.assertRaises(ValueError):
            mission.status = MissionStatus.WAITING_FOR_TIME

        self.assertEqual(mission.status, MissionStatus.FAILED)

    def test_expired_mission_cannot_be_revived_by_direct_assignment(self):
        mission = self._mission(MissionStatus.EXPIRED)

        with self.assertRaises(ValueError):
            mission.status = MissionStatus.ACTIVE

        self.assertEqual(mission.status, MissionStatus.EXPIRED)

    def test_same_terminal_state_assignment_is_idempotent_control(self):
        mission = self._mission(MissionStatus.CANCELLED)

        mission.status = MissionStatus.CANCELLED

        self.assertEqual(mission.status, MissionStatus.CANCELLED)

    def test_non_terminal_transition_remains_outside_this_slice_control(self):
        mission = self._mission(MissionStatus.ACTIVE)

        mission.status = MissionStatus.WAITING_FOR_TIME

        self.assertEqual(mission.status, MissionStatus.WAITING_FOR_TIME)


if __name__ == "__main__":
    unittest.main()
