from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.mission import CommitmentRecord, MissionRecord, MissionStatus
from runtime.mission_dispatch import (
    MissionDispatchLeaseLostError,
    MissionExecutionGrant,
    MissionWakeDispatcher,
)
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_scheduler import DurableMissionScheduler, WakeState
from runtime.mission_store import MissionStore


NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


class MissionWakeDispatchV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.missions = MissionStore(database_path=str(root / "missions.sqlite3"))
        self.scheduler = DurableMissionScheduler(
            database_path=str(root / "scheduler.sqlite3"),
            mission_store=self.missions,
        )
        self.leases = DurableMissionLeaseStore(
            database_path=str(root / "leases.sqlite3"),
            mission_store=self.missions,
        )
        self.dispatcher = MissionWakeDispatcher(
            mission_store=self.missions,
            scheduler=self.scheduler,
            mission_leases=self.leases,
        )

        mission = MissionRecord(
            mission_id="MISSION-1",
            objective="Run durable marketing mission",
            business_id="BIZ-1",
            project_id="PROJECT-1",
            user_id="USER-1",
        )
        commitment = CommitmentRecord(
            commitment_id="COMMIT-1",
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            user_id=mission.user_id,
            authority_mode="SUPERVISED",
            deadline_at=NOW + timedelta(days=1),
        )
        mission.mark_ready(commitment, now=NOW)
        self.missions.save_mission(mission)
        self.scheduler.schedule_wake(
            mission_id=mission.mission_id,
            business_id=mission.business_id,
            project_id=mission.project_id,
            due_at=NOW,
            reason="scheduled continuation",
            wake_id="WAKE-1",
            now=NOW,
        )

    def tearDown(self) -> None:
        self.leases.close()
        self.scheduler.close()
        self.missions.close()
        self.tempdir.cleanup()

    def test_claim_next_composes_exact_wake_and_mission_authority(self) -> None:
        grant = self.dispatcher.claim_next(worker_id="worker-a", now=NOW)

        self.assertIsInstance(grant, MissionExecutionGrant)
        assert grant is not None
        self.assertEqual(grant.worker_id, "worker-a")
        self.assertEqual(grant.mission_id, "MISSION-1")
        self.assertEqual(grant.business_id, "BIZ-1")
        self.assertEqual(grant.project_id, "PROJECT-1")
        self.assertEqual(grant.wake.state, WakeState.LEASED)
        self.assertEqual(grant.wake.lease_owner, "worker-a")
        self.assertEqual(grant.mission_lease.lease_owner, "worker-a")
        self.assertEqual(grant.fencing_token, 1)

    def test_live_wake_and_mission_are_not_double_owned(self) -> None:
        first = self.dispatcher.claim_next(
            worker_id="worker-a",
            now=NOW,
            wake_lease_seconds=30,
            mission_lease_seconds=30,
        )
        self.assertIsNotNone(first)

        second = self.dispatcher.claim_next(
            worker_id="worker-b",
            now=NOW + timedelta(seconds=1),
            wake_lease_seconds=30,
            mission_lease_seconds=30,
        )
        self.assertIsNone(second)

    def test_crash_takeover_invalidates_old_grant_and_advances_fence(self) -> None:
        first = self.dispatcher.claim_next(
            worker_id="worker-a",
            now=NOW,
            wake_lease_seconds=5,
            mission_lease_seconds=5,
        )
        assert first is not None

        takeover_time = NOW + timedelta(seconds=6)
        second = self.dispatcher.claim_next(
            worker_id="worker-b",
            now=takeover_time,
            wake_lease_seconds=30,
            mission_lease_seconds=30,
        )
        assert second is not None

        self.assertGreater(second.fencing_token, first.fencing_token)
        self.assertEqual(second.worker_id, "worker-b")
        with self.assertRaises(MissionDispatchLeaseLostError):
            self.dispatcher.validate(first, now=takeover_time)

    def test_renew_keeps_same_fencing_epoch_and_extends_both_leases(self) -> None:
        grant = self.dispatcher.claim_next(
            worker_id="worker-a",
            now=NOW,
            wake_lease_seconds=5,
            mission_lease_seconds=5,
        )
        assert grant is not None
        old_wake_expiry = grant.wake.lease_expires_at
        old_mission_expiry = grant.mission_lease.lease_expires_at

        renewed = self.dispatcher.renew(
            grant,
            now=NOW + timedelta(seconds=2),
            wake_lease_seconds=20,
            mission_lease_seconds=20,
        )

        self.assertEqual(renewed.fencing_token, grant.fencing_token)
        self.assertGreater(renewed.wake.lease_expires_at, old_wake_expiry)
        self.assertGreater(renewed.mission_lease.lease_expires_at, old_mission_expiry)

    def test_finish_delivery_acknowledges_wake_and_releases_mission(self) -> None:
        grant = self.dispatcher.claim_next(worker_id="worker-a", now=NOW)
        assert grant is not None

        acknowledged = self.dispatcher.finish_delivery(
            grant,
            now=NOW + timedelta(seconds=1),
        )

        self.assertEqual(acknowledged.state, WakeState.ACKNOWLEDGED)
        stored_wake = self.scheduler.get_wake(
            "WAKE-1",
            business_id="BIZ-1",
            project_id="PROJECT-1",
        )
        assert stored_wake is not None
        self.assertEqual(stored_wake.state, WakeState.ACKNOWLEDGED)

        stored_lease = self.leases.get(
            mission_id="MISSION-1",
            business_id="BIZ-1",
            project_id="PROJECT-1",
        )
        assert stored_lease is not None
        self.assertFalse(stored_lease.leased)
        self.assertEqual(stored_lease.fencing_token, grant.fencing_token)

        self.assertIsNone(
            self.dispatcher.claim_next(
                worker_id="worker-b",
                now=NOW + timedelta(seconds=2),
            )
        )

    def test_acknowledge_fails_after_mission_lease_is_lost(self) -> None:
        first = self.dispatcher.claim_next(
            worker_id="worker-a",
            now=NOW,
            wake_lease_seconds=5,
            mission_lease_seconds=5,
        )
        assert first is not None

        takeover_time = NOW + timedelta(seconds=6)
        second = self.dispatcher.claim_next(
            worker_id="worker-b",
            now=takeover_time,
            wake_lease_seconds=30,
            mission_lease_seconds=30,
        )
        assert second is not None

        with self.assertRaises(MissionDispatchLeaseLostError):
            self.dispatcher.acknowledge_wake(first, now=takeover_time)

        live = self.scheduler.get_wake(
            "WAKE-1",
            business_id="BIZ-1",
            project_id="PROJECT-1",
        )
        assert live is not None
        self.assertEqual(live.state, WakeState.LEASED)
        self.assertEqual(live.lease_owner, "worker-b")


if __name__ == "__main__":
    unittest.main()
