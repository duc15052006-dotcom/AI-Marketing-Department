from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_checkpoint import DurableMissionCheckpointStore
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_scheduler import DurableMissionScheduler, WakeState
from runtime.mission_store import MissionStore
from runtime.persistent_worker import (
    PersistentMissionWorker,
    PersistentWorkerCycleResult,
    PersistentWorkerCycleStatus,
)


class RuntimeContinuityAuthorityStackV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mission_db = str(root / "missions.sqlite3")
        self.scheduler_db = str(root / "mission-wakes.sqlite3")
        self.lease_db = str(root / "mission-leases.sqlite3")
        self.checkpoint_db = str(root / "mission-checkpoints.sqlite3")
        self.base = datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc)
        self.now = [self.base]
        self._open_runtime()
        self.mission = self._create_mission()

    def tearDown(self) -> None:
        for name in ("checkpoints", "leases", "scheduler", "store"):
            value = getattr(self, name, None)
            if value is not None:
                value.close()
        self._tmp.cleanup()

    def _open_runtime(self) -> None:
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
        self.worker = PersistentMissionWorker(
            mission_store=self.store,
            scheduler=self.scheduler,
            mission_leases=self.leases,
            checkpoints=self.checkpoints,
            clock=lambda: self.now[0],
        )

    def _reopen_runtime(self) -> None:
        for name in ("checkpoints", "leases", "scheduler", "store"):
            getattr(self, name).close()
        self._open_runtime()

    def _create_mission(self) -> MissionRecord:
        mission = MissionRecord(
            mission_id="MISSION-CONTINUITY-STACK-1",
            objective="Qualify durable Continuity Runtime authority composition",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id="COMMIT-CONTINUITY-STACK-1",
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

    def test_restart_resume_preserves_checkpoint_wake_and_monotonic_fence(self) -> None:
        first_wake = self.scheduler.schedule_wake(
            wake_id="WAKE-CONTINUITY-STACK-A",
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
            due_at=self.base,
            reason="integration-start",
            now=self.base,
        )
        seen_fences: list[int] = []

        def first_executor(context):
            seen_fences.append(context.fencing_token)
            self.assertIsNone(context.restored_checkpoint)
            return PersistentWorkerCycleResult(
                resume_cursor="phase:research",
                state={"phase": "research", "step": 1},
                next_wake_at=self.base + timedelta(seconds=5),
                next_wake_reason="resume-after-process-reopen",
            )

        first = self.worker.run_once(
            worker_id="worker-a",
            executor=first_executor,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )
        self.assertEqual(PersistentWorkerCycleStatus.CONTINUED, first.status)
        self.assertEqual(1, first.checkpoint_sequence)
        self.assertIsNotNone(first.next_wake_id)

        consumed = self.scheduler.get_wake(
            first_wake.wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(consumed)
        assert consumed is not None
        self.assertEqual(WakeState.ACKNOWLEDGED, consumed.state)

        self.now[0] = self.base + timedelta(seconds=6)
        self._reopen_runtime()

        def second_executor(context):
            seen_fences.append(context.fencing_token)
            self.assertIsNotNone(context.restored_checkpoint)
            assert context.restored_checkpoint is not None
            self.assertEqual(1, context.restored_checkpoint.checkpoint_sequence)
            self.assertEqual("phase:research", context.restored_checkpoint.resume_cursor)
            self.assertEqual(
                {"phase": "research", "step": 1},
                context.restored_checkpoint.state,
            )
            return PersistentWorkerCycleResult(
                resume_cursor="phase:complete",
                state={"phase": "complete", "step": 2},
            )

        second = self.worker.run_once(
            worker_id="worker-b",
            executor=second_executor,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )
        self.assertEqual(PersistentWorkerCycleStatus.FINISHED, second.status)
        self.assertEqual(2, second.checkpoint_sequence)
        self.assertIsNone(second.next_wake_id)
        self.assertEqual(2, len(seen_fences))
        self.assertGreater(seen_fences[1], seen_fences[0])

        resumed_wake = self.scheduler.get_wake(
            first.next_wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(resumed_wake)
        assert resumed_wake is not None
        self.assertEqual(WakeState.ACKNOWLEDGED, resumed_wake.state)

        latest = self.checkpoints.get_latest(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(2, latest.checkpoint_sequence)
        self.assertEqual("phase:complete", latest.resume_cursor)
        self.assertEqual({"phase": "complete", "step": 2}, latest.state)

        # Prove the integrated fenced Mission persistence boundary accepts only a
        # fresh post-restart fencing epoch, then release it cleanly.
        third = self.leases.acquire(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
            worker_id="worker-c",
            lease_seconds=120,
            now=self.now[0] + timedelta(seconds=1),
        )
        self.assertGreater(third.fencing_token, seen_fences[1])
        persisted = self.store.get_mission(
            self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.store.save_mission_fenced(
            persisted,
            worker_id=third.lease_owner or "",
            lease_token=third.lease_token or "",
            fencing_token=third.fencing_token,
            now=self.now[0] + timedelta(seconds=1),
        )
        released = self.leases.release(
            third,
            now=self.now[0] + timedelta(seconds=2),
        )
        self.assertIsNone(released.lease_owner)


if __name__ == "__main__":
    unittest.main()
