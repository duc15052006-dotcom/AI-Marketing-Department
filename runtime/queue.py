"""Multi-Run Queue & Provider Resource Limiter for AI Marketing Department.

Provides controlled concurrent execution, rate-limit throttling, per-provider
cooldown management, and unified run lifecycle tracking.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RuntimeContext, RuntimeStatus
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
    """Manages provider rate limits, cooldowns, and concurrency locks."""

    def __init__(self) -> None:
        self._providers: Dict[str, ProviderResourceState] = {
            "xkiro": ProviderResourceState(provider_id="xkiro", max_concurrent_calls=2),
            "gemini": ProviderResourceState(provider_id="gemini", max_concurrent_calls=3),
            "web": ProviderResourceState(provider_id="web", max_concurrent_calls=5),
            "analytics": ProviderResourceState(provider_id="analytics", max_concurrent_calls=5),
        }
        self._lock = threading.Lock()

    def acquire_slot(self, provider_id: str, timeout_seconds: float = 10.0) -> bool:
        start = time.time()
        while time.time() - start < timeout_seconds:
            with self._lock:
                state = self._providers.get(provider_id)
                if not state or state.can_call():
                    if state:
                        state.active_calls += 1
                    return True
            time.sleep(0.1)
        return False

    def release_slot(self, provider_id: str) -> None:
        with self._lock:
            state = self._providers.get(provider_id)
            if state and state.active_calls > 0:
                state.active_calls -= 1

    def record_rate_limit(self, provider_id: str, cooldown_seconds: float = 30.0) -> None:
        with self._lock:
            state = self._providers.get(provider_id)
            if state:
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
            "error": self.error,
            "artifact_hash": self.artifact.final_artifact_hash if self.artifact else None,
        }


class RunManager:
    """Asynchronous background run queue and worker pool controller."""

    def __init__(
        self,
        runtime: FiveAgentDepartmentRuntime,
        max_workers: int = 2,
        resource_limiter: Optional[ResourceLimiter] = None,
    ) -> None:
        self.runtime = runtime
        self.max_workers = max_workers
        self.resource_limiter = resource_limiter or ResourceLimiter()
        self._queue: queue.Queue[QueueItem] = queue.Queue()
        self._items: Dict[str, QueueItem] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._workers: List[threading.Thread] = []

        for i in range(max_workers):
            t = threading.Thread(target=self._worker_loop, name=f"RunWorker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

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
        if run_id:
            if not self.runtime.is_reserved_run_id(run_id):
                # Auto-reserve if trusted/valid format
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
            self._items[rid] = item
        self._queue.put(item)
        return item

    def _sync_item_status(self, item: QueueItem) -> None:
        if item.status in (RunQueueStatus.QUEUED, RunQueueStatus.RUNNING, RunQueueStatus.WAITING_APPROVAL, RunQueueStatus.PAUSED):
            ctx = self.runtime.get_active_context(item.run_id) if hasattr(self.runtime, "get_active_context") else self.runtime._active_contexts.get(item.run_id)
            if ctx:
                if ctx.status == RuntimeStatus.WAITING_FOR_APPROVAL:
                    item.status = RunQueueStatus.WAITING_APPROVAL
                elif ctx.status == RuntimeStatus.RUNNING:
                    item.status = RunQueueStatus.RUNNING
                elif ctx.status == RuntimeStatus.PAUSED:
                    item.status = RunQueueStatus.PAUSED

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

    def cancel_run(self, run_id: str) -> bool:
        with self._lock:
            item = self._items.get(run_id)
            if item:
                if item.status in (RunQueueStatus.QUEUED, RunQueueStatus.RUNNING, RunQueueStatus.WAITING_APPROVAL, RunQueueStatus.PAUSED):
                    item.status = RunQueueStatus.CANCELLED
                    self.runtime.cancel_run(run_id)
                    return True
        return False

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._lock:
                if item.status == RunQueueStatus.CANCELLED:
                    self._queue.task_done()
                    continue
                item.status = RunQueueStatus.RUNNING
                item.started_at = datetime.now(timezone.utc)

            try:
                # Execute Supervised Campaign through Canonical Department Runtime Entrypoint
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
                    if ctx.status == RuntimeStatus.CANCELLED or item.status == RunQueueStatus.CANCELLED:
                        item.status = RunQueueStatus.CANCELLED
                        item.error = "RUN_CANCELLED"
                    elif ctx.status == RuntimeStatus.WAITING_FOR_APPROVAL:
                        item.status = RunQueueStatus.WAITING_APPROVAL
                    elif ctx.status == RuntimeStatus.FAILED or cmo_final.get("status") == "FAILED":
                        item.status = RunQueueStatus.FAILED
                        item.error = cmo_final.get("reason") or "RUN_FAILED"
                    else:
                        item.status = RunQueueStatus.COMPLETED
                    item.completed_at = datetime.now(timezone.utc)
            except Exception as e:
                with self._lock:
                    item.status = RunQueueStatus.FAILED
                    item.error = str(e)
                    item.completed_at = datetime.now(timezone.utc)
            finally:
                self._queue.task_done()
