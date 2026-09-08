from __future__ import annotations

import importlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_checkpoint import DurableMissionCheckpointStore
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_scheduler import DurableMissionScheduler, WakeState
from runtime.mission_store import MissionStore


class RuntimePersistentWorkerWakeCycleV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            module = importlib.import_module("runtime.persistent_worker")
        except ModuleNotFoundError:
            module = None

        cls.PersistentMissionWorker = (
            None if module is None else getattr(module, "PersistentMissionWorker", None)
        )
        cls.PersistentWorkerCycleContext = (
            None
            if module is None
            else getattr(module, "PersistentWorkerCycleContext", None)
        )
        cls.PersistentWorkerCycleResult = (
            None
            if module is None
            else getattr(module, "PersistentWorkerCycleResult", None)
        )
        cls.PersistentWorkerCycleStatus = (
            None
            if module is None
            else getattr(module, "PersistentWorkerCycleStatus", None)
        )
        cls.PersistentWorkerAuthorityError = (
            None
            if module is None
            else getattr(module, "PersistentWorkerAuthorityError", None)
        )

    def setUp(self) -> None:
        required = (
            self.PersistentMissionWorker,
            self.PersistentWorkerCycleContext,
            self.PersistentWorkerCycleResult,
            self.PersistentWorkerCycleStatus,
            self.PersistentWorkerAuthorityError,
        )
        if any(value is None for value in required):
            self.fail(
                "PERSISTENT_WORKER_WAKE_CYCLE_BOUNDARY_MISSING: "
                "runtime.persistent_worker must expose the bounded durable wake-cycle contract"
            )

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mission_db = str(root / "missions.sqlite3")
        self.scheduler_db = str(root / "mission-wakes.sqlite3")
        self.lease_db = str(root / "mission-leases.sqlite3")
        self.checkpoint_db = str(root / "mission-checkpoints.sqlite3")
        self.base = datetime.now(timezone.utc).replace(microsecond=0)
        self.fake_now = [self.base]
        self._open_runtime()
        self.mission = self._create_mission()

    def tearDown(self) -> None:
        for name in ("checkpoints", "leases", "scheduler", "store"):
            value = getattr(self, name, None)
            if value is not None:
                value.close()
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

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
        self.worker = self.PersistentMissionWorker(
            mission_store=self.store,
            scheduler=self.scheduler,
            mission_leases=self.leases,
            checkpoints=self.checkpoints,
            clock=lambda: self.fake_now[0],
        )

    def _reopen_runtime(self) -> None:
        for name in ("checkpoints", "leases", "scheduler", "store"):
            getattr(self, name).close()
        self._open_runtime()

    def _create_mission(self, mission_id: str = "MISSION-WORKER-1") -> MissionRecord:
        mission = MissionRecord(
            mission_id=mission_id,
            objective="Execute one durable bounded worker wake cycle",
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

    def _schedule(self, wake_id: str, *, due_at: datetime | None = None):
        return self.scheduler.schedule_wake(
            wake_id=wake_id,
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
            due_at=due_at or self.fake_now[0],
            reason="persistent-worker-contract",
            now=self.fake_now[0],
        )

    def test_no_due_wake_is_idle_and_executor_is_not_called(self) -> None:
        calls = []

        def executor(context):
            calls.append(context)
            raise AssertionError("executor must not run without due work")

        report = self.worker.run_once(
            worker_id="worker-a",
            executor=executor,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )

        self.assertEqual(self.PersistentWorkerCycleStatus.IDLE, report.status)
        self.assertEqual([], calls)
        self.assertIsNone(report.mission_id)
        self.assertIsNone(report.wake_id)

    def test_due_wake_restores_executes_checkpoints_schedules_and_acks_once(self) -> None:
        wake = self._schedule("WAKE-A")
        seen = []

        def executor(context):
            self.assertIsInstance(context, self.PersistentWorkerCycleContext)
            self.assertEqual(self.mission.mission_id, context.mission_id)
            self.assertEqual(self.mission.business_id, context.business_id)
            self.assertEqual(self.mission.project_id, context.project_id)
            self.assertEqual(wake.wake_id, context.wake_id)
            self.assertIsNone(context.restored_checkpoint)
            self.assertGreaterEqual(context.fencing_token, 1)
            seen.append(context)
            return self.PersistentWorkerCycleResult(
                resume_cursor="phase:plan",
                state={"step": 1, "phase": "plan"},
                next_wake_at=self.base + timedelta(seconds=5),
                next_wake_reason="continue-mission",
            )

        report = self.worker.run_once(
            worker_id="worker-a",
            executor=executor,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )

        self.assertEqual(1, len(seen))
        self.assertEqual(self.PersistentWorkerCycleStatus.CONTINUED, report.status)
        self.assertEqual(1, report.checkpoint_sequence)
        self.assertIsNotNone(report.next_wake_id)

        latest = self.checkpoints.get_latest(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(1, latest.checkpoint_sequence)
        self.assertEqual("phase:plan", latest.resume_cursor)
        self.assertEqual({"step": 1, "phase": "plan"}, latest.state)

        original = self.scheduler.get_wake(
            wake.wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(original)
        assert original is not None
        self.assertEqual(WakeState.ACKNOWLEDGED, original.state)

        next_wake = self.scheduler.get_wake(
            report.next_wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(next_wake)
        assert next_wake is not None
        self.assertEqual(WakeState.SCHEDULED, next_wake.state)
        self.assertEqual(self.base + timedelta(seconds=5), next_wake.due_at)

    def test_process_style_reopen_restores_latest_checkpoint_and_advances_sequence(self) -> None:
        self._schedule("WAKE-REOPEN-A")

        first = self.worker.run_once(
            worker_id="worker-a",
            executor=lambda context: self.PersistentWorkerCycleResult(
                resume_cursor="phase:research",
                state={"step": 1, "phase": "research"},
                next_wake_at=self.base + timedelta(seconds=1),
                next_wake_reason="resume-after-restart",
            ),
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )
        self.assertEqual(self.PersistentWorkerCycleStatus.CONTINUED, first.status)

        self.fake_now[0] = self.base + timedelta(seconds=2)
        self._reopen_runtime()
        restored_seen = []

        def second_executor(context):
            restored_seen.append(context.restored_checkpoint)
            self.assertIsNotNone(context.restored_checkpoint)
            self.assertEqual(1, context.restored_checkpoint.checkpoint_sequence)
            self.assertEqual("phase:research", context.restored_checkpoint.resume_cursor)
            self.assertEqual(
                {"step": 1, "phase": "research"},
                context.restored_checkpoint.state,
            )
            return self.PersistentWorkerCycleResult(
                resume_cursor="phase:strategy",
                state={"step": 2, "phase": "strategy"},
            )

        second = self.worker.run_once(
            worker_id="worker-b",
            executor=second_executor,
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )
        self.assertEqual(1, len(restored_seen))
        self.assertEqual(self.PersistentWorkerCycleStatus.FINISHED, second.status)
        self.assertEqual(2, second.checkpoint_sequence)
        self.assertIsNone(second.next_wake_id)

        latest = self.checkpoints.get_latest(
            mission_id=self.mission.mission_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(2, latest.checkpoint_sequence)
        self.assertEqual("phase:strategy", latest.resume_cursor)
        self.assertEqual({"step": 2, "phase": "strategy"}, latest.state)

    def test_stale_worker_after_crash_takeover_cannot_checkpoint_or_ack(self) -> None:
        wake = self._schedule("WAKE-STALE")

        def executor(context):
            takeover_at = self.base + timedelta(seconds=121)
            self.leases.acquire(
                mission_id=self.mission.mission_id,
                business_id=self.mission.business_id,
                project_id=self.mission.project_id,
                worker_id="worker-b",
                lease_seconds=120,
                now=takeover_at,
            )
            self.fake_now[0] = takeover_at
            return self.PersistentWorkerCycleResult(
                resume_cursor="phase:stale",
                state={"step": "must-not-persist"},
            )

        with self.assertRaises(self.PersistentWorkerAuthorityError):
            self.worker.run_once(
                worker_id="worker-a",
                executor=executor,
                wake_lease_seconds=120,
                mission_lease_seconds=120,
            )

        self.assertIsNone(
            self.checkpoints.get_latest(
                mission_id=self.mission.mission_id,
                business_id=self.mission.business_id,
                project_id=self.mission.project_id,
            )
        )
        current_wake = self.scheduler.get_wake(
            wake.wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(current_wake)
        assert current_wake is not None
        self.assertEqual(WakeState.LEASED, current_wake.state)
        self.assertNotEqual(WakeState.ACKNOWLEDGED, current_wake.state)

    def test_run_once_is_bounded_to_one_wake_and_terminal_mission_is_not_resurrected(self) -> None:
        first = self._schedule("WAKE-BOUND-A")
        second = self._schedule("WAKE-BOUND-B")
        calls = []

        report = self.worker.run_once(
            worker_id="worker-a",
            executor=lambda context: (
                calls.append(context.wake_id)
                or self.PersistentWorkerCycleResult(
                    resume_cursor="phase:bounded",
                    state={"handled": context.wake_id},
                )
            ),
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )
        self.assertEqual(self.PersistentWorkerCycleStatus.FINISHED, report.status)
        self.assertEqual([first.wake_id], calls)

        untouched = self.scheduler.get_wake(
            second.wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(untouched)
        assert untouched is not None
        self.assertEqual(WakeState.SCHEDULED, untouched.state)

        self.mission.transition_to(MissionStatus.CANCELLED)
        self.store.save_mission(self.mission)

        terminal_calls = []
        terminal_report = self.worker.run_once(
            worker_id="worker-b",
            executor=lambda context: terminal_calls.append(context),
            wake_lease_seconds=120,
            mission_lease_seconds=120,
        )
        self.assertEqual(self.PersistentWorkerCycleStatus.IDLE, terminal_report.status)
        self.assertEqual([], terminal_calls)

        cancelled_wake = self.scheduler.get_wake(
            second.wake_id,
            business_id=self.mission.business_id,
            project_id=self.mission.project_id,
        )
        self.assertIsNotNone(cancelled_wake)
        assert cancelled_wake is not None
        self.assertEqual(WakeState.CANCELLED, cancelled_wake.state)


if __name__ == "__main__":
    unittest.main()
