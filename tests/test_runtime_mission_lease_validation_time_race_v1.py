from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.mission_lease as mission_lease_module
from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_lease import DurableMissionLeaseStore, MissionLeaseLostError
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


class MissionLeaseValidationTimeRaceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = MissionStore(database_path=str(root / "missions.sqlite3"))
        self.leases = DurableMissionLeaseStore(
            database_path=str(root / "mission-leases.sqlite3"),
            mission_store=self.store,
        )
        self.base = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

        mission = self._persist_waiting_mission("MISSION-LEASE-TIME-RACE-1")
        self.mission = mission
        self.lease = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=10,
            now=self.base,
        )

    def tearDown(self) -> None:
        self.leases.close()
        self.store.close()
        self._tmp.cleanup()

    def _persist_waiting_mission(self, mission_id: str) -> MissionRecord:
        mission = MissionRecord(
            mission_id=mission_id,
            objective="Reject expired Mission lease authority after contention",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id=f"COMMIT-{mission_id}",
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
        return mission

    def _advance_during_live_check(self) -> None:
        original = self.leases._require_exact_live_lease_locked

        def after_wait(lease, *, now):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original(lease, now=now)

        self.leases._require_exact_live_lease_locked = after_wait

    def test_acquire_cannot_return_new_lease_already_expired_at_authority_boundary(self) -> None:
        mission = self._persist_waiting_mission("MISSION-LEASE-TIME-RACE-ACQUIRE")
        original_row_locked = self.leases._row_locked

        def row_after_wait(mission_id):
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return original_row_locked(mission_id)

        self.leases._row_locked = row_after_wait
        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        with patch.object(mission_lease_module, "datetime", _ControlledDateTime):
            acquired = self.leases.acquire(
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                worker_id="worker-b",
                lease_seconds=5,
            )

        self.assertIsNotNone(acquired.lease_expires_at)
        assert acquired.lease_expires_at is not None
        self.assertGreater(
            acquired.lease_expires_at,
            _ControlledDateTime.current,
            "acquire returned a Mission lease already expired when serialized authority was acquired",
        )

    def test_validate_cannot_accept_lease_that_expires_while_waiting_for_lock(self) -> None:
        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        self._advance_during_live_check()
        with patch.object(mission_lease_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionLeaseLostError):
                self.leases.validate(self.lease)

    def test_renew_cannot_resurrect_lease_that_expires_while_waiting_for_transaction(self) -> None:
        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        self._advance_during_live_check()
        with patch.object(mission_lease_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionLeaseLostError):
                self.leases.renew(self.lease, lease_seconds=60)

    def test_release_requires_lease_still_live_at_serialized_authority_boundary(self) -> None:
        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        self._advance_during_live_check()
        with patch.object(mission_lease_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionLeaseLostError):
                self.leases.release(self.lease)


if __name__ == "__main__":
    unittest.main()
