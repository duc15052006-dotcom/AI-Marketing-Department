"""Auditable adaptive replanning semantics for the Brain layer.

Adaptive replanning validates *why* an existing cognitive plan should change
and *which* prior steps are affected. It deliberately does not implement a
second planner or scheduler: canonical revision construction remains owned by
``brain.planning.apply_plan_revision``.

The public entry point reconstructs nested inputs at the use boundary so
post-construction mutation cannot bypass the semantic invariants captured by
``PlanSnapshot``, ``PlanStep``, and ``ReplanSignal``.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Type, TypeVar

from brain.planning import (
    PlanRevision,
    PlanSnapshot,
    PlanStep,
    RevisionTrigger,
    apply_plan_revision,
)
from schemas.base import BaseModel, Field, ValidationError


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _enum(value: object, enum_cls: Type[E], field_name: str) -> E:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().upper())
        except ValueError:
            pass
    raise ValidationError(
        f"{field_name} must be one of: "
        f"{', '.join(member.value for member in enum_cls)}"
    )


def _strict_unique_text_list(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of strings")
    result: List[str] = []
    seen = set()
    for raw in value:
        item = _required_text(raw, field_name)
        if item in seen:
            raise ValidationError(f"{field_name} contains duplicate id: {item}")
        seen.add(item)
        result.append(item)
    return result


def _canonical_plan(raw: object, field_name: str = "current_plan") -> PlanSnapshot:
    if isinstance(raw, PlanSnapshot):
        return PlanSnapshot(**raw.model_dump())
    if isinstance(raw, dict):
        return PlanSnapshot(**raw)
    raise ValidationError(f"{field_name} must be a PlanSnapshot or serialized mapping")


def _canonical_step(raw: object) -> PlanStep:
    if isinstance(raw, PlanStep):
        return PlanStep(**raw.model_dump())
    if isinstance(raw, dict):
        return PlanStep(**raw)
    raise ValidationError("replacement_steps must contain PlanStep objects")


class ReplanSignal(BaseModel):
    """Semantic provenance that explains why specific prior steps need revision."""

    signal_id: str
    plan_id: str
    goal_id: str
    trigger: RevisionTrigger
    reason: str
    affected_step_ids: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.signal_id = _required_text(self.signal_id, "signal_id")
        self.plan_id = _required_text(self.plan_id, "plan_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.trigger = _enum(self.trigger, RevisionTrigger, "trigger")
        self.reason = _required_text(self.reason, "reason")
        self.affected_step_ids = _strict_unique_text_list(
            self.affected_step_ids,
            "affected_step_ids",
        )


def _canonical_signal(raw: object) -> ReplanSignal:
    if isinstance(raw, ReplanSignal):
        return ReplanSignal(**raw.model_dump())
    if isinstance(raw, dict):
        return ReplanSignal(**raw)
    raise ValidationError("signal must be a ReplanSignal or serialized mapping")


class AdaptiveReplanRequest(BaseModel):
    """A provider-neutral request to adapt one canonical cognitive plan."""

    current_plan: PlanSnapshot
    signal: ReplanSignal
    replacement_steps: List[PlanStep] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.current_plan = _canonical_plan(self.current_plan)
        self.signal = _canonical_signal(self.signal)
        if not isinstance(self.replacement_steps, list):
            raise ValidationError("replacement_steps must be a list")
        self.replacement_steps = [
            _canonical_step(step) for step in self.replacement_steps
        ]


class AdaptiveReplanResult(BaseModel):
    """Auditable result containing both revision provenance and next snapshot."""

    current_plan: PlanSnapshot
    signal: ReplanSignal
    revision: PlanRevision
    revised_plan: PlanSnapshot

    def __post_init__(self) -> None:
        super().__post_init__()
        self.current_plan = _canonical_plan(self.current_plan)
        self.signal = _canonical_signal(self.signal)
        if isinstance(self.revision, PlanRevision):
            self.revision = PlanRevision(**self.revision.model_dump())
        elif isinstance(self.revision, dict):
            self.revision = PlanRevision(**self.revision)
        else:
            raise ValidationError("revision must be a PlanRevision")
        self.revised_plan = _canonical_plan(self.revised_plan, "revised_plan")


def _canonical_request(raw: object) -> AdaptiveReplanRequest:
    if isinstance(raw, AdaptiveReplanRequest):
        return AdaptiveReplanRequest(**raw.model_dump())
    if isinstance(raw, dict):
        return AdaptiveReplanRequest(**raw)
    raise ValidationError(
        "request must be an AdaptiveReplanRequest or serialized mapping"
    )


def apply_adaptive_replan(request: AdaptiveReplanRequest | dict) -> AdaptiveReplanResult:
    """Validate a semantic replan signal and create the next plan snapshot.

    Every invocation rehydrates the request before use. The signal's affected
    step identities become the revision's exact invalidation set, while every
    other prior step is explicitly preserved. Canonical planning validation
    then enforces terminal-plan, fresh-identity, dependency, DAG, and lineage
    invariants.
    """

    canonical = _canonical_request(request)
    plan = canonical.current_plan
    signal = canonical.signal

    if signal.plan_id != plan.plan_id:
        raise ValidationError("signal plan_id does not match current_plan.plan_id")
    if signal.goal_id != plan.goal_id:
        raise ValidationError("signal goal_id does not match current_plan.goal_id")

    existing_ids = {step.step_id for step in plan.steps}
    affected_ids = set(signal.affected_step_ids)
    unknown = affected_ids - existing_ids
    if unknown:
        raise ValidationError(
            f"signal references unknown affected steps: {sorted(unknown)}"
        )

    if not signal.affected_step_ids and not canonical.replacement_steps:
        raise ValidationError("adaptive replan must affect or add at least one step")

    preserved_step_ids = [
        step.step_id for step in plan.steps if step.step_id not in affected_ids
    ]

    revision = PlanRevision(
        revision_id=f"adaptive-replan:{signal.signal_id}",
        plan_id=plan.plan_id,
        from_revision=plan.revision,
        trigger=signal.trigger,
        reason=signal.reason,
        preserved_step_ids=preserved_step_ids,
        invalidated_step_ids=list(signal.affected_step_ids),
        replacement_steps=[
            PlanStep(**step.model_dump()) for step in canonical.replacement_steps
        ],
    )
    revised_plan = apply_plan_revision(plan, revision)

    return AdaptiveReplanResult(
        current_plan=PlanSnapshot(**plan.model_dump()),
        signal=ReplanSignal(**signal.model_dump()),
        revision=PlanRevision(**revision.model_dump()),
        revised_plan=PlanSnapshot(**revised_plan.model_dump()),
    )
