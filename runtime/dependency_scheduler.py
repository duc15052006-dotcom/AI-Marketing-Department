"""Dependency-aware runtime scheduler baseline.

This RED baseline intentionally remains sequential. The regression suite on this
branch defines the authority and concurrency contract before production
parallelism is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Tuple


@dataclass(frozen=True)
class RuntimeTaskSpec:
    """Trusted runtime task metadata used for scheduling decisions.

    Model/planner output must not be treated as authority for resource safety.
    Runtime adapters are responsible for constructing these specs from trusted
    capability/stage metadata.
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
    waves: Tuple[Tuple[str, ...], ...]
    mode: str = "SEQUENTIAL_BASELINE"


class DependencyAwareScheduler:
    """RED baseline: conservatively emits one task per wave."""

    def plan(self, tasks: Iterable[RuntimeTaskSpec]) -> ExecutionPlan:
        ordered = tuple(tasks)
        return ExecutionPlan(waves=tuple((task.task_id,) for task in ordered))
