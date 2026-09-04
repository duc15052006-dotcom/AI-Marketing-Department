"""Provider-neutral evidence intelligence for the Brain layer.

This module decides whether evidence is sufficient for a semantic claim. It
binds evidence to an exact goal and claim, requires observed evidence for strong
conclusions, treats source independence explicitly, and surfaces contradictions
instead of hiding them.

The Brain reasons only about semantic evidence. It does not know provider IDs,
model IDs, tools, connectors, runtime receipts, persistence, or execution state.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Type, TypeVar

from brain.contracts import BrainAgentId
from schemas.base import BaseModel, Field, ValidationError


class EvidenceRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"


class EvidenceStrength(str, Enum):
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class EvidenceOrigin(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"


class ClaimVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTESTED = "CONTESTED"
    REFUTED = "REFUTED"
    INSUFFICIENT = "INSUFFICIENT"


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


class EvidenceSignal(BaseModel):
    """One semantic evidence signal explicitly bound to a goal and claim."""

    evidence_id: str
    goal_id: str
    claim_id: str
    source_id: str
    relation: EvidenceRelation
    strength: EvidenceStrength
    origin: EvidenceOrigin

    def __post_init__(self) -> None:
        super().__post_init__()
        self.evidence_id = _required_text(self.evidence_id, "evidence_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.claim_id = _required_text(self.claim_id, "claim_id")
        self.source_id = _required_text(self.source_id, "source_id")
        self.relation = _enum(self.relation, EvidenceRelation, "relation")
        self.strength = _enum(self.strength, EvidenceStrength, "strength")
        self.origin = _enum(self.origin, EvidenceOrigin, "origin")


class ClaimEvidenceRequest(BaseModel):
    """Evidence submitted for one exact semantic claim assessment."""

    assessment_id: str
    goal_id: str
    claim_id: str
    agent_id: BrainAgentId
    evidence: List[EvidenceSignal] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.claim_id = _required_text(self.claim_id, "claim_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        if not isinstance(self.evidence, list):
            raise ValidationError("evidence must be a list of EvidenceSignal")
        for item in self.evidence:
            if not isinstance(item, EvidenceSignal):
                raise ValidationError("evidence must contain only EvidenceSignal items")


class ClaimEvidenceAssessment(BaseModel):
    """Auditable verdict for one exact claim and its qualifying evidence."""

    assessment_id: str
    goal_id: str
    claim_id: str
    agent_id: BrainAgentId
    verdict: ClaimVerdict
    supporting_evidence_refs: List[str] = Field(default_factory=list)
    contradicting_evidence_refs: List[str] = Field(default_factory=list)
    ignored_evidence_refs: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.claim_id = _required_text(self.claim_id, "claim_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.verdict = _enum(self.verdict, ClaimVerdict, "verdict")
        self.supporting_evidence_refs = _unique_text_list(
            self.supporting_evidence_refs, "supporting_evidence_refs"
        )
        self.contradicting_evidence_refs = _unique_text_list(
            self.contradicting_evidence_refs, "contradicting_evidence_refs"
        )
        self.ignored_evidence_refs = _unique_text_list(
            self.ignored_evidence_refs, "ignored_evidence_refs"
        )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one assessment reason")


def _side_qualifies(signals: List[EvidenceSignal]) -> bool:
    """Return whether one side has enough independent observed evidence."""

    observed_by_source = {}
    strength_rank = {
        EvidenceStrength.WEAK: 0,
        EvidenceStrength.MODERATE: 1,
        EvidenceStrength.STRONG: 2,
    }

    for signal in signals:
        if signal.origin != EvidenceOrigin.OBSERVED:
            continue
        previous = observed_by_source.get(signal.source_id)
        if previous is None or strength_rank[signal.strength] > strength_rank[previous]:
            observed_by_source[signal.source_id] = signal.strength

    if any(strength == EvidenceStrength.STRONG for strength in observed_by_source.values()):
        return True

    moderate_sources = sum(
        strength == EvidenceStrength.MODERATE
        for strength in observed_by_source.values()
    )
    return moderate_sources >= 2


def assess_claim_evidence(request: ClaimEvidenceRequest) -> ClaimEvidenceAssessment:
    """Assess evidence conservatively for one exact goal/claim pair.

    Evidence IDs are authoritative identities and identical replays are counted
    once. Conflicting reuse of an ID fails closed before any verdict is returned,
    including conflicts in records outside the target goal/claim. Other
    out-of-scope and neutral evidence is ignored. Source IDs establish
    independence: repeating the same source cannot manufacture corroboration.
    """

    if not isinstance(request, ClaimEvidenceRequest):
        raise ValidationError("request must be a ClaimEvidenceRequest")

    support: List[EvidenceSignal] = []
    contradict: List[EvidenceSignal] = []
    supporting_refs: List[str] = []
    contradicting_refs: List[str] = []
    ignored_refs: List[str] = []
    evidence_identity_by_id = {}

    for signal in request.evidence:
        identity = (
            signal.goal_id,
            signal.claim_id,
            signal.source_id,
            signal.relation,
            signal.strength,
            signal.origin,
        )
        if signal.evidence_id in evidence_identity_by_id:
            if evidence_identity_by_id[signal.evidence_id] != identity:
                raise ValidationError(
                    f"conflicting evidence_id: {signal.evidence_id}"
                )
            if signal.evidence_id not in ignored_refs:
                ignored_refs.append(signal.evidence_id)
            continue
        evidence_identity_by_id[signal.evidence_id] = identity

        if signal.goal_id != request.goal_id or signal.claim_id != request.claim_id:
            ignored_refs.append(signal.evidence_id)
            continue

        if signal.relation == EvidenceRelation.SUPPORTS:
            support.append(signal)
            supporting_refs.append(signal.evidence_id)
        elif signal.relation == EvidenceRelation.CONTRADICTS:
            contradict.append(signal)
            contradicting_refs.append(signal.evidence_id)
        else:
            ignored_refs.append(signal.evidence_id)

    support_qualifies = _side_qualifies(support)
    contradiction_qualifies = _side_qualifies(contradict)

    if support_qualifies and contradiction_qualifies:
        verdict = ClaimVerdict.CONTESTED
        reasons = [
            "independent observed evidence materially supports and contradicts the claim"
        ]
    elif support_qualifies:
        verdict = ClaimVerdict.SUPPORTED
        reasons = [
            "qualifying independent observed evidence supports the exact goal/claim binding"
        ]
    elif contradiction_qualifies:
        verdict = ClaimVerdict.REFUTED
        reasons = [
            "qualifying independent observed evidence contradicts the exact goal/claim binding"
        ]
    else:
        verdict = ClaimVerdict.INSUFFICIENT
        reasons = [
            "evidence does not meet the observed-strength and source-independence threshold"
        ]

    if ignored_refs:
        reasons.append("out-of-scope, neutral, or duplicate evidence was ignored")
    if any(signal.origin == EvidenceOrigin.DERIVED for signal in support + contradict):
        reasons.append("derived evidence was retained for lineage but cannot establish a strong verdict")

    return ClaimEvidenceAssessment(
        assessment_id=request.assessment_id,
        goal_id=request.goal_id,
        claim_id=request.claim_id,
        agent_id=request.agent_id,
        verdict=verdict,
        supporting_evidence_refs=supporting_refs,
        contradicting_evidence_refs=contradicting_refs,
        ignored_evidence_refs=ignored_refs,
        reasons=reasons,
    )
