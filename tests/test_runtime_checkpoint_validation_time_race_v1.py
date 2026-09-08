from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_checkpoint import (
    DurableMissionCheckpointStore,
    MissionCheckpointAuthorityError,
)
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_store import MissionStore


class RuntimeCheckpointValidationTimeRaceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = MissionStore(database_path=str(root / "missions.sqlite3"))
        self.leases = DurableMissionLeaseStore(
            database_path=str(root / "mission-leases.sqlite3"),
            mission_store=self.store,
        )
        self.checkpoints = DurableMissionCheckpointStore(
            database_path=str(root / "mission-checkpoints.sqlite3"),
            mission_store=self.store,
            lease_database_path=str(root / "mission-leases.sqlite3"),
        )
        self.base = datetime(2026, 1, 1, tzinfo=timezone.utc)

        mission = MissionRecord(
            mission_id="MISSION-TIME-RACE-1",
            objective="Reject checkpoint authority after lease expiry",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id="COMMIT-TIME-RACE-1",
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
        self.checkpoints.close()
        self.leases.close()
        self.store.close()
        self._tmp.cleanup()

    def test_clock_advance_during_authority_read_cannot_reuse_pre_transaction_time(self) -> None:
        lease = self.leases.acquire(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
            worker_id="worker-a",
            lease_seconds=10,
            now=self.base,
        )

        fake_now = [self.base + timedelta(seconds=1)]
        self.checkpoints._aware_utc_now = lambda: fake_now[0]
        original_lease_row = self.checkpoints._lease_row_locked

        def read_authority_after_time_advance(mission_id: str):
            row = original_lease_row(mission_id)
            # Deterministically model time passing while the checkpoint writer
            # waits for/acquires durable authority. The lease expired at +10s.
            fake_now[0] = self.base + timedelta(seconds=11)
            return row

        self.checkpoints._lease_row_locked = read_authority_after_time_advance

        with self.assertRaises(MissionCheckpointAuthorityError) as caught:
            self.checkpoints.save_checkpoint(
                mission_id=self.mission.mission_id,
                business_id=self.mission.business_id,
                project_id=self.mission.project_id,
                worker_id=lease.lease_owner,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
                checkpoint_sequence=1,
                resume_cursor="phase:plan",
                state={"cursor": "phase:plan"},
            )

        self.assertEqual(
            "MISSION_CHECKPOINT_EXECUTION_LEASE_EXPIRED",
            str(caught.exception),
        )
        self.assertIsNone(
            self.checkpoints.get_latest(
                mission_id=self.mission.mission_id,
                business_id=self.mission.business_id,
                project_id=self.mission.project_id,
            )
        )


if __name__ == "__main__":
    unittest.main()
