"""Provider-neutral planning and replanning semantics for the Brain layer.

A plan is a cognitive snapshot, not an execution queue. The Brain describes
what should happen and why; it never owns worker state, retries, provider IDs,
tool dispatch, or persistence.

Replanning is modeled as an explicit revision event. Applying a revision
creates a new snapshot and never mutates the previous plan, preserving a clean
audit trail for later Body-side persistence/integration.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Dict, List, Optional, Set, Type, TypeVar

from brain.contracts import ActionIntent, BrainAgentId, EvidenceNeed
from schemas.base import BaseModel, Field, ValidationError


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NEEDS_REVISION = "NEEDS_REVISION"
    SATISFIED = "SATISFIED"
    ABANDONED = "ABANDONED"


class PlanStepState(str, Enum):
    """Cognitive state only; deliberately not a scheduler/worker state machine."""

    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


class RevisionTrigger(str, Enum):
    NEW_EVIDENCE = "NEW_EVIDENCE"
    CONTRADICTION = "CONTRADICTION"
    USER_STEERING = "USER_STEERING"
    FAILED_ASSUMPTION = "FAILED_ASSUMPTION"
    CHANGED_CONTEXT = "CHANGED_CONTEXT"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    BETTER_PATH = "BETTER_PATH"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string or None")
    cleaned = value.strip()
    return cleaned or None


def _text_list(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of strings")
    result: List[str] = []
    seen: Set[str] = set()
    for raw in value:
        item = _required_text(raw, field_name)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _enum(value: object, enum_cls: Type[E], field_name: str) -> E:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().upper())
        except ValueError:
            pass
    raise ValidationError(
        f"{field_name} must be one of: {', '.join(member.value for member in enum_cls)}"
    )


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{field_name} must be a positive integer")
    return value


class PlanStep(BaseModel):
    """One semantic step in a cognitive plan.

    References action/evidence needs by Brain-owned IDs. Concrete tools and
    provider mechanics remain outside this layer.
    """

    step_id: str
    goal_id: str
    owner_agent: BrainAgentId
    objective: str
    depends_on: List[str] = Field(default_factory=list)
    completion_criteria: List[str] = Field(default_factory=list)
    evidence_need_ids: List[str] = Field(default_factory=list)
    action_intent_ids: List[str] = Field(default_factory=list)
    state: PlanStepState = PlanStepState.PENDING

    def __post_init__(self) -> None:
        super().__post_init__()
        self.step_id = _required_text(self.step_id, "step_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.objective = _required_text(self.objective, "objective")
        self.depends_on = _text_list(self.depends_on, "depends_on")
        self.completion_criteria = _text_list(
            self.completion_criteria, "completion_criteria"
        )
        self.evidence_need_ids = _text_list(
            self.evidence_need_ids, "evidence_need_ids"
        )
        self.action_intent_ids = _text_list(
            self.action_intent_ids, "action_intent_ids"
        )
        self.state = _enum(self.state, PlanStepState, "state")
        if self.step_id in self.depends_on:
            raise ValidationError("A plan step cannot depend on itself")


class PlanSnapshot(BaseModel):
    """A validated DAG snapshot for one goal at one cognitive revision."""

    plan_id: str
    goal_id: str
    revision: int = 1
    steps: List[PlanStep] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.ACTIVE
    parent_revision: Optional[int] = None
    revision_reason: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.plan_id = _required_text(self.plan_id, "plan_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.revision = _positive_int(self.revision, "revision")
        self.status = _enum(self.status, PlanStatus, "status")
        if self.parent_revision is not None:
            self.parent_revision = _positive_int(
                self.parent_revision, "parent_revision"
            )
        self.revision_reason = _optional_text(
            self.revision_reason, "revision_reason"
        )

        if self.revision == 1:
            if self.parent_revision is not None:
                raise ValidationError("Initial plan revision cannot have a parent")
            if self.revision_reason is not None:
                raise ValidationError("Initial plan revision cannot have a revision_reason")
        else:
            if self.parent_revision != self.revision - 1:
                raise ValidationError(
                    "Non-initial plan revisions require the immediately preceding parent revision"
                )
            if self.revision_reason is None:
                raise ValidationError("Non-initial plan revisions require a revision_reason")

        if not isinstance(self.steps, list) or not self.steps:
            raise ValidationError("steps must contain at least one plan step")
        normalized_steps: List[PlanStep] = []
        for raw in self.steps:
            if isinstance(raw, PlanStep):
                step = raw.model_copy(deep=True)
            elif isinstance(raw, dict):
                step = PlanStep(**raw)
            else:
                raise ValidationError("steps must contain PlanStep objects")
            if step.goal_id != self.goal_id:
                raise ValidationError(
                    f"step '{step.step_id}' belongs to goal '{step.goal_id}', "
                    f"expected '{self.goal_id}'"
                )
            normalized_steps.append(step)
        self.steps = normalized_steps
        self._validate_graph()
        self._validate_state_consistency()

    def _validate_graph(self) -> None:
        by_id: Dict[str, PlanStep] = {}
        for step in self.steps:
            if step.step_id in by_id:
                raise ValidationError(f"Duplicate plan step id: {step.step_id}")
            by_id[step.step_id] = step

        for step in self.steps:
            unknown = [dep for dep in step.depends_on if dep not in by_id]
            if unknown:
                raise ValidationError(
                    f"step '{step.step_id}' depends on unknown steps: {unknown}"
                )

        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValidationError("Plan dependency graph contains a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in by_id[step_id].depends_on:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in by_id:
            visit(step_id)

    def _validate_state_consistency(self) -> None:
        by_id = {step.step_id: step for step in self.steps}
        for step in self.steps:
            if step.state == PlanStepState.COMPLETED:
                incomplete_dependencies = [
                    dep
                    for dep in step.depends_on
                    if by_id[dep].state != PlanStepState.COMPLETED
                ]
                if incomplete_dependencies:
                    raise ValidationError(
                        f"completed step '{step.step_id}' has incomplete dependencies: "
                        f"{incomplete_dependencies}"
                    )

        if self.status == PlanStatus.SATISFIED and any(
            step.state != PlanStepState.COMPLETED for step in self.steps
        ):
            raise ValidationError(
                "A SATISFIED plan cannot contain incomplete or blocked steps"
            )


class PlanRevision(BaseModel):
    """Auditable instructions for replacing one PlanSnapshot with the next.

    Every prior step must be classified explicitly as preserved or invalidated.
    Silent step disappearance is forbidden.
    """

    revision_id: str
    plan_id: str
    from_revision: int
    trigger: RevisionTrigger
    reason: str
    preserved_step_ids: List[str] = Field(default_factory=list)
    invalidated_step_ids: List[str] = Field(default_factory=list)
    replacement_steps: List[PlanStep] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.revision_id = _required_text(self.revision_id, "revision_id")
        self.plan_id = _required_text(self.plan_id, "plan_id")
        self.from_revision = _positive_int(self.from_revision, "from_revision")
        self.trigger = _enum(self.trigger, RevisionTrigger, "trigger")
        self.reason = _required_text(self.reason, "reason")
        self.preserved_step_ids = _text_list(
            self.preserved_step_ids, "preserved_step_ids"
        )
        self.invalidated_step_ids = _text_list(
            self.invalidated_step_ids, "invalidated_step_ids"
        )
        overlap = set(self.preserved_step_ids) & set(self.invalidated_step_ids)
        if overlap:
            raise ValidationError(
                f"preserved and invalidated steps cannot overlap: {sorted(overlap)}"
            )

        if not isinstance(self.replacement_steps, list):
            raise ValidationError("replacement_steps must be a list")
        normalized: List[PlanStep] = []
        for raw in self.replacement_steps:
            if isinstance(raw, PlanStep):
                normalized.append(raw.model_copy(deep=True))
            elif isinstance(raw, dict):
                normalized.append(PlanStep(**raw))
            else:
                raise ValidationError(
                    "replacement_steps must contain PlanStep objects"
                )
        self.replacement_steps = normalized

        if not self.invalidated_step_ids and not self.replacement_steps:
            raise ValidationError(
                "A plan revision must invalidate or add at least one step"
            )


def validate_plan_action_intent_bindings(
    plan: PlanSnapshot,
    action_intents: List[ActionIntent],
) -> None:
    """Fail closed unless every plan action reference resolves canonically.

    The plan remains a provider-neutral cognitive artifact. This validator binds
    its Brain-owned action intent references to canonical ActionIntent objects
    without introducing runtime/tool/provider execution concerns.
    """

    if not isinstance(plan, PlanSnapshot):
        raise ValidationError("plan must be a PlanSnapshot")
    if not isinstance(action_intents, list):
        raise ValidationError("action_intents must be a list of ActionIntent objects")

    by_id: Dict[str, ActionIntent] = {}
    for raw in action_intents:
        if not isinstance(raw, ActionIntent):
            raise ValidationError("action_intents must contain ActionIntent objects")
        intent = raw.model_copy(deep=True)
        if intent.intent_id in by_id:
            raise ValidationError(f"duplicate action intent id: {intent.intent_id}")
        by_id[intent.intent_id] = intent

    bound_step_by_intent_id: Dict[str, str] = {}
    for step in plan.steps:
        for intent_id in step.action_intent_ids:
            previous_step_id = bound_step_by_intent_id.get(intent_id)
            if previous_step_id is not None and previous_step_id != step.step_id:
                raise ValidationError(
                    f"action intent '{intent_id}' cannot be bound to multiple plan steps: "
                    f"'{previous_step_id}' and '{step.step_id}'"
                )
            bound_step_by_intent_id[intent_id] = step.step_id

            intent = by_id.get(intent_id)
            if intent is None:
                raise ValidationError(
                    f"step '{step.step_id}' references unknown action intent '{intent_id}'"
                )
            if intent.goal_id != plan.goal_id or intent.goal_id != step.goal_id:
                raise ValidationError(
                    f"action intent '{intent_id}' goal_id must match plan/step goal_id"
                )
            if intent.owner_agent != step.owner_agent:
                raise ValidationError(
                    f"action intent '{intent_id}' owner_agent must match step owner_agent"
                )


def validate_plan_evidence_need_bindings(
    plan: PlanSnapshot,
    evidence_needs: List[EvidenceNeed],
) -> None:
    """Fail closed unless every plan evidence reference resolves canonically.

    Validation reconstructs both the mutable plan and evidence inputs at the use
    boundary so post-construction mutation cannot silently weaken provenance.
    Evidence references remain semantic Brain artifacts and confer no runtime or
    execution authority.
    """

    if not isinstance(plan, PlanSnapshot):
        raise ValidationError("plan must be a PlanSnapshot")
    if not isinstance(evidence_needs, list):
        raise ValidationError("evidence_needs must be a list of EvidenceNeed objects")

    canonical_plan = PlanSnapshot(**copy.deepcopy(plan.model_dump()))
    by_id: Dict[str, EvidenceNeed] = {}
    for raw in evidence_needs:
        if not isinstance(raw, EvidenceNeed):
            raise ValidationError("evidence_needs must contain EvidenceNeed objects")
        need = EvidenceNeed(**copy.deepcopy(raw.model_dump()))
        if need.need_id in by_id:
            raise ValidationError(f"duplicate evidence need id: {need.need_id}")
        by_id[need.need_id] = need

    for step in canonical_plan.steps:
        for need_id in step.evidence_need_ids:
            need = by_id.get(need_id)
            if need is None:
                raise ValidationError(
                    f"step '{step.step_id}' references unknown evidence need '{need_id}'"
                )
            if need.goal_id != canonical_plan.goal_id or need.goal_id != step.goal_id:
                raise ValidationError(
                    f"evidence need '{need_id}' goal_id must match plan/step goal_id"
                )


def ready_step_ids(plan: PlanSnapshot) -> List[str]:
    """Return cognitively actionable steps in deterministic plan order."""

    if not isinstance(plan, PlanSnapshot):
        raise ValidationError("plan must be a PlanSnapshot")
    if plan.status != PlanStatus.ACTIVE:
        return []
    by_id = {step.step_id: step for step in plan.steps}
    return [
        step.step_id
        for step in plan.steps
        if step.state == PlanStepState.PENDING
        and all(
            by_id[dependency].state == PlanStepState.COMPLETED
            for dependency in step.depends_on
        )
    ]


def apply_plan_revision(
    plan: PlanSnapshot,
    revision: PlanRevision,
) -> PlanSnapshot:
    """Create the next plan snapshot without mutating the prior snapshot."""

    if not isinstance(plan, PlanSnapshot):
        raise ValidationError("plan must be a PlanSnapshot")
    if not isinstance(revision, PlanRevision):
        raise ValidationError("revision must be a PlanRevision")
    if plan.status in (PlanStatus.SATISFIED, PlanStatus.ABANDONED):
        raise ValidationError(
            f"Cannot revise terminal plan status {plan.status.value}"
        )
    if revision.plan_id != plan.plan_id:
        raise ValidationError("revision plan_id does not match the plan")
    if revision.from_revision != plan.revision:
        raise ValidationError(
            "revision from_revision does not match the current plan revision"
        )

    existing = {step.step_id: step for step in plan.steps}
    existing_ids = set(existing)
    preserved_ids = set(revision.preserved_step_ids)
    invalidated_ids = set(revision.invalidated_step_ids)
    classified_ids = preserved_ids | invalidated_ids

    unknown = classified_ids - existing_ids
    if unknown:
        raise ValidationError(
            f"revision references unknown existing steps: {sorted(unknown)}"
        )
    unclassified = existing_ids - classified_ids
    if unclassified:
        raise ValidationError(
            f"revision must explicitly preserve or invalidate every prior step; "
            f"unclassified={sorted(unclassified)}"
        )

    replacement_ids = [step.step_id for step in revision.replacement_steps]
    if len(replacement_ids) != len(set(replacement_ids)):
        raise ValidationError("replacement step ids must be unique")
    reused = set(replacement_ids) & existing_ids
    if reused:
        raise ValidationError(
            f"replacement steps must use new identities; reused={sorted(reused)}"
        )

    next_steps = [
        existing[step.step_id].model_copy(deep=True)
        for step in plan.steps
        if step.step_id in preserved_ids
    ]
    next_steps.extend(step.model_copy(deep=True) for step in revision.replacement_steps)
    if not next_steps:
        raise ValidationError("A revision cannot produce an empty plan")

    return PlanSnapshot(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        revision=plan.revision + 1,
        parent_revision=plan.revision,
        revision_reason=revision.reason,
        status=PlanStatus.ACTIVE,
        steps=next_steps,
    )