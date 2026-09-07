"""Adversarial RED regressions for canonical Mission lifecycle authority.

This suite intentionally lands before the production FSM patch.  At the exact
parent it proves that non-terminal callers can bypass lifecycle authority with
raw status assignment and that no canonical ``transition_to`` API/policy exists.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import runtime.mission as mission_module
from runtime.mission import (
    CommitmentRecord,
    MissionCommitmentError,
    MissionRecord,
    MissionStatus,
    MissionTransitionError,
)


class MissionLifecycleTransitionAuthorityV1Tests(unittest.TestCase):
    _ALLOWED_TRANSITIONS = frozenset(
        {
            (MissionStatus.CREATED, MissionStatus.CANCELLED),
            (MissionStatus.CREATED, MissionStatus.EXPIRED),
            (MissionStatus.READY, MissionStatus.ACTIVE),
            (MissionStatus.READY, MissionStatus.CANCELLED),
            (MissionStatus.READY, MissionStatus.FAILED),
            (MissionStatus.READY, MissionStatus.EXPIRED),
            (MissionStatus.ACTIVE, MissionStatus.WAITING_FOR_TIME),
            (MissionStatus.ACTIVE, MissionStatus.WAITING_FOR_EVENT),
            (MissionStatus.ACTIVE, MissionStatus.WAITING_FOR_CONDITION),
            (MissionStatus.ACTIVE, MissionStatus.WAITING_FOR_APPROVAL),
            (MissionStatus.ACTIVE, MissionStatus.WAITING_FOR_RESULT),
            (MissionStatus.ACTIVE, MissionStatus.SLEEPING),
            (MissionStatus.ACTIVE, MissionStatus.COMPLETED),
            (MissionStatus.ACTIVE, MissionStatus.CANCELLED),
            (MissionStatus.ACTIVE, MissionStatus.FAILED),
            (MissionStatus.ACTIVE, MissionStatus.EXPIRED),
            (MissionStatus.WAITING_FOR_TIME, MissionStatus.ACTIVE),
            (MissionStatus.WAITING_FOR_TIME, MissionStatus.CANCELLED),
            (MissionStatus.WAITING_FOR_TIME, MissionStatus.FAILED),
            (MissionStatus.WAITING_FOR_TIME, MissionStatus.EXPIRED),
            (MissionStatus.WAITING_FOR_EVENT, MissionStatus.ACTIVE),
            (MissionStatus.WAITING_FOR_EVENT, MissionStatus.CANCELLED),
            (MissionStatus.WAITING_FOR_EVENT, MissionStatus.FAILED),
            (MissionStatus.WAITING_FOR_EVENT, MissionStatus.EXPIRED),
            (MissionStatus.WAITING_FOR_CONDITION, MissionStatus.ACTIVE),
            (MissionStatus.WAITING_FOR_CONDITION, MissionStatus.CANCELLED),
            (MissionStatus.WAITING_FOR_CONDITION, MissionStatus.FAILED),
            (MissionStatus.WAITING_FOR_CONDITION, MissionStatus.EXPIRED),
            (MissionStatus.WAITING_FOR_APPROVAL, MissionStatus.ACTIVE),
            (MissionStatus.WAITING_FOR_APPROVAL, MissionStatus.CANCELLED),
            (MissionStatus.WAITING_FOR_APPROVAL, MissionStatus.FAILED),
            (MissionStatus.WAITING_FOR_APPROVAL, MissionStatus.EXPIRED),
            (MissionStatus.WAITING_FOR_RESULT, MissionStatus.ACTIVE),
            (MissionStatus.WAITING_FOR_RESULT, MissionStatus.CANCELLED),
            (MissionStatus.WAITING_FOR_RESULT, MissionStatus.FAILED),
            (MissionStatus.WAITING_FOR_RESULT, MissionStatus.EXPIRED),
            (MissionStatus.SLEEPING, MissionStatus.ACTIVE),
            (MissionStatus.SLEEPING, MissionStatus.CANCELLED),
            (MissionStatus.SLEEPING, MissionStatus.FAILED),
            (MissionStatus.SLEEPING, MissionStatus.EXPIRED),
        }
    )

    def _mission(self, status: MissionStatus = MissionStatus.CREATED) -> MissionRecord:
        return MissionRecord(
            mission_id="MISSION-FSM-001",
            objective="Enforce canonical lifecycle authority",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            status=status,
            commitment_id=None if status == MissionStatus.CREATED else "COMMIT-001",
        )

    def _commitment(
        self,
        *,
        active: bool = True,
        mission_id: str = "MISSION-FSM-001",
        deadline_at: datetime | None = None,
    ) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id="COMMIT-001",
            mission_id=mission_id,
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            authority_mode="bounded",
            active=active,
            deadline_at=deadline_at,
        )

    # ---- Expected RED errors: transition authority API/policy absent pre-fix. ----

    def test_transition_to_allows_created_to_cancelled(self):
        mission = self._mission(MissionStatus.CREATED)
        mission.transition_to(MissionStatus.CANCELLED)
        self.assertEqual(mission.status, MissionStatus.CANCELLED)

    def test_transition_to_allows_ready_to_active(self):
        mission = self._mission(MissionStatus.READY)
        mission.transition_to(MissionStatus.ACTIVE)
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_transition_to_allows_active_to_waiting_for_time(self):
        mission = self._mission(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_TIME)
        self.assertEqual(mission.status, MissionStatus.WAITING_FOR_TIME)

    def test_exhaustive_169_fsm_pairs_match_canonical_policy(self):
        # Collapse the pre-fix missing-method signal to one deterministic ERROR.
        # Once the API exists, the same test exercises all 169 pairs.
        if not hasattr(MissionRecord, "transition_to"):
            raise AttributeError("MissionRecord.transition_to is required")

        statuses = tuple(MissionStatus)
        self.assertEqual(len(statuses) * len(statuses), 169)

        for source in statuses:
            for target in statuses:
                with self.subTest(source=source.value, target=target.value):
                    mission = self._mission(source)
                    if target == MissionStatus.READY:
                        with self.assertRaisesRegex(
                            MissionTransitionError,
                            "MISSION_READY_REQUIRES_COMMITMENT_VALIDATION",
                        ):
                            mission.transition_to(target)
                    elif source == target:
                        mission.transition_to(target)
                        self.assertEqual(mission.status, source)
                    elif (source, target) in self._ALLOWED_TRANSITIONS:
                        mission.transition_to(target)
                        self.assertEqual(mission.status, target)
                    else:
                        with self.assertRaises(MissionTransitionError):
                            mission.transition_to(target)
                        self.assertEqual(mission.status, source)

    def test_transition_policy_is_private_immutable_frozenset(self):
        policy = mission_module._MISSION_TRANSITION_PAIRS
        self.assertIsInstance(policy, frozenset)
        with self.assertRaises(AttributeError):
            policy.add((MissionStatus.CREATED, MissionStatus.ACTIVE))

    # ---- Expected RED failures: raw non-terminal status assignment bypasses. ----

    def test_direct_created_to_active_is_rejected(self):
        mission = self._mission(MissionStatus.CREATED)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.ACTIVE
        self.assertEqual(mission.status, MissionStatus.CREATED)

    def test_direct_created_to_ready_is_rejected(self):
        mission = self._mission(MissionStatus.CREATED)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.READY
        self.assertEqual(mission.status, MissionStatus.CREATED)

    def test_direct_ready_to_active_is_rejected(self):
        mission = self._mission(MissionStatus.READY)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.ACTIVE
        self.assertEqual(mission.status, MissionStatus.READY)

    def test_direct_active_to_waiting_is_rejected(self):
        mission = self._mission(MissionStatus.ACTIVE)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.WAITING_FOR_TIME
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_direct_active_to_completed_is_rejected(self):
        mission = self._mission(MissionStatus.ACTIVE)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.COMPLETED
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_invalid_raw_status_injection_is_rejected(self):
        mission = self._mission(MissionStatus.CREATED)
        with self.assertRaisesRegex(MissionTransitionError, "MISSION_STATUS_INVALID"):
            mission.status = "NOT_A_MISSION_STATUS"
        self.assertEqual(mission.status, MissionStatus.CREATED)

    # ---- Controls expected to remain GREEN at the exact parent. ----

    def test_same_state_direct_assignment_is_idempotent_control(self):
        mission = self._mission(MissionStatus.ACTIVE)
        mission.status = MissionStatus.ACTIVE
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

    def test_completed_cannot_be_revived_control(self):
        mission = self._mission(MissionStatus.COMPLETED)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.ACTIVE
        self.assertEqual(mission.status, MissionStatus.COMPLETED)

    def test_cancelled_cannot_be_revived_control(self):
        mission = self._mission(MissionStatus.CANCELLED)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.READY
        self.assertEqual(mission.status, MissionStatus.CANCELLED)

    def test_failed_cannot_be_revived_control(self):
        mission = self._mission(MissionStatus.FAILED)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.WAITING_FOR_TIME
        self.assertEqual(mission.status, MissionStatus.FAILED)

    def test_expired_cannot_be_revived_control(self):
        mission = self._mission(MissionStatus.EXPIRED)
        with self.assertRaises(MissionTransitionError):
            mission.status = MissionStatus.ACTIVE
        self.assertEqual(mission.status, MissionStatus.EXPIRED)

    def test_mark_ready_valid_commitment_control(self):
        mission = self._mission(MissionStatus.CREATED)
        mission.mark_ready(self._commitment())
        self.assertEqual(mission.status, MissionStatus.READY)
        self.assertEqual(mission.commitment_id, "COMMIT-001")

    def test_mark_ready_mission_mismatch_is_atomic_control(self):
        mission = self._mission(MissionStatus.CREATED)
        with self.assertRaises(MissionCommitmentError):
            mission.mark_ready(self._commitment(mission_id="OTHER-MISSION"))
        self.assertEqual(mission.status, MissionStatus.CREATED)
        self.assertIsNone(mission.commitment_id)

    def test_mark_ready_inactive_commitment_is_atomic_control(self):
        mission = self._mission(MissionStatus.CREATED)
        with self.assertRaises(MissionCommitmentError):
            mission.mark_ready(self._commitment(active=False))
        self.assertEqual(mission.status, MissionStatus.CREATED)
        self.assertIsNone(mission.commitment_id)

    def test_mark_ready_expired_commitment_is_atomic_control(self):
        now = datetime.now(timezone.utc)
        mission = self._mission(MissionStatus.CREATED)
        with self.assertRaises(MissionCommitmentError):
            mission.mark_ready(
                self._commitment(deadline_at=now - timedelta(seconds=1)),
                now=now,
            )
        self.assertEqual(mission.status, MissionStatus.CREATED)
        self.assertIsNone(mission.commitment_id)


if __name__ == "__main__":
    unittest.main()
