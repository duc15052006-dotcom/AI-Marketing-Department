"""Multi-Run Queue & Provider Resource Limiter for AI Marketing Department.

Provides controlled concurrent execution, bounded queue backpressure, provider
rate-limit throttling, and unified run lifecycle tracking.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from governance.redaction import sanitize_sensitive_text
from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RunIdAlreadyExistsError, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime

logger = logging.getLogger("runtime_queue")


class RunQueueStatus(str, Enum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class ProviderResourceState:
    """Tracks concurrency and rate-limit states per model/tool provider."""

    provider_id: str
    max_concurrent_calls: int = 4
    active_calls: int = 0
    queued_calls: int = 0
    recent_429_count: int = 0
    cooldown_until: Optional[float] = None
    is_rate_limited: bool = False

    def can_call(self) -> bool:
        if self.cooldown_until and time.time() < self.cooldown_until:
            return False
        return self.active_calls < self.max_concurrent_calls

    def record_429(self, cooldown_seconds: float = 30.0) -> None:
        self.recent_429_count += 1
        self.is_rate_limited = True
        self.cooldown_until = time.time() + cooldown_seconds

    def clear_cooldown(self) -> None:
        self.is_rate_limited = False
        self.cooldown_until = None

    def model_dump(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "max_concurrent_calls": self.max_concurrent_calls,
            "active_calls": self.active_calls,
            "queued_calls": self.queued_calls,
            "recent_429_count": self.recent_429_count,
            "cooldown_until": self.cooldown_until,
            "is_rate_limited": self.is_rate_limited,
        }


class ResourceLimiter:
    """Manages provider rate limits, cooldowns, and concurrency locks.

    Unknown providers are registered automatically with a conservative default
    limit instead of bypassing resource accounting. This matters for dynamic
    plugin, MCP, and custom-provider backends added by the shared platform.
    """

    DEFAULT_PROVIDER_LIMITS: Dict[str, int] = {
        "xkiro": 2,
        "gemini": 3,
        "web": 5,
        "analytics": 5,
    }

    def __init__(
        self,
        provider_limits: Optional[Dict[str, int]] = None,
        default_max_concurrent_calls: int = 1,
    ) -> None:
        self._validate_limit(default_max_concurrent_calls)
        self._default_max_concurrent_calls = default_max_concurrent_calls
        self._providers: Dict[str, ProviderResourceState] = {}
        self._lock = threading.Lock()

        limits = dict(self.DEFAULT_PROVIDER_LIMITS)
        if provider_limits:
            limits.update(provider_limits)
        for provider_id, max_calls in limits.items():
            self._validate_provider_id(provider_id)
            self._validate_limit(max_calls)
            self._providers[provider_id] = ProviderResourceState(
                provider_id=provider_id,
                max_concurrent_calls=max_calls,
            )

    @staticmethod
    def _validate_provider_id(provider_id: str) -> None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("PROVIDER_ID_REQUIRED: provider_id must be a non-empty string")

    @staticmethod
    def _validate_limit(max_concurrent_calls: int) -> None:
        if not isinstance(max_concurrent_calls, int) or isinstance(max_concurrent_calls, bool) or max_concurrent_calls <= 0:
            raise ValueError("INVALID_PROVIDER_LIMIT: max_concurrent_calls must be a positive integer")

    def _ensure_provider_locked(self, provider_id: str) -> ProviderResourceState:
        state = self._providers.get(provider_id)
        if state is None:
            state = ProviderResourceState(
                provider_id=provider_id,
                max_concurrent_calls=self._default_max_concurrent_calls,
            )
            self._providers[provider_id] = state
        return state

    def register_provider(
        self,
        provider_id: str,
        max_concurrent_calls: Optional[int] = None,
    ) -> ProviderResourceState:
        """Register or update a provider concurrency limit."""
        self._validate_provider_id(provider_id)
        if max_concurrent_calls is not None:
            self._validate_limit(max_concurrent_calls)

        provider_id = provider_id.strip()
        with self._lock:
            state = self._ensure_provider_locked(provider_id)
            if max_concurrent_calls is not None:
                state.max_concurrent_calls = max_concurrent_calls
            return state

    def set_provider_limit(self, provider_id: str, max_concurrent_calls: int) -> None:
        self.register_provider(provider_id, max_concurrent_calls=max_concurrent_calls)

    def acquire_slot(self, provider_id: str, timeout_seconds: float = 10.0) -> bool:
        self._validate_provider_id(provider_id)
        if timeout_seconds < 0:
            raise ValueError("INVALID_TIMEOUT: timeout_seconds cannot be negative")

        provider_id = provider_id.strip()
        deadline = time.monotonic() + timeout_seconds
        while True:
            with self._lock:
                state = self._ensure_provider_locked(provider_id)
                if state.cooldown_until and time.time() >= state.cooldown_until:
                    state.clear_cooldown()
                if state.can_call():
                    state.active_calls += 1
                    return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def release_slot(self, provider_id: str) -> None:
        self._validate_provider_id(provider_id)
        provider_id = provider_id.strip()
        with self._lock:
            state = self._providers.get(provider_id)
            if state and state.active_calls > 0:
                state.active_calls -= 1

    def record_rate_limit(self, provider_id: str, cooldown_seconds: float = 30.0) -> None:
        self._validate_provider_id(provider_id)
        if cooldown_seconds < 0:
            raise ValueError("INVALID_COOLDOWN: cooldown_seconds cannot be negative")
        provider_id = provider_id.strip()
        with self._lock:
            state = self._ensure_provider_locked(provider_id)
            state.record_429(cooldown_seconds)

    def get_provider_states(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: v.model_dump() for k, v in self._providers.items()}


@dataclass
class QueueItem:
    """Encapsulates a queued department execution request."""

    run_id: str
    objective: str
    business_id: Optional[str] = None
    project_id: Optional[str] = None
    chat_id: Optional[str] = None
    status: RunQueueStatus = RunQueueStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    artifact: Optional[DepartmentRunArtifact] = None

    def model_dump(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "business_id": self.business_id,
            "project_id": self.project_id,
            "chat_id": self.chat_id,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": sanitize_sensitive_text(self.error) if self.error else None,
            "artifact_hash": self.artifact.final_artifact_hash if self.artifact else None,
        }


class RunManager:
    """Asynchronous bounded run queue and worker-pool controller."""

    ACTIVE_STATUSES = {
        RunQueueStatus.QUEUED,
        RunQueueStatus.STARTING,
        RunQueueStatus.RUNNING,
        RunQueueStatus.WAITING_TOOL,
        RunQueueStatus.WAITING_APPROVAL,
        RunQueueStatus.PAUSED,
    }

    def __init__(
        self,
        runtime: FiveAgentDepartmentRuntime,
        max_workers: int = 2,
        resource_limiter: Optional[ResourceLimiter] = None,
        max_queue_size: int = 100,
    ) -> None:
        if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 0:
            raise ValueError("INVALID_WORKER_COUNT: max_workers must be a non-negative integer")
        if not isinstance(max_queue_size, int) or isinstance(max_queue_size, bool) or max_queue_size <= 0:
            raise ValueError("INVALID_QUEUE_SIZE: max_queue_size must be a positive integer")

        self.runtime = runtime
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self.resource_limiter = resource_limiter or ResourceLimiter()
        self._queue: queue.Queue[QueueItem] = queue.Queue(maxsize=max_queue_size)
        self._items: Dict[str, QueueItem] = {}
        self._lock = threading.Lock()
        self._enqueue_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._accepting_runs = True
        self._workers: List[threading.Thread] = []

        for i in range(max_workers):
            t = threading.Thread(target=self._worker_loop, name=f"RunWorker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    @property
    def is_shutdown(self) -> bool:
        return self._stop_event.is_set() or not self._accepting_runs

    def enqueue_run(
        self,
        objective: str,
        run_id: Optional[str] = None,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        auto_approve_token: Optional[str] = None,
    ) -> QueueItem:
        if auto_approve_token:
            raise RuntimeError(
                "AUTO_APPROVAL_FORBIDDEN: Auto-approval of human-gated actions is not permitted. "
                "Use explicit human approval via the approvals API."
            )

        # Serialize only admission/reservation. Workers can continue draining in parallel.
        # Checking capacity before run-id reservation avoids leaking reserved IDs on overload.
        with self._enqueue_lock:
            if not self._accepting_runs or self._stop_event.is_set():
                raise RuntimeError("RUN_MANAGER_SHUTDOWN: run manager is not accepting new work")

            if run_id:
                with self._lock:
                    if run_id in self._items:
                        raise RunIdAlreadyExistsError(
                            f"RUN_ID_ALREADY_EXISTS: queue already tracks run_id={run_id}"
                        )
            if self._queue.full():
                raise RuntimeError(
                    f"RUN_QUEUE_FULL: queue capacity {self.max_queue_size} reached; retry later"
                )

            if run_id:
                if not self.runtime.is_reserved_run_id(run_id):
                    rid = self.runtime.reserve_run_id(custom_id=run_id, trusted=True)
                else:
                    rid = run_id
            else:
                rid = self.runtime.reserve_run_id()

            item = QueueItem(
                run_id=rid,
                objective=objective,
                business_id=business_id,
                project_id=project_id,
                chat_id=chat_id,
            )

            with self._lock:
                if rid in self._items:
                    raise RunIdAlreadyExistsError(
                        f"RUN_ID_ALREADY_EXISTS: queue already tracks run_id={rid}"
                    )
                self._items[rid] = item
                try:
                    self._queue.put_nowait(item)
                except queue.Full as exc:
                    # Defensive rollback. With serialized admission and workers only draining,
                    # this should be unreachable, but never leave a ghost queue item.
                    self._items.pop(rid, None)
                    raise RuntimeError(
                        f"RUN_QUEUE_FULL: queue capacity {self.max_queue_size} reached; retry later"
                    ) from exc

            return item

    def _sync_item_status(self, item: QueueItem) -> None:
        if item.status not in self.ACTIVE_STATUSES:
            return

        if hasattr(self.runtime, "get_active_context"):
            ctx = self.runtime.get_active_context(item.run_id)
        else:
            ctx = getattr(self.runtime, "_active_contexts", {}).get(item.run_id)
        if not ctx:
            return

        now = datetime.now(timezone.utc)
        if ctx.status == RuntimeStatus.WAITING_FOR_APPROVAL:
            item.status = RunQueueStatus.WAITING_APPROVAL
            item.completed_at = None
        elif ctx.status == RuntimeStatus.WAITING_FOR_TOOL:
            item.status = RunQueueStatus.WAITING_TOOL
            item.completed_at = None
        elif ctx.status == RuntimeStatus.RUNNING:
            item.status = RunQueueStatus.RUNNING
            item.completed_at = None
        elif ctx.status == RuntimeStatus.PAUSED:
            item.status = RunQueueStatus.PAUSED
            item.completed_at = None
        elif ctx.status == RuntimeStatus.CANCELLED:
            item.status = RunQueueStatus.CANCELLED
            item.completed_at = item.completed_at or now
        elif ctx.status == RuntimeStatus.FAILED:
            item.status = RunQueueStatus.FAILED
            item.completed_at = item.completed_at or now
        elif ctx.status == RuntimeStatus.COMPLETED:
            item.status = RunQueueStatus.COMPLETED
            item.completed_at = item.completed_at or now

    def get_run(self, run_id: str) -> Optional[QueueItem]:
        with self._lock:
            item = self._items.get(run_id)
            if item:
                self._sync_item_status(item)
            return item

    def list_runs(self) -> List[QueueItem]:
        with self._lock:
            for item in self._items.values():
                self._sync_item_status(item)
            return list(self._items.values())

    def get_queue_stats(self) -> Dict[str, Any]:
        with self._lock:
            active = sum(1 for item in self._items.values() if item.status in self.ACTIVE_STATUSES)
            tracked = len(self._items)
        return {
            "queue_size": self._queue.qsize(),
            "queue_capacity": self.max_queue_size,
            "tracked_runs": tracked,
            "active_runs": active,
            "max_workers": self.max_workers,
            "alive_workers": sum(1 for worker in self._workers if worker.is_alive()),
            "accepting_runs": self._accepting_runs and not self._stop_event.is_set(),
            "shutdown": self.is_shutdown,
        }

    def cancel_run(self, run_id: str) -> bool:
        previous_status: Optional[RunQueueStatus] = None
        should_signal_runtime = False
        with self._lock:
            item = self._items.get(run_id)
            if item is None or item.status not in self.ACTIVE_STATUSES:
                return False

            previous_status = item.status
            item.status = RunQueueStatus.CANCELLED
            item.error = "RUN_CANCELLED"
            if previous_status in (RunQueueStatus.QUEUED, RunQueueStatus.STARTING):
                item.completed_at = datetime.now(timezone.utc)
            else:
                should_signal_runtime = True

        if not should_signal_runtime:
            return True

        try:
            signal_result = self.runtime.cancel_run(run_id)
        except Exception as exc:
            safe_error = sanitize_sensitive_text(str(exc))
            with self._lock:
                item = self._items.get(run_id)
                if item is not None and item.status == RunQueueStatus.CANCELLED:
                    item.status = previous_status or RunQueueStatus.RUNNING
                    item.error = f"CANCEL_SIGNAL_FAILED: {safe_error}"
                    item.completed_at = None
            return False

        if signal_result is False:
            with self._lock:
                item = self._items.get(run_id)
                if item is not None and item.status == RunQueueStatus.CANCELLED:
                    item.status = previous_status or RunQueueStatus.RUNNING
                    item.error = "CANCEL_SIGNAL_REJECTED"
                    item.completed_at = None
            return False
        return True

    def shutdown(
        self,
        *,
        wait: bool = True,
        cancel_pending: bool = True,
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Stop accepting work and terminate worker polling safely.

        ``cancel_pending=True`` marks runs that have not started as cancelled. Running
        work is not force-killed here; callers should use ``cancel_run`` explicitly
        when they want to signal the canonical runtime to stop an active run.

        Returns True when all worker threads have stopped by the requested deadline.
        """
        if timeout_seconds < 0:
            raise ValueError("INVALID_TIMEOUT: timeout_seconds cannot be negative")

        with self._enqueue_lock:
            self._accepting_runs = False
            self._stop_event.set()
            if cancel_pending:
                now = datetime.now(timezone.utc)
                with self._lock:
                    for item in self._items.values():
                        if item.status in (RunQueueStatus.QUEUED, RunQueueStatus.STARTING):
                            item.status = RunQueueStatus.CANCELLED
                            item.error = "RUN_CANCELLED_ON_SHUTDOWN"
                            item.completed_at = now

        if not wait:
            return all(not worker.is_alive() for worker in self._workers)

        deadline = time.monotonic() + timeout_seconds
        for worker in self._workers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)
        return all(not worker.is_alive() for worker in self._workers)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                # A shutdown may arrive after queue.get() but before work starts.
                if self._stop_event.is_set():
                    continue

                with self._lock:
                    if item.status == RunQueueStatus.CANCELLED:
                        if item.completed_at is None:
                            item.completed_at = datetime.now(timezone.utc)
                        continue
                    item.status = RunQueueStatus.RUNNING
                    item.started_at = datetime.now(timezone.utc)
                    item.completed_at = None

                try:
                    # Execute Supervised Campaign through Canonical Department Runtime Entrypoint.
                    ctx = self.runtime.start_run(
                        objective=item.objective,
                        business_id=item.business_id or "BIZ_AD_HOC_EXPLORATION",
                        project_id=item.project_id,
                        chat_id=item.chat_id,
                        reserved_run_id=item.run_id,
                    )
                    ctx, cmo_final, artifact = self.runtime.execute_run(ctx)

                    with self._lock:
                        item.artifact = artifact
                        now = datetime.now(timezone.utc)
                        if ctx.status == RuntimeStatus.CANCELLED or item.status == RunQueueStatus.CANCELLED:
                            item.status = RunQueueStatus.CANCELLED
                            item.error = "RUN_CANCELLED"
                            item.completed_at = now
                        elif ctx.status == RuntimeStatus.WAITING_FOR_APPROVAL:
                            item.status = RunQueueStatus.WAITING_APPROVAL
                            item.error = None
                            item.completed_at = None
                        elif ctx.status == RuntimeStatus.WAITING_FOR_TOOL:
                            item.status = RunQueueStatus.WAITING_TOOL
                            item.error = None
                            item.completed_at = None
                        elif ctx.status == RuntimeStatus.PAUSED:
                            item.status = RunQueueStatus.PAUSED
                            item.error = None
                            item.completed_at = None
                        elif ctx.status == RuntimeStatus.FAILED or cmo_final.get("status") == "FAILED":
                            item.status = RunQueueStatus.FAILED
                            item.error = sanitize_sensitive_text(cmo_final.get("reason") or "RUN_FAILED")
                            item.completed_at = now
                        else:
                            item.status = RunQueueStatus.COMPLETED
                            item.error = None
                            item.completed_at = now
                except Exception as exc:
                    with self._lock:
                        item.status = RunQueueStatus.FAILED
                        item.error = sanitize_sensitive_text(str(exc))
                        item.completed_at = datetime.now(timezone.utc)
            finally:
                self._queue.task_done()
