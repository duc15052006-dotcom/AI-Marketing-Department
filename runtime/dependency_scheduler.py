"""Fail-closed dependency-aware scheduling for runtime subtasks.

The scheduler is an execution authority, not a model policy surface. A model or
planner may suggest *what* work is useful, but only trusted runtime metadata is
used to decide *how* that work may execute.

Safety rules:
- explicit dependencies always run in a later wave;
- write/write and read/write conflicts are serialized;
- side-effecting tasks are exclusive;
- tasks with unknown resource scope are exclusive;
- malformed or cyclic dependency graphs fail closed;
- model-supplied scheduling/authority fields are ignored;
- ordering is deterministic for equivalent inputs.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple


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
    task_kind: str = ""
    instruction: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    """Deterministic sequence of execution waves.

    Tasks within one wave are mutually conflict-free and may execute in
    parallel. Waves themselves always execute in order.
    """

    waves: Tuple[Tuple[str, ...], ...]
    mode: str = "ADAPTIVE_DAG"


@dataclass(frozen=True)
class TrustedTaskTemplate:
    """Runtime-owned scheduling contract for one planner-visible task kind."""

    kind: str
    agent_id: str
    stage_rank: int
    reads: FrozenSet[str]
    writes: FrozenSet[str]
    side_effecting: bool = False
    resource_scope_known: bool = True


@dataclass(frozen=True)
class CompiledAdaptivePlan:
    """Result of translating untrusted planner proposals into trusted specs."""

    tasks: Tuple[RuntimeTaskSpec, ...]
    execution_plan: ExecutionPlan
    rejected_kinds: Tuple[str, ...] = ()
    fallback_required: bool = False


# Planner-visible vocabulary. The model may select a kind, but every scheduling
# property below remains owned by code. Stage ranks express conservative data
# flow: tasks at a later rank depend on all selected earlier-rank tasks.
DEFAULT_TRUSTED_TASK_TEMPLATES: Tuple[TrustedTaskTemplate, ...] = (
    TrustedTaskTemplate(
        kind="intelligence.market",
        agent_id="intelligence",
        stage_rank=10,
        reads=frozenset({"objective", "grounded_context"}),
        writes=frozenset({"isolated.intelligence.market"}),
    ),
    TrustedTaskTemplate(
        kind="intelligence.competitors",
        agent_id="intelligence",
        stage_rank=10,
        reads=frozenset({"objective", "grounded_context"}),
        writes=frozenset({"isolated.intelligence.competitors"}),
    ),
    TrustedTaskTemplate(
        kind="intelligence.customers",
        agent_id="intelligence",
        stage_rank=10,
        reads=frozenset({"objective", "grounded_context"}),
        writes=frozenset({"isolated.intelligence.customers"}),
    ),
    TrustedTaskTemplate(
        kind="strategist.positioning",
        agent_id="strategist",
        stage_rank=20,
        reads=frozenset({"objective", "research.aggregate"}),
        writes=frozenset({"isolated.strategy.positioning"}),
    ),
    TrustedTaskTemplate(
        kind="creative.angles",
        agent_id="creative",
        stage_rank=30,
        reads=frozenset({"objective", "strategy.aggregate"}),
        writes=frozenset({"isolated.creative.angles"}),
    ),
    TrustedTaskTemplate(
        kind="performance.plan",
        agent_id="performance",
        stage_rank=40,
        reads=frozenset({"objective", "strategy.aggregate", "creative.aggregate"}),
        writes=frozenset({"isolated.performance.plan"}),
    ),
    TrustedTaskTemplate(
        kind="cmo.final",
        agent_id="cmo",
        stage_rank=50,
        reads=frozenset({"research.aggregate", "strategy.aggregate", "creative.aggregate", "performance.aggregate"}),
        writes=frozenset({"isolated.cmo.final"}),
    ),
)


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


class AdaptiveTaskCompiler:
    """Translate untrusted planner proposals into trusted scheduling metadata.

    Planner-controlled fields other than ``kind`` and human-readable
    ``instruction`` are deliberately ignored. In particular, a planner cannot
    lower dependencies, hide a side effect, claim resource isolation, or force
    parallel execution.
    """

    def __init__(
        self,
        scheduler: Optional[DependencyAwareScheduler] = None,
        templates: Iterable[TrustedTaskTemplate] = DEFAULT_TRUSTED_TASK_TEMPLATES,
    ) -> None:
        self.scheduler = scheduler or DependencyAwareScheduler()
        self._templates = {template.kind: template for template in templates}

    def compile(self, raw_proposals: Any) -> CompiledAdaptivePlan:
        if not isinstance(raw_proposals, list) or not raw_proposals:
            return CompiledAdaptivePlan(
                tasks=(),
                execution_plan=ExecutionPlan(waves=(), mode="SEQUENTIAL_FALLBACK"),
                fallback_required=True,
            )

        accepted: List[Tuple[TrustedTaskTemplate, str]] = []
        rejected: List[str] = []
        counts: Dict[str, int] = {}

        for raw in raw_proposals:
            if not isinstance(raw, dict):
                rejected.append("<malformed>")
                continue
            kind = str(raw.get("kind") or "").strip().lower()
            template = self._templates.get(kind)
            if template is None:
                rejected.append(kind or "<missing-kind>")
                continue
            instruction = str(raw.get("instruction") or "").strip()
            accepted.append((template, instruction))
            counts[kind] = counts.get(kind, 0) + 1

        if not accepted:
            return CompiledAdaptivePlan(
                tasks=(),
                execution_plan=ExecutionPlan(waves=(), mode="SEQUENTIAL_FALLBACK"),
                rejected_kinds=tuple(rejected),
                fallback_required=True,
            )

        occurrence: Dict[str, int] = {}
        provisional: List[Tuple[TrustedTaskTemplate, str, str]] = []
        for template, instruction in accepted:
            occurrence[template.kind] = occurrence.get(template.kind, 0) + 1
            suffix = f"-{occurrence[template.kind]}" if counts[template.kind] > 1 else ""
            task_id = template.kind.replace(".", "-") + suffix
            provisional.append((template, task_id, instruction))

        # Conservative server-owned dependency rule: every selected task at a
        # later stage rank waits for all selected lower-rank tasks. Tasks within
        # the same rank remain eligible for parallel execution.
        tasks: List[RuntimeTaskSpec] = []
        for template, task_id, instruction in provisional:
            dependencies = frozenset(
                other_id
                for other_template, other_id, _ in provisional
                if other_template.stage_rank < template.stage_rank
            )
            tasks.append(
                RuntimeTaskSpec(
                    task_id=task_id,
                    agent_id=template.agent_id,
                    depends_on=dependencies,
                    reads=template.reads,
                    writes=template.writes,
                    side_effecting=template.side_effecting,
                    resource_scope_known=template.resource_scope_known,
                    task_kind=template.kind,
                    instruction=instruction,
                )
            )

        task_tuple = tuple(tasks)
        return CompiledAdaptivePlan(
            tasks=task_tuple,
            execution_plan=self.scheduler.plan(task_tuple),
            rejected_kinds=tuple(rejected),
            fallback_required=False,
        )
