"""Provider-neutral goal outcome and trajectory evaluation for the Brain layer.

Planning progress is not evidence of goal success. A plan may finish every step
while the semantic goal remains unproven, contradicted, or contested. This
module therefore evaluates GoalSpec.success_criteria against raw semantic
evidence from ``brain.evidence`` and decides whether the cognitive trajectory
should stop, continue, revise, or escalate.

This layer is semantic only. It never executes plans, dispatches tools, reads
runtime receipts, selects providers/models, persists state, or mutates a goal or
plan. Existing snapshots remain immutable inputs to an auditable evaluation.

Core invariant: caller-constructed evidence assessments are audit material only.
Autonomous goal success must be re-derived from the raw criterion evidence at
the Outcome use boundary.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Dict, List, Type, TypeVar

from brain.contracts import GoalSpec
from brain.evidence import (
    ClaimEvidenceAssessment,
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceSignal,
    assess_claim_evidence,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStepState
from schemas.base import BaseModel, Field, ValidationError


class OutcomeVerdict(str, Enum):
    SATISFIED = "SATISFIED"
    REFUTED = "REFUTED"
    CONTESTED = "CONTESTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class TrajectoryDisposition(str, Enum):
    STOP = "STOP"
    CONTINUE = "CONTINUE"
    REVISE = "REVISE"
    ESCALATE = "ESCALATE"


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


def _unique_text_list(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of strings")
    result: List[str] = []
    seen = set()
    for raw in value:
        item = _required_text(raw, field_name)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _claim_evidence_request(value: object, field_name: str) -> ClaimEvidenceRequest:
    if isinstance(value, ClaimEvidenceRequest):
        return value.model_copy(deep=True)
    if not isinstance(value, dict):
        raise ValidationError(
            f"{field_name} must contain only ClaimEvidenceRequest objects"
        )

    data = copy.deepcopy(value)
    raw_evidence = data.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ValidationError(f"{field_name}.evidence must be a list")
    normalized_evidence: List[EvidenceSignal] = []
    for raw_signal in raw_evidence:
        if isinstance(raw_signal, EvidenceSignal):
            normalized_evidence.append(raw_signal.model_copy(deep=True))
        elif isinstance(raw_signal, dict):
            normalized_evidence.append(EvidenceSignal(**raw_signal))
        else:
            raise ValidationError(
                f"{field_name}.evidence must contain only EvidenceSignal objects"
            )
    data["evidence"] = normalized_evidence
    return ClaimEvidenceRequest(**data)


def _assessment_matches(
    supplied: ClaimEvidenceAssessment, canonical: ClaimEvidenceAssessment
) -> bool:
    return supplied.model_dump() == canonical.model_dump()


class TrajectoryEvaluationRequest(BaseModel):
    """Exact semantic inputs for deciding whether one goal is actually met.

    ``criterion_evidence_requests`` are authority-bearing raw evidence inputs.
    ``criterion_assessments`` are optional audit snapshots and never substitute
    for a matching raw request.
    """

    evaluation_id: str
    goal: GoalSpec
    plan: PlanSnapshot
    criterion_assessments: List[ClaimEvidenceAssessment] = Field(default_factory=list)
    criterion_evidence_requests: List[ClaimEvidenceRequest] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.evaluation_id = _required_text(self.evaluation_id, "evaluation_id")

        if not isinstance(self.goal, GoalSpec):
            if isinstance(self.goal, dict):
                self.goal = GoalSpec(**self.goal)
            else:
                raise ValidationError("goal must be a GoalSpec")
        else:
            self.goal = self.goal.model_copy(deep=True)

        if not isinstance(self.plan, PlanSnapshot):
            if isinstance(self.plan, dict):
                self.plan = PlanSnapshot(**self.plan)
            else:
                raise ValidationError("plan must be a PlanSnapshot")
        else:
            self.plan = self.plan.model_copy(deep=True)

        if self.plan.goal_id != self.goal.goal_id:
            raise ValidationError("plan.goal_id must exactly match goal.goal_id")

        if not isinstance(self.criterion_assessments, list):
            raise ValidationError(
                "criterion_assessments must be a list of ClaimEvidenceAssessment objects"
            )
        normalized_assessments: List[ClaimEvidenceAssessment] = []
        seen_assessment_ids = set()
        for raw in self.criterion_assessments:
            if isinstance(raw, ClaimEvidenceAssessment):
                assessment = raw.model_copy(deep=True)
            elif isinstance(raw, dict):
                assessment = ClaimEvidenceAssessment(**raw)
            else:
                raise ValidationError(
                    "criterion_assessments must contain only ClaimEvidenceAssessment objects"
                )
            if assessment.assessment_id in seen_assessment_ids:
                raise ValidationError(
                    f"duplicate criterion assessment_id: {assessment.assessment_id}"
                )
            seen_assessment_ids.add(assessment.assessment_id)
            normalized_assessments.append(assessment)
        self.criterion_assessments = normalized_assessments

        if not isinstance(self.criterion_evidence_requests, list):
            raise ValidationError(
                "criterion_evidence_requests must be a list of ClaimEvidenceRequest objects"
            )
        normalized_requests: List[ClaimEvidenceRequest] = []
        seen_request_ids = set()
        for raw in self.criterion_evidence_requests:
            evidence_request = _claim_evidence_request(
                raw, "criterion_evidence_requests"
            )
            if evidence_request.assessment_id in seen_request_ids:
                raise ValidationError(
                    f"duplicate criterion evidence assessment_id: {evidence_request.assessment_id}"
                )
            seen_request_ids.add(evidence_request.assessment_id)
            normalized_requests.append(evidence_request)
        self.criterion_evidence_requests = normalized_requests


class TrajectoryEvaluation(BaseModel):
    """Auditable semantic outcome with success and trajectory control separated."""

    evaluation_id: str
    goal_id: str
    plan_id: str
    plan_revision: int
    outcome_verdict: OutcomeVerdict
    disposition: TrajectoryDisposition
    supported_criteria: List[str] = Field(default_factory=list)
    refuted_criteria: List[str] = Field(default_factory=list)
    contested_criteria: List[str] = Field(default_factory=list)
    unresolved_criteria: List[str] = Field(default_factory=list)
    ambiguous_criteria: List[str] = Field(default_factory=list)
    ignored_assessment_ids: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.evaluation_id = _required_text(self.evaluation_id, "evaluation_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.plan_id = _required_text(self.plan_id, "plan_id")
        if isinstance(self.plan_revision, bool) or not isinstance(self.plan_revision, int) or self.plan_revision < 1:
            raise ValidationError("plan_revision must be a positive integer")
        self.outcome_verdict = _enum(
            self.outcome_verdict, OutcomeVerdict, "outcome_verdict"
        )
        self.disposition = _enum(
            self.disposition, TrajectoryDisposition, "disposition"
        )
        self.supported_criteria = _unique_text_list(
            self.supported_criteria, "supported_criteria"
        )
        self.refuted_criteria = _unique_text_list(
            self.refuted_criteria, "refuted_criteria"
        )
        self.contested_criteria = _unique_text_list(
            self.contested_criteria, "contested_criteria"
        )
        self.unresolved_criteria = _unique_text_list(
            self.unresolved_criteria, "unresolved_criteria"
        )
        self.ambiguous_criteria = _unique_text_list(
            self.ambiguous_criteria, "ambiguous_criteria"
        )
        self.ignored_assessment_ids = _unique_text_list(
            self.ignored_assessment_ids, "ignored_assessment_ids"
        )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one outcome reason")


def evaluate_trajectory(request: TrajectoryEvaluationRequest) -> TrajectoryEvaluation:
    """Evaluate actual goal success independently from plan/task completion.

    Raw ``ClaimEvidenceRequest`` objects are the evidence authority. Each one is
    re-evaluated canonically at this use boundary. Optional supplied assessments
    are only accepted as audit snapshots when they exactly equal the canonical
    result for the same assessment ID. Multiple raw assessments for one criterion
    remain ambiguous rather than allowing callers to cherry-pick a verdict.
    """

    if not isinstance(request, TrajectoryEvaluationRequest):
        raise ValidationError("request must be a TrajectoryEvaluationRequest")

    goal = request.goal
    plan = request.plan
    criteria = list(goal.success_criteria)
    reasons: List[str] = []
    ignored_assessment_ids: List[str] = []

    if not criteria:
        return TrajectoryEvaluation(
            evaluation_id=request.evaluation_id,
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            plan_revision=plan.revision,
            outcome_verdict=OutcomeVerdict.INCONCLUSIVE,
            disposition=TrajectoryDisposition.ESCALATE,
            reasons=[
                "goal has no explicit success criteria, so autonomous success cannot be established"
            ],
        )

    grouped: Dict[str, List[ClaimEvidenceAssessment]] = {
        criterion: [] for criterion in criteria
    }
    criterion_set = set(criteria)
    canonical_by_assessment_id: Dict[str, ClaimEvidenceAssessment] = {}

    for evidence_request in request.criterion_evidence_requests:
        if evidence_request.goal_id != goal.goal_id:
            ignored_assessment_ids.append(evidence_request.assessment_id)
            reasons.append(
                f"raw evidence {evidence_request.assessment_id} ignored: goal_id does not match the evaluated goal"
            )
            continue
        if evidence_request.claim_id not in criterion_set:
            ignored_assessment_ids.append(evidence_request.assessment_id)
            reasons.append(
                f"raw evidence {evidence_request.assessment_id} ignored: claim_id is not an exact declared success criterion"
            )
            continue

        canonical = assess_claim_evidence(evidence_request)
        canonical_by_assessment_id[evidence_request.assessment_id] = canonical
        grouped[evidence_request.claim_id].append(canonical)

    for assessment in request.criterion_assessments:
        canonical = canonical_by_assessment_id.get(assessment.assessment_id)
        if canonical is None:
            ignored_assessment_ids.append(assessment.assessment_id)
            reasons.append(
                f"assessment {assessment.assessment_id} ignored: no matching raw criterion evidence request exists"
            )
            continue
        if not _assessment_matches(assessment, canonical):
            raise ValidationError(
                f"criterion assessment {assessment.assessment_id} must exactly match canonical raw evidence evaluation"
            )

    supported: List[str] = []
    refuted: List[str] = []
    contested: List[str] = []
    unresolved: List[str] = []
    ambiguous: List[str] = []

    for criterion in criteria:
        assessments = grouped[criterion]
        if not assessments:
            unresolved.append(criterion)
            reasons.append(f"success criterion unresolved: {criterion}")
            continue

        if len(assessments) > 1:
            ambiguous.append(criterion)
            unresolved.append(criterion)
            ignored_assessment_ids.extend(
                assessment.assessment_id for assessment in assessments
            )
            reasons.append(
                f"success criterion ambiguous: multiple canonical raw evidence assessments exist for exact criterion '{criterion}'"
            )
            continue

        assessment = assessments[0]
        if assessment.verdict == ClaimVerdict.SUPPORTED:
            if assessment.supporting_evidence_refs:
                supported.append(criterion)
            else:
                unresolved.append(criterion)
                reasons.append(
                    f"SUPPORTED criterion lacks retained supporting evidence refs and fails closed: {criterion}"
                )
        elif assessment.verdict == ClaimVerdict.REFUTED:
            if assessment.contradicting_evidence_refs:
                refuted.append(criterion)
            else:
                unresolved.append(criterion)
                reasons.append(
                    f"REFUTED criterion lacks retained contradicting evidence refs and fails closed: {criterion}"
                )
        elif assessment.verdict == ClaimVerdict.CONTESTED:
            if assessment.supporting_evidence_refs and assessment.contradicting_evidence_refs:
                contested.append(criterion)
            else:
                unresolved.append(criterion)
                reasons.append(
                    f"CONTESTED criterion lacks both sides of retained evidence and fails closed: {criterion}"
                )
        else:
            unresolved.append(criterion)
            reasons.append(f"success criterion has insufficient raw evidence: {criterion}")

    # Contradiction outranks ordinary refutation because it explicitly requires
    # unresolved competing evidence to be surfaced rather than silently revised.
    if contested:
        outcome_verdict = OutcomeVerdict.CONTESTED
        disposition = TrajectoryDisposition.ESCALATE
        reasons.append(
            "at least one success criterion is CONTESTED; contradictory evidence must be resolved before stopping"
        )
    elif refuted:
        outcome_verdict = OutcomeVerdict.REFUTED
        disposition = TrajectoryDisposition.REVISE
        reasons.append(
            "at least one success criterion is canonically evidence-backed REFUTED; the trajectory requires revision"
        )
    elif unresolved:
        outcome_verdict = OutcomeVerdict.INCONCLUSIVE
        plan_has_remaining_work = any(
            step.state != PlanStepState.COMPLETED for step in plan.steps
        )
        if plan.status == PlanStatus.ACTIVE and plan_has_remaining_work:
            disposition = TrajectoryDisposition.CONTINUE
            reasons.append(
                "goal success is unresolved and the active plan still contains unfinished cognitive work"
            )
        elif plan.status == PlanStatus.ABANDONED:
            disposition = TrajectoryDisposition.ESCALATE
            reasons.append(
                "goal success is unresolved and the plan is abandoned; a new human or higher-level decision is required"
            )
        else:
            disposition = TrajectoryDisposition.REVISE
            reasons.append(
                "goal success is unresolved but the current trajectory has no remaining active work that can establish it"
            )
    else:
        outcome_verdict = OutcomeVerdict.SATISFIED
        disposition = TrajectoryDisposition.STOP
        reasons.append(
            "every declared success criterion has a canonical raw-evidence-backed SUPPORTED assessment"
        )

    return TrajectoryEvaluation(
        evaluation_id=request.evaluation_id,
        goal_id=goal.goal_id,
        plan_id=plan.plan_id,
        plan_revision=plan.revision,
        outcome_verdict=outcome_verdict,
        disposition=disposition,
        supported_criteria=supported,
        refuted_criteria=refuted,
        contested_criteria=contested,
        unresolved_criteria=unresolved,
        ambiguous_criteria=ambiguous,
        ignored_assessment_ids=ignored_assessment_ids,
        reasons=reasons,
    )
