from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_lease import (
    DurableMissionLeaseStore,
    MissionLeaseAuthorityError,
    MissionLeaseLostError,
    MissionLeaseStateError,
)
from runtime.mission_store import MissionStore


class DurableMissionLeaseV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mission_db = str(root / "missions.sqlite3")
        self.lease_db = str(root / "mission-leases.sqlite3")
        self.store = MissionStore(database_path=self.mission_db)
        self.leases = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )
        self.now = datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.leases.close()
        self.store.close()
        self._tmp.cleanup()

    def _persist_waiting_mission(self, mission_id: str = "MISSION-LEASE-1") -> MissionRecord:
        mission = MissionRecord(
            mission_id=mission_id,
            objective="Long-lived autonomous marketing mission",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        commitment = CommitmentRecord(
            commitment_id=f"COMMIT-{mission_id}",
            mission_id=mission_id,
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
            authority_mode="SUPERVISED",
            deadline_at=self.now + timedelta(days=7),
        )
        mission.mark_ready(commitment, now=self.now)
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_TIME)
        self.store.save_mission(mission)
        return mission

    def test_live_lease_blocks_second_worker_across_connections(self) -> None:
        mission = self._persist_waiting_mission()
        first = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        second_store = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )
        try:
            with self.assertRaises(MissionLeaseStateError):
                second_store.acquire(
                    mission_id=mission.mission_id,
                    business_id=mission.business_id,
                    project_id=mission.project_id,
                    worker_id="worker-b",
                    lease_seconds=60,
                    now=self.now,
                )
            self.assertEqual("worker-a", first.lease_owner)
        finally:
            second_store.close()

    def test_expired_lease_can_be_reclaimed_with_higher_fencing_token(self) -> None:
        mission = self._persist_waiting_mission()
        first = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=1,
            now=self.now,
        )
        second_store = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )
        try:
            second = second_store.acquire(
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                worker_id="worker-b",
                lease_seconds=60,
                now=self.now + timedelta(seconds=2),
            )
            self.assertGreater(second.fencing_token, first.fencing_token)
            self.assertNotEqual(second.lease_token, first.lease_token)
            self.assertEqual("worker-b", second.lease_owner)
        finally:
            second_store.close()

    def test_stale_worker_cannot_validate_renew_or_release_after_takeover(self) -> None:
        mission = self._persist_waiting_mission()
        first = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=1,
            now=self.now,
        )
        second_store = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )
        try:
            second_store.acquire(
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                worker_id="worker-b",
                lease_seconds=60,
                now=self.now + timedelta(seconds=2),
            )
            for operation in (
                lambda: self.leases.validate(first, now=self.now + timedelta(seconds=2)),
                lambda: self.leases.renew(first, lease_seconds=60, now=self.now + timedelta(seconds=2)),
                lambda: self.leases.release(first, now=self.now + timedelta(seconds=2)),
            ):
                with self.assertRaises(MissionLeaseLostError):
                    operation()
        finally:
            second_store.close()

    def test_release_then_reacquire_increments_fencing_token(self) -> None:
        mission = self._persist_waiting_mission()
        first = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        released = self.leases.release(first, now=self.now + timedelta(seconds=1))
        self.assertIsNone(released.lease_owner)
        second = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-b",
            lease_seconds=60,
            now=self.now + timedelta(seconds=2),
        )
        self.assertGreater(second.fencing_token, first.fencing_token)

    def test_lease_and_fencing_epoch_survive_process_reopen(self) -> None:
        mission = self._persist_waiting_mission()
        first = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        self.leases.close()
        self.leases = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )
        recovered = self.leases.get(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
        )
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(first.lease_token, recovered.lease_token)
        self.assertEqual(first.fencing_token, recovered.fencing_token)
        self.assertEqual("worker-a", recovered.lease_owner)

    def test_foreign_scope_cannot_read_or_acquire_mission_lease(self) -> None:
        mission = self._persist_waiting_mission()
        with self.assertRaises(MissionLeaseAuthorityError):
            self.leases.acquire(
                mission_id=mission.mission_id,
                business_id="BIZ-FOREIGN",
                project_id=mission.project_id,
                worker_id="worker-a",
                lease_seconds=60,
                now=self.now,
            )
        self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        self.assertIsNone(
            self.leases.get(
                mission_id=mission.mission_id,
                business_id="BIZ-FOREIGN",
                project_id=mission.project_id,
            )
        )

    def test_terminal_mission_cannot_acquire_new_execution_lease(self) -> None:
        mission = self._persist_waiting_mission()
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.COMPLETED)
        self.store.save_mission(mission)
        with self.assertRaises(MissionLeaseStateError):
            self.leases.acquire(
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                worker_id="worker-a",
                lease_seconds=60,
                now=self.now,
            )

    def test_renew_extends_live_lease_without_changing_fencing_token(self) -> None:
        mission = self._persist_waiting_mission()
        first = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=30,
            now=self.now,
        )
        renewed = self.leases.renew(
            first,
            lease_seconds=30,
            now=self.now + timedelta(seconds=10),
        )
        self.assertEqual(first.fencing_token, renewed.fencing_token)
        self.assertEqual(first.lease_token, renewed.lease_token)
        self.assertGreater(renewed.lease_expires_at, first.lease_expires_at)


if __name__ == "__main__":
    unittest.main()
