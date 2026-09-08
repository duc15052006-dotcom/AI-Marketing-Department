"""Adversarial regressions for Mission commitment binding authority.

RED invariant: once a MissionRecord exists, direct commitment_id mutation must
never create, remove, or replace executable authority. Binding is granted only
by mark_ready() after canonical Commitment validation.
"""

from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timedelta, timezone


class MissionCommitmentBindingAuthorityV1Tests(unittest.TestCase):
    def _contracts(self):
        module = importlib.import_module("runtime.mission")
        return (
            module.MissionRecord,
            module.CommitmentRecord,
            module.MissionStatus,
            module.MissionCommitmentError,
        )

    def _mission(self, *, status=None, commitment_id=None):
        MissionRecord, _, MissionStatus, _ = self._contracts()
        return MissionRecord(
            mission_id="MISSION-001",
            objective="Operate a durable marketing mission",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            status=MissionStatus.CREATED if status is None else status,
            commitment_id=commitment_id,
        )

    def _commitment(self, *, commitment_id="COMMIT-001"):
        _, CommitmentRecord, _, _ = self._contracts()
        return CommitmentRecord(
            commitment_id=commitment_id,
            mission_id="MISSION-001",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            authority_mode="SUPERVISED",
            active=True,
            deadline_at=datetime.now(timezone.utc) + timedelta(days=1),
            budget_limits={"money": 100.0},
            stop_conditions=["operator_cancelled"],
        )

    def _assert_direct_binding_rejected(self, mission, target):
        _, _, _, MissionCommitmentError = self._contracts()
        previous = mission.commitment_id
        with self.assertRaises(MissionCommitmentError) as raised:
            mission.commitment_id = target
        self.assertEqual(
            str(raised.exception),
            "MISSION_COMMITMENT_BINDING_REQUIRES_MARK_READY",
        )
        self.assertEqual(mission.commitment_id, previous)

    def test_created_none_to_fake_binding_is_rejected(self):
        mission = self._mission()
        self._assert_direct_binding_rejected(mission, "COMMIT-FAKE")

    def test_ready_binding_cannot_be_replaced(self):
        _, _, MissionStatus, _ = self._contracts()
        mission = self._mission(status=MissionStatus.READY, commitment_id="COMMIT-001")
        self._assert_direct_binding_rejected(mission, "COMMIT-002")

    def test_active_binding_cannot_be_removed(self):
        _, _, MissionStatus, _ = self._contracts()
        mission = self._mission(status=MissionStatus.ACTIVE, commitment_id="COMMIT-001")
        self._assert_direct_binding_rejected(mission, None)

    def test_waiting_binding_cannot_be_replaced(self):
        _, _, MissionStatus, _ = self._contracts()
        mission = self._mission(
            status=MissionStatus.WAITING_FOR_TIME,
            commitment_id="COMMIT-001",
        )
        self._assert_direct_binding_rejected(mission, "COMMIT-002")

    def test_malformed_active_unbound_mission_cannot_gain_fake_binding(self):
        _, _, MissionStatus, _ = self._contracts()
        mission = self._mission(status=MissionStatus.ACTIVE, commitment_id=None)
        self._assert_direct_binding_rejected(mission, "COMMIT-FAKE")

    def test_same_commitment_assignment_is_idempotent_control(self):
        _, _, MissionStatus, _ = self._contracts()
        mission = self._mission(status=MissionStatus.READY, commitment_id="COMMIT-001")
        mission.commitment_id = "COMMIT-001"
        self.assertEqual(mission.commitment_id, "COMMIT-001")

    def test_mark_ready_validated_binding_remains_authoritative_control(self):
        _, _, MissionStatus, _ = self._contracts()
        mission = self._mission()
        commitment = self._commitment(commitment_id="COMMIT-001")
        mission.mark_ready(commitment)
        self.assertEqual(mission.status, MissionStatus.READY)
        self.assertEqual(mission.commitment_id, "COMMIT-001")


if __name__ == "__main__":
    unittest.main()
