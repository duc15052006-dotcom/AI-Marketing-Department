from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_store import MissionStore, MissionStoreAuthorityError


class FencedMissionPersistenceV1Tests(unittest.TestCase):
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
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self) -> None:
        self.leases.close()
        self.store.close()
        self._tmp.cleanup()

    def _persist_waiting_mission(self, mission_id: str = "MISSION-FENCE-1") -> MissionRecord:
        mission = MissionRecord(
            mission_id=mission_id,
            objective="Crash-safe long-lived marketing mission",
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

    def _save_with_lease(self, mission: MissionRecord, lease: object) -> None:
        self.store.save_mission_fenced(
            mission,
            worker_id=lease.lease_owner,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )

    def test_current_fence_can_persist_mission_snapshot(self) -> None:
        mission = self._persist_waiting_mission()
        lease = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        mission.transition_to(MissionStatus.ACTIVE)
        self._save_with_lease(mission, lease)
        restored = self.store.get_mission(
            mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(MissionStatus.ACTIVE, restored.status)

    def test_stale_fence_cannot_write_after_takeover(self) -> None:
        mission = self._persist_waiting_mission()
        stale = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=1,
            now=self.now,
        )
        current = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-b",
            lease_seconds=60,
            now=self.now + timedelta(seconds=2),
        )
        self.assertGreater(current.fencing_token, stale.fencing_token)

        mission.transition_to(MissionStatus.ACTIVE)
        with self.assertRaises(MissionStoreAuthorityError):
            self._save_with_lease(mission, stale)

        self._save_with_lease(mission, current)
        restored = self.store.get_mission(
            mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(MissionStatus.ACTIVE, restored.status)

    def test_plain_save_cannot_bypass_an_established_write_fence(self) -> None:
        mission = self._persist_waiting_mission()
        self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        mission.transition_to(MissionStatus.ACTIVE)
        with self.assertRaises(MissionStoreAuthorityError):
            self.store.save_mission(mission)

    def test_fence_is_bound_to_exact_worker_and_opaque_lease_token(self) -> None:
        mission = self._persist_waiting_mission()
        lease = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        mission.transition_to(MissionStatus.ACTIVE)
        with self.assertRaises(MissionStoreAuthorityError):
            self.store.save_mission_fenced(
                mission,
                worker_id="worker-foreign",
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
        with self.assertRaises(MissionStoreAuthorityError):
            self.store.save_mission_fenced(
                mission,
                worker_id=lease.lease_owner,
                lease_token="forged-token",
                fencing_token=lease.fencing_token,
            )

    def test_fenced_authority_survives_mission_store_reopen(self) -> None:
        mission = self._persist_waiting_mission()
        lease = self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id="worker-a",
            lease_seconds=60,
            now=self.now,
        )
        self.leases.close()
        self.store.close()
        self.store = MissionStore(database_path=self.mission_db)
        self.leases = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )

        restored = self.store.get_mission(
            mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        restored.transition_to(MissionStatus.ACTIVE)
        self._save_with_lease(restored, lease)


if __name__ == "__main__":
    unittest.main()
