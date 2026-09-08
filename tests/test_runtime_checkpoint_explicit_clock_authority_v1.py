from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


class RuntimeCheckpointExplicitClockAuthorityV1Tests(unittest.TestCase):
    """Expose split authority time between PersistentWorker and checkpoint store."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mission_db = str(root / "missions.sqlite3")
        self.scheduler_db = str(root / "wakes.sqlite3")
        self.lease_db = str(root / "leases.sqlite3")
        self.checkpoint_db = str(root / "checkpoints.sqlite3")
        self.store = MissionStore(database_path=self.mission_db)
        self.scheduler = DurableMissionScheduler(
            database_path=self.scheduler_db,
            mission_store=self.store,
        )
        self.leases = DurableMissionLeaseStore(
            database_path=self.lease_db,
            mission_store=self.store,
        )
        self.checkpoints = DurableMissionCheckpointStore(
            database_path=self.checkpoint_db,
            mission_store=self.store,
            lease_database_path=self.lease_db,
        )

    def tearDown(self) -> None:
        for value in (self.checkpoints, self.leases, self.scheduler, self.store):
            value.close()
        self._tmp.cleanup()

    def _mission(self, *, mission_id: str, now: datetime) -> MissionRecord:
        mission = MissionRecord(
            mission_id=mission_id,
            objective="Qualify explicit Continuity authority clock propagation",
            business_id="BIZ-CLOCK",
            project_id="PROJ-CLOCK",
            user_id="USER-CLOCK",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id=f"COMMIT-{mission_id}",
                mission_id=mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                user_id=mission.user_id,
                authority_mode="SUPERVISED",
                deadline_at=now + timedelta(days=1),
            ),
            now=now,
        )
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_TIME)
        self.store.save_mission(mission)
        return mission

    @staticmethod
    def _executor(_context) -> PersistentWorkerCycleResult:
        return PersistentWorkerCycleResult(
            resume_cursor="phase:clock-authority",
            state={"phase": "clock-authority"},
        )

    def test_explicit_worker_clock_must_reach_checkpoint_authority(self) -> None:
        """Injected authority time must not be replaced by checkpoint wall clock."""
        explicit_now = datetime(2001, 1, 1, 0, 0, tzinfo=timezone.utc)
        mission = self._mission(mission_id="MISSION-EXPLICIT-CLOCK", now=explicit_now)
        self.scheduler.schedule_wake(
            wake_id="WAKE-EXPLICIT-CLOCK",
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=explicit_now,
            reason="explicit-clock-red",
            now=explicit_now,
        )
        worker = PersistentMissionWorker(
            mission_store=self.store,
            scheduler=self.scheduler,
            mission_leases=self.leases,
            checkpoints=self.checkpoints,
            clock=lambda: explicit_now,
        )

        report = worker.run_once(
            worker_id="worker-explicit-clock",
            executor=self._executor,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )

        self.assertEqual(PersistentWorkerCycleStatus.FINISHED, report.status)
        self.assertEqual(1, report.checkpoint_sequence)

    def test_wall_clock_control_remains_valid(self) -> None:
        """Control: ordinary wall-clock execution still checkpoints successfully."""
        wall_now = datetime.now(timezone.utc)
        mission = self._mission(mission_id="MISSION-WALL-CLOCK", now=wall_now)
        self.scheduler.schedule_wake(
            wake_id="WAKE-WALL-CLOCK",
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=wall_now,
            reason="wall-clock-control",
            now=wall_now,
        )
        worker = PersistentMissionWorker(
            mission_store=self.store,
            scheduler=self.scheduler,
            mission_leases=self.leases,
            checkpoints=self.checkpoints,
        )

        report = worker.run_once(
            worker_id="worker-wall-clock",
            executor=self._executor,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )

        self.assertEqual(PersistentWorkerCycleStatus.FINISHED, report.status)
        self.assertEqual(1, report.checkpoint_sequence)


if __name__ == "__main__":
    unittest.main()
