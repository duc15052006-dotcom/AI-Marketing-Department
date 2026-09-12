"""Evidence-authoritative collective cognition for exactly five permanent ASIs.

This module composes already-canonical collaboration decisions into one semantic
five-ASI synthesis decision. It deliberately does not dispatch agents, execute
tools, access providers, persist state, or create a sixth coordinator.

Core invariants:
- all five permanent ASIs must participate in every collective cycle;
- candidate identity, goal and author bind exactly to its collaboration assessment;
- collaboration authority is re-derived at the use boundary;
- dissent is preserved and never averaged into consensus;
- multiple accepted alternatives require arbitration rather than majority voting;
- insufficient evidence routes to research even when peers agree;
- output remains semantic-only and detached from caller-owned mutable inputs.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.collaboration import (
    CollaborationAssessment,
    CollaborationDecision,
    CollaborationDisposition,
    evaluate_collaboration,
)
from brain.contracts import BrainAgentId
from schemas.base import BaseModel, Field, ValidationError


class CollectiveCognitionDisposition(str, Enum):
    READY_FOR_SYNTHESIS = "READY_FOR_SYNTHESIS"
    NEEDS_REVISION = "NEEDS_REVISION"
    NEEDS_RESEARCH = "NEEDS_RESEARCH"
    NEEDS_ARBITRATION = "NEEDS_ARBITRATION"


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


def _collaboration_assessment(value: object) -> CollaborationAssessment:
    if isinstance(value, CollaborationAssessment):
        return copy.deepcopy(value)
    if isinstance(value, dict):
        return CollaborationAssessment(**copy.deepcopy(value))
    raise ValidationError(
        "collaboration_assessment must be a CollaborationAssessment or mapping"
    )


class CollectiveCandidate(BaseModel):
    """One candidate semantic proposal entering five-ASI synthesis."""

    candidate_id: str
    goal_id: str
    author_agent: BrainAgentId
    collaboration_assessment: CollaborationAssessment

    def __post_init__(self) -> None:
        super().__post_init__()
        self.candidate_id = _required_text(self.candidate_id, "candidate_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.author_agent = _enum(self.author_agent, BrainAgentId, "author_agent")
        self.collaboration_assessment = _collaboration_assessment(
            self.collaboration_assessment
        )

        assessment = self.collaboration_assessment
        if assessment.proposal_id != self.candidate_id:
            raise ValidationError(
                "candidate_id must exactly match collaboration proposal_id"
            )
        if assessment.goal_id != self.goal_id:
            raise ValidationError(
                "candidate goal_id must exactly match collaboration goal_id"
            )
        if assessment.author_agent != self.author_agent:
            raise ValidationError(
                "candidate author_agent must exactly match collaboration author_agent"
            )


class CollectiveCognitionRequest(BaseModel):
    """One semantic five-ASI collective reasoning cycle."""

    cycle_id: str
    goal_id: str
    candidates: List[CollectiveCandidate] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cycle_id = _required_text(self.cycle_id, "cycle_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        if not isinstance(self.candidates, list) or not self.candidates:
            raise ValidationError("candidates must contain at least one candidate")

        normalized: List[CollectiveCandidate] = []
        seen_candidate_ids = set()
        seen_assessment_ids = set()
        for raw in self.candidates:
            if isinstance(raw, CollectiveCandidate):
                candidate = copy.deepcopy(raw)
            elif isinstance(raw, dict):
                candidate = CollectiveCandidate(**copy.deepcopy(raw))
            else:
                raise ValidationError(
                    "candidates must contain only CollectiveCandidate objects"
                )

            if candidate.goal_id != self.goal_id:
                raise ValidationError(
                    "every candidate goal_id must exactly match collective goal_id"
                )
            if candidate.candidate_id in seen_candidate_ids:
                raise ValidationError(
                    f"duplicate collective candidate_id: {candidate.candidate_id}"
                )
            seen_candidate_ids.add(candidate.candidate_id)

            assessment_id = candidate.collaboration_assessment.assessment_id
            if assessment_id in seen_assessment_ids:
                raise ValidationError(
                    f"duplicate collaboration assessment_id: {assessment_id}"
                )
            seen_assessment_ids.add(assessment_id)
            normalized.append(candidate)

        self.candidates = normalized


class CollectiveCandidateDecision(BaseModel):
    """Canonical collaboration decision preserved for one candidate."""

    candidate_id: str
    assessment_id: str
    disposition: CollaborationDisposition
    supporting_review_ids: List[str] = Field(default_factory=list)
    dissenting_review_ids: List[str] = Field(default_factory=list)
    ignored_review_ids: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.candidate_id = _required_text(self.candidate_id, "candidate_id")
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.disposition = _enum(
            self.disposition, CollaborationDisposition, "disposition"
        )
        self.supporting_review_ids = _unique_text_list(
            self.supporting_review_ids, "supporting_review_ids"
        )
        self.dissenting_review_ids = _unique_text_list(
            self.dissenting_review_ids, "dissenting_review_ids"
        )
        self.ignored_review_ids = _unique_text_list(
            self.ignored_review_ids, "ignored_review_ids"
        )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one reason")


class CollectiveCognitionDecision(BaseModel):
    """Auditable five-ASI synthesis routing decision without vote authority."""

    cycle_id: str
    goal_id: str
    disposition: CollectiveCognitionDisposition
    participant_agents: List[BrainAgentId] = Field(default_factory=list)
    accepted_candidate_ids: List[str] = Field(default_factory=list)
    selected_candidate_id: Optional[str] = None
    candidate_decisions: List[CollectiveCandidateDecision] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cycle_id = _required_text(self.cycle_id, "cycle_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.disposition = _enum(
            self.disposition, CollectiveCognitionDisposition, "disposition"
        )
        if not isinstance(self.participant_agents, list):
            raise ValidationError("participant_agents must be a list")
        self.participant_agents = [
            _enum(agent, BrainAgentId, "participant_agents")
            for agent in self.participant_agents
        ]
        if len(set(self.participant_agents)) != len(self.participant_agents):
            raise ValidationError("participant_agents must be unique")
        self.accepted_candidate_ids = _unique_text_list(
            self.accepted_candidate_ids, "accepted_candidate_ids"
        )
        if self.selected_candidate_id is not None:
            self.selected_candidate_id = _required_text(
                self.selected_candidate_id, "selected_candidate_id"
            )
            if self.selected_candidate_id not in self.accepted_candidate_ids:
                raise ValidationError(
                    "selected_candidate_id must be one of accepted_candidate_ids"
                )
        if not isinstance(self.candidate_decisions, list):
            raise ValidationError("candidate_decisions must be a list")
        normalized_decisions: List[CollectiveCandidateDecision] = []
        for raw in self.candidate_decisions:
            if isinstance(raw, CollectiveCandidateDecision):
                normalized_decisions.append(copy.deepcopy(raw))
            elif isinstance(raw, dict):
                normalized_decisions.append(CollectiveCandidateDecision(**copy.deepcopy(raw)))
            else:
                raise ValidationError(
                    "candidate_decisions must contain CollectiveCandidateDecision objects"
                )
        self.candidate_decisions = normalized_decisions
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one collective reason")


def _canonical_request(raw_request: CollectiveCognitionRequest) -> CollectiveCognitionRequest:
    if not isinstance(raw_request, CollectiveCognitionRequest):
        raise ValidationError("request must be a CollectiveCognitionRequest")
    try:
        return CollectiveCognitionRequest(**copy.deepcopy(raw_request.model_dump()))
    except (ValidationError, TypeError, AttributeError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("collective cognition request failed canonical reconstruction") from exc


def _participants(request: CollectiveCognitionRequest) -> List[BrainAgentId]:
    seen = set()
    for candidate in request.candidates:
        seen.add(candidate.author_agent)
        for review in candidate.collaboration_assessment.reviews:
            seen.add(review.reviewer_agent)

    expected = set(BrainAgentId)
    if seen != expected:
        missing = [agent.value for agent in BrainAgentId if agent not in seen]
        unexpected = [str(agent) for agent in seen if agent not in expected]
        details: List[str] = []
        if missing:
            details.append(f"missing permanent ASI participation: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected participant identity: {', '.join(unexpected)}")
        raise ValidationError(
            "; ".join(details) or "collective cycle must contain exactly five permanent ASIs"
        )
    return list(BrainAgentId)


def _candidate_decision(
    candidate: CollectiveCandidate,
    decision: CollaborationDecision,
) -> CollectiveCandidateDecision:
    return CollectiveCandidateDecision(
        candidate_id=candidate.candidate_id,
        assessment_id=decision.assessment_id,
        disposition=decision.disposition,
        supporting_review_ids=list(decision.supporting_review_ids),
        dissenting_review_ids=list(decision.dissenting_review_ids),
        ignored_review_ids=list(decision.ignored_review_ids),
        reasons=list(decision.reasons),
    )


def synthesize_collective_cognition(
    request: CollectiveCognitionRequest,
) -> CollectiveCognitionDecision:
    """Compose five-ASI collaboration outcomes without manufacturing consensus."""

    canonical = _canonical_request(request)
    participant_agents = _participants(canonical)

    candidate_decisions: List[CollectiveCandidateDecision] = []
    accepted_candidate_ids: List[str] = []
    has_revision = False
    has_research = False
    has_arbitration = False

    for candidate in canonical.candidates:
        collaboration = evaluate_collaboration(candidate.collaboration_assessment)
        candidate_decisions.append(_candidate_decision(candidate, collaboration))
        if collaboration.disposition == CollaborationDisposition.ACCEPT:
            accepted_candidate_ids.append(candidate.candidate_id)
        elif collaboration.disposition == CollaborationDisposition.REVISE:
            has_revision = True
        elif collaboration.disposition == CollaborationDisposition.INCONCLUSIVE:
            has_research = True
        elif collaboration.disposition == CollaborationDisposition.ESCALATE:
            has_arbitration = True

    selected_candidate_id: Optional[str] = None
    reasons: List[str] = []

    if has_arbitration:
        disposition = CollectiveCognitionDisposition.NEEDS_ARBITRATION
        reasons.append(
            "at least one candidate contains unresolved contested or escalated evidence; collective synthesis must preserve that conflict"
        )
    elif has_research:
        disposition = CollectiveCognitionDisposition.NEEDS_RESEARCH
        reasons.append(
            "at least one non-refuted alternative lacks sufficient canonical evidence; peer agreement cannot replace research"
        )
    elif len(accepted_candidate_ids) > 1:
        disposition = CollectiveCognitionDisposition.NEEDS_ARBITRATION
        reasons.append(
            "multiple alternatives are independently evidence-accepted; choosing among them requires explicit arbitration rather than majority voting"
        )
    elif len(accepted_candidate_ids) == 1:
        disposition = CollectiveCognitionDisposition.READY_FOR_SYNTHESIS
        selected_candidate_id = accepted_candidate_ids[0]
        if has_revision:
            reasons.append(
                "one candidate is canonically accepted while remaining alternatives are revision-bound/refuted; only the accepted candidate is synthesis-ready"
            )
        else:
            reasons.append(
                "exactly one candidate is canonically accepted with no unresolved evidence conflict"
            )
    elif has_revision:
        disposition = CollectiveCognitionDisposition.NEEDS_REVISION
        reasons.append(
            "no candidate is acceptable and at least one is canonically revision-bound or refuted"
        )
    else:
        disposition = CollectiveCognitionDisposition.NEEDS_RESEARCH
        reasons.append(
            "no candidate has sufficient canonical authority for synthesis"
        )

    return CollectiveCognitionDecision(
        cycle_id=canonical.cycle_id,
        goal_id=canonical.goal_id,
        disposition=disposition,
        participant_agents=participant_agents,
        accepted_candidate_ids=accepted_candidate_ids,
        selected_candidate_id=selected_candidate_id,
        candidate_decisions=candidate_decisions,
        reasons=reasons,
    )
