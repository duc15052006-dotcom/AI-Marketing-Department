"""Deterministic semantic coordination for one five-ASI cognitive cycle.

The cognitive loop chooses the next Brain phase from canonical goal, evidence,
plan, decision, action-intent, and reflection artifacts.  It is deliberately a
coordination boundary rather than an execution engine: ACTION_READY means that
semantic action intents are prepared for a later trusted boundary, not that any
external effect has occurred.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Dict, List, Optional, Set, Type, TypeVar

from brain.contracts import (
    ActionIntent,
    DecisionDisposition,
    DecisionRecord,
    EvidenceNeed,
    GoalSpec,
    GoalStatus,
    UnknownRecord,
)
from brain.planning import (
    PlanSnapshot,
    PlanStatus,
    ready_step_ids,
    validate_plan_action_intent_bindings,
    validate_plan_evidence_need_bindings,
)
from brain.reflection import CognitiveReflectionReport, ReflectionDirective
from schemas.base import BaseModel, Field, ValidationError


class CognitivePhase(str, Enum):
    """Semantic phase selected for the next cognitive transition."""

    RESEARCH = "RESEARCH"
    PLANNING = "PLANNING"
    REPLANNING = "REPLANNING"
    DECISION = "DECISION"
    ACTION_READY = "ACTION_READY"
    COMPLETE = "COMPLETE"


class CognitiveDirectiveKind(str, Enum):
    """Provider-neutral instruction emitted by the cognitive coordinator."""

    RESEARCH = "RESEARCH"
    BUILD_PLAN = "BUILD_PLAN"
    REPLAN = "REPLAN"
    MAKE_DECISION = "MAKE_DECISION"
    REVISE_DECISION = "REVISE_DECISION"
    PREPARE_ACTION = "PREPARE_ACTION"
    STOP = "STOP"


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
        f"{field_name} must be one of: {', '.join(member.value for member in enum_cls)}"
    )


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must contain {expected_type.__name__} values or serialized mappings"
    )


def _canonical_list(
    raw_values: object,
    expected_type: type,
    field_name: str,
) -> list:
    if not isinstance(raw_values, list):
        raise ValidationError(f"{field_name} must be a list")
    return [
        expected_type(**_payload(raw, expected_type, field_name))
        for raw in raw_values
    ]


def _ensure_unique_ids(values: list, attribute: str, field_name: str) -> None:
    seen: Set[str] = set()
    for value in values:
        semantic_id = getattr(value, attribute)
        if semantic_id in seen:
            raise ValidationError(f"duplicate {field_name} id: {semantic_id}")
        seen.add(semantic_id)


class CognitiveDirective(BaseModel):
    """One deterministic semantic directive for the selected phase."""

    directive_id: str
    kind: CognitiveDirectiveKind
    target_ids: List[str] = Field(default_factory=list)
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.directive_id = _required_text(self.directive_id, "directive_id")
        self.kind = _enum(self.kind, CognitiveDirectiveKind, "kind")
        if not isinstance(self.target_ids, list):
            raise ValidationError("target_ids must be a list")
        normalized: List[str] = []
        seen = set()
        for raw in self.target_ids:
            target_id = _required_text(raw, "target_ids")
            if target_id not in seen:
                seen.add(target_id)
                normalized.append(target_id)
        self.target_ids = normalized
        self.rationale = _required_text(self.rationale, "rationale")


class CognitiveCycleRequest(BaseModel):
    """Canonical semantic inputs considered in one cognitive cycle."""

    cycle_id: str
    goal: GoalSpec
    evidence_needs: List[EvidenceNeed] = Field(default_factory=list)
    unknowns: List[UnknownRecord] = Field(default_factory=list)
    plan: Optional[PlanSnapshot] = None
    decisions: List[DecisionRecord] = Field(default_factory=list)
    action_intents: List[ActionIntent] = Field(default_factory=list)
    reflection_reports: List[CognitiveReflectionReport] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cycle_id = _required_text(self.cycle_id, "cycle_id")
        self.goal = GoalSpec(**_payload(self.goal, GoalSpec, "goal"))
        goal_id = self.goal.goal_id

        self.evidence_needs = _canonical_list(
            self.evidence_needs, EvidenceNeed, "evidence_needs"
        )
        self.unknowns = _canonical_list(self.unknowns, UnknownRecord, "unknowns")
        self.decisions = _canonical_list(
            self.decisions, DecisionRecord, "decisions"
        )
        self.action_intents = _canonical_list(
            self.action_intents, ActionIntent, "action_intents"
        )
        self.reflection_reports = _canonical_list(
            self.reflection_reports,
            CognitiveReflectionReport,
            "reflection_reports",
        )

        if self.plan is not None:
            self.plan = PlanSnapshot(**_payload(self.plan, PlanSnapshot, "plan"))
            if self.plan.goal_id != goal_id:
                raise ValidationError("plan goal_id must match cognitive cycle goal_id")

        for need in self.evidence_needs:
            if need.goal_id != goal_id:
                raise ValidationError(
                    "evidence_need goal_id must match cognitive cycle goal_id"
                )
        for unknown in self.unknowns:
            if unknown.goal_id != goal_id:
                raise ValidationError(
                    "unknown goal_id must match cognitive cycle goal_id"
                )
        for decision in self.decisions:
            if decision.goal_id != goal_id:
                raise ValidationError(
                    "decision goal_id must match cognitive cycle goal_id"
                )
        for intent in self.action_intents:
            if intent.goal_id != goal_id:
                raise ValidationError(
                    "action_intent goal_id must match cognitive cycle goal_id"
                )
        for report in self.reflection_reports:
            if report.goal_id != goal_id:
                raise ValidationError(
                    "reflection_report goal_id must match cognitive cycle goal_id"
                )

        _ensure_unique_ids(self.evidence_needs, "need_id", "evidence_need")
        _ensure_unique_ids(self.unknowns, "unknown_id", "unknown")
        _ensure_unique_ids(self.decisions, "decision_id", "decision")
        _ensure_unique_ids(self.action_intents, "intent_id", "action_intent")
        _ensure_unique_ids(
            self.reflection_reports, "reflection_id", "reflection_report"
        )


class CognitiveCycle(BaseModel):
    """Canonical semantic result for one deterministic cognitive transition."""

    cycle_id: str
    goal: GoalSpec
    phase: CognitivePhase
    directives: List[CognitiveDirective] = Field(default_factory=list)
    action_intent_ids: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cycle_id = _required_text(self.cycle_id, "cycle_id")
        self.goal = GoalSpec(**_payload(self.goal, GoalSpec, "goal"))
        self.phase = _enum(self.phase, CognitivePhase, "phase")
        self.directives = _canonical_list(
            self.directives, CognitiveDirective, "directives"
        )
        if not self.directives:
            raise ValidationError("directives must contain at least one directive")
        if not isinstance(self.action_intent_ids, list):
            raise ValidationError("action_intent_ids must be a list")
        normalized: List[str] = []
        seen = set()
        for raw in self.action_intent_ids:
            intent_id = _required_text(raw, "action_intent_ids")
            if intent_id not in seen:
                seen.add(intent_id)
                normalized.append(intent_id)
        self.action_intent_ids = normalized
        if self.phase != CognitivePhase.ACTION_READY and self.action_intent_ids:
            raise ValidationError(
                "only ACTION_READY cycles may expose prepared action intent ids"
            )


def _canonical_request(raw: object) -> CognitiveCycleRequest:
    if isinstance(raw, CognitiveCycleRequest):
        data = copy.deepcopy(raw.model_dump())
    elif isinstance(raw, dict):
        data = copy.deepcopy(raw)
    else:
        raise ValidationError(
            "request must be a CognitiveCycleRequest or serialized mapping"
        )
    return CognitiveCycleRequest(**data)


def _directive(
    request: CognitiveCycleRequest,
    kind: CognitiveDirectiveKind,
    target_ids: List[str],
    rationale: str,
) -> CognitiveDirective:
    return CognitiveDirective(
        directive_id=f"{request.cycle_id}:{kind.value.lower()}",
        kind=kind,
        target_ids=target_ids,
        rationale=rationale,
    )


def _result(
    request: CognitiveCycleRequest,
    phase: CognitivePhase,
    directives: List[CognitiveDirective],
    action_intent_ids: Optional[List[str]] = None,
) -> CognitiveCycle:
    return CognitiveCycle(
        cycle_id=request.cycle_id,
        goal=request.goal.model_copy(deep=True),
        phase=phase,
        directives=[directive.model_copy(deep=True) for directive in directives],
        action_intent_ids=list(action_intent_ids or []),
    )


def _reflection_scrutiny(
    reports: List[CognitiveReflectionReport],
) -> tuple[List[str], List[str]]:
    research_directives = {
        ReflectionDirective.RESEARCH_PREMISE,
        ReflectionDirective.RESOLVE_CONTRADICTION,
        ReflectionDirective.REVIEW_IGNORED_EVIDENCE,
        ReflectionDirective.DIVERSIFY_SOURCES,
        ReflectionDirective.REOPEN_HYPOTHESES,
        ReflectionDirective.DEFINE_FALSIFICATION_TEST,
    }
    decision_directives = {
        ReflectionDirective.REVISE_DECISION,
        ReflectionDirective.REMOVE_UNSUPPORTED_CONFIDENCE,
    }
    research_targets: Set[str] = set()
    decision_targets: Set[str] = set()
    for report in reports:
        if any(item in research_directives for item in report.directives):
            research_targets.add(report.reflection_id)
        if any(item in decision_directives for item in report.directives):
            decision_targets.add(report.decision_id)
    return sorted(research_targets), sorted(decision_targets)


def _validate_action_decision_provenance(
    request: CognitiveCycleRequest,
) -> Dict[str, DecisionRecord]:
    decisions = {decision.decision_id: decision for decision in request.decisions}
    for intent in request.action_intents:
        if intent.decision_id is None:
            raise ValidationError(
                f"action intent '{intent.intent_id}' requires decision provenance"
            )
        decision = decisions.get(intent.decision_id)
        if decision is None:
            raise ValidationError(
                f"action intent '{intent.intent_id}' references unknown decision"
            )
        if intent.goal_id != decision.goal_id:
            raise ValidationError(
                f"action intent '{intent.intent_id}' goal must match its decision"
            )
        if intent.owner_agent != decision.agent_id:
            raise ValidationError(
                f"action intent '{intent.intent_id}' owner must match its decision"
            )
    return decisions


def derive_cognitive_cycle(raw_request: object) -> CognitiveCycle:
    """Derive exactly one next semantic phase without performing external effects."""

    request = _canonical_request(raw_request)

    if request.goal.status == GoalStatus.BLOCKED:
        return _result(
            request,
            CognitivePhase.COMPLETE,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.STOP,
                    [request.goal.goal_id],
                    "The canonical goal is blocked; no semantic planning or action is prepared until it is unblocked.",
                )
            ],
        )

    if request.goal.status in (GoalStatus.SATISFIED, GoalStatus.ABANDONED):
        return _result(
            request,
            CognitivePhase.COMPLETE,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.STOP,
                    [request.goal.goal_id],
                    "The canonical goal is terminal; no further semantic action is prepared.",
                )
            ],
        )

    blocking_targets = sorted(
        [need.need_id for need in request.evidence_needs if need.blocking and not need.evidence_refs]
        + [unknown.unknown_id for unknown in request.unknowns if unknown.blocking]
    )
    reflection_research, reflection_decision = _reflection_scrutiny(
        request.reflection_reports
    )
    if blocking_targets or reflection_research:
        targets = sorted(set(blocking_targets + reflection_research))
        return _result(
            request,
            CognitivePhase.RESEARCH,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.RESEARCH,
                    targets,
                    "Blocking uncertainty or reflection scrutiny requires more evidence before action preparation.",
                )
            ],
        )

    if request.plan is None:
        return _result(
            request,
            CognitivePhase.PLANNING,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.BUILD_PLAN,
                    [request.goal.goal_id],
                    "The active goal has no canonical plan snapshot.",
                )
            ],
        )

    if request.plan.status in (PlanStatus.NEEDS_REVISION, PlanStatus.ABANDONED):
        return _result(
            request,
            CognitivePhase.REPLANNING,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.REPLAN,
                    [request.plan.plan_id],
                    "The canonical plan cannot be used as the current active path.",
                )
            ],
        )

    if request.plan.status == PlanStatus.SATISFIED:
        raise ValidationError(
            "a SATISFIED plan cannot be paired with a non-terminal goal"
        )

    if not request.decisions:
        return _result(
            request,
            CognitivePhase.DECISION,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.MAKE_DECISION,
                    [request.goal.goal_id],
                    "The active plan has no canonical decision record.",
                )
            ],
        )

    if reflection_decision:
        return _result(
            request,
            CognitivePhase.DECISION,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.REVISE_DECISION,
                    reflection_decision,
                    "Reflection requires decision revision before action preparation.",
                )
            ],
        )

    non_proceeding = sorted(
        decision.decision_id
        for decision in request.decisions
        if decision.disposition != DecisionDisposition.PROCEED
    )
    if non_proceeding:
        return _result(
            request,
            CognitivePhase.DECISION,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.REVISE_DECISION,
                    non_proceeding,
                    "Non-PROCEED decisions cannot support action preparation.",
                )
            ],
        )

    _validate_action_decision_provenance(request)
    validate_plan_evidence_need_bindings(request.plan, request.evidence_needs)
    validate_plan_action_intent_bindings(request.plan, request.action_intents)

    ready_steps = set(ready_step_ids(request.plan))
    ready_intent_ids: List[str] = []
    for step in request.plan.steps:
        if step.step_id not in ready_steps:
            continue
        ready_intent_ids.extend(step.action_intent_ids)

    if not ready_intent_ids:
        return _result(
            request,
            CognitivePhase.REPLANNING,
            [
                _directive(
                    request,
                    CognitiveDirectiveKind.REPLAN,
                    [request.plan.plan_id],
                    "The active plan has no ready semantic action path.",
                )
            ],
        )

    return _result(
        request,
        CognitivePhase.ACTION_READY,
        [
            _directive(
                request,
                CognitiveDirectiveKind.PREPARE_ACTION,
                ready_intent_ids,
                "Canonical plan and decision provenance support semantic action preparation.",
            )
        ],
        action_intent_ids=ready_intent_ids,
    )