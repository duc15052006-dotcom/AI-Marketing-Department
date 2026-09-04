"""Provider-neutral collaboration and peer-review policy for the Brain layer.

This module decides whether a semantic proposal has enough independent review to
be accepted, must be revised, should be escalated because of unresolved dissent,
or remains inconclusive. It deliberately does not dispatch agents, execute tools,
read runtime handoffs, persist state, or select model/provider implementations.

Core invariants:
- peer agreement never upgrades a proposal whose own evidence verdict is weak;
- self-review never counts as independent review;
- reviews are bound to one exact goal and proposal;
- duplicate reviewer identities cannot manufacture quorum;
- contradictions and refutations are preserved rather than averaged away;
- exactly five permanent Brain agents remain authoritative.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.evidence import ClaimVerdict
from schemas.base import BaseModel, Field, ValidationError


class CollaborationDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    REVISE = "REVISE"
    ESCALATE = "ESCALATE"
    INCONCLUSIVE = "INCONCLUSIVE"


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


def _review_quorum(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("minimum_supporting_reviewers must be an integer")
    if value < 1 or value > 4:
        raise ValidationError(
            "minimum_supporting_reviewers must be between 1 and 4 because one of the five permanent agents is the author"
        )
    return value


class PeerReview(BaseModel):
    """One semantic review of one exact proposal by a permanent peer agent."""

    review_id: str
    goal_id: str
    proposal_id: str
    reviewer_agent: BrainAgentId
    verdict: ClaimVerdict
    rationale: str
    evidence_refs: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.review_id = _required_text(self.review_id, "review_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.proposal_id = _required_text(self.proposal_id, "proposal_id")
        self.reviewer_agent = _enum(
            self.reviewer_agent, BrainAgentId, "reviewer_agent"
        )
        self.verdict = _enum(self.verdict, ClaimVerdict, "verdict")
        self.rationale = _required_text(self.rationale, "rationale")
        self.evidence_refs = _unique_text_list(self.evidence_refs, "evidence_refs")


class CollaborationAssessment(BaseModel):
    """A request to evaluate independent review around one semantic proposal."""

    assessment_id: str
    goal_id: str
    proposal_id: str
    author_agent: BrainAgentId
    proposal_verdict: ClaimVerdict
    proposal_evidence_refs: List[str] = Field(default_factory=list)
    reviews: List[PeerReview] = Field(default_factory=list)
    minimum_supporting_reviewers: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.proposal_id = _required_text(self.proposal_id, "proposal_id")
        self.author_agent = _enum(self.author_agent, BrainAgentId, "author_agent")
        self.proposal_verdict = _enum(
            self.proposal_verdict, ClaimVerdict, "proposal_verdict"
        )
        self.proposal_evidence_refs = _unique_text_list(
            self.proposal_evidence_refs, "proposal_evidence_refs"
        )
        self.minimum_supporting_reviewers = _review_quorum(
            self.minimum_supporting_reviewers
        )

        if not isinstance(self.reviews, list):
            raise ValidationError("reviews must be a list of PeerReview objects")
        normalized: List[PeerReview] = []
        seen_review_ids = set()
        for raw in self.reviews:
            if isinstance(raw, PeerReview):
                review = raw.model_copy(deep=True)
            elif isinstance(raw, dict):
                review = PeerReview(**raw)
            else:
                raise ValidationError("reviews must contain only PeerReview objects")
            if review.review_id in seen_review_ids:
                raise ValidationError(f"duplicate review_id: {review.review_id}")
            seen_review_ids.add(review.review_id)
            normalized.append(review)
        self.reviews = normalized


class CollaborationDecision(BaseModel):
    """Auditable Brain decision that keeps consensus and dissent separate."""

    assessment_id: str
    proposal_id: str
    disposition: CollaborationDisposition
    supporting_review_ids: List[str] = Field(default_factory=list)
    dissenting_review_ids: List[str] = Field(default_factory=list)
    ignored_review_ids: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.proposal_id = _required_text(self.proposal_id, "proposal_id")
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
            raise ValidationError("reasons must contain at least one collaboration reason")


def evaluate_collaboration(
    assessment: CollaborationAssessment,
) -> CollaborationDecision:
    """Evaluate proposal review without allowing consensus to replace evidence.

    Review independence is established by permanent reviewer identity, not by the
    number of review records. Structurally invalid reviews are ignored. A
    supported proposal can be accepted only when its own evidence lineage is
    retained and the configured number of distinct peers provide evidence-backed
    support. Any credible refutation dominates supportive votes; unresolved
    contradiction is escalated instead of being averaged into a majority result.
    """

    if not isinstance(assessment, CollaborationAssessment):
        raise ValidationError("assessment must be a CollaborationAssessment")

    reasons: List[str] = []
    ignored_review_ids: List[str] = []
    structurally_eligible: List[PeerReview] = []

    for review in assessment.reviews:
        if review.goal_id != assessment.goal_id:
            ignored_review_ids.append(review.review_id)
            reasons.append(
                f"review {review.review_id} ignored: goal_id does not match the assessed goal"
            )
            continue
        if review.proposal_id != assessment.proposal_id:
            ignored_review_ids.append(review.review_id)
            reasons.append(
                f"review {review.review_id} ignored: proposal_id does not match the assessed proposal"
            )
            continue
        if review.reviewer_agent == assessment.author_agent:
            ignored_review_ids.append(review.review_id)
            reasons.append(
                f"review {review.review_id} ignored: self-review is not independent peer review"
            )
            continue
        structurally_eligible.append(review)

    reviewer_counts: Dict[BrainAgentId, int] = {}
    for review in structurally_eligible:
        reviewer_counts[review.reviewer_agent] = (
            reviewer_counts.get(review.reviewer_agent, 0) + 1
        )
    duplicated_reviewers = {
        reviewer for reviewer, count in reviewer_counts.items() if count > 1
    }

    eligible: List[PeerReview] = []
    for review in structurally_eligible:
        if review.reviewer_agent in duplicated_reviewers:
            ignored_review_ids.append(review.review_id)
            reasons.append(
                f"review {review.review_id} ignored: duplicate reviewer identity cannot manufacture independent quorum"
            )
        else:
            eligible.append(review)

    supporting = [
        review
        for review in eligible
        if review.verdict == ClaimVerdict.SUPPORTED and bool(review.evidence_refs)
    ]
    dissenting = [
        review
        for review in eligible
        if review.verdict in (ClaimVerdict.REFUTED, ClaimVerdict.CONTESTED)
    ]
    evidence_backed_refutations = [
        review
        for review in dissenting
        if review.verdict == ClaimVerdict.REFUTED and bool(review.evidence_refs)
    ]
    unsubstantiated_refutations = [
        review
        for review in dissenting
        if review.verdict == ClaimVerdict.REFUTED and not review.evidence_refs
    ]
    contested_reviews = [
        review for review in dissenting if review.verdict == ClaimVerdict.CONTESTED
    ]

    supporting_ids = [review.review_id for review in supporting]
    dissenting_ids = [review.review_id for review in dissenting]

    if assessment.proposal_verdict == ClaimVerdict.REFUTED:
        reasons.append(
            "proposal evidence verdict is REFUTED; peer agreement cannot override refutation"
        )
        disposition = CollaborationDisposition.REVISE
    elif assessment.proposal_verdict == ClaimVerdict.CONTESTED:
        reasons.append(
            "proposal evidence verdict is CONTESTED; contradiction requires escalation before acceptance"
        )
        disposition = CollaborationDisposition.ESCALATE
    elif assessment.proposal_verdict == ClaimVerdict.INSUFFICIENT:
        reasons.append(
            "proposal evidence verdict is INSUFFICIENT; peer agreement cannot substitute for proposal evidence"
        )
        disposition = CollaborationDisposition.INCONCLUSIVE
    elif not assessment.proposal_evidence_refs:
        reasons.append(
            "SUPPORTED proposal did not retain evidence references and therefore fails closed"
        )
        disposition = CollaborationDisposition.INCONCLUSIVE
    elif evidence_backed_refutations:
        reasons.append(
            "at least one independent evidence-backed peer review REFUTED the proposal"
        )
        disposition = CollaborationDisposition.REVISE
    elif contested_reviews:
        reasons.append(
            "at least one independent peer review reports CONTESTED evidence; dissent must be resolved explicitly"
        )
        disposition = CollaborationDisposition.ESCALATE
    elif unsubstantiated_refutations:
        reasons.append(
            "an independent peer raised a refutation without evidence references; acceptance is blocked until the challenge is resolved"
        )
        disposition = CollaborationDisposition.ESCALATE
    elif len(supporting) >= assessment.minimum_supporting_reviewers:
        reasons.append(
            f"proposal is evidence-supported and has {len(supporting)} distinct evidence-backed peer reviewer(s), meeting quorum {assessment.minimum_supporting_reviewers}"
        )
        disposition = CollaborationDisposition.ACCEPT
    else:
        reasons.append(
            f"independent evidence-backed peer support {len(supporting)} is below required quorum {assessment.minimum_supporting_reviewers}"
        )
        disposition = CollaborationDisposition.INCONCLUSIVE

    return CollaborationDecision(
        assessment_id=assessment.assessment_id,
        proposal_id=assessment.proposal_id,
        disposition=disposition,
        supporting_review_ids=supporting_ids,
        dissenting_review_ids=dissenting_ids,
        ignored_review_ids=ignored_review_ids,
        reasons=reasons,
    )
