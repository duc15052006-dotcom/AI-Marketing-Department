from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.mission_scheduler as mission_scheduler_module
from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_scheduler import (
    DurableMissionScheduler,
    MissionSchedulerLeaseError,
)
from runtime.mission_store import MissionStore


_REAL_DATETIME = datetime


class _ControlledDateTime(_REAL_DATETIME):
    current = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(cls.current.timestamp(), tz=timezone.utc)
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)


class _AdvanceAfterAcquireLock:
    """Acquire the real scheduler lock, then model time spent waiting for it."""

    def __init__(self, delegate, *, advance_to: datetime) -> None:
        self._delegate = delegate
        self._advance_to = advance_to

    def __enter__(self):
        self._delegate.acquire()
        _ControlledDateTime.current = self._advance_to
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._delegate.release()
        return False


class MissionSchedulerValidationTimeRaceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = MissionStore(database_path=str(root / "missions.sqlite3"))
        self.scheduler = DurableMissionScheduler(
            database_path=str(root / "scheduler.sqlite3"),
            mission_store=self.store,
        )
        self.base = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

        mission = MissionRecord(
            mission_id="MISSION-SCHEDULER-TIME-RACE-1",
            objective="Reject stale wake-lease authority after lock contention",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id="COMMIT-SCHEDULER-TIME-RACE-1",
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                user_id=mission.user_id,
                authority_mode="SUPERVISED",
                deadline_at=self.base + timedelta(days=1),
            ),
            now=self.base,
        )
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_TIME)
        self.store.save_mission(mission)
        self.mission = mission

    def tearDown(self) -> None:
        self.scheduler.close()
        self.store.close()
        self._tmp.cleanup()

    def _schedule_due(self, wake_id: str) -> None:
        self.scheduler.schedule_wake(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
            due_at=self.base,
            reason="TIME_RACE",
            wake_id=wake_id,
            now=self.base,
        )

    def _advance_when_scheduler_lock_is_acquired(self, *, seconds: int) -> None:
        self.scheduler._lock = _AdvanceAfterAcquireLock(
            self.scheduler._lock,
            advance_to=self.base + timedelta(seconds=seconds),
        )

    def test_claim_due_cannot_return_a_lease_already_expired_at_authority_boundary(self) -> None:
        self._schedule_due("WAKE-CLAIM-RACE")
        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        self._advance_when_scheduler_lock_is_acquired(seconds=11)

        with patch.object(mission_scheduler_module, "datetime", _ControlledDateTime):
            claimed = self.scheduler.claim_due(
                worker_id="worker-a",
                lease_seconds=5,
            )

        self.assertEqual(1, len(claimed))
        self.assertIsNotNone(claimed[0].lease_expires_at)
        assert claimed[0].lease_expires_at is not None
        self.assertGreater(
            claimed[0].lease_expires_at,
            _ControlledDateTime.current,
            "claim_due returned a wake lease that was already expired when durable authority was acquired",
        )

    def test_acknowledge_cannot_use_prelock_time_after_lease_expires(self) -> None:
        self._schedule_due("WAKE-ACK-RACE")
        claim = self.scheduler.claim_due(
            worker_id="worker-a",
            now=self.base,
            lease_seconds=10,
        )[0]

        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        self._advance_when_scheduler_lock_is_acquired(seconds=11)
        with patch.object(mission_scheduler_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionSchedulerLeaseError):
                self.scheduler.acknowledge_wake(
                    wake_id=claim.wake_id,
                    worker_id="worker-a",
                    lease_token=claim.lease_token or "",
                )

    def test_renew_cannot_resurrect_lease_that_expires_while_waiting_for_lock(self) -> None:
        self._schedule_due("WAKE-RENEW-RACE")
        claim = self.scheduler.claim_due(
            worker_id="worker-a",
            now=self.base,
            lease_seconds=10,
        )[0]

        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        self._advance_when_scheduler_lock_is_acquired(seconds=11)
        with patch.object(mission_scheduler_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionSchedulerLeaseError):
                self.scheduler.renew_lease(
                    wake_id=claim.wake_id,
                    worker_id="worker-a",
                    lease_token=claim.lease_token or "",
                    lease_seconds=60,
                )


if __name__ == "__main__":
    unittest.main()
