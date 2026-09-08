"""Provider-neutral hypothesis portfolio and research-agenda semantics.

The five-ASI Brain should not collapse onto the first plausible explanation.
This module keeps competing hypotheses explicit, evaluates each against canonical
evidence, and chooses research probes by ordinal information value rather than
by arbitrary preference.

The layer is deliberately semantic: it does not choose providers, search tools,
experiment executors, budgets, or runtime workers.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceAssessment,
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceSignal,
    assess_claim_evidence,
)
from schemas.base import BaseModel, Field, ValidationError


class InquiryCost(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InformationValue(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


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


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must contain only {expected_type.__name__} items or serialized mappings"
    )


def _canonical_evidence_request(raw: object) -> ClaimEvidenceRequest:
    data = _payload(raw, ClaimEvidenceRequest, "evidence_requests")
    raw_evidence = data.pop("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ValidationError("evidence_request evidence must be a list")
    evidence: List[EvidenceSignal] = []
    for item in raw_evidence:
        evidence.append(EvidenceSignal(**_payload(item, EvidenceSignal, "evidence")))
    return ClaimEvidenceRequest(**data, evidence=evidence)


class HypothesisCandidate(BaseModel):
    """One explicit competing explanation or prediction for a goal."""

    hypothesis_id: str
    goal_id: str
    owner_agent: BrainAgentId
    statement: str
    differentiating_predictions: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.statement = _required_text(self.statement, "statement")
        self.differentiating_predictions = _unique_text_list(
            self.differentiating_predictions, "differentiating_predictions"
        )


class HypothesisPortfolioRequest(BaseModel):
    portfolio_id: str
    goal_id: str
    owner_agent: BrainAgentId
    hypotheses: List[HypothesisCandidate] = Field(default_factory=list)
    evidence_requests: List[ClaimEvidenceRequest] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.portfolio_id = _required_text(self.portfolio_id, "portfolio_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")

        if not isinstance(self.hypotheses, list) or not self.hypotheses:
            raise ValidationError("hypotheses must contain at least one hypothesis")
        normalized_hypotheses: List[HypothesisCandidate] = []
        ids = set()
        for raw in self.hypotheses:
            hypothesis = HypothesisCandidate(
                **_payload(raw, HypothesisCandidate, "hypotheses")
            )
            if hypothesis.goal_id != self.goal_id:
                raise ValidationError("hypothesis goal_id must match portfolio goal_id")
            if hypothesis.hypothesis_id in ids:
                raise ValidationError(
                    f"duplicate hypothesis_id: {hypothesis.hypothesis_id}"
                )
            ids.add(hypothesis.hypothesis_id)
            normalized_hypotheses.append(hypothesis)
        self.hypotheses = normalized_hypotheses

        if not isinstance(self.evidence_requests, list):
            raise ValidationError("evidence_requests must be a list")
        normalized_requests: List[ClaimEvidenceRequest] = []
        covered_claims = set()
        for raw in self.evidence_requests:
            request = _canonical_evidence_request(raw)
            if request.goal_id != self.goal_id:
                raise ValidationError(
                    "evidence request goal_id must match portfolio goal_id"
                )
            if request.claim_id not in ids:
                raise ValidationError(
                    f"evidence request references unknown hypothesis: {request.claim_id}"
                )
            if request.claim_id in covered_claims:
                raise ValidationError(
                    f"duplicate evidence request for hypothesis: {request.claim_id}"
                )
            covered_claims.add(request.claim_id)
            normalized_requests.append(request)
        self.evidence_requests = normalized_requests


class HypothesisAssessment(BaseModel):
    hypothesis_id: str
    verdict: ClaimVerdict
    supporting_evidence_refs: List[str] = Field(default_factory=list)
    contradicting_evidence_refs: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.verdict = _enum(self.verdict, ClaimVerdict, "verdict")
        self.supporting_evidence_refs = _unique_text_list(
            self.supporting_evidence_refs, "supporting_evidence_refs"
        )
        self.contradicting_evidence_refs = _unique_text_list(
            self.contradicting_evidence_refs, "contradicting_evidence_refs"
        )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one hypothesis reason")


class HypothesisPortfolioDecision(BaseModel):
    portfolio_id: str
    goal_id: str
    owner_agent: BrainAgentId
    assessments: List[HypothesisAssessment] = Field(default_factory=list)
    active_hypothesis_ids: List[str] = Field(default_factory=list)
    refuted_hypothesis_ids: List[str] = Field(default_factory=list)
    leading_hypothesis_id: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.portfolio_id = _required_text(self.portfolio_id, "portfolio_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        if not isinstance(self.assessments, list) or not self.assessments:
            raise ValidationError("assessments must contain at least one item")
        normalized: List[HypothesisAssessment] = []
        ids = set()
        for raw in self.assessments:
            item = HypothesisAssessment(
                **_payload(raw, HypothesisAssessment, "assessments")
            )
            if item.hypothesis_id in ids:
                raise ValidationError(
                    f"duplicate hypothesis assessment: {item.hypothesis_id}"
                )
            ids.add(item.hypothesis_id)
            normalized.append(item)
        self.assessments = normalized
        self.active_hypothesis_ids = _unique_text_list(
            self.active_hypothesis_ids, "active_hypothesis_ids"
        )
        self.refuted_hypothesis_ids = _unique_text_list(
            self.refuted_hypothesis_ids, "refuted_hypothesis_ids"
        )
        overlap = set(self.active_hypothesis_ids) & set(self.refuted_hypothesis_ids)
        if overlap:
            raise ValidationError("active and refuted hypotheses cannot overlap")
        if self.leading_hypothesis_id is not None:
            self.leading_hypothesis_id = _required_text(
                self.leading_hypothesis_id, "leading_hypothesis_id"
            )
            if self.leading_hypothesis_id not in self.active_hypothesis_ids:
                raise ValidationError("leading hypothesis must remain active")
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one portfolio reason")


class ProbePrediction(BaseModel):
    hypothesis_id: str
    predicted_observation: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.predicted_observation = _required_text(
            self.predicted_observation, "predicted_observation"
        )


class ResearchProbe(BaseModel):
    probe_id: str
    goal_id: str
    question: str
    cost: InquiryCost
    predictions: List[ProbePrediction] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.probe_id = _required_text(self.probe_id, "probe_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.question = _required_text(self.question, "question")
        self.cost = _enum(self.cost, InquiryCost, "cost")
        if not isinstance(self.predictions, list) or not self.predictions:
            raise ValidationError("predictions must contain at least one item")
        normalized: List[ProbePrediction] = []
        ids = set()
        for raw in self.predictions:
            prediction = ProbePrediction(
                **_payload(raw, ProbePrediction, "predictions")
            )
            if prediction.hypothesis_id in ids:
                raise ValidationError(
                    f"duplicate probe prediction for hypothesis: {prediction.hypothesis_id}"
                )
            ids.add(prediction.hypothesis_id)
            normalized.append(prediction)
        self.predictions = normalized


class ResearchAgendaRequest(BaseModel):
    agenda_id: str
    goal_id: str
    portfolio: HypothesisPortfolioDecision
    probes: List[ResearchProbe] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.agenda_id = _required_text(self.agenda_id, "agenda_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        if isinstance(self.portfolio, HypothesisPortfolioDecision):
            self.portfolio = HypothesisPortfolioDecision(**self.portfolio.model_dump())
        elif isinstance(self.portfolio, dict):
            self.portfolio = HypothesisPortfolioDecision(**copy.deepcopy(self.portfolio))
        else:
            raise ValidationError("portfolio must be a HypothesisPortfolioDecision")
        if self.portfolio.goal_id != self.goal_id:
            raise ValidationError("portfolio goal_id must match agenda goal_id")
        if not isinstance(self.probes, list):
            raise ValidationError("probes must be a list of ResearchProbe")
        normalized: List[ResearchProbe] = []
        probe_ids = set()
        known_hypotheses = {
            assessment.hypothesis_id for assessment in self.portfolio.assessments
        }
        for raw in self.probes:
            probe = ResearchProbe(**_payload(raw, ResearchProbe, "probes"))
            if probe.goal_id != self.goal_id:
                raise ValidationError("probe goal_id must match agenda goal_id")
            if probe.probe_id in probe_ids:
                raise ValidationError(f"duplicate research probe id: {probe.probe_id}")
            probe_ids.add(probe.probe_id)
            for prediction in probe.predictions:
                if prediction.hypothesis_id not in known_hypotheses:
                    raise ValidationError(
                        f"probe references unknown hypothesis: {prediction.hypothesis_id}"
                    )
            normalized.append(probe)
        self.probes = normalized


class ResearchRecommendation(BaseModel):
    probe_id: str
    information_value: InformationValue
    cost: InquiryCost
    targeted_hypothesis_ids: List[str] = Field(default_factory=list)
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.probe_id = _required_text(self.probe_id, "probe_id")
        self.information_value = _enum(
            self.information_value, InformationValue, "information_value"
        )
        if self.information_value == InformationValue.NONE:
            raise ValidationError("recommendations cannot carry NONE information value")
        self.cost = _enum(self.cost, InquiryCost, "cost")
        self.targeted_hypothesis_ids = _unique_text_list(
            self.targeted_hypothesis_ids, "targeted_hypothesis_ids"
        )
        self.rationale = _required_text(self.rationale, "rationale")


class ResearchAgenda(BaseModel):
    agenda_id: str
    goal_id: str
    recommendations: List[ResearchRecommendation] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.agenda_id = _required_text(self.agenda_id, "agenda_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        if not isinstance(self.recommendations, list):
            raise ValidationError("recommendations must be a list")
        self.recommendations = [
            ResearchRecommendation(
                **_payload(raw, ResearchRecommendation, "recommendations")
            )
            for raw in self.recommendations
        ]
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one agenda reason")


def _assessment_from_request(request: ClaimEvidenceRequest) -> ClaimEvidenceAssessment:
    return assess_claim_evidence(request)


def assess_hypothesis_portfolio(
    request: HypothesisPortfolioRequest,
) -> HypothesisPortfolioDecision:
    """Evaluate competing hypotheses without prematurely collapsing the portfolio."""

    if not isinstance(request, HypothesisPortfolioRequest):
        raise ValidationError("request must be a HypothesisPortfolioRequest")
    request = HypothesisPortfolioRequest(**copy.deepcopy(request.model_dump()))

    evidence_by_claim = {
        item.claim_id: item for item in request.evidence_requests
    }
    assessments: List[HypothesisAssessment] = []
    active: List[str] = []
    refuted: List[str] = []

    for hypothesis in request.hypotheses:
        evidence_request = evidence_by_claim.get(hypothesis.hypothesis_id)
        if evidence_request is None:
            assessment = HypothesisAssessment(
                hypothesis_id=hypothesis.hypothesis_id,
                verdict=ClaimVerdict.INSUFFICIENT,
                reasons=["no canonical evidence request exists for this hypothesis"],
            )
        else:
            evidence = _assessment_from_request(evidence_request)
            assessment = HypothesisAssessment(
                hypothesis_id=hypothesis.hypothesis_id,
                verdict=evidence.verdict,
                supporting_evidence_refs=list(evidence.supporting_evidence_refs),
                contradicting_evidence_refs=list(evidence.contradicting_evidence_refs),
                reasons=list(evidence.reasons),
            )
        assessments.append(assessment)
        if assessment.verdict == ClaimVerdict.REFUTED:
            refuted.append(hypothesis.hypothesis_id)
        else:
            active.append(hypothesis.hypothesis_id)

    supported = [
        item.hypothesis_id
        for item in assessments
        if item.verdict == ClaimVerdict.SUPPORTED
    ]
    unresolved_nonleaders = [
        item.hypothesis_id
        for item in assessments
        if item.verdict in {ClaimVerdict.CONTESTED, ClaimVerdict.INSUFFICIENT}
    ]
    leading: Optional[str] = None
    if len(supported) == 1 and not unresolved_nonleaders:
        if all(
            item.hypothesis_id == supported[0]
            or item.verdict == ClaimVerdict.REFUTED
            for item in assessments
        ):
            leading = supported[0]

    if leading is not None:
        reasons = [
            "one hypothesis is supported while every competing hypothesis is canonically refuted"
        ]
    elif len(active) > 1:
        reasons = [
            "multiple hypotheses remain epistemically live; further discrimination is required"
        ]
    elif len(active) == 1:
        reasons = [
            "one hypothesis remains active but lacks enough comparative evidence for a unique supported leader"
        ]
    else:
        reasons = ["all hypotheses are refuted; the hypothesis space must be expanded"]

    return HypothesisPortfolioDecision(
        portfolio_id=request.portfolio_id,
        goal_id=request.goal_id,
        owner_agent=request.owner_agent,
        assessments=assessments,
        active_hypothesis_ids=active,
        refuted_hypothesis_ids=refuted,
        leading_hypothesis_id=leading,
        reasons=reasons,
    )


_INFO_RANK = {
    InformationValue.NONE: 0,
    InformationValue.LOW: 1,
    InformationValue.MEDIUM: 2,
    InformationValue.HIGH: 3,
}
_COST_RANK = {InquiryCost.LOW: 0, InquiryCost.MEDIUM: 1, InquiryCost.HIGH: 2}


def prioritize_research_agenda(request: ResearchAgendaRequest) -> ResearchAgenda:
    """Rank probes by ordinal discriminative information value and then cost."""

    if not isinstance(request, ResearchAgendaRequest):
        raise ValidationError("request must be a ResearchAgendaRequest")
    # ResearchAgendaRequest is mutable, so construction-time validation is not
    # an authority boundary. Rebuild the complete semantic envelope from its
    # current serialized state before portfolio/probe state influences research.
    request = ResearchAgendaRequest(**copy.deepcopy(request.model_dump()))
    active = set(request.portfolio.active_hypothesis_ids)
    recommendations: List[ResearchRecommendation] = []

    for probe in request.probes:
        active_predictions = [
            prediction
            for prediction in probe.predictions
            if prediction.hypothesis_id in active
        ]
        targeted = [prediction.hypothesis_id for prediction in active_predictions]
        distinct_predictions = {
            prediction.predicted_observation for prediction in active_predictions
        }

        value = InformationValue.NONE
        if len(active) == 1 and len(active_predictions) == 1:
            value = InformationValue.LOW
        elif len(active_predictions) >= 2 and len(distinct_predictions) >= 2:
            value = (
                InformationValue.HIGH
                if len(active) >= 3 and len(targeted) == len(active)
                else InformationValue.MEDIUM
            )

        if value == InformationValue.NONE:
            continue
        recommendations.append(
            ResearchRecommendation(
                probe_id=probe.probe_id,
                information_value=value,
                cost=probe.cost,
                targeted_hypothesis_ids=targeted,
                rationale=(
                    "probe distinguishes competing active hypotheses"
                    if value in {InformationValue.MEDIUM, InformationValue.HIGH}
                    else "probe verifies the sole remaining active hypothesis"
                ),
            )
        )

    recommendations.sort(
        key=lambda item: (
            -_INFO_RANK[item.information_value],
            -len(item.targeted_hypothesis_ids),
            _COST_RANK[item.cost],
            item.probe_id,
        )
    )

    reasons = (
        ["research probes are ordered by information value, active-hypothesis coverage, then cost"]
        if recommendations
        else ["no proposed probe can currently discriminate or verify active hypotheses"]
    )
    return ResearchAgenda(
        agenda_id=request.agenda_id,
        goal_id=request.goal_id,
        recommendations=recommendations,
        reasons=reasons,
    )
