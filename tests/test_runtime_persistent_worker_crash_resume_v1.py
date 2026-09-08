from __future__ import annotations

import sqlite3
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


class SimulatedProcessCrash(RuntimeError):
    pass


class RuntimePersistentWorkerCrashResumeV1Tests(unittest.TestCase):
    """A durably completed source wake must not replay semantic work after crash."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mission_db = str(root / "missions.sqlite3")
        self.scheduler_db = str(root / "mission-wakes.sqlite3")
        self.lease_db = str(root / "mission-leases.sqlite3")
        self.checkpoint_db = str(root / "mission-checkpoints.sqlite3")
        self.base = datetime.now(timezone.utc).replace(microsecond=0)
        self.now = [self.base]
        self._open_runtime()
        self.mission = self._create_mission()

    def tearDown(self) -> None:
        self._close_runtime()
        self._tmp.cleanup()

    def _close_runtime(self) -> None:
        for name in ("checkpoints", "leases", "scheduler", "store"):
            value = getattr(self, name, None)
            if value is not None:
                try:
                    value.close()
                except Exception:
                    pass
                setattr(self, name, None)

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

    def _reopen_after_lease_expiry(self) -> None:
        self._close_runtime()
        self.now[0] = self.base + timedelta(seconds=121)
        self._open_runtime()

    def _create_mission(self) -> MissionRecord:
        mission = MissionRecord(
            mission_id="MISSION-CRASH-RESUME-1",
            objective="Prove post-checkpoint crash recovery cannot replay a wake",
            business_id="BIZ-1",
            project_id="PROJ-1",
            user_id="USER-1",
        )
        mission.mark_ready(
            CommitmentRecord(
                commitment_id="COMMIT-CRASH-RESUME-1",
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

    def _schedule_source(self, wake_id: str) -> None:
        self.scheduler.schedule_wake(
            wake_id=wake_id,
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
            due_at=self.base,
            reason="crash-resume-source",
            now=self.base,
        )

    def _wake(self, wake_id: str):
        return self.scheduler.get_wake(
            wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )

    def _wake_count(self) -> int:
        connection = sqlite3.connect(self.scheduler_db)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM mission_wakes WHERE mission_id = ?",
                (self.mission.mission_id,),
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        return int(row[0])

    def _latest_checkpoint(self):
        return self.checkpoints.get_latest(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )

    def test_crash_after_checkpoint_before_continuation_schedule_does_not_replay_executor(self) -> None:
        source_id = "WAKE-CRASH-BEFORE-SCHEDULE"
        self._schedule_source(source_id)

        def first_executor(_context):
            return PersistentWorkerCycleResult(
                resume_cursor="phase:checkpointed",
                state={"step": 1, "phase": "checkpointed"},
                next_wake_at=self.base + timedelta(seconds=5),
                next_wake_reason="continue-after-crash",
            )

        original_schedule = self.scheduler.schedule_wake

        def crash_before_schedule(**_kwargs):
            raise SimulatedProcessCrash("CRASH_AFTER_CHECKPOINT_BEFORE_CONTINUATION_SCHEDULE")

        self.scheduler.schedule_wake = crash_before_schedule  # type: ignore[method-assign]
        with self.assertRaises(SimulatedProcessCrash):
            self.worker.run_once(
                worker_id="worker-a",
                executor=first_executor,
                wake_lease_seconds=120,
                mission_lease_seconds=120,
            )
        self.scheduler.schedule_wake = original_schedule  # type: ignore[method-assign]

        checkpoint = self._latest_checkpoint()
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertEqual(1, checkpoint.checkpoint_sequence)
        self.assertEqual(source_id, checkpoint.source_wake_id)
        self.assertEqual({"step": 1, "phase": "checkpointed"}, checkpoint.state)
        self.assertIsInstance(checkpoint.worker_cycle, dict)
        assert checkpoint.worker_cycle is not None
        persisted_next_id = checkpoint.worker_cycle.get("next_wake_id")
        self.assertIsInstance(persisted_next_id, str)
        self.assertTrue(persisted_next_id)
        self.assertEqual(1, self._wake_count())
        source = self._wake(source_id)
        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(WakeState.LEASED, source.state)

        self._reopen_after_lease_expiry()
        replayed: list[str] = []

        def forbidden_replay(context):
            replayed.append(context.wake_id)
            return PersistentWorkerCycleResult(
                resume_cursor="phase:incorrect-replay",
                state={"step": 2, "replayed": True},
                next_wake_at=self.now[0] + timedelta(seconds=5),
                next_wake_reason="incorrect-duplicate",
            )

        recovered = self.worker.run_once(
            worker_id="worker-b",
            executor=forbidden_replay,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )

        self.assertEqual([], replayed, "durably checkpointed source wake was executed again")
        self.assertEqual(PersistentWorkerCycleStatus.CONTINUED, recovered.status)
        self.assertEqual(1, recovered.checkpoint_sequence)
        self.assertEqual(persisted_next_id, recovered.next_wake_id)
        self.assertEqual(2, self._wake_count())
        source = self._wake(source_id)
        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(WakeState.ACKNOWLEDGED, source.state)

    def test_crash_after_continuation_schedule_before_source_ack_does_not_duplicate_continuation(self) -> None:
        source_id = "WAKE-CRASH-AFTER-SCHEDULE"
        self._schedule_source(source_id)
        scheduled = []
        original_schedule = self.scheduler.schedule_wake

        def capture_schedule(**kwargs):
            record = original_schedule(**kwargs)
            scheduled.append(record)
            return record

        self.scheduler.schedule_wake = capture_schedule  # type: ignore[method-assign]

        def first_executor(_context):
            return PersistentWorkerCycleResult(
                resume_cursor="phase:scheduled",
                state={"step": 1, "phase": "scheduled"},
                next_wake_at=self.base + timedelta(seconds=5),
                next_wake_reason="already-scheduled-continuation",
            )

        def crash_before_ack(*_args, **_kwargs):
            raise SimulatedProcessCrash("CRASH_AFTER_CONTINUATION_SCHEDULE_BEFORE_SOURCE_ACK")

        self.worker._dispatcher.finish_delivery = crash_before_ack  # type: ignore[method-assign]
        with self.assertRaises(SimulatedProcessCrash):
            self.worker.run_once(
                worker_id="worker-a",
                executor=first_executor,
                wake_lease_seconds=120,
                mission_lease_seconds=120,
            )

        self.assertEqual(1, len(scheduled))
        original_next_id = scheduled[0].wake_id
        self.assertEqual(2, self._wake_count())
        checkpoint = self._latest_checkpoint()
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertEqual(1, checkpoint.checkpoint_sequence)
        self.assertEqual(source_id, checkpoint.source_wake_id)
        self.assertIsInstance(checkpoint.worker_cycle, dict)
        assert checkpoint.worker_cycle is not None
        self.assertEqual(original_next_id, checkpoint.worker_cycle.get("next_wake_id"))

        self._reopen_after_lease_expiry()
        replayed: list[str] = []

        def forbidden_replay(context):
            replayed.append(context.wake_id)
            return PersistentWorkerCycleResult(
                resume_cursor="phase:incorrect-replay",
                state={"step": 2, "replayed": True},
                next_wake_at=self.now[0] + timedelta(seconds=10),
                next_wake_reason="duplicate-continuation",
            )

        recovered = self.worker.run_once(
            worker_id="worker-b",
            executor=forbidden_replay,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )

        self.assertEqual([], replayed, "source wake replayed after continuation was already durable")
        self.assertEqual(PersistentWorkerCycleStatus.CONTINUED, recovered.status)
        self.assertEqual(1, recovered.checkpoint_sequence)
        self.assertEqual(original_next_id, recovered.next_wake_id)
        self.assertEqual(2, self._wake_count(), "recovery created a duplicate continuation wake")
        existing_next = self._wake(original_next_id)
        self.assertIsNotNone(existing_next)
        source = self._wake(source_id)
        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(WakeState.ACKNOWLEDGED, source.state)

    def test_crash_after_final_checkpoint_before_ack_finishes_without_replaying_executor(self) -> None:
        source_id = "WAKE-CRASH-FINAL-BEFORE-ACK"
        self._schedule_source(source_id)

        def first_executor(_context):
            return PersistentWorkerCycleResult(
                resume_cursor="phase:complete",
                state={"step": 1, "phase": "complete"},
            )

        def crash_before_ack(*_args, **_kwargs):
            raise SimulatedProcessCrash("CRASH_AFTER_FINAL_CHECKPOINT_BEFORE_SOURCE_ACK")

        self.worker._dispatcher.finish_delivery = crash_before_ack  # type: ignore[method-assign]
        with self.assertRaises(SimulatedProcessCrash):
            self.worker.run_once(
                worker_id="worker-a",
                executor=first_executor,
                wake_lease_seconds=120,
                mission_lease_seconds=120,
            )

        checkpoint = self._latest_checkpoint()
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertEqual(1, checkpoint.checkpoint_sequence)
        self.assertEqual(source_id, checkpoint.source_wake_id)
        self.assertEqual({"step": 1, "phase": "complete"}, checkpoint.state)
        self.assertIsInstance(checkpoint.worker_cycle, dict)
        assert checkpoint.worker_cycle is not None
        self.assertIsNone(checkpoint.worker_cycle.get("next_wake_id"))
        self.assertEqual(1, self._wake_count())

        self._reopen_after_lease_expiry()
        replayed: list[str] = []

        def forbidden_replay(context):
            replayed.append(context.wake_id)
            return PersistentWorkerCycleResult(
                resume_cursor="phase:incorrect-replay",
                state={"step": 2, "replayed": True},
            )

        recovered = self.worker.run_once(
            worker_id="worker-b",
            executor=forbidden_replay,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )

        self.assertEqual([], replayed, "final checkpointed source wake was executed again")
        self.assertEqual(PersistentWorkerCycleStatus.FINISHED, recovered.status)
        self.assertEqual(1, recovered.checkpoint_sequence)
        self.assertIsNone(recovered.next_wake_id)
        self.assertEqual(1, self._wake_count())
        source = self._wake(source_id)
        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(WakeState.ACKNOWLEDGED, source.state)


if __name__ == "__main__":
    unittest.main()
