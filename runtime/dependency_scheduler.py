"""Fail-closed dependency-aware scheduling for runtime subtasks.

The scheduler is an execution authority, not a model policy surface. A model or
planner may suggest work, but only trusted ``RuntimeTaskSpec`` metadata is used
to decide whether work may share a parallel execution wave.

Safety rules:
- explicit dependencies always run in a later wave;
- write/write and read/write conflicts are serialized;
- side-effecting tasks are exclusive;
- tasks with unknown resource scope are exclusive;
- malformed or cyclic dependency graphs fail closed;
- ordering is deterministic for equivalent inputs.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Tuple


class ScheduleValidationError(ValueError):
    """Raised when trusted task metadata cannot produce a safe DAG plan."""


class TaskExecutionError(RuntimeError):
    """Raised when a scheduled task fails during execution."""

    def __init__(self, task_id: str, cause: BaseException) -> None:
        super().__init__(f"TASK_EXECUTION_FAILED: {task_id}: {cause}")
        self.task_id = task_id
        self.cause = cause


@dataclass(frozen=True)
class RuntimeTaskSpec:
    """Trusted runtime task metadata used for scheduling decisions.

    ``depends_on``, ``reads``, ``writes``, ``side_effecting`` and
    ``resource_scope_known`` are runtime-owned authority metadata. Free-form
    model output must never be copied into these fields as authorization.
    """

    task_id: str
    agent_id: str
    depends_on: FrozenSet[str] = field(default_factory=frozenset)
    reads: FrozenSet[str] = field(default_factory=frozenset)
    writes: FrozenSet[str] = field(default_factory=frozenset)
    side_effecting: bool = False
    resource_scope_known: bool = True


@dataclass(frozen=True)
class ExecutionPlan:
    """Deterministic sequence of execution waves.

    Tasks within one wave are mutually conflict-free and may execute in
    parallel. Waves themselves always execute in order.
    """

    waves: Tuple[Tuple[str, ...], ...]
    mode: str = "ADAPTIVE_DAG"


class DependencyAwareScheduler:
    """Build and execute deterministic, fail-closed parallel execution waves."""

    def __init__(self, max_workers: int = 4) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = max_workers

    @staticmethod
    def _validate(tasks: Tuple[RuntimeTaskSpec, ...]) -> Mapping[str, RuntimeTaskSpec]:
        by_id: Dict[str, RuntimeTaskSpec] = {}
        for task in tasks:
            task_id = str(task.task_id or "").strip()
            agent_id = str(task.agent_id or "").strip()
            if not task_id:
                raise ScheduleValidationError("TASK_ID_REQUIRED")
            if not agent_id:
                raise ScheduleValidationError(f"AGENT_ID_REQUIRED: {task_id}")
            if task_id in by_id:
                raise ScheduleValidationError(f"DUPLICATE_TASK_ID: {task_id}")
            by_id[task_id] = task

        known = set(by_id)
        for task in tasks:
            if task.task_id in task.depends_on:
                raise ScheduleValidationError(f"SELF_DEPENDENCY: {task.task_id}")
            missing = sorted(set(task.depends_on) - known)
            if missing:
                raise ScheduleValidationError(
                    f"UNKNOWN_DEPENDENCY: {task.task_id}: {','.join(missing)}"
                )
        return by_id

    @staticmethod
    def _is_exclusive(task: RuntimeTaskSpec) -> bool:
        return task.side_effecting or not task.resource_scope_known

    @classmethod
    def _conflicts(cls, left: RuntimeTaskSpec, right: RuntimeTaskSpec) -> bool:
        if cls._is_exclusive(left) or cls._is_exclusive(right):
            return True
        if left.writes & right.writes:
            return True
        if left.writes & right.reads:
            return True
        if right.writes & left.reads:
            return True
        return False

    @classmethod
    def _partition_ready(
        cls,
        ready: Tuple[RuntimeTaskSpec, ...],
    ) -> Tuple[Tuple[str, ...], ...]:
        """Partition one topological generation into safe waves.

        Input order is authoritative for deterministic barrier semantics: an
        unknown-scope or side-effecting task splits compatible work before and
        after it instead of being moved to another position.
        """

        waves: List[Tuple[str, ...]] = []
        current: List[RuntimeTaskSpec] = []

        def flush() -> None:
            nonlocal current
            if current:
                waves.append(tuple(task.task_id for task in current))
                current = []

        for task in ready:
            if cls._is_exclusive(task):
                flush()
                waves.append((task.task_id,))
                continue

            if current and any(cls._conflicts(task, other) for other in current):
                flush()
            current.append(task)

        flush()
        return tuple(waves)

    def plan(self, tasks: Iterable[RuntimeTaskSpec]) -> ExecutionPlan:
        ordered = tuple(tasks)
        self._validate(ordered)
        if not ordered:
            return ExecutionPlan(waves=())

        remaining = list(ordered)
        completed: set[str] = set()
        waves: List[Tuple[str, ...]] = []

        while remaining:
            ready = tuple(task for task in remaining if set(task.depends_on) <= completed)
            if not ready:
                unresolved = ",".join(task.task_id for task in remaining)
                raise ScheduleValidationError(f"CYCLIC_DEPENDENCY_GRAPH: {unresolved}")

            waves.extend(self._partition_ready(ready))
            ready_ids = {task.task_id for task in ready}
            completed.update(ready_ids)
            remaining = [task for task in remaining if task.task_id not in ready_ids]

        return ExecutionPlan(waves=tuple(waves))

    def execute(
        self,
        tasks: Iterable[RuntimeTaskSpec],
        runner: Callable[[RuntimeTaskSpec], Any],
    ) -> Dict[str, Any]:
        """Execute safe waves while returning results in deterministic task order.

        The scheduler never mutates a RuntimeContext. ``runner`` is expected to
        operate on isolated inputs and return an isolated result that a trusted
        merge boundary can commit after the wave completes.
        """

        ordered = tuple(tasks)
        plan = self.plan(ordered)
        by_id = {task.task_id: task for task in ordered}
        results: Dict[str, Any] = {}

        for wave in plan.waves:
            if len(wave) == 1:
                task_id = wave[0]
                try:
                    results[task_id] = runner(by_id[task_id])
                except BaseException as exc:
                    raise TaskExecutionError(task_id, exc) from exc
                continue

            futures: Dict[str, Future[Any]] = {}
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(wave))) as pool:
                for task_id in wave:
                    futures[task_id] = pool.submit(runner, by_id[task_id])

                # Consume in wave order so returned result ordering is stable even
                # when workers finish in a different order.
                for task_id in wave:
                    try:
                        results[task_id] = futures[task_id].result()
                    except BaseException as exc:
                        for other_id, future in futures.items():
                            if other_id != task_id:
                                future.cancel()
                        raise TaskExecutionError(task_id, exc) from exc

        return results
