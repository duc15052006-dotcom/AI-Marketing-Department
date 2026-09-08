from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import runtime.mission_store as mission_store_module
from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_store import MissionStore, MissionStoreAuthorityError


_REAL_DATETIME = datetime


class _ControlledDateTime:
    current = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        value = cls.current
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)

    @staticmethod
    def fromisoformat(value: str):
        return _REAL_DATETIME.fromisoformat(value)


class RuntimeFencedPersistenceValidationTimeRaceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = MissionStore(database_path=str(root / "missions.sqlite3"))
        self.leases = DurableMissionLeaseStore(
            database_path=str(root / "mission-leases.sqlite3"),
            mission_store=self.store,
        )
        self.base = _REAL_DATETIME(2026, 1, 1, tzinfo=timezone.utc)

        mission = MissionRecord(
            mission_id="MISSION-FENCED-TIME-RACE-1",
            objective="Reject fenced persistence after lease expiry",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id="COMMIT-FENCED-TIME-RACE-1",
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
        self.leases.close()
        self.store.close()
        self._tmp.cleanup()

    def test_clock_advance_during_fence_read_cannot_reuse_pre_transaction_time(self) -> None:
        lease = self.leases.acquire(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
            worker_id="worker-a",
            lease_seconds=10,
            now=self.base,
        )
        self.mission.transition_to(MissionStatus.ACTIVE)

        _ControlledDateTime.current = self.base + timedelta(seconds=1)
        original_lease_row = self.store._lease_row_locked

        def read_authority_after_time_advance(mission_id: str):
            row = original_lease_row(mission_id)
            # Model time advancing past the +10s lease expiry while this writer
            # waits for/acquires the durable fencing authority.
            _ControlledDateTime.current = self.base + timedelta(seconds=11)
            return row

        self.store._lease_row_locked = read_authority_after_time_advance

        with patch.object(mission_store_module, "datetime", _ControlledDateTime):
            with self.assertRaises(MissionStoreAuthorityError) as caught:
                self.store.save_mission_fenced(
                    self.mission,
                    worker_id=lease.lease_owner,
                    lease_token=lease.lease_token,
                    fencing_token=lease.fencing_token,
                )

        self.assertEqual("MISSION_STORE_EXECUTION_LEASE_EXPIRED", str(caught.exception))
        restored = self.store.get_mission(
            self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(MissionStatus.WAITING_FOR_TIME, restored.status)


if __name__ == "__main__":
    unittest.main()
