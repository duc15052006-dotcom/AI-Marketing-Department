from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.mission_dispatch as mission_dispatch_module
import runtime.persistent_worker as persistent_worker_module
from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_checkpoint import DurableMissionCheckpointStore
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_scheduler import DurableMissionScheduler
from runtime.mission_store import MissionStore
from runtime.persistent_worker import (
    PersistentMissionWorker,
    PersistentWorkerCycleResult,
    PersistentWorkerCycleStatus,
)


_REAL_DATETIME = datetime


class _ControlledDateTime(_REAL_DATETIME):
    current = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(cls.current.timestamp(), tz=timezone.utc)
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)


class PersistentWorkerValidationTimeRaceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.base = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

        self.store = MissionStore(database_path=str(root / "missions.sqlite3"))
        self.scheduler = DurableMissionScheduler(
            database_path=str(root / "scheduler.sqlite3"),
            mission_store=self.store,
        )
        self.leases = DurableMissionLeaseStore(
            database_path=str(root / "leases.sqlite3"),
            mission_store=self.store,
        )
        self.checkpoints = DurableMissionCheckpointStore(
            database_path=str(root / "checkpoints.sqlite3"),
            mission_store=self.store,
            lease_database_path=str(root / "leases.sqlite3"),
        )

        mission = MissionRecord(
            mission_id="MISSION-WORKER-TIME-RACE-1",
            objective="Do not freeze default authority time above Dispatcher",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id="COMMIT-WORKER-TIME-RACE-1",
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

        self.scheduler.schedule_wake(
            wake_id="WAKE-WORKER-TIME-RACE-1",
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.base,
            reason="WORKER_TIME_RACE",
            now=self.base,
        )

        # Keep checkpoint expiry evaluation on the same deterministic clock so
        # a GREEN run can complete the bounded cycle instead of consulting the
        # real hosted-run wall clock months after this synthetic lease epoch.
        self.checkpoints._aware_utc_now = lambda: _ControlledDateTime.current

    def tearDown(self) -> None:
        self.checkpoints.close()
        self.leases.close()
        self.scheduler.close()
        self.store.close()
        self._tmp.cleanup()

    def test_default_worker_clock_is_not_frozen_before_dispatch_authority_boundary(self) -> None:
        worker = PersistentMissionWorker(
            mission_store=self.store,
            scheduler=self.scheduler,
            mission_leases=self.leases,
            checkpoints=self.checkpoints,
        )
        original_claim = worker._dispatcher.claim_next
        captured = []

        def claim_after_wait(**kwargs):
            # Model time passing after PersistentMissionWorker has entered its
            # composed call but before Dispatcher reaches downstream authority.
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            grant = original_claim(**kwargs)
            captured.append(grant)
            return grant

        worker._dispatcher.claim_next = claim_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        executor_calls = []

        def executor(context):
            executor_calls.append(context)
            self.assertEqual(1, len(captured))
            grant = captured[0]
            self.assertIsNotNone(grant)
            assert grant is not None
            self.assertIsNotNone(grant.wake.lease_expires_at)
            self.assertIsNotNone(grant.mission_lease.lease_expires_at)
            assert grant.wake.lease_expires_at is not None
            assert grant.mission_lease.lease_expires_at is not None
            self.assertGreater(
                grant.wake.lease_expires_at,
                _ControlledDateTime.current,
                "worker froze default time before dispatch and began work under an already-expired wake lease",
            )
            self.assertGreater(
                grant.mission_lease.lease_expires_at,
                _ControlledDateTime.current,
                "worker froze default time before dispatch and began work under an already-expired Mission lease",
            )
            return PersistentWorkerCycleResult(
                resume_cursor="phase:worker-time-race-complete",
                state={"authority_time": "fresh"},
            )

        with (
            patch.object(persistent_worker_module, "datetime", _ControlledDateTime),
            patch.object(mission_dispatch_module, "datetime", _ControlledDateTime),
        ):
            report = worker.run_once(
                worker_id="worker-a",
                executor=executor,
                wake_lease_seconds=5,
                mission_lease_seconds=5,
            )

        self.assertEqual(1, len(executor_calls))
        self.assertEqual(PersistentWorkerCycleStatus.FINISHED, report.status)
        self.assertEqual(1, report.checkpoint_sequence)

    def test_explicit_injected_worker_clock_remains_caller_controlled(self) -> None:
        injected = self.base + timedelta(seconds=1)
        worker = PersistentMissionWorker(
            mission_store=self.store,
            scheduler=self.scheduler,
            mission_leases=self.leases,
            checkpoints=self.checkpoints,
            clock=lambda: injected,
        )
        original_claim = worker._dispatcher.claim_next
        observed_now = []

        def capture_explicit_now(**kwargs):
            observed_now.append(kwargs.get("now"))
            return original_claim(**kwargs)

        worker._dispatcher.claim_next = capture_explicit_now
        self.checkpoints._aware_utc_now = lambda: injected

        report = worker.run_once(
            worker_id="worker-explicit",
            executor=lambda context: PersistentWorkerCycleResult(
                resume_cursor="phase:explicit-clock-control",
                state={"clock": "explicit"},
            ),
            wake_lease_seconds=30,
            mission_lease_seconds=30,
        )

        self.assertEqual([injected], observed_now)
        self.assertEqual(PersistentWorkerCycleStatus.FINISHED, report.status)


if __name__ == "__main__":
    unittest.main()
