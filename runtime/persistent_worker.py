"""Bounded persistent worker cycle for durable Continuity Runtime Missions.

This module composes existing durable runtime authorities into one deliberately
small control-plane cycle:

    due wake -> execution grant -> restore checkpoint -> one callback
    -> revalidate authority -> checkpoint -> continuation/finish
    -> acknowledge wake -> release Mission lease

It does not perform Brain reasoning, choose providers/tools, retry consequential
external effects, or reconcile ambiguous provider outcomes. Those remain
separate authority boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, Optional, Any

from runtime.mission_checkpoint import (
    DurableMissionCheckpointStore,
    MissionCheckpointAuthorityError,
    MissionCheckpointRecord,
    MissionCheckpointStateError,
)
from runtime.mission_dispatch import (
    MissionDispatchAuthorityError,
    MissionDispatchLeaseLostError,
    MissionExecutionGrant,
    MissionWakeDispatcher,
)
from runtime.mission_lease import DurableMissionLeaseStore
from runtime.mission_scheduler import DurableMissionScheduler
from runtime.mission_store import MissionStore


class PersistentWorkerAuthorityError(RuntimeError):
    """Raised when a worker loses durable execution authority mid-cycle."""


class PersistentWorkerStateError(RuntimeError):
    """Raised when a bounded worker callback returns an invalid continuation."""


class PersistentWorkerCycleStatus(str, Enum):
    """Outcome of one bounded worker polling cycle."""

    IDLE = "IDLE"
    CONTINUED = "CONTINUED"
    FINISHED = "FINISHED"


@dataclass(frozen=True)
class PersistentWorkerCycleContext:
    """Detached authority/context snapshot delivered to one bounded callback."""

    worker_id: str
    mission_id: str
    business_id: str
    project_id: Optional[str]
    wake_id: str
    fencing_token: int
    restored_checkpoint: Optional[MissionCheckpointRecord]


@dataclass(frozen=True)
class PersistentWorkerCycleResult:
    """Pure callback result describing the next durable resume point."""

    resume_cursor: str
    state: Dict[str, Any]
    next_wake_at: Optional[datetime] = None
    next_wake_reason: Optional[str] = None


@dataclass(frozen=True)
class PersistentWorkerRunReport:
    """Detached report for exactly one call to :meth:`PersistentMissionWorker.run_once`."""

    status: PersistentWorkerCycleStatus
    mission_id: Optional[str] = None
    wake_id: Optional[str] = None
    checkpoint_sequence: Optional[int] = None
    next_wake_id: Optional[str] = None


class PersistentMissionWorker:
    """Consume at most one due Mission wake per call.

    The worker never trusts a grant merely because it was valid before the
    callback. Authority is revalidated after callback execution and again by the
    underlying checkpoint/acknowledgement boundaries before durable progress is
    committed.
    """

    def __init__(
        self,
        *,
        mission_store: MissionStore,
        scheduler: DurableMissionScheduler,
        mission_leases: DurableMissionLeaseStore,
        checkpoints: DurableMissionCheckpointStore,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(mission_store, MissionStore):
            raise TypeError("PERSISTENT_WORKER_REQUIRES_MISSION_STORE")
        if not isinstance(scheduler, DurableMissionScheduler):
            raise TypeError("PERSISTENT_WORKER_REQUIRES_DURABLE_SCHEDULER")
        if not isinstance(mission_leases, DurableMissionLeaseStore):
            raise TypeError("PERSISTENT_WORKER_REQUIRES_MISSION_LEASE_STORE")
        if not isinstance(checkpoints, DurableMissionCheckpointStore):
            raise TypeError("PERSISTENT_WORKER_REQUIRES_CHECKPOINT_STORE")
        if clock is not None and not callable(clock):
            raise TypeError("PERSISTENT_WORKER_CLOCK_MUST_BE_CALLABLE")

        self._mission_store = mission_store
        self._scheduler = scheduler
        self._mission_leases = mission_leases
        self._checkpoints = checkpoints
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._dispatcher = MissionWakeDispatcher(
            mission_store=mission_store,
            scheduler=scheduler,
            mission_leases=mission_leases,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValueError("PERSISTENT_WORKER_CLOCK_MUST_RETURN_DATETIME")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PERSISTENT_WORKER_NOW_MUST_BE_TIMEZONE_AWARE")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _require_worker_id(worker_id: object) -> str:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("PERSISTENT_WORKER_WORKER_ID_REQUIRED")
        return worker_id.strip()

    @staticmethod
    def _validate_result(result: object) -> PersistentWorkerCycleResult:
        if not isinstance(result, PersistentWorkerCycleResult):
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_EXECUTOR_RESULT_REQUIRED"
            )
        if not isinstance(result.resume_cursor, str) or not result.resume_cursor.strip():
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RESUME_CURSOR_REQUIRED"
            )
        if not isinstance(result.state, dict):
            raise PersistentWorkerStateError("PERSISTENT_WORKER_STATE_MUST_BE_DICT")

        if result.next_wake_at is None:
            if result.next_wake_reason is not None:
                raise PersistentWorkerStateError(
                    "PERSISTENT_WORKER_NEXT_WAKE_REASON_WITHOUT_TIME"
                )
        else:
            if (
                not isinstance(result.next_wake_at, datetime)
                or result.next_wake_at.tzinfo is None
                or result.next_wake_at.utcoffset() is None
            ):
                raise PersistentWorkerStateError(
                    "PERSISTENT_WORKER_NEXT_WAKE_AT_MUST_BE_TIMEZONE_AWARE"
                )
            if (
                not isinstance(result.next_wake_reason, str)
                or not result.next_wake_reason.strip()
            ):
                raise PersistentWorkerStateError(
                    "PERSISTENT_WORKER_NEXT_WAKE_REASON_REQUIRED"
                )
        return result

    @staticmethod
    def _authority_error(exc: BaseException) -> PersistentWorkerAuthorityError:
        return PersistentWorkerAuthorityError(
            f"PERSISTENT_WORKER_EXECUTION_AUTHORITY_LOST: {exc}"
        )

    def _validate_grant(
        self,
        grant: MissionExecutionGrant,
    ) -> MissionExecutionGrant:
        try:
            return self._dispatcher.validate(grant, now=self._now())
        except (MissionDispatchLeaseLostError, MissionDispatchAuthorityError) as exc:
            raise self._authority_error(exc) from exc

    def run_once(
        self,
        *,
        worker_id: str,
        executor: Callable[[PersistentWorkerCycleContext], PersistentWorkerCycleResult],
        wake_lease_seconds: float = 60.0,
        mission_lease_seconds: float = 60.0,
    ) -> PersistentWorkerRunReport:
        """Poll and execute at most one due wake under exact durable authority."""

        normalized_worker = self._require_worker_id(worker_id)
        if not callable(executor):
            raise TypeError("PERSISTENT_WORKER_EXECUTOR_MUST_BE_CALLABLE")

        try:
            grant = self._dispatcher.claim_next(
                worker_id=normalized_worker,
                now=self._now(),
                wake_lease_seconds=wake_lease_seconds,
                mission_lease_seconds=mission_lease_seconds,
            )
        except (MissionDispatchLeaseLostError, MissionDispatchAuthorityError) as exc:
            raise self._authority_error(exc) from exc

        if grant is None:
            return PersistentWorkerRunReport(status=PersistentWorkerCycleStatus.IDLE)

        restored = self._checkpoints.get_latest(
            mission_id=grant.mission_id,
            business_id=grant.business_id,
            project_id=grant.project_id,
        )
        next_sequence = 1 if restored is None else restored.checkpoint_sequence + 1

        context = PersistentWorkerCycleContext(
            worker_id=normalized_worker,
            mission_id=grant.mission_id,
            business_id=grant.business_id,
            project_id=grant.project_id,
            wake_id=grant.wake.wake_id,
            fencing_token=grant.fencing_token,
            restored_checkpoint=restored,
        )

        result = self._validate_result(executor(context))

        # The callback may take arbitrary bounded application time. Never use the
        # pre-callback grant as proof that execution authority is still current.
        grant = self._validate_grant(grant)

        try:
            checkpoint = self._checkpoints.save_checkpoint(
                mission_id=grant.mission_id,
                business_id=grant.business_id,
                project_id=grant.project_id,
                worker_id=normalized_worker,
                lease_token=grant.mission_lease.lease_token or "",
                fencing_token=grant.fencing_token,
                checkpoint_sequence=next_sequence,
                resume_cursor=result.resume_cursor.strip(),
                state=result.state,
            )
        except (MissionCheckpointAuthorityError, MissionCheckpointStateError) as exc:
            raise self._authority_error(exc) from exc

        next_wake_id: Optional[str] = None
        if result.next_wake_at is not None:
            # Scheduling continuation is authority-bearing control-plane work.
            # Revalidate after checkpoint persistence instead of assuming the
            # previous validation remains current.
            grant = self._validate_grant(grant)
            next_wake = self._scheduler.schedule_wake(
                mission_id=grant.mission_id,
                business_id=grant.business_id,
                project_id=grant.project_id,
                due_at=result.next_wake_at.astimezone(timezone.utc),
                reason=(result.next_wake_reason or "").strip(),
                now=self._now(),
            )
            next_wake_id = next_wake.wake_id

        try:
            self._dispatcher.finish_delivery(grant, now=self._now())
        except (MissionDispatchLeaseLostError, MissionDispatchAuthorityError) as exc:
            raise self._authority_error(exc) from exc

        status = (
            PersistentWorkerCycleStatus.CONTINUED
            if next_wake_id is not None
            else PersistentWorkerCycleStatus.FINISHED
        )
        return PersistentWorkerRunReport(
            status=status,
            mission_id=grant.mission_id,
            wake_id=grant.wake.wake_id,
            checkpoint_sequence=checkpoint.checkpoint_sequence,
            next_wake_id=next_wake_id,
        )
