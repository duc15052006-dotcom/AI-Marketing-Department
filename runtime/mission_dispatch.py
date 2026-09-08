"""Continuity Runtime handoff from durable wakes to Mission execution authority.

This module composes two already-durable authorities without performing Brain
reasoning or external actions:

* ``DurableMissionScheduler`` owns queue/wake delivery authority.
* ``DurableMissionLeaseStore`` owns Mission-wide execution authority and its
  monotonic fencing epoch.

A ``MissionExecutionGrant`` is therefore a bounded, detached capability: a
worker may begin one Mission wake cycle only while it owns both exact leases.
The grant itself is not permission to publish, spend, retry, or write stale
Mission state; downstream execution still crosses ToolGateway and fenced
Mission-persistence boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from runtime.mission_lease import (
    DurableMissionLeaseStore,
    MissionLeaseLostError,
    MissionLeaseRecord,
    MissionLeaseStateError,
)
from runtime.mission_scheduler import (
    DurableMissionScheduler,
    MissionSchedulerLeaseError,
    WakeRecord,
    WakeState,
)
from runtime.mission_store import MissionStore


class MissionDispatchAuthorityError(RuntimeError):
    """Raised when a wake cannot be bound to exact Mission execution authority."""


class MissionDispatchLeaseLostError(RuntimeError):
    """Raised when either half of a composed execution grant is no longer live."""


@dataclass(frozen=True)
class MissionExecutionGrant:
    """Detached snapshot binding one wake lease to one Mission fencing epoch."""

    worker_id: str
    wake: WakeRecord
    mission_lease: MissionLeaseRecord
    acquired_at: datetime

    @property
    def mission_id(self) -> str:
        return self.wake.mission_id

    @property
    def business_id(self) -> str:
        return self.wake.business_id

    @property
    def project_id(self) -> Optional[str]:
        return self.wake.project_id

    @property
    def fencing_token(self) -> int:
        return self.mission_lease.fencing_token


class MissionWakeDispatcher:
    """Compose durable wake ownership with Mission-wide fenced ownership.

    This is deliberately a control-plane primitive, not a worker loop.  It does
    not call the five-agent runtime, mutate Mission lifecycle state, or retry an
    external effect.  A future persistent worker can consume grants from here
    and must carry the grant's fencing token into authoritative persistence.
    """

    def __init__(
        self,
        *,
        mission_store: MissionStore,
        scheduler: DurableMissionScheduler,
        mission_leases: DurableMissionLeaseStore,
    ) -> None:
        if not isinstance(mission_store, MissionStore):
            raise TypeError("MISSION_DISPATCH_REQUIRES_MISSION_STORE")
        if not isinstance(scheduler, DurableMissionScheduler):
            raise TypeError("MISSION_DISPATCH_REQUIRES_DURABLE_SCHEDULER")
        if not isinstance(mission_leases, DurableMissionLeaseStore):
            raise TypeError("MISSION_DISPATCH_REQUIRES_MISSION_LEASE_STORE")
        self._mission_store = mission_store
        self._scheduler = scheduler
        self._mission_leases = mission_leases

    @staticmethod
    def _require_worker_id(worker_id: object) -> str:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("MISSION_DISPATCH_WORKER_ID_REQUIRED")
        return worker_id.strip()

    @staticmethod
    def _require_aware_now(now: Optional[datetime]) -> datetime:
        reference = now if now is not None else datetime.now(timezone.utc)
        if reference.tzinfo is None or reference.utcoffset() is None:
            raise ValueError("MISSION_DISPATCH_NOW_MUST_BE_TIMEZONE_AWARE")
        return reference.astimezone(timezone.utc)

    @classmethod
    def _explicit_now(cls, now: Optional[datetime]) -> Optional[datetime]:
        """Normalize caller-controlled time without manufacturing a default early."""

        return None if now is None else cls._require_aware_now(now)

    @staticmethod
    def _assert_composed_identity(
        wake: WakeRecord,
        mission_lease: MissionLeaseRecord,
        *,
        worker_id: str,
    ) -> None:
        if wake.state != WakeState.LEASED:
            raise MissionDispatchAuthorityError("MISSION_DISPATCH_WAKE_NOT_LEASED")
        if not wake.lease_owner or not wake.lease_token or wake.lease_expires_at is None:
            raise MissionDispatchAuthorityError("MISSION_DISPATCH_WAKE_LEASE_INCOMPLETE")
        if wake.lease_owner != worker_id:
            raise MissionDispatchAuthorityError("MISSION_DISPATCH_WAKE_OWNER_MISMATCH")
        if (
            mission_lease.mission_id != wake.mission_id
            or mission_lease.business_id != wake.business_id
            or mission_lease.project_id != wake.project_id
        ):
            raise MissionDispatchAuthorityError("MISSION_DISPATCH_SCOPE_MISMATCH")
        if mission_lease.lease_owner != worker_id or not mission_lease.leased:
            raise MissionDispatchAuthorityError("MISSION_DISPATCH_MISSION_OWNER_MISMATCH")

    @staticmethod
    def _assert_live_at(
        wake: WakeRecord,
        mission_lease: MissionLeaseRecord,
        *,
        reference: datetime,
    ) -> None:
        if wake.lease_expires_at is None or wake.lease_expires_at <= reference:
            raise MissionDispatchLeaseLostError("MISSION_DISPATCH_WAKE_LEASE_LOST")
        if (
            mission_lease.lease_expires_at is None
            or mission_lease.lease_expires_at <= reference
        ):
            raise MissionDispatchLeaseLostError("MISSION_DISPATCH_MISSION_LEASE_LOST")

    def claim_next(
        self,
        *,
        worker_id: str,
        now: Optional[datetime] = None,
        wake_lease_seconds: float = 60.0,
        mission_lease_seconds: float = 60.0,
    ) -> Optional[MissionExecutionGrant]:
        """Claim one due wake and bind it to a fresh Mission fencing epoch.

        Only one wake is claimed per call.  This avoids one worker taking several
        wakes for the same Mission before Mission-wide ownership is established.
        If another worker already owns the Mission, the wake lease is left
        bounded and recoverable by normal scheduler expiry rather than being
        destructively acknowledged or replayed.
        """

        normalized_worker = self._require_worker_id(worker_id)
        explicit_reference = self._explicit_now(now)
        wakes = self._scheduler.claim_due(
            worker_id=normalized_worker,
            now=explicit_reference,
            lease_seconds=wake_lease_seconds,
            limit=1,
        )
        if not wakes:
            return None

        wake = wakes[0]
        try:
            mission_lease = self._mission_leases.acquire(
                mission_id=wake.mission_id,
                business_id=wake.business_id,
                project_id=wake.project_id,
                worker_id=normalized_worker,
                lease_seconds=mission_lease_seconds,
                now=explicit_reference,
            )
        except MissionLeaseStateError:
            # The wake remains leased for a bounded period.  We intentionally do
            # not acknowledge it: ownership contention is not completion.
            return None

        self._assert_composed_identity(
            wake,
            mission_lease,
            worker_id=normalized_worker,
        )
        composed_at = (
            explicit_reference
            if explicit_reference is not None
            else self._require_aware_now(None)
        )
        self._assert_live_at(wake, mission_lease, reference=composed_at)
        return MissionExecutionGrant(
            worker_id=normalized_worker,
            wake=wake,
            mission_lease=mission_lease,
            acquired_at=composed_at,
        )

    def validate(
        self,
        grant: MissionExecutionGrant,
        *,
        now: Optional[datetime] = None,
    ) -> MissionExecutionGrant:
        """Fail closed unless both exact leases in the grant are still current."""

        if not isinstance(grant, MissionExecutionGrant):
            raise MissionDispatchLeaseLostError("MISSION_DISPATCH_GRANT_REQUIRED")
        explicit_reference = self._explicit_now(now)

        current_wake = self._scheduler.get_wake(
            grant.wake.wake_id,
            business_id=grant.business_id,
            project_id=grant.project_id,
        )
        reference = (
            explicit_reference
            if explicit_reference is not None
            else self._require_aware_now(None)
        )
        if (
            current_wake is None
            or current_wake.state != WakeState.LEASED
            or current_wake.lease_owner != grant.worker_id
            or current_wake.lease_token != grant.wake.lease_token
            or current_wake.lease_expires_at is None
            or current_wake.lease_expires_at <= reference
        ):
            raise MissionDispatchLeaseLostError("MISSION_DISPATCH_WAKE_LEASE_LOST")

        try:
            current_mission_lease = self._mission_leases.validate(
                grant.mission_lease,
                now=explicit_reference,
            )
        except MissionLeaseLostError as exc:
            raise MissionDispatchLeaseLostError(
                "MISSION_DISPATCH_MISSION_LEASE_LOST"
            ) from exc

        self._assert_composed_identity(
            current_wake,
            current_mission_lease,
            worker_id=grant.worker_id,
        )
        final_reference = (
            explicit_reference
            if explicit_reference is not None
            else self._require_aware_now(None)
        )
        self._assert_live_at(
            current_wake,
            current_mission_lease,
            reference=final_reference,
        )
        return MissionExecutionGrant(
            worker_id=grant.worker_id,
            wake=current_wake,
            mission_lease=current_mission_lease,
            acquired_at=grant.acquired_at,
        )

    def renew(
        self,
        grant: MissionExecutionGrant,
        *,
        now: Optional[datetime] = None,
        wake_lease_seconds: float = 60.0,
        mission_lease_seconds: float = 60.0,
    ) -> MissionExecutionGrant:
        """Renew both authorities or fail closed and relinquish Mission ownership."""

        explicit_reference = self._explicit_now(now)
        validated = self.validate(grant, now=explicit_reference)
        renewed_mission = self._mission_leases.renew(
            validated.mission_lease,
            lease_seconds=mission_lease_seconds,
            now=explicit_reference,
        )
        try:
            renewed_wake = self._scheduler.renew_lease(
                wake_id=validated.wake.wake_id,
                worker_id=validated.worker_id,
                lease_token=validated.wake.lease_token or "",
                lease_seconds=wake_lease_seconds,
                now=explicit_reference,
            )
        except MissionSchedulerLeaseError as exc:
            try:
                self._mission_leases.release(
                    renewed_mission,
                    now=explicit_reference,
                )
            except MissionLeaseLostError:
                pass
            raise MissionDispatchLeaseLostError(
                "MISSION_DISPATCH_WAKE_RENEWAL_LOST"
            ) from exc

        final_reference = (
            explicit_reference
            if explicit_reference is not None
            else self._require_aware_now(None)
        )
        self._assert_live_at(
            renewed_wake,
            renewed_mission,
            reference=final_reference,
        )
        return MissionExecutionGrant(
            worker_id=validated.worker_id,
            wake=renewed_wake,
            mission_lease=renewed_mission,
            acquired_at=validated.acquired_at,
        )

    def acknowledge_wake(
        self,
        grant: MissionExecutionGrant,
        *,
        now: Optional[datetime] = None,
    ) -> WakeRecord:
        """Acknowledge delivery only while Mission execution authority is live."""

        explicit_reference = self._explicit_now(now)
        validated = self.validate(grant, now=explicit_reference)
        try:
            return self._scheduler.acknowledge_wake(
                wake_id=validated.wake.wake_id,
                worker_id=validated.worker_id,
                lease_token=validated.wake.lease_token or "",
                now=explicit_reference,
            )
        except MissionSchedulerLeaseError as exc:
            raise MissionDispatchLeaseLostError(
                "MISSION_DISPATCH_WAKE_LEASE_LOST"
            ) from exc

    def release_mission(
        self,
        grant: MissionExecutionGrant,
        *,
        now: Optional[datetime] = None,
    ) -> MissionLeaseRecord:
        """Release only the exact Mission fencing epoch carried by the grant."""

        explicit_reference = self._explicit_now(now)
        return self._mission_leases.release(
            grant.mission_lease,
            now=explicit_reference,
        )

    def finish_delivery(
        self,
        grant: MissionExecutionGrant,
        *,
        now: Optional[datetime] = None,
    ) -> WakeRecord:
        """Acknowledge one wake then release Mission ownership.

        Wake acknowledgement is committed first.  If the process dies before the
        Mission lease release, the lease merely expires and can be reclaimed; the
        already-acknowledged wake is never replayed by this coordinator.
        """

        explicit_reference = self._explicit_now(now)
        acknowledged = self.acknowledge_wake(grant, now=explicit_reference)
        try:
            self._mission_leases.release(
                grant.mission_lease,
                now=explicit_reference,
            )
        except MissionLeaseLostError:
            # Acknowledgement truth is not rolled back.  A lost Mission lease is
            # already non-authoritative and cannot be revived by this path.
            pass
        return acknowledged
