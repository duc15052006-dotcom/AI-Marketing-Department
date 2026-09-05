"""Provider-neutral decision authorization policy for the Brain layer.

A ``DecisionRecord`` is a proposal made by an agent, not authority to proceed.
This module evaluates that proposal against exact raw evidence lineage, semantic
risk/reversibility, and (when risk warrants it) independent peer review.

Caller-supplied evidence assessments are audit material only. Autonomous
authorization is derived again from the raw ``ClaimEvidenceRequest`` through
the canonical Brain evidence evaluator so a fabricated verdict cannot grant
``PROCEED`` authority.

It intentionally owns no runtime execution, tools, providers, connectors,
approvals, persistence, or goal-completion authority.
"""

from __future__ import annotations

from typing import List, Optional

from brain.collaboration import (
    CollaborationAssessment,
    CollaborationDisposition,
    evaluate_collaboration,
)
from brain.contracts import DecisionDisposition, DecisionRecord
from brain.evidence import (
    ClaimEvidenceAssessment,
    ClaimEvidenceRequest,
    ClaimVerdict,
    assess_claim_evidence,
)
from brain.reasoning import ReasoningAssessment, Reversibility, SignalLevel
from schemas.base import BaseModel, Field, ValidationError


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


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


def _assessment_signature(assessment: ClaimEvidenceAssessment) -> tuple:
    """Canonical semantic identity of an evidence assessment for audit checks."""

    return (
        assessment.assessment_id,
        assessment.goal_id,
        assessment.claim_id,
        assessment.agent_id,
        assessment.verdict,
        tuple(assessment.supporting_evidence_refs),
        tuple(assessment.contradicting_evidence_refs),
        tuple(assessment.ignored_evidence_refs),
        tuple(assessment.reasons),
    )


class DecisionEvaluationRequest(BaseModel):
    """Exact semantic inputs required to authorize one proposed decision.

    ``evidence_request`` is the authority-bearing raw evidence input. An optional
    ``evidence_assessment`` may be supplied as an audit snapshot, but when raw
    evidence is present it must exactly match the canonical recomputation and it
    never substitutes for raw provenance.
    """

    evaluation_id: str
    decision: DecisionRecord
    reasoning_assessment: ReasoningAssessment
    evidence_request: Optional[ClaimEvidenceRequest] = None
    evidence_assessment: Optional[ClaimEvidenceAssessment] = None
    collaboration_assessment: Optional[CollaborationAssessment] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.evaluation_id = _required_text(self.evaluation_id, "evaluation_id")

        if not isinstance(self.decision, DecisionRecord):
            if isinstance(self.decision, dict):
                self.decision = DecisionRecord(**self.decision)
            else:
                raise ValidationError("decision must be a DecisionRecord")

        if not isinstance(self.reasoning_assessment, ReasoningAssessment):
            if isinstance(self.reasoning_assessment, dict):
                self.reasoning_assessment = ReasoningAssessment(
                    **self.reasoning_assessment
                )
            else:
                raise ValidationError(
                    "reasoning_assessment must be a ReasoningAssessment"
                )

        if self.reasoning_assessment.goal_id != self.decision.goal_id:
            raise ValidationError(
                "reasoning_assessment goal_id must match the decision goal_id"
            )
        if self.reasoning_assessment.agent_id != self.decision.agent_id:
            raise ValidationError(
                "reasoning_assessment agent_id must match the decision owner"
            )

        if self.evidence_request is not None:
            if not isinstance(self.evidence_request, ClaimEvidenceRequest):
                if isinstance(self.evidence_request, dict):
                    self.evidence_request = ClaimEvidenceRequest(
                        **self.evidence_request
                    )
                else:
                    raise ValidationError(
                        "evidence_request must be a ClaimEvidenceRequest or None"
                    )
            if self.evidence_request.goal_id != self.decision.goal_id:
                raise ValidationError(
                    "evidence_request goal_id must match the decision goal_id"
                )
            if self.evidence_request.claim_id != self.decision.decision_id:
                raise ValidationError(
                    "evidence_request claim_id must match the decision_id"
                )

        if self.evidence_assessment is not None:
            if not isinstance(self.evidence_assessment, ClaimEvidenceAssessment):
                if isinstance(self.evidence_assessment, dict):
                    self.evidence_assessment = ClaimEvidenceAssessment(
                        **self.evidence_assessment
                    )
                else:
                    raise ValidationError(
                        "evidence_assessment must be a ClaimEvidenceAssessment or None"
                    )
            if self.evidence_assessment.goal_id != self.decision.goal_id:
                raise ValidationError(
                    "evidence_assessment goal_id must match the decision goal_id"
                )
            if self.evidence_assessment.claim_id != self.decision.decision_id:
                raise ValidationError(
                    "evidence_assessment claim_id must match the decision_id"
                )

        authoritative_evidence: Optional[ClaimEvidenceAssessment] = None
        if self.evidence_request is not None:
            authoritative_evidence = assess_claim_evidence(self.evidence_request)
            if self.evidence_assessment is not None and _assessment_signature(
                self.evidence_assessment
            ) != _assessment_signature(authoritative_evidence):
                raise ValidationError(
                    "evidence_assessment must exactly match the canonical assessment recomputed from evidence_request"
                )

        if self.collaboration_assessment is not None:
            if not isinstance(
                self.collaboration_assessment, CollaborationAssessment
            ):
                if isinstance(self.collaboration_assessment, dict):
                    self.collaboration_assessment = CollaborationAssessment(
                        **self.collaboration_assessment
                    )
                else:
                    raise ValidationError(
                        "collaboration_assessment must be a CollaborationAssessment or None"
                    )
            collaboration = self.collaboration_assessment
            if collaboration.goal_id != self.decision.goal_id:
                raise ValidationError(
                    "collaboration_assessment goal_id must match the decision goal_id"
                )
            if collaboration.proposal_id != self.decision.decision_id:
                raise ValidationError(
                    "collaboration_assessment proposal_id must match the decision_id"
                )
            if collaboration.author_agent != self.decision.agent_id:
                raise ValidationError(
                    "collaboration_assessment author_agent must match the decision owner"
                )
            if authoritative_evidence is None:
                raise ValidationError(
                    "collaboration cannot substitute for raw primary evidence provenance"
                )
            if collaboration.proposal_verdict != authoritative_evidence.verdict:
                raise ValidationError(
                    "collaboration proposal_verdict must match the canonical primary evidence verdict"
                )
            if set(collaboration.proposal_evidence_refs) != set(
                authoritative_evidence.supporting_evidence_refs
            ):
                raise ValidationError(
                    "collaboration proposal_evidence_refs must match canonical primary supporting evidence"
                )


class DecisionEvaluation(BaseModel):
    """Auditable semantic authorization result for one DecisionRecord."""

    evaluation_id: str
    decision_id: str
    goal_id: str
    disposition: DecisionDisposition
    peer_review_required: bool
    verified_evidence_refs: List[str] = Field(default_factory=list)
    unverified_evidence_refs: List[str] = Field(default_factory=list)
    collaboration_assessment_id: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.evaluation_id = _required_text(self.evaluation_id, "evaluation_id")
        self.decision_id = _required_text(self.decision_id, "decision_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        if not isinstance(self.disposition, DecisionDisposition):
            try:
                self.disposition = DecisionDisposition(str(self.disposition).upper())
            except ValueError as exc:
                raise ValidationError("invalid decision disposition") from exc
        if type(self.peer_review_required) is not bool:
            raise ValidationError("peer_review_required must be a boolean")
        self.verified_evidence_refs = _unique_text_list(
            self.verified_evidence_refs, "verified_evidence_refs"
        )
        self.unverified_evidence_refs = _unique_text_list(
            self.unverified_evidence_refs, "unverified_evidence_refs"
        )
        if self.collaboration_assessment_id is not None:
            self.collaboration_assessment_id = _required_text(
                self.collaboration_assessment_id,
                "collaboration_assessment_id",
            )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one policy reason")


def _peer_review_required(assessment: ReasoningAssessment) -> bool:
    return (
        assessment.consequence in (SignalLevel.HIGH, SignalLevel.CRITICAL)
        or assessment.evidence_conflict in (SignalLevel.HIGH, SignalLevel.CRITICAL)
        or assessment.reversibility
        in (Reversibility.COSTLY_TO_REVERSE, Reversibility.IRREVERSIBLE)
    )


def evaluate_decision(request: DecisionEvaluationRequest) -> DecisionEvaluation:
    """Conservatively authorize one semantic decision proposal.

    Confidence never grants authority. Primary evidence is recomputed from raw
    evidence provenance and must retain exact supporting lineage. High-risk
    decisions additionally require an exact, independent collaboration
    assessment. Conservative agent dispositions are respected, while ``STOP``
    is escalated because BRAIN-8 Outcome Intelligence owns proof of goal
    completion.
    """

    if not isinstance(request, DecisionEvaluationRequest):
        raise ValidationError("request must be a DecisionEvaluationRequest")

    decision = request.decision
    evidence_request = request.evidence_request
    evidence: Optional[ClaimEvidenceAssessment] = None
    if evidence_request is not None:
        if evidence_request.goal_id != decision.goal_id:
            raise ValidationError(
                "evidence_request goal_id must match the decision goal_id at evaluation time"
            )
        if evidence_request.claim_id != decision.decision_id:
            raise ValidationError(
                "evidence_request claim_id must match the decision_id at evaluation time"
            )
        evidence = assess_claim_evidence(evidence_request)

    if request.evidence_assessment is not None and evidence is not None:
        if _assessment_signature(request.evidence_assessment) != _assessment_signature(
            evidence
        ):
            raise ValidationError(
                "evidence_assessment no longer matches canonical raw evidence provenance"
            )

    peer_required = _peer_review_required(request.reasoning_assessment)
    reasons: List[str] = []

    supporting_refs = (
        list(evidence.supporting_evidence_refs) if evidence is not None else []
    )
    supporting_set = set(supporting_refs)
    verified = [ref for ref in decision.evidence_refs if ref in supporting_set]
    unverified = [ref for ref in decision.evidence_refs if ref not in supporting_set]

    def result(
        disposition: DecisionDisposition,
        reason: str,
        collaboration_assessment_id: Optional[str] = None,
    ) -> DecisionEvaluation:
        return DecisionEvaluation(
            evaluation_id=request.evaluation_id,
            decision_id=decision.decision_id,
            goal_id=decision.goal_id,
            disposition=disposition,
            peer_review_required=peer_required,
            verified_evidence_refs=verified,
            unverified_evidence_refs=unverified,
            collaboration_assessment_id=collaboration_assessment_id,
            reasons=reasons + [reason],
        )

    if decision.disposition == DecisionDisposition.STOP:
        return result(
            DecisionDisposition.ESCALATE,
            "DecisionRecord STOP is not goal-completion authority; outcome proof must be evaluated separately.",
        )

    if decision.disposition == DecisionDisposition.REVISE:
        return result(
            DecisionDisposition.REVISE,
            "A conservative requested REVISE disposition is never silently upgraded.",
        )
    if decision.disposition == DecisionDisposition.ESCALATE:
        return result(
            DecisionDisposition.ESCALATE,
            "A conservative requested ESCALATE disposition is never silently upgraded.",
        )

    if evidence is None:
        return result(
            DecisionDisposition.REVISE,
            "PROCEED requires raw primary evidence provenance evaluated by the canonical evidence policy; confidence or a supplied assessment alone has no authority.",
        )

    if evidence.verdict == ClaimVerdict.REFUTED:
        return result(
            DecisionDisposition.REVISE,
            "Canonical primary evidence REFUTED the exact decision claim.",
        )
    if evidence.verdict == ClaimVerdict.CONTESTED:
        return result(
            DecisionDisposition.ESCALATE,
            "Canonical primary evidence is CONTESTED and must be resolved explicitly.",
        )
    if evidence.verdict == ClaimVerdict.INSUFFICIENT:
        return result(
            DecisionDisposition.REVISE,
            "Canonical primary evidence is INSUFFICIENT for PROCEED.",
        )

    if not supporting_refs:
        return result(
            DecisionDisposition.REVISE,
            "SUPPORTED without retained supporting evidence references fails closed.",
        )
    if unverified:
        return result(
            DecisionDisposition.REVISE,
            "DecisionRecord contains evidence references not verified from raw primary evidence provenance.",
        )
    if not verified:
        return result(
            DecisionDisposition.REVISE,
            "DecisionRecord did not retain any verified supporting evidence lineage.",
        )

    if not peer_required:
        return result(
            DecisionDisposition.PROCEED,
            "Canonical supporting evidence is retained and semantic risk does not require independent peer review.",
        )

    collaboration = request.collaboration_assessment
    if collaboration is None:
        return result(
            DecisionDisposition.ESCALATE,
            "Semantic risk requires independent peer review before PROCEED.",
        )

    if collaboration.proposal_verdict != evidence.verdict or set(
        collaboration.proposal_evidence_refs
    ) != set(evidence.supporting_evidence_refs):
        raise ValidationError(
            "collaboration assessment no longer matches canonical raw evidence provenance"
        )

    collaboration_decision = evaluate_collaboration(collaboration)
    collaboration_id = collaboration.assessment_id
    if collaboration_decision.disposition == CollaborationDisposition.ACCEPT:
        return result(
            DecisionDisposition.PROCEED,
            "High-risk decision retained canonical evidence and passed independent peer review.",
            collaboration_id,
        )
    if collaboration_decision.disposition == CollaborationDisposition.REVISE:
        return result(
            DecisionDisposition.REVISE,
            "Independent peer review found evidence-backed grounds to revise the decision.",
            collaboration_id,
        )
    return result(
        DecisionDisposition.ESCALATE,
        "Independent peer review is unresolved or contested; PROCEED remains blocked.",
        collaboration_id,
    )
