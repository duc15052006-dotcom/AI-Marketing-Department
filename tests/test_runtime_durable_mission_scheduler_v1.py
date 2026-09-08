from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_store import MissionStore
from runtime.mission_scheduler import (
    DurableMissionScheduler,
    MissionSchedulerAuthorityError,
    MissionSchedulerLeaseError,
    MissionSchedulerStateError,
    WakeState,
)


class DurableMissionSchedulerV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mission_db = str(root / "missions.sqlite3")
        self.scheduler_db = str(root / "scheduler.sqlite3")
        self.store = MissionStore(database_path=self.mission_db)
        self.scheduler = DurableMissionScheduler(
            database_path=self.scheduler_db,
            mission_store=self.store,
        )
        self.now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.scheduler.close()
        self.store.close()
        self._tmp.cleanup()

    def _persist_waiting_mission(
        self,
        *,
        mission_id: str = "MISSION-1",
        business_id: str = "BIZ-1",
        project_id: str | None = "PROJ-1",
        user_id: str = "USER-1",
    ) -> MissionRecord:
        mission = MissionRecord(
            mission_id=mission_id,
            objective="Run a durable long-lived marketing mission",
            business_id=business_id,
            project_id=project_id,
            user_id=user_id,
        )
        commitment = CommitmentRecord(
            commitment_id=f"COMMIT-{mission_id}",
            mission_id=mission_id,
            business_id=business_id,
            project_id=project_id,
            user_id=user_id,
            authority_mode="SUPERVISED",
            deadline_at=self.now + timedelta(days=7),
        )
        mission.mark_ready(commitment, now=self.now)
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.WAITING_FOR_TIME)
        self.store.save_mission(mission)
        return mission

    def test_scheduled_wake_survives_scheduler_process_reopen(self) -> None:
        mission = self._persist_waiting_mission()
        wake = self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now + timedelta(hours=2),
            reason="RECHECK_CAMPAIGN_TELEMETRY",
            wake_id="WAKE-PERSIST-1",
            now=self.now,
        )
        self.assertEqual(WakeState.SCHEDULED, wake.state)

        self.scheduler.close()
        self.scheduler = DurableMissionScheduler(
            database_path=self.scheduler_db,
            mission_store=self.store,
        )

        recovered = self.scheduler.get_wake(
            "WAKE-PERSIST-1",
            business_id="BIZ-1",
            project_id="PROJ-1",
        )
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual("MISSION-1", recovered.mission_id)
        self.assertEqual("RECHECK_CAMPAIGN_TELEMETRY", recovered.reason)
        self.assertEqual(self.now + timedelta(hours=2), recovered.due_at)
        self.assertEqual(WakeState.SCHEDULED, recovered.state)

    def test_only_due_wakes_are_claimed(self) -> None:
        mission = self._persist_waiting_mission()
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now + timedelta(minutes=10),
            reason="FUTURE",
            wake_id="WAKE-FUTURE",
            now=self.now,
        )
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now,
            reason="DUE",
            wake_id="WAKE-DUE",
            now=self.now,
        )

        claimed = self.scheduler.claim_due(
            worker_id="worker-a",
            now=self.now,
            lease_seconds=30,
            limit=10,
        )
        self.assertEqual(["WAKE-DUE"], [wake.wake_id for wake in claimed])
        self.assertEqual(WakeState.LEASED, claimed[0].state)

    def test_foreign_scope_cannot_schedule_or_read_wake(self) -> None:
        mission = self._persist_waiting_mission()
        with self.assertRaises(MissionSchedulerAuthorityError):
            self.scheduler.schedule_wake(
                mission_id=mission.mission_id,
                business_id="BIZ-FOREIGN",
                project_id=mission.project_id,
                due_at=self.now,
                reason="FOREIGN",
                wake_id="WAKE-FOREIGN",
                now=self.now,
            )

        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now,
            reason="OWNED",
            wake_id="WAKE-OWNED",
            now=self.now,
        )
        self.assertIsNone(
            self.scheduler.get_wake(
                "WAKE-OWNED",
                business_id="BIZ-FOREIGN",
                project_id=mission.project_id,
            )
        )

    def test_two_scheduler_connections_cannot_claim_same_live_lease(self) -> None:
        mission = self._persist_waiting_mission()
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now,
            reason="SINGLE_OWNER",
            wake_id="WAKE-SINGLE",
            now=self.now,
        )
        second = DurableMissionScheduler(
            database_path=self.scheduler_db,
            mission_store=self.store,
        )
        try:
            first_claim = self.scheduler.claim_due(
                worker_id="worker-a",
                now=self.now,
                lease_seconds=60,
            )
            second_claim = second.claim_due(
                worker_id="worker-b",
                now=self.now,
                lease_seconds=60,
            )
            self.assertEqual(1, len(first_claim))
            self.assertEqual([], second_claim)
        finally:
            second.close()

    def test_expired_lease_is_reclaimed_with_new_token(self) -> None:
        mission = self._persist_waiting_mission()
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now,
            reason="RECOVER_AFTER_CRASH",
            wake_id="WAKE-RECOVER",
            now=self.now,
        )
        first = self.scheduler.claim_due(
            worker_id="worker-a",
            now=self.now,
            lease_seconds=1,
        )[0]

        second = DurableMissionScheduler(
            database_path=self.scheduler_db,
            mission_store=self.store,
        )
        try:
            reclaimed = second.claim_due(
                worker_id="worker-b",
                now=self.now + timedelta(seconds=2),
                lease_seconds=30,
            )[0]
            self.assertEqual(first.wake_id, reclaimed.wake_id)
            self.assertNotEqual(first.lease_token, reclaimed.lease_token)
            self.assertEqual("worker-b", reclaimed.lease_owner)
        finally:
            second.close()

    def test_stale_worker_cannot_acknowledge_after_lease_reclaim(self) -> None:
        mission = self._persist_waiting_mission()
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now,
            reason="STALE_ACK",
            wake_id="WAKE-STALE",
            now=self.now,
        )
        first = self.scheduler.claim_due(
            worker_id="worker-a",
            now=self.now,
            lease_seconds=1,
        )[0]
        second = DurableMissionScheduler(
            database_path=self.scheduler_db,
            mission_store=self.store,
        )
        try:
            second.claim_due(
                worker_id="worker-b",
                now=self.now + timedelta(seconds=2),
                lease_seconds=30,
            )
            with self.assertRaises(MissionSchedulerLeaseError):
                self.scheduler.acknowledge_wake(
                    wake_id=first.wake_id,
                    worker_id="worker-a",
                    lease_token=first.lease_token or "",
                    now=self.now + timedelta(seconds=2),
                )
        finally:
            second.close()

    def test_acknowledged_wake_is_durable_and_never_claimed_again(self) -> None:
        mission = self._persist_waiting_mission()
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now,
            reason="ACK",
            wake_id="WAKE-ACK",
            now=self.now,
        )
        claim = self.scheduler.claim_due(
            worker_id="worker-a",
            now=self.now,
            lease_seconds=60,
        )[0]
        acknowledged = self.scheduler.acknowledge_wake(
            wake_id=claim.wake_id,
            worker_id="worker-a",
            lease_token=claim.lease_token or "",
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(WakeState.ACKNOWLEDGED, acknowledged.state)

        self.scheduler.close()
        self.scheduler = DurableMissionScheduler(
            database_path=self.scheduler_db,
            mission_store=self.store,
        )
        self.assertEqual(
            [],
            self.scheduler.claim_due(
                worker_id="worker-b",
                now=self.now + timedelta(hours=1),
                lease_seconds=60,
            ),
        )

    def test_terminal_mission_cannot_receive_new_wake(self) -> None:
        mission = self._persist_waiting_mission()
        mission.transition_to(MissionStatus.ACTIVE)
        mission.transition_to(MissionStatus.COMPLETED)
        self.store.save_mission(mission)

        with self.assertRaises(MissionSchedulerStateError):
            self.scheduler.schedule_wake(
                mission_id=mission.mission_id,
                business_id=mission.business_id,
                project_id=mission.project_id,
                due_at=self.now,
                reason="SHOULD_NOT_WAKE",
                wake_id="WAKE-TERMINAL",
                now=self.now,
            )

    def test_cancelled_wake_is_durable_and_not_claimable(self) -> None:
        mission = self._persist_waiting_mission()
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=self.now,
            reason="CANCEL_ME",
            wake_id="WAKE-CANCEL",
            now=self.now,
        )
        cancelled = self.scheduler.cancel_wake(
            "WAKE-CANCEL",
            business_id=mission.business_id,
            project_id=mission.project_id,
            now=self.now,
        )
        self.assertEqual(WakeState.CANCELLED, cancelled.state)
        self.assertEqual(
            [],
            self.scheduler.claim_due(
                worker_id="worker-a",
                now=self.now + timedelta(hours=1),
                lease_seconds=60,
            ),
        )


if __name__ == "__main__":
    unittest.main()
