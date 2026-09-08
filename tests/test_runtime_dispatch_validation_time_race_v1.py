from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.mission_dispatch as mission_dispatch_module
from runtime.mission import CommitmentRecord, MissionRecord
from runtime.mission_dispatch import MissionDispatchLeaseLostError, MissionWakeDispatcher
from runtime.mission_lease import (
    DurableMissionLeaseStore,
    MissionLeaseLostError,
)
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


class MissionDispatchValidationTimeRaceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.missions = MissionStore(database_path=str(root / "missions.sqlite3"))
        self.scheduler = DurableMissionScheduler(
            database_path=str(root / "scheduler.sqlite3"),
            mission_store=self.missions,
        )
        self.leases = DurableMissionLeaseStore(
            database_path=str(root / "leases.sqlite3"),
            mission_store=self.missions,
        )
        self.dispatcher = MissionWakeDispatcher(
            mission_store=self.missions,
            scheduler=self.scheduler,
            mission_leases=self.leases,
        )
        self.base = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

        mission = MissionRecord(
            mission_id="MISSION-DISPATCH-TIME-RACE-1",
            objective="Reject stale composed execution authority",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id="COMMIT-DISPATCH-TIME-RACE-1",
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                user_id=mission.user_id,
                authority_mode="SUPERVISED",
                deadline_at=self.base + timedelta(days=1),
            ),
            now=self.base,
        )
        self.missions.save_mission(mission)
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.base,
            reason="TIME_RACE",
            wake_id="WAKE-DISPATCH-TIME-RACE-1",
            now=self.base,
        )

    def tearDown(self) -> None:
        self.leases.close()
        self.scheduler.close()
        self.missions.close()
        self._tmp.cleanup()

    def _claim(self, *, lease_seconds: float = 10.0):
        grant = self.dispatcher.claim_next(
            worker_id="worker-a",
            now=self.base,
            wake_lease_seconds=lease_seconds,
            mission_lease_seconds=lease_seconds,
        )
        self.assertIsNotNone(grant)
        assert grant is not None
        return grant

    def test_claim_next_cannot_return_composed_grant_already_expired_after_contention(self) -> None:
        original_claim_due = self.scheduler.claim_due

        def claim_after_wait(**kwargs):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original_claim_due(**kwargs)

        self.scheduler.claim_due = claim_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)

        with patch.object(mission_dispatch_module, "datetime", _ControlledDateTime):
            grant = self.dispatcher.claim_next(
                worker_id="worker-a",
                wake_lease_seconds=5,
                mission_lease_seconds=5,
            )

        self.assertIsNotNone(grant)
        assert grant is not None
        self.assertIsNotNone(grant.wake.lease_expires_at)
        self.assertIsNotNone(grant.mission_lease.lease_expires_at)
        assert grant.wake.lease_expires_at is not None
        assert grant.mission_lease.lease_expires_at is not None
        self.assertGreater(
            grant.wake.lease_expires_at,
            _ControlledDateTime.current,
            "dispatcher returned an already-expired wake lease after composition wait",
        )
        self.assertGreater(
            grant.mission_lease.lease_expires_at,
            _ControlledDateTime.current,
            "dispatcher returned an already-expired Mission lease after composition wait",
        )

    def test_validate_cannot_accept_grant_that_expires_during_composed_validation(self) -> None:
        grant = self._claim()
        original_get_wake = self.scheduler.get_wake

        def get_after_wait(*args, **kwargs):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original_get_wake(*args, **kwargs)

        self.scheduler.get_wake = get_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)

        with patch.object(mission_dispatch_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionDispatchLeaseLostError):
                self.dispatcher.validate(grant)

    def test_renew_cannot_resurrect_grant_that_expires_before_downstream_renewal(self) -> None:
        grant = self._claim()
        original_renew = self.leases.renew

        def renew_after_wait(*args, **kwargs):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original_renew(*args, **kwargs)

        self.leases.renew = renew_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)

        with patch.object(mission_dispatch_module, "datetime", _ControlledDateTime):
            with self.assertRaises((MissionDispatchLeaseLostError, MissionLeaseLostError)):
                self.dispatcher.renew(
                    grant,
                    wake_lease_seconds=60,
                    mission_lease_seconds=60,
                )

    def test_acknowledge_cannot_commit_delivery_after_grant_expires_downstream(self) -> None:
        grant = self._claim()
        original_ack = self.scheduler.acknowledge_wake

        def acknowledge_after_wait(*args, **kwargs):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original_ack(*args, **kwargs)

        self.scheduler.acknowledge_wake = acknowledge_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)

        with patch.object(mission_dispatch_module, "datetime", _ControlledDateTime):
            with self.assertRaises((MissionDispatchLeaseLostError, MissionSchedulerLeaseError)):
                self.dispatcher.acknowledge_wake(grant)

    def test_release_mission_cannot_use_timestamp_sampled_before_downstream_wait(self) -> None:
        grant = self._claim()
        original_release = self.leases.release

        def release_after_wait(*args, **kwargs):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original_release(*args, **kwargs)

        self.leases.release = release_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)

        with patch.object(mission_dispatch_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionLeaseLostError):
                self.dispatcher.release_mission(grant)

    def test_finish_delivery_cannot_acknowledge_after_authority_expires_mid_composition(self) -> None:
        grant = self._claim()
        original_ack = self.scheduler.acknowledge_wake

        def acknowledge_after_wait(*args, **kwargs):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original_ack(*args, **kwargs)

        self.scheduler.acknowledge_wake = acknowledge_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)

        with patch.object(mission_dispatch_module, "datetime", _ControlledDateTime):
            with self.assertRaises((MissionDispatchLeaseLostError, MissionSchedulerLeaseError)):
                self.dispatcher.finish_delivery(grant)


if __name__ == "__main__":
    unittest.main()
