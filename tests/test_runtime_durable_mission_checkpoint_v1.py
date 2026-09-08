from __future__ import annotations

import importlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_store import MissionStore


class DurableMissionCheckpointV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            module = importlib.import_module("runtime.mission_checkpoint")
        except ModuleNotFoundError:
            cls.CheckpointStore = None
            cls.CheckpointAuthorityError = None
            cls.CheckpointStateError = None
        else:
            cls.CheckpointStore = getattr(module, "DurableMissionCheckpointStore", None)
            cls.CheckpointAuthorityError = getattr(
                module, "MissionCheckpointAuthorityError", None
            )
            cls.CheckpointStateError = getattr(module, "MissionCheckpointStateError", None)

    def setUp(self) -> None:
        if (
            self.CheckpointStore is None
            or self.CheckpointAuthorityError is None
            or self.CheckpointStateError is None
        ):
            self.fail(
                "MISSION_CHECKPOINT_DURABILITY_BOUNDARY_MISSING: "
                "runtime.mission_checkpoint must expose the durable fenced checkpoint contract"
            )

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mission_db = str(root / "missions.sqlite3")
        self.lease_db = str(root / "mission-leases.sqlite3")
        self.checkpoint_db = str(root / "mission-checkpoints.sqlite3")
        self.store = MissionStore(database_path=self.mission_db)
        self.leases = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )
        self.checkpoints = self.CheckpointStore(
            database_path=self.checkpoint_db,
            mission_store=self.store,
            lease_database_path=self.lease_db,
        )
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self) -> None:
        for name in ("checkpoints", "leases", "store"):
            value = getattr(self, name, None)
            if value is not None:
                value.close()
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def _mission(self, mission_id: str = "MISSION-CP-1") -> MissionRecord:
        mission = MissionRecord(
            mission_id=mission_id,
            objective="Crash-safe persistent Mission continuation",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        commitment = CommitmentRecord(
            commitment_id=f"COMMIT-{mission_id}",
            mission_id=mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            user_id=mission.user_id,
            authority_mode="SUPERVISED",
            deadline_at=self.now + timedelta(days=7),
        )
        mission.mark_ready(commitment, now=self.now)
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_TIME)
        self.store.save_mission(mission)
        return mission

    def _lease(self, mission: MissionRecord, worker: str, *, now: datetime, seconds: float = 60):
        return self.leases.acquire(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id=worker,
            lease_seconds=seconds,
            now=now,
        )

    def _save(self, mission: MissionRecord, lease: object, *, sequence: int, cursor: str):
        return self.checkpoints.save_checkpoint(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            worker_id=lease.lease_owner,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
            checkpoint_sequence=sequence,
            resume_cursor=cursor,
            state={"cursor": cursor, "attempt": sequence},
        )

    def test_current_fence_persists_and_restores_detached_checkpoint(self) -> None:
        mission = self._mission()
        lease = self._lease(mission, "worker-a", now=self.now)
        written = self._save(mission, lease, sequence=1, cursor="phase:research")

        restored = self.checkpoints.get_latest(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(written.checkpoint_id, restored.checkpoint_id)
        self.assertEqual(1, restored.checkpoint_sequence)
        self.assertEqual("phase:research", restored.resume_cursor)
        self.assertEqual(lease.fencing_token, restored.fencing_token)

        restored.state["cursor"] = "tampered"
        again = self.checkpoints.get_latest(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
        )
        self.assertEqual("phase:research", again.state["cursor"])

    def test_stale_worker_cannot_checkpoint_after_crash_takeover(self) -> None:
        mission = self._mission()
        stale = self._lease(mission, "worker-a", now=self.now, seconds=1)
        self._save(mission, stale, sequence=1, cursor="phase:plan")

        current = self._lease(
            mission,
            "worker-b",
            now=self.now + timedelta(seconds=2),
            seconds=60,
        )
        self.assertGreater(current.fencing_token, stale.fencing_token)

        with self.assertRaises(self.CheckpointAuthorityError):
            self._save(mission, stale, sequence=2, cursor="phase:stale-action")

        fresh = self._save(mission, current, sequence=2, cursor="phase:resume")
        self.assertEqual(current.fencing_token, fresh.fencing_token)

    def test_checkpoint_sequence_must_advance_monotonically(self) -> None:
        mission = self._mission()
        lease = self._lease(mission, "worker-a", now=self.now)
        self._save(mission, lease, sequence=3, cursor="phase:creative")

        with self.assertRaises(self.CheckpointStateError):
            self._save(mission, lease, sequence=3, cursor="phase:duplicate")
        with self.assertRaises(self.CheckpointStateError):
            self._save(mission, lease, sequence=2, cursor="phase:rollback")

    def test_checkpoint_read_is_exact_scope_authority(self) -> None:
        mission = self._mission()
        lease = self._lease(mission, "worker-a", now=self.now)
        self._save(mission, lease, sequence=1, cursor="phase:strategy")

        self.assertIsNone(
            self.checkpoints.get_latest(
                mission_id=mission.mission_id,
                business_id="BIZ-FOREIGN",
                project_id=mission.project_id,
            )
        )
        self.assertIsNone(
            self.checkpoints.get_latest(
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id="PROJ-FOREIGN",
            )
        )

    def test_checkpoint_survives_process_style_reopen(self) -> None:
        mission = self._mission()
        lease = self._lease(mission, "worker-a", now=self.now)
        written = self._save(mission, lease, sequence=1, cursor="phase:waiting-result")

        self.checkpoints.close()
        self.checkpoints = self.CheckpointStore(
            database_path=self.checkpoint_db,
            mission_store=self.store,
            lease_database_path=self.lease_db,
        )
        restored = self.checkpoints.get_latest(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(written.checkpoint_id, restored.checkpoint_id)
        self.assertEqual("phase:waiting-result", restored.resume_cursor)
        self.assertEqual({"cursor": "phase:waiting-result", "attempt": 1}, restored.state)


if __name__ == "__main__":
    unittest.main()
