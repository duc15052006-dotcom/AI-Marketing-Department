"""Provider-neutral stop and trajectory-control policy for the Brain layer.

This module converts an already-evaluated semantic trajectory plus explicit
outstanding unknowns/evidence needs into one auditable ``StopDecision``.  It
never executes plans, dispatches tools, mutates runtime state, selects a model
or provider, or persists data.

Core invariants:
- trajectory verdict/disposition pairs must be canonical;
- a claimed successful stop must retain evidence-backed supported criteria and
  no unresolved/refuted/contested/ambiguous criteria;
- outstanding records are bound to exactly one goal and identities are unique;
- blocking unknowns/evidence needs cannot be hidden by a nominal success;
- evidence references on an outstanding EvidenceNeed do not silently mark it
  resolved; resolution is represented by removing it from the outstanding set.
"""

from __future__ import annotations

from typing import List

from brain.contracts import EvidenceNeed, StopDecision, StopReason, UnknownRecord
from brain.outcomes import OutcomeVerdict, TrajectoryDisposition, TrajectoryEvaluation
from schemas.base import BaseModel, Field, ValidationError


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _normalize_unknowns(value: object, goal_id: str) -> List[UnknownRecord]:
    if not isinstance(value, list):
        raise ValidationError("outstanding_unknowns must be a list")
    result: List[UnknownRecord] = []
    seen = set()
    for raw in value:
        if isinstance(raw, UnknownRecord):
            item = raw.model_copy(deep=True)
        elif isinstance(raw, dict):
            item = UnknownRecord(**raw)
        else:
            raise ValidationError(
                "outstanding_unknowns must contain only UnknownRecord objects"
            )
        if item.goal_id != goal_id:
            raise ValidationError(
                "outstanding unknown goal_id must exactly match request.goal_id"
            )
        if item.unknown_id in seen:
            raise ValidationError(f"duplicate outstanding unknown_id: {item.unknown_id}")
        seen.add(item.unknown_id)
        result.append(item)
    return result


def _normalize_needs(value: object, goal_id: str) -> List[EvidenceNeed]:
    if not isinstance(value, list):
        raise ValidationError("outstanding_evidence_needs must be a list")
    result: List[EvidenceNeed] = []
    seen = set()
    for raw in value:
        if isinstance(raw, EvidenceNeed):
            item = raw.model_copy(deep=True)
        elif isinstance(raw, dict):
            item = EvidenceNeed(**raw)
        else:
            raise ValidationError(
                "outstanding_evidence_needs must contain only EvidenceNeed objects"
            )
        if item.goal_id != goal_id:
            raise ValidationError(
                "outstanding evidence need goal_id must exactly match request.goal_id"
            )
        if item.need_id in seen:
            raise ValidationError(f"duplicate outstanding need_id: {item.need_id}")
        seen.add(item.need_id)
        result.append(item)
    return result


def _validate_trajectory_contract(trajectory: TrajectoryEvaluation) -> None:
    """Reject trajectory state combinations that BRAIN-8 would never emit."""

    pair = (trajectory.outcome_verdict, trajectory.disposition)
    allowed = {
        (OutcomeVerdict.SATISFIED, TrajectoryDisposition.STOP),
        (OutcomeVerdict.REFUTED, TrajectoryDisposition.REVISE),
        (OutcomeVerdict.CONTESTED, TrajectoryDisposition.ESCALATE),
        (OutcomeVerdict.INCONCLUSIVE, TrajectoryDisposition.CONTINUE),
        (OutcomeVerdict.INCONCLUSIVE, TrajectoryDisposition.REVISE),
        (OutcomeVerdict.INCONCLUSIVE, TrajectoryDisposition.ESCALATE),
    }
    if pair not in allowed:
        raise ValidationError(
            "trajectory outcome_verdict/disposition pair is not canonical"
        )

    if trajectory.outcome_verdict == OutcomeVerdict.SATISFIED:
        if not trajectory.supported_criteria:
            raise ValidationError(
                "SATISFIED/STOP requires at least one supported success criterion"
            )
        if (
            trajectory.refuted_criteria
            or trajectory.contested_criteria
            or trajectory.unresolved_criteria
            or trajectory.ambiguous_criteria
        ):
            raise ValidationError(
                "SATISFIED/STOP cannot retain unresolved, refuted, contested, or ambiguous criteria"
            )


class StopEvaluationRequest(BaseModel):
    """Exact semantic inputs used to authorize stopping or continuing a goal."""

    evaluation_id: str
    goal_id: str
    trajectory: TrajectoryEvaluation
    outstanding_unknowns: List[UnknownRecord] = Field(default_factory=list)
    outstanding_evidence_needs: List[EvidenceNeed] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.evaluation_id = _required_text(self.evaluation_id, "evaluation_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")

        if isinstance(self.trajectory, TrajectoryEvaluation):
            self.trajectory = self.trajectory.model_copy(deep=True)
        elif isinstance(self.trajectory, dict):
            self.trajectory = TrajectoryEvaluation(**self.trajectory)
        else:
            raise ValidationError("trajectory must be a TrajectoryEvaluation")

        if self.trajectory.goal_id != self.goal_id:
            raise ValidationError(
                "trajectory.goal_id must exactly match request.goal_id"
            )
        _validate_trajectory_contract(self.trajectory)

        self.outstanding_unknowns = _normalize_unknowns(
            self.outstanding_unknowns, self.goal_id
        )
        self.outstanding_evidence_needs = _normalize_needs(
            self.outstanding_evidence_needs, self.goal_id
        )


def evaluate_stop(request: StopEvaluationRequest) -> StopDecision:
    """Return the semantic stopping decision for one exact goal trajectory."""

    if not isinstance(request, StopEvaluationRequest):
        raise ValidationError("request must be a StopEvaluationRequest")

    trajectory = request.trajectory
    open_questions = [item.question for item in request.outstanding_unknowns]
    open_questions.extend(item.question for item in request.outstanding_evidence_needs)

    blocking = any(item.blocking for item in request.outstanding_unknowns) or any(
        item.blocking for item in request.outstanding_evidence_needs
    )

    # Explicit blockers dominate a nominal trajectory stop. A blocking record is
    # outstanding by definition; merely attaching an evidence reference does not
    # resolve it.
    if blocking:
        return StopDecision(
            should_stop=True,
            reason=StopReason.BLOCKED,
            rationale=(
                "The current trajectory is blocked by at least one unresolved "
                "blocking unknown or evidence need."
            ),
            unresolved_questions=open_questions,
        )

    if (
        trajectory.outcome_verdict == OutcomeVerdict.SATISFIED
        and trajectory.disposition == TrajectoryDisposition.STOP
    ):
        return StopDecision(
            should_stop=True,
            reason=StopReason.GOAL_SATISFIED,
            rationale=(
                "Every declared success criterion is evidence-backed and no "
                "blocking outstanding state remains."
            ),
            unresolved_questions=open_questions,
        )

    if trajectory.disposition == TrajectoryDisposition.CONTINUE:
        return StopDecision(
            should_stop=False,
            reason=StopReason.CONTINUE,
            rationale=(
                "Goal success remains unresolved and the current cognitive "
                "trajectory still has valid work to continue."
            ),
            unresolved_questions=open_questions,
        )

    if trajectory.disposition == TrajectoryDisposition.REVISE:
        return StopDecision(
            should_stop=True,
            reason=StopReason.INSUFFICIENT_EVIDENCE,
            rationale=(
                "The current cognitive path cannot establish the goal and must "
                "stop before a revised trajectory is created."
            ),
            unresolved_questions=open_questions,
        )

    if trajectory.disposition == TrajectoryDisposition.ESCALATE:
        return StopDecision(
            should_stop=True,
            reason=StopReason.HUMAN_DECISION_REQUIRED,
            rationale=(
                "The trajectory requires explicit higher-level or human "
                "resolution before autonomous work can continue."
            ),
            unresolved_questions=open_questions,
        )

    # Defensive fail-closed branch. Construction validation should make this
    # unreachable, but keeping it explicit prevents future enum expansion from
    # silently granting continuation authority.
    raise ValidationError("unsupported trajectory disposition for stopping policy")
