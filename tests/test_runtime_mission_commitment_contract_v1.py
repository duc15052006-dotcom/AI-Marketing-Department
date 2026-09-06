"""Adversarial regressions for the Continuity Runtime Mission/Commitment trust boundary.

RED invariant: a Mission must not enter executable READY state unless a canonical,
active Commitment is bound to the same mission and authoritative scope.
"""

from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timedelta, timezone


class MissionCommitmentContractV1Tests(unittest.TestCase):
    def _contracts(self):
        try:
            module = importlib.import_module("runtime.mission")
        except ModuleNotFoundError as exc:
            self.fail(
                "Continuity Runtime Mission/Commitment contracts are missing; "
                "runtime.mission must enforce the executable trust boundary"
            )
        return (
            module.MissionRecord,
            module.CommitmentRecord,
            module.MissionStatus,
            module.MissionCommitmentError,
        )

    def _mission(self):
        MissionRecord, _, MissionStatus, _ = self._contracts()
        return MissionRecord(
            mission_id="MISSION-001",
            objective="Operate a durable marketing mission",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            status=MissionStatus.CREATED,
        )

    def _commitment(self, **overrides):
        _, CommitmentRecord, _, _ = self._contracts()
        data = {
            "commitment_id": "COMMIT-001",
            "mission_id": "MISSION-001",
            "business_id": "BIZ-001",
            "project_id": "PROJECT-001",
            "user_id": "USER-001",
            "authority_mode": "SUPERVISED",
            "active": True,
            "deadline_at": datetime.now(timezone.utc) + timedelta(days=1),
            "budget_limits": {"money": 100.0, "tokens": 100000.0},
            "stop_conditions": ["operator_cancelled"],
        }
        data.update(overrides)
        return CommitmentRecord(**data)

    def test_missing_commitment_cannot_make_mission_ready(self):
        _, _, MissionStatus, MissionCommitmentError = self._contracts()
        mission = self._mission()

        with self.assertRaises(MissionCommitmentError):
            mission.mark_ready(None)

        self.assertEqual(mission.status, MissionStatus.CREATED)
        self.assertIsNone(mission.commitment_id)

    def test_commitment_must_bind_same_mission_identity(self):
        _, _, MissionStatus, MissionCommitmentError = self._contracts()
        mission = self._mission()
        wrong = self._commitment(mission_id="MISSION-OTHER")

        with self.assertRaises(MissionCommitmentError):
            mission.mark_ready(wrong)

        self.assertEqual(mission.status, MissionStatus.CREATED)
        self.assertIsNone(mission.commitment_id)

    def test_commitment_must_bind_same_authoritative_scope(self):
        _, _, MissionStatus, MissionCommitmentError = self._contracts()
        mismatches = (
            {"business_id": "BIZ-OTHER"},
            {"project_id": "PROJECT-OTHER"},
            {"user_id": "USER-OTHER"},
        )

        for mismatch in mismatches:
            with self.subTest(mismatch=mismatch):
                mission = self._mission()
                wrong = self._commitment(**mismatch)
                with self.assertRaises(MissionCommitmentError):
                    mission.mark_ready(wrong)
                self.assertEqual(mission.status, MissionStatus.CREATED)
                self.assertIsNone(mission.commitment_id)

    def test_inactive_or_expired_commitment_cannot_make_mission_ready(self):
        _, _, MissionStatus, MissionCommitmentError = self._contracts()
        invalid_commitments = (
            self._commitment(active=False),
            self._commitment(deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
        )

        for invalid in invalid_commitments:
            with self.subTest(commitment_id=invalid.commitment_id, active=invalid.active):
                mission = self._mission()
                with self.assertRaises(MissionCommitmentError):
                    mission.mark_ready(invalid)
                self.assertEqual(mission.status, MissionStatus.CREATED)
                self.assertIsNone(mission.commitment_id)

    def test_matching_active_commitment_is_control_path(self):
        _, _, MissionStatus, _ = self._contracts()
        mission = self._mission()
        commitment = self._commitment()

        mission.mark_ready(commitment)

        self.assertEqual(mission.status, MissionStatus.READY)
        self.assertEqual(mission.commitment_id, commitment.commitment_id)


if __name__ == "__main__":
    unittest.main()
