"""Provider-neutral stop and trajectory-control policy for the Brain layer.

This module converts a canonically re-evaluated semantic trajectory plus explicit
outstanding unknowns/evidence needs into one auditable ``StopDecision``. It
never executes plans, dispatches tools, mutates runtime state, selects a model
or provider, or persists data.

Core invariants:
- raw ``TrajectoryEvaluationRequest`` is the authority-bearing trajectory input;
- caller-supplied ``TrajectoryEvaluation`` is optional audit material only;
- trajectory verdict/disposition pairs must be canonical;
- a claimed successful stop must retain evidence-backed supported criteria and
  no unresolved/refuted/contested/ambiguous criteria;
- outstanding records are bound to exactly one goal and identities are unique;
- blocking unknowns/evidence needs cannot be hidden by a nominal success;
- evidence references on an outstanding EvidenceNeed do not silently mark it
  resolved; resolution is represented by removing it from the outstanding set.
"""

from __future__ import annotations

import copy
from typing import List, Optional

from brain.contracts import EvidenceNeed, StopDecision, StopReason, UnknownRecord
from brain.outcomes import (
    OutcomeVerdict,
    TrajectoryDisposition,
    TrajectoryEvaluation,
    TrajectoryEvaluationRequest,
    evaluate_trajectory,
)
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


def _normalize_trajectory(value: object) -> TrajectoryEvaluation:
    if isinstance(value, TrajectoryEvaluation):
        return copy.deepcopy(value)
    if isinstance(value, dict):
        return TrajectoryEvaluation(**copy.deepcopy(value))
    raise ValidationError("trajectory must be a TrajectoryEvaluation")


def _normalize_trajectory_request(value: object) -> TrajectoryEvaluationRequest:
    if isinstance(value, TrajectoryEvaluationRequest):
        return copy.deepcopy(value)
    if isinstance(value, dict):
        return TrajectoryEvaluationRequest(**copy.deepcopy(value))
    raise ValidationError("trajectory_request must be a TrajectoryEvaluationRequest")


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


def _trajectory_matches(
    supplied: TrajectoryEvaluation, canonical: TrajectoryEvaluation
) -> bool:
    return supplied.model_dump() == canonical.model_dump()


class StopEvaluationRequest(BaseModel):
    """Exact semantic inputs used to authorize stopping or continuing a goal.

    ``trajectory_request`` carries the raw Outcome inputs and is the only
    authority that can establish a trajectory at the Stop use boundary.
    ``trajectory`` is retained as an optional audit snapshot for compatibility;
    it can never substitute for the raw request.
    """

    evaluation_id: str
    goal_id: str
    trajectory: Optional[TrajectoryEvaluation] = None
    trajectory_request: Optional[TrajectoryEvaluationRequest] = None
    outstanding_unknowns: List[UnknownRecord] = Field(default_factory=list)
    outstanding_evidence_needs: List[EvidenceNeed] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.evaluation_id = _required_text(self.evaluation_id, "evaluation_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")

        if self.trajectory is not None:
            self.trajectory = _normalize_trajectory(self.trajectory)
            if self.trajectory.goal_id != self.goal_id:
                raise ValidationError(
                    "trajectory.goal_id must exactly match request.goal_id"
                )
            _validate_trajectory_contract(self.trajectory)

        if self.trajectory_request is not None:
            self.trajectory_request = _normalize_trajectory_request(
                self.trajectory_request
            )
            if self.trajectory_request.goal.goal_id != self.goal_id:
                raise ValidationError(
                    "trajectory_request.goal.goal_id must exactly match request.goal_id"
                )
            if self.trajectory_request.plan.goal_id != self.goal_id:
                raise ValidationError(
                    "trajectory_request.plan.goal_id must exactly match request.goal_id"
                )

        if self.trajectory is None and self.trajectory_request is None:
            raise ValidationError(
                "trajectory_request or trajectory audit snapshot must be provided"
            )

        self.outstanding_unknowns = _normalize_unknowns(
            self.outstanding_unknowns, self.goal_id
        )
        self.outstanding_evidence_needs = _normalize_needs(
            self.outstanding_evidence_needs, self.goal_id
        )


def evaluate_stop(request: StopEvaluationRequest) -> StopDecision:
    """Return the semantic stopping decision for one exact goal trajectory.

    Stop recomputes Outcome authority from the raw ``trajectory_request`` at the
    use boundary. A caller-built trajectory without those raw inputs cannot
    independently authorize any trajectory-derived stop/continue result.
    """

    if not isinstance(request, StopEvaluationRequest):
        raise ValidationError("request must be a StopEvaluationRequest")

    open_questions = [item.question for item in request.outstanding_unknowns]
    open_questions.extend(item.question for item in request.outstanding_evidence_needs)

    blocking = any(item.blocking for item in request.outstanding_unknowns) or any(
        item.blocking for item in request.outstanding_evidence_needs
    )

    # Explicit blockers do not depend on a trajectory verdict and therefore
    # dominate even when raw outcome provenance is unavailable.
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

    if request.trajectory_request is None:
        return StopDecision(
            should_stop=True,
            reason=StopReason.INSUFFICIENT_EVIDENCE,
            rationale=(
                "Stop cannot derive authoritative trajectory state because the "
                "raw Outcome evaluation request is missing. A caller-supplied "
                "trajectory audit snapshot cannot authorize goal completion."
            ),
            unresolved_questions=open_questions,
        )

    canonical_request = copy.deepcopy(request.trajectory_request)
    trajectory = evaluate_trajectory(canonical_request)
    if trajectory.goal_id != request.goal_id:
        raise ValidationError(
            "canonical trajectory goal_id must exactly match request.goal_id"
        )
    _validate_trajectory_contract(trajectory)

    if request.trajectory is not None and not _trajectory_matches(
        request.trajectory, trajectory
    ):
        raise ValidationError(
            "trajectory audit snapshot must exactly match canonical raw Outcome evaluation"
        )

    if (
        trajectory.outcome_verdict == OutcomeVerdict.SATISFIED
        and trajectory.disposition == TrajectoryDisposition.STOP
    ):
        return StopDecision(
            should_stop=True,
            reason=StopReason.GOAL_SATISFIED,
            rationale=(
                "Every declared success criterion is canonically backed by raw "
                "evidence and no blocking outstanding state remains."
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

    raise ValidationError("unsupported trajectory disposition for stopping policy")
