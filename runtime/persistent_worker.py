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

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

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
from runtime.mission_scheduler import DurableMissionScheduler, WakeState
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

    The source-wake identity and continuation delivery specification are also
    persisted atomically with the checkpoint.  If a process dies after that
    checkpoint but before scheduling/acknowledgement completes, recovery repairs
    only the missing control-plane work and never invokes the semantic executor
    for the same source wake twice.
    """

    _WORKER_CYCLE_VERSION = 1

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
        self._clock_is_explicit = clock is not None
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

    def _authority_now(self) -> Optional[datetime]:
        """Preserve omitted authority time until the downstream authority layer.

        A caller-injected clock is an explicit deterministic authority seam and
        is propagated. The worker's ordinary default wall clock is not sampled
        early and converted into caller-controlled time before Dispatcher /
        Scheduler / Mission-lease authority is reached.
        """

        return self._now() if self._clock_is_explicit else None

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
            return self._dispatcher.validate(grant, now=self._authority_now())
        except (MissionDispatchLeaseLostError, MissionDispatchAuthorityError) as exc:
            raise self._authority_error(exc) from exc

    @classmethod
    def _build_worker_cycle(
        cls,
        *,
        result: PersistentWorkerCycleResult,
        next_wake_id: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "version": cls._WORKER_CYCLE_VERSION,
            "next_wake_id": next_wake_id,
            "next_wake_at": (
                None
                if result.next_wake_at is None
                else result.next_wake_at.astimezone(timezone.utc).isoformat()
            ),
            "next_wake_reason": (
                None
                if result.next_wake_reason is None
                else result.next_wake_reason.strip()
            ),
        }

    @classmethod
    def _parse_worker_cycle(
        cls,
        checkpoint: MissionCheckpointRecord,
    ) -> Tuple[Optional[str], Optional[datetime], Optional[str]]:
        cycle = checkpoint.worker_cycle
        if not isinstance(cycle, dict):
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RECOVERY_METADATA_MISSING"
            )
        if cycle.get("version") != cls._WORKER_CYCLE_VERSION:
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RECOVERY_METADATA_VERSION_INVALID"
            )

        next_wake_id = cycle.get("next_wake_id")
        raw_next_wake_at = cycle.get("next_wake_at")
        next_wake_reason = cycle.get("next_wake_reason")

        if next_wake_id is None:
            if raw_next_wake_at is not None or next_wake_reason is not None:
                raise PersistentWorkerStateError(
                    "PERSISTENT_WORKER_RECOVERY_TERMINAL_METADATA_INVALID"
                )
            return None, None, None

        if not isinstance(next_wake_id, str) or not next_wake_id.strip():
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RECOVERY_NEXT_WAKE_ID_INVALID"
            )
        if not isinstance(raw_next_wake_at, str) or not raw_next_wake_at:
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RECOVERY_NEXT_WAKE_AT_INVALID"
            )
        if not isinstance(next_wake_reason, str) or not next_wake_reason.strip():
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RECOVERY_NEXT_WAKE_REASON_INVALID"
            )
        try:
            parsed_at = datetime.fromisoformat(raw_next_wake_at)
        except ValueError as exc:
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RECOVERY_NEXT_WAKE_AT_INVALID"
            ) from exc
        if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
            raise PersistentWorkerStateError(
                "PERSISTENT_WORKER_RECOVERY_NEXT_WAKE_AT_NOT_TIMEZONE_AWARE"
            )
        return (
            next_wake_id.strip(),
            parsed_at.astimezone(timezone.utc),
            next_wake_reason.strip(),
        )

    def _recover_checkpointed_delivery(
        self,
        *,
        grant: MissionExecutionGrant,
        checkpoint: MissionCheckpointRecord,
    ) -> PersistentWorkerRunReport:
        """Repair post-checkpoint delivery work without replaying semantics."""

        grant = self._validate_grant(grant)
        next_wake_id, next_wake_at, next_wake_reason = self._parse_worker_cycle(
            checkpoint
        )

        if next_wake_id is not None:
            assert next_wake_at is not None
            assert next_wake_reason is not None
            existing = self._scheduler.get_wake(
                next_wake_id,
                business_id=grant.business_id,
                project_id=grant.project_id,
            )
            if existing is None:
                self._scheduler.schedule_wake(
                    wake_id=next_wake_id,
                    mission_id=grant.mission_id,
                    business_id=grant.business_id,
                    project_id=grant.project_id,
                    due_at=next_wake_at,
                    reason=next_wake_reason,
                    now=self._now(),
                )
            else:
                if (
                    existing.mission_id != grant.mission_id
                    or existing.business_id != grant.business_id
                    or existing.project_id != grant.project_id
                    or existing.due_at != next_wake_at
                    or existing.reason != next_wake_reason
                ):
                    raise PersistentWorkerStateError(
                        "PERSISTENT_WORKER_RECOVERY_CONTINUATION_CONFLICT"
                    )
                if existing.state == WakeState.CANCELLED:
                    raise PersistentWorkerStateError(
                        "PERSISTENT_WORKER_RECOVERY_CONTINUATION_CANCELLED"
                    )

        try:
            self._dispatcher.finish_delivery(grant, now=self._authority_now())
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
                now=self._authority_now(),
                wake_lease_seconds=wake_lease_seconds,
                mission_lease_seconds=mission_lease_seconds,
            )
        except (MissionDispatchLeaseLostError, MissionDispatchAuthorityError) as exc:
            raise self._authority_error(exc) from exc

        if grant is None:
            return PersistentWorkerRunReport(status=PersistentWorkerCycleStatus.IDLE)

        # Recovery lookup is by exact source wake, not merely "latest". A later
        # continuation may already have advanced the Mission checkpoint sequence
        # before an older unacknowledged source wake is reclaimed.
        checkpointed_source = self._checkpoints.get_by_source_wake(
            mission_id=grant.mission_id,
            business_id=grant.business_id,
            project_id=grant.project_id,
            source_wake_id=grant.wake.wake_id,
        )
        if checkpointed_source is not None:
            return self._recover_checkpointed_delivery(
                grant=grant,
                checkpoint=checkpointed_source,
            )

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

        next_wake_id: Optional[str] = None
        if result.next_wake_at is not None:
            # Generate the continuation identity before the semantic checkpoint.
            # The exact ID/spec becomes durable with that checkpoint, so a crash
            # before/after scheduling can be repaired idempotently.
            next_wake_id = f"WAKE-{uuid.uuid4().hex.upper()}"

        worker_cycle = self._build_worker_cycle(
            result=result,
            next_wake_id=next_wake_id,
        )

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
                source_wake_id=grant.wake.wake_id,
                worker_cycle=worker_cycle,
                now=self._authority_now(),
            )
        except (MissionCheckpointAuthorityError, MissionCheckpointStateError) as exc:
            raise self._authority_error(exc) from exc

        if next_wake_id is not None:
            assert result.next_wake_at is not None
            # Scheduling continuation is authority-bearing control-plane work.
            # Revalidate after checkpoint persistence instead of assuming the
            # previous validation remains current.
            grant = self._validate_grant(grant)
            self._scheduler.schedule_wake(
                wake_id=next_wake_id,
                mission_id=grant.mission_id,
                business_id=grant.business_id,
                project_id=grant.project_id,
                due_at=result.next_wake_at.astimezone(timezone.utc),
                reason=(result.next_wake_reason or "").strip(),
                now=self._now(),
            )

        try:
            self._dispatcher.finish_delivery(grant, now=self._authority_now())
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
