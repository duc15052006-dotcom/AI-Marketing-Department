"""Evidence-grounded cognitive reflection for the five-ASI Brain.

Reflection in this module is a structured semantic audit, not an LLM prompt that
asks a model to criticize its own prose. It re-validates a decision against a
canonical world-state snapshot, explicit decision premises, raw evidence
telemetry, and (when supplied) a canonically re-evaluated hypothesis portfolio.

The output is advisory scrutiny only. It cannot authorize execution, upgrade an
evidence verdict, revise WorldState, manufacture probability, or turn a critique
into truth. Caller-provided telemetry may increase scrutiny but cannot lower it.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Dict, List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId, DecisionRecord
from brain.evidence import ClaimEvidenceRequest, EvidenceOrigin, EvidenceSignal
from brain.hypotheses import HypothesisPortfolioRequest, assess_hypothesis_portfolio
from brain.world_state import BeliefStatus, WorldBelief, WorldStateSnapshot
from schemas.base import BaseModel, Field, ValidationError


class ReflectionFindingKind(str, Enum):
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"
    CONTESTED_PREMISE = "CONTESTED_PREMISE"
    REFUTED_PREMISE = "REFUTED_PREMISE"
    IGNORED_CONTRADICTING_EVIDENCE = "IGNORED_CONTRADICTING_EVIDENCE"
    UNSUPPORTED_NUMERIC_CONFIDENCE = "UNSUPPORTED_NUMERIC_CONFIDENCE"
    SHARED_SOURCE_DEPENDENCE = "SHARED_SOURCE_DEPENDENCE"
    PREMATURE_CONVERGENCE = "PREMATURE_CONVERGENCE"
    MISSING_FALSIFICATION_TEST = "MISSING_FALSIFICATION_TEST"


class ReflectionDirective(str, Enum):
    RESEARCH_PREMISE = "RESEARCH_PREMISE"
    RESOLVE_CONTRADICTION = "RESOLVE_CONTRADICTION"
    REVISE_DECISION = "REVISE_DECISION"
    REVIEW_IGNORED_EVIDENCE = "REVIEW_IGNORED_EVIDENCE"
    REMOVE_UNSUPPORTED_CONFIDENCE = "REMOVE_UNSUPPORTED_CONFIDENCE"
    DIVERSIFY_SOURCES = "DIVERSIFY_SOURCES"
    REOPEN_HYPOTHESES = "REOPEN_HYPOTHESES"
    DEFINE_FALSIFICATION_TEST = "DEFINE_FALSIFICATION_TEST"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return _required_text(value, field_name)


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


def _unique_agents(value: object, field_name: str) -> List[BrainAgentId]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of BrainAgentId values")
    result: List[BrainAgentId] = []
    seen = set()
    for raw in value:
        agent = _enum(raw, BrainAgentId, field_name)
        if agent not in seen:
            seen.add(agent)
            result.append(agent)
    return result


def _unique_directives(value: object) -> List[ReflectionDirective]:
    if not isinstance(value, list):
        raise ValidationError("directives must be a list")
    result: List[ReflectionDirective] = []
    seen = set()
    for raw in value:
        directive = _enum(raw, ReflectionDirective, "directives")
        if directive not in seen:
            seen.add(directive)
            result.append(directive)
    return result


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must contain {expected_type.__name__} values or serialized mappings"
    )


def _canonical_evidence_request(raw: object) -> ClaimEvidenceRequest:
    data = _payload(raw, ClaimEvidenceRequest, "evidence_requests")
    raw_evidence = data.pop("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ValidationError("evidence_request evidence must be a list")
    evidence = [
        EvidenceSignal(**_payload(item, EvidenceSignal, "evidence"))
        for item in raw_evidence
    ]
    request = ClaimEvidenceRequest(**data, evidence=evidence)
    for signal in request.evidence:
        if signal.goal_id != request.goal_id:
            raise ValidationError(
                "reflection evidence signal goal_id must match its enclosing evidence request"
            )
        if signal.claim_id != request.claim_id:
            raise ValidationError(
                "reflection evidence signal claim_id must match its enclosing evidence request"
            )
    return request


def _canonical_world_state(raw: object) -> WorldStateSnapshot:
    return WorldStateSnapshot(**_payload(raw, WorldStateSnapshot, "source_state"))


def _canonical_decision(raw: object) -> DecisionRecord:
    return DecisionRecord(**_payload(raw, DecisionRecord, "decision"))


def _canonical_portfolio(raw: object) -> HypothesisPortfolioRequest:
    return HypothesisPortfolioRequest(
        **_payload(raw, HypothesisPortfolioRequest, "portfolio_request")
    )


class DecisionPremise(BaseModel):
    """An explicit proposition/state assumption on which one decision relies."""

    premise_id: str
    decision_id: str
    proposition_id: str
    expected_status: BeliefStatus
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.premise_id = _required_text(self.premise_id, "premise_id")
        self.decision_id = _required_text(self.decision_id, "decision_id")
        self.proposition_id = _required_text(self.proposition_id, "proposition_id")
        self.expected_status = _enum(
            self.expected_status, BeliefStatus, "expected_status"
        )
        if self.expected_status not in (
            BeliefStatus.ESTABLISHED,
            BeliefStatus.REFUTED,
        ):
            raise ValidationError(
                "decision premise expected_status must be ESTABLISHED or REFUTED; "
                "uncertainty states are audit outcomes, not asserted premise truth"
            )
        self.rationale = _required_text(self.rationale, "rationale")


class ReflectionFinding(BaseModel):
    """One provenance-bearing reflection finding; it carries no truth authority."""

    finding_id: str
    kind: ReflectionFindingKind
    target_id: str
    proposition_ids: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    agent_ids: List[BrainAgentId] = Field(default_factory=list)
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.finding_id = _required_text(self.finding_id, "finding_id")
        self.kind = _enum(self.kind, ReflectionFindingKind, "kind")
        self.target_id = _required_text(self.target_id, "target_id")
        self.proposition_ids = _unique_text_list(
            self.proposition_ids, "proposition_ids"
        )
        self.evidence_refs = _unique_text_list(self.evidence_refs, "evidence_refs")
        self.source_ids = _unique_text_list(self.source_ids, "source_ids")
        self.agent_ids = _unique_agents(self.agent_ids, "agent_ids")
        self.rationale = _required_text(self.rationale, "rationale")


class CognitiveReflectionRequest(BaseModel):
    """Canonical inputs required to reflect on one exact ASI decision."""

    reflection_id: str
    goal_id: str
    agent_id: BrainAgentId
    decision: DecisionRecord
    source_state: WorldStateSnapshot
    premises: List[DecisionPremise] = Field(default_factory=list)
    evidence_requests: List[ClaimEvidenceRequest] = Field(default_factory=list)
    portfolio_request: Optional[HypothesisPortfolioRequest] = None
    selected_hypothesis_id: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.reflection_id = _required_text(self.reflection_id, "reflection_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.decision = _canonical_decision(self.decision)
        self.source_state = _canonical_world_state(self.source_state)

        if self.decision.goal_id != self.goal_id:
            raise ValidationError("decision goal_id must match reflection goal_id")
        if self.decision.agent_id != self.agent_id:
            raise ValidationError("decision agent_id must match reflection agent_id")
        if self.source_state.goal_id != self.goal_id:
            raise ValidationError("source_state goal_id must match reflection goal_id")
        if self.source_state.agent_id != self.agent_id:
            raise ValidationError("source_state agent_id must match reflection agent_id")

        if not isinstance(self.premises, list) or not self.premises:
            raise ValidationError("premises must contain at least one DecisionPremise")
        normalized_premises: List[DecisionPremise] = []
        premise_ids = set()
        proposition_targets = set()
        known_propositions = {
            belief.proposition.proposition_id for belief in self.source_state.beliefs
        }
        for raw in self.premises:
            premise = DecisionPremise(
                **_payload(raw, DecisionPremise, "premises")
            )
            if premise.premise_id in premise_ids:
                raise ValidationError(f"duplicate premise_id: {premise.premise_id}")
            premise_ids.add(premise.premise_id)
            if premise.decision_id != self.decision.decision_id:
                raise ValidationError(
                    "premise decision_id must match the reflected decision"
                )
            if premise.proposition_id not in known_propositions:
                raise ValidationError(
                    "premise references unknown world-state proposition: "
                    f"{premise.proposition_id}"
                )
            if premise.proposition_id in proposition_targets:
                raise ValidationError(
                    "multiple premises cannot assert the same proposition twice: "
                    f"{premise.proposition_id}"
                )
            proposition_targets.add(premise.proposition_id)
            normalized_premises.append(premise)
        self.premises = normalized_premises

        if self.portfolio_request is not None:
            self.portfolio_request = _canonical_portfolio(self.portfolio_request)
            if self.portfolio_request.goal_id != self.goal_id:
                raise ValidationError(
                    "portfolio_request goal_id must match reflection goal_id"
                )
            if self.portfolio_request.owner_agent != self.agent_id:
                raise ValidationError(
                    "portfolio_request owner_agent must match reflection agent_id"
                )

        self.selected_hypothesis_id = _optional_text(
            self.selected_hypothesis_id, "selected_hypothesis_id"
        )
        if self.selected_hypothesis_id is not None:
            if self.portfolio_request is None:
                raise ValidationError(
                    "selected_hypothesis_id requires a canonical portfolio_request"
                )
            known_hypotheses = {
                item.hypothesis_id for item in self.portfolio_request.hypotheses
            }
            if self.selected_hypothesis_id not in known_hypotheses:
                raise ValidationError(
                    "selected_hypothesis_id references an unknown hypothesis"
                )

        if not isinstance(self.evidence_requests, list):
            raise ValidationError("evidence_requests must be a list")
        normalized_evidence: List[ClaimEvidenceRequest] = []
        assessment_ids = set()
        known_claims = set(known_propositions)
        if self.portfolio_request is not None:
            known_claims.update(
                item.hypothesis_id for item in self.portfolio_request.hypotheses
            )
        evidence_identity: Dict[str, tuple] = {}
        for raw in self.evidence_requests:
            request = _canonical_evidence_request(raw)
            if request.assessment_id in assessment_ids:
                raise ValidationError(
                    f"duplicate evidence assessment_id: {request.assessment_id}"
                )
            assessment_ids.add(request.assessment_id)
            if request.goal_id != self.goal_id:
                raise ValidationError(
                    "reflection evidence_request goal_id must match reflection goal_id"
                )
            if request.claim_id not in known_claims:
                raise ValidationError(
                    "reflection evidence_request references unknown claim: "
                    f"{request.claim_id}"
                )
            for signal in request.evidence:
                identity = (
                    signal.goal_id,
                    signal.claim_id,
                    signal.source_id,
                    signal.relation,
                    signal.strength,
                    signal.origin,
                )
                previous = evidence_identity.get(signal.evidence_id)
                if previous is not None and previous != identity:
                    raise ValidationError(
                        "same evidence_id cannot carry conflicting semantic identity: "
                        f"{signal.evidence_id}"
                    )
                evidence_identity[signal.evidence_id] = identity
            normalized_evidence.append(request)
        self.evidence_requests = normalized_evidence


class CognitiveReflectionReport(BaseModel):
    """Advisory reflection output. Empty findings means no structural issue found."""

    reflection_id: str
    goal_id: str
    agent_id: BrainAgentId
    decision_id: str
    source_snapshot_id: str
    findings: List[ReflectionFinding] = Field(default_factory=list)
    directives: List[ReflectionDirective] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.reflection_id = _required_text(self.reflection_id, "reflection_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.decision_id = _required_text(self.decision_id, "decision_id")
        self.source_snapshot_id = _required_text(
            self.source_snapshot_id, "source_snapshot_id"
        )
        if not isinstance(self.findings, list):
            raise ValidationError("findings must be a list")
        normalized_findings: List[ReflectionFinding] = []
        finding_ids = set()
        for raw in self.findings:
            finding = ReflectionFinding(
                **_payload(raw, ReflectionFinding, "findings")
            )
            if finding.finding_id in finding_ids:
                raise ValidationError(f"duplicate reflection finding_id: {finding.finding_id}")
            finding_ids.add(finding.finding_id)
            normalized_findings.append(finding)
        self.findings = normalized_findings
        self.directives = _unique_directives(self.directives)
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one reflection reason")


def _canonical_request(request: CognitiveReflectionRequest) -> CognitiveReflectionRequest:
    if not isinstance(request, CognitiveReflectionRequest):
        raise ValidationError("request must be a CognitiveReflectionRequest")
    return CognitiveReflectionRequest(**copy.deepcopy(request.model_dump()))


def _beliefs_by_id(source_state: WorldStateSnapshot) -> Dict[str, WorldBelief]:
    return {
        belief.proposition.proposition_id: belief
        for belief in source_state.beliefs
    }


def _finding(
    request: CognitiveReflectionRequest,
    *,
    kind: ReflectionFindingKind,
    target_id: str,
    proposition_ids: Optional[List[str]] = None,
    evidence_refs: Optional[List[str]] = None,
    source_ids: Optional[List[str]] = None,
    agent_ids: Optional[List[BrainAgentId]] = None,
    rationale: str,
) -> ReflectionFinding:
    return ReflectionFinding(
        finding_id=(
            f"{request.reflection_id}:{kind.value.lower()}:{target_id}"
        ),
        kind=kind,
        target_id=target_id,
        proposition_ids=proposition_ids or [],
        evidence_refs=evidence_refs or [],
        source_ids=source_ids or [],
        agent_ids=agent_ids or [],
        rationale=rationale,
    )


def reflect_on_decision(
    request: CognitiveReflectionRequest,
) -> CognitiveReflectionReport:
    """Run deterministic, provenance-preserving reflection over one decision."""

    request = _canonical_request(request)
    findings: List[ReflectionFinding] = []
    directives: List[ReflectionDirective] = []
    beliefs = _beliefs_by_id(request.source_state)

    def add_directive(value: ReflectionDirective) -> None:
        if value not in directives:
            directives.append(value)

    for premise in request.premises:
        belief = beliefs[premise.proposition_id]
        if belief.status != premise.expected_status:
            evidence_refs = list(belief.supporting_evidence_refs) + list(
                belief.contradicting_evidence_refs
            )
            if belief.status == BeliefStatus.UNKNOWN:
                kind = ReflectionFindingKind.UNSUPPORTED_ASSUMPTION
                directive = ReflectionDirective.RESEARCH_PREMISE
                rationale = (
                    "the decision asserts a premise whose canonical world-state status is UNKNOWN"
                )
            elif belief.status == BeliefStatus.CONTESTED:
                kind = ReflectionFindingKind.CONTESTED_PREMISE
                directive = ReflectionDirective.RESOLVE_CONTRADICTION
                rationale = (
                    "the decision relies on a premise whose canonical evidence remains CONTESTED"
                )
            else:
                kind = ReflectionFindingKind.REFUTED_PREMISE
                directive = ReflectionDirective.REVISE_DECISION
                rationale = (
                    "the canonical world-state status contradicts the premise state asserted by the decision"
                )
            findings.append(
                _finding(
                    request,
                    kind=kind,
                    target_id=premise.premise_id,
                    proposition_ids=[premise.proposition_id],
                    evidence_refs=evidence_refs,
                    rationale=rationale,
                )
            )
            add_directive(directive)

        if premise.expected_status == BeliefStatus.ESTABLISHED:
            omitted = [
                ref
                for ref in belief.contradicting_evidence_refs
                if ref not in request.decision.evidence_refs
            ]
            if omitted:
                findings.append(
                    _finding(
                        request,
                        kind=ReflectionFindingKind.IGNORED_CONTRADICTING_EVIDENCE,
                        target_id=premise.premise_id,
                        proposition_ids=[premise.proposition_id],
                        evidence_refs=omitted,
                        rationale=(
                            "canonical contradicting evidence for a relied-on premise is absent from the decision evidence lineage"
                        ),
                    )
                )
                add_directive(ReflectionDirective.REVIEW_IGNORED_EVIDENCE)

    if request.decision.confidence is not None:
        findings.append(
            _finding(
                request,
                kind=ReflectionFindingKind.UNSUPPORTED_NUMERIC_CONFIDENCE,
                target_id=request.decision.decision_id,
                rationale=(
                    "DecisionRecord confidence is a caller-supplied number; no calibrated evidence policy in this reflection boundary makes it truth authority"
                ),
            )
        )
        add_directive(ReflectionDirective.REMOVE_UNSUPPORTED_CONFIDENCE)

    source_agents: Dict[str, set] = {}
    source_evidence: Dict[str, List[str]] = {}
    for evidence_request in request.evidence_requests:
        for signal in evidence_request.evidence:
            if signal.origin != EvidenceOrigin.OBSERVED:
                continue
            source_agents.setdefault(signal.source_id, set()).add(
                evidence_request.agent_id
            )
            refs = source_evidence.setdefault(signal.source_id, [])
            if signal.evidence_id not in refs:
                refs.append(signal.evidence_id)

    for source_id in sorted(source_agents):
        agents = sorted(source_agents[source_id], key=lambda item: item.value)
        if len(agents) < 2:
            continue
        findings.append(
            _finding(
                request,
                kind=ReflectionFindingKind.SHARED_SOURCE_DEPENDENCE,
                target_id=source_id,
                evidence_refs=source_evidence[source_id],
                source_ids=[source_id],
                agent_ids=agents,
                rationale=(
                    "multiple ASI evidence assessments reuse the same observed source, so ASI agreement does not imply source independence"
                ),
            )
        )
        add_directive(ReflectionDirective.DIVERSIFY_SOURCES)

    if request.selected_hypothesis_id is not None:
        assert request.portfolio_request is not None  # guaranteed by request validation
        canonical_portfolio = assess_hypothesis_portfolio(request.portfolio_request)
        selected_id = request.selected_hypothesis_id
        if canonical_portfolio.leading_hypothesis_id != selected_id:
            findings.append(
                _finding(
                    request,
                    kind=ReflectionFindingKind.PREMATURE_CONVERGENCE,
                    target_id=selected_id,
                    rationale=(
                        "the selected hypothesis is not the unique canonical portfolio leader after re-evaluating raw evidence"
                    ),
                )
            )
            add_directive(ReflectionDirective.REOPEN_HYPOTHESES)

        candidate = next(
            item
            for item in request.portfolio_request.hypotheses
            if item.hypothesis_id == selected_id
        )
        if not candidate.differentiating_predictions:
            findings.append(
                _finding(
                    request,
                    kind=ReflectionFindingKind.MISSING_FALSIFICATION_TEST,
                    target_id=selected_id,
                    rationale=(
                        "the selected hypothesis has no explicit differentiating prediction that can be tested against alternatives"
                    ),
                )
            )
            add_directive(ReflectionDirective.DEFINE_FALSIFICATION_TEST)

    reasons = [
        (
            "structured reflection found no authority or provenance issue in the supplied canonical slice"
            if not findings
            else f"structured reflection identified {len(findings)} scrutiny finding(s) without changing canonical truth or authorization"
        )
    ]
    return CognitiveReflectionReport(
        reflection_id=request.reflection_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        decision_id=request.decision.decision_id,
        source_snapshot_id=request.source_state.snapshot_id,
        findings=findings,
        directives=directives,
        reasons=reasons,
    )
