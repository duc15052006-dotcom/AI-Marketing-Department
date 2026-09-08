"""Long-horizon semantic goal decomposition for the five-ASI brain.

The capability preserves canonical GoalSpec semantics while validating a rooted
parent hierarchy, a separate dependency DAG, and explicit success-criterion
responsibility.  It carries no execution, provider, scheduling, or persistence
authority.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from brain.contracts import GoalSpec
from schemas.base import BaseModel, Field, ValidationError


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _text_list(value: object, field_name: str, *, require_nonempty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of strings")
    result: List[str] = []
    seen: Set[str] = set()
    for raw in value:
        item = _required_text(raw, field_name)
        if item in seen:
            raise ValidationError(f"{field_name} cannot contain duplicate value {item!r}")
        seen.add(item)
        result.append(item)
    if require_nonempty and not result:
        raise ValidationError(f"{field_name} must contain at least one value")
    return result


def _model_payload(value: Any, model_name: str) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, BaseModel):
        return value.model_dump()
    raise ValidationError(f"{model_name} must be a mapping or canonical model")


def _canonical_goal(value: Any) -> GoalSpec:
    try:
        return GoalSpec(**_model_payload(value, "goal"))
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(f"invalid GoalSpec: {exc}") from exc


class GoalDependency(BaseModel):
    """A semantic prerequisite edge between goals in one decomposition."""

    prerequisite_goal_id: str
    dependent_goal_id: str
    rationale: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.prerequisite_goal_id = _required_text(
            self.prerequisite_goal_id, "prerequisite_goal_id"
        )
        self.dependent_goal_id = _required_text(
            self.dependent_goal_id, "dependent_goal_id"
        )
        if not isinstance(self.rationale, str):
            raise ValidationError("rationale must be a string")
        self.rationale = self.rationale.strip()
        if self.prerequisite_goal_id == self.dependent_goal_id:
            raise ValidationError("goal dependency cannot be a self-edge")


class SuccessCriterionTrace(BaseModel):
    """Binds an exact goal criterion to the strict descendants responsible for it."""

    criterion_goal_id: str
    criterion: str
    responsible_goal_ids: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.criterion_goal_id = _required_text(
            self.criterion_goal_id, "criterion_goal_id"
        )
        self.criterion = _required_text(self.criterion, "criterion")
        self.responsible_goal_ids = _text_list(
            self.responsible_goal_ids,
            "responsible_goal_ids",
            require_nonempty=True,
        )


class GoalDecompositionRequest(BaseModel):
    """Caller-supplied semantic decomposition proposal."""

    decomposition_id: str
    root_goal: GoalSpec
    subgoals: List[GoalSpec] = Field(default_factory=list)
    dependencies: List[GoalDependency] = Field(default_factory=list)
    criterion_traces: List[SuccessCriterionTrace] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.decomposition_id = _required_text(self.decomposition_id, "decomposition_id")
        if not isinstance(self.subgoals, list):
            raise ValidationError("subgoals must be a list")
        if not isinstance(self.dependencies, list):
            raise ValidationError("dependencies must be a list")
        if not isinstance(self.criterion_traces, list):
            raise ValidationError("criterion_traces must be a list")


class GoalDecomposition(BaseModel):
    """Canonical, provenance-preserving long-horizon goal structure."""

    decomposition_id: str
    root_goal: GoalSpec
    subgoals: List[GoalSpec] = Field(default_factory=list)
    dependencies: List[GoalDependency] = Field(default_factory=list)
    criterion_traces: List[SuccessCriterionTrace] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.decomposition_id = _required_text(self.decomposition_id, "decomposition_id")


def _canonical_request(value: GoalDecompositionRequest | Dict[str, Any]) -> GoalDecompositionRequest:
    payload = _model_payload(value, "GoalDecompositionRequest")
    try:
        request = GoalDecompositionRequest(**payload)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(f"invalid GoalDecompositionRequest: {exc}") from exc

    root = _canonical_goal(request.root_goal)
    subgoals = [_canonical_goal(goal) for goal in request.subgoals]

    dependencies: List[GoalDependency] = []
    for dependency in request.dependencies:
        try:
            dependencies.append(
                GoalDependency(**_model_payload(dependency, "GoalDependency"))
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(f"invalid GoalDependency: {exc}") from exc

    traces: List[SuccessCriterionTrace] = []
    for trace in request.criterion_traces:
        try:
            traces.append(
                SuccessCriterionTrace(
                    **_model_payload(trace, "SuccessCriterionTrace")
                )
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(f"invalid SuccessCriterionTrace: {exc}") from exc

    return GoalDecompositionRequest(
        decomposition_id=request.decomposition_id,
        root_goal=root,
        subgoals=subgoals,
        dependencies=dependencies,
        criterion_traces=traces,
    )


def _validate_parent_hierarchy(
    root: GoalSpec,
    subgoals: List[GoalSpec],
) -> Dict[str, GoalSpec]:
    if root.parent_goal_id is not None:
        raise ValidationError("root_goal.parent_goal_id must be None")
    if not subgoals:
        raise ValidationError("long-horizon decomposition requires at least one subgoal")

    goals: Dict[str, GoalSpec] = {root.goal_id: root}
    for goal in subgoals:
        if goal.goal_id in goals:
            raise ValidationError(f"duplicate goal_id {goal.goal_id!r}")
        goals[goal.goal_id] = goal

    for goal in subgoals:
        if goal.parent_goal_id is None:
            raise ValidationError(f"subgoal {goal.goal_id!r} must declare parent_goal_id")
        if goal.parent_goal_id not in goals:
            raise ValidationError(
                f"subgoal {goal.goal_id!r} has unknown parent {goal.parent_goal_id!r}"
            )

    # Every subgoal must reach the one canonical root, which simultaneously
    # rejects cycles and disconnected/orphan parent components.
    for goal in subgoals:
        seen: Set[str] = set()
        current = goal
        while current.goal_id != root.goal_id:
            if current.goal_id in seen:
                raise ValidationError("goal parent hierarchy must be acyclic")
            seen.add(current.goal_id)
            parent_id = current.parent_goal_id
            if parent_id is None or parent_id not in goals:
                raise ValidationError(
                    f"goal {goal.goal_id!r} is not connected to root {root.goal_id!r}"
                )
            current = goals[parent_id]

    return goals


def _validate_dependency_dag(
    dependencies: List[GoalDependency],
    goal_ids: Set[str],
) -> None:
    edges: Set[Tuple[str, str]] = set()
    outgoing: Dict[str, List[str]] = {goal_id: [] for goal_id in goal_ids}
    indegree: Dict[str, int] = {goal_id: 0 for goal_id in goal_ids}

    for edge in dependencies:
        pair = (edge.prerequisite_goal_id, edge.dependent_goal_id)
        if pair in edges:
            raise ValidationError(f"duplicate goal dependency {pair!r}")
        edges.add(pair)
        if edge.prerequisite_goal_id not in goal_ids:
            raise ValidationError(
                f"unknown prerequisite goal {edge.prerequisite_goal_id!r}"
            )
        if edge.dependent_goal_id not in goal_ids:
            raise ValidationError(f"unknown dependent goal {edge.dependent_goal_id!r}")
        if edge.prerequisite_goal_id == edge.dependent_goal_id:
            raise ValidationError("goal dependency cannot be a self-edge")
        outgoing[edge.prerequisite_goal_id].append(edge.dependent_goal_id)
        indegree[edge.dependent_goal_id] += 1

    frontier = [goal_id for goal_id, degree in indegree.items() if degree == 0]
    visited = 0
    while frontier:
        current = frontier.pop()
        visited += 1
        for dependent in outgoing[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                frontier.append(dependent)
    if visited != len(goal_ids):
        raise ValidationError("goal dependency graph must be acyclic")


def _is_strict_descendant(
    descendant_id: str,
    ancestor_id: str,
    goals: Dict[str, GoalSpec],
) -> bool:
    if descendant_id == ancestor_id:
        return False
    current = goals[descendant_id]
    seen: Set[str] = set()
    while current.parent_goal_id is not None:
        parent_id = current.parent_goal_id
        if parent_id == ancestor_id:
            return True
        if parent_id in seen or parent_id not in goals:
            return False
        seen.add(parent_id)
        current = goals[parent_id]
    return False


def _validate_criterion_traces(
    root: GoalSpec,
    traces: List[SuccessCriterionTrace],
    goals: Dict[str, GoalSpec],
) -> None:
    root_coverage: Set[str] = set()
    for trace in traces:
        owner = goals.get(trace.criterion_goal_id)
        if owner is None:
            raise ValidationError(
                f"criterion trace references unknown goal {trace.criterion_goal_id!r}"
            )
        if trace.criterion not in owner.success_criteria:
            raise ValidationError(
                f"criterion {trace.criterion!r} is not declared by goal {owner.goal_id!r}"
            )
        for responsible_id in trace.responsible_goal_ids:
            if responsible_id not in goals:
                raise ValidationError(
                    f"criterion trace references unknown responsible goal {responsible_id!r}"
                )
            if not _is_strict_descendant(responsible_id, owner.goal_id, goals):
                raise ValidationError(
                    f"responsible goal {responsible_id!r} must be a strict descendant "
                    f"of criterion owner {owner.goal_id!r}"
                )
        if owner.goal_id == root.goal_id:
            root_coverage.add(trace.criterion)

    missing = [
        criterion
        for criterion in root.success_criteria
        if criterion not in root_coverage
    ]
    if missing:
        raise ValidationError(
            "every root success criterion must be traced to a responsible descendant; "
            f"missing={missing!r}"
        )


def build_goal_decomposition(
    request: GoalDecompositionRequest | Dict[str, Any],
) -> GoalDecomposition:
    """Build and validate a canonical long-horizon goal decomposition.

    All authority-bearing nested models are reconstructed at the use boundary,
    so post-construction caller mutation cannot silently rebind hierarchy or
    criterion responsibility.
    """

    canonical = _canonical_request(request)
    goals = _validate_parent_hierarchy(canonical.root_goal, canonical.subgoals)
    _validate_dependency_dag(canonical.dependencies, set(goals))
    _validate_criterion_traces(
        canonical.root_goal,
        canonical.criterion_traces,
        goals,
    )

    # Reconstruct once more for output ownership isolation.
    return GoalDecomposition(
        decomposition_id=canonical.decomposition_id,
        root_goal=_canonical_goal(canonical.root_goal),
        subgoals=[_canonical_goal(goal) for goal in canonical.subgoals],
        dependencies=[
            GoalDependency(**edge.model_dump()) for edge in canonical.dependencies
        ],
        criterion_traces=[
            SuccessCriterionTrace(**trace.model_dump())
            for trace in canonical.criterion_traces
        ],
    )
