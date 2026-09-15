"""Provider-neutral metacognitive control for the five-ASI Brain.

This module answers whether current knowledge is sufficient to act and, when it
is not, which semantic learning move should happen next. It deliberately does
not select providers, tools, search engines, experiment runners, persistence
backends, or runtime workers.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Type, TypeVar

from brain.contracts import BrainAgentId, EvidenceNeed, UnknownRecord
from brain.evidence import ClaimEvidenceAssessment, ClaimVerdict
from schemas.base import BaseModel, Field, ValidationError


class KnowledgeState(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INCOMPLETE = "INCOMPLETE"
    CONTESTED = "CONTESTED"
    BLOCKED = "BLOCKED"


class KnowledgeGapKind(str, Enum):
    UNKNOWN = "UNKNOWN"
    EVIDENCE = "EVIDENCE"
    CONTRADICTION = "CONTRADICTION"
    CAUSAL = "CAUSAL"
    PROCEDURAL = "PROCEDURAL"
    PREDICTIVE = "PREDICTIVE"


class LearningStrategy(str, Enum):
    NONE = "NONE"
    RESEARCH = "RESEARCH"
    RESOLVE_CONTRADICTION = "RESOLVE_CONTRADICTION"
    EXPERIMENT = "EXPERIMENT"
    DECOMPOSE = "DECOMPOSE"


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


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field_name} must be a boolean")
    return value


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


def _model_payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must contain only {expected_type.__name__} items or serialized mappings"
    )


class KnowledgeGap(BaseModel):
    """One explicit uncertainty that should be reduced before or during action."""

    gap_id: str
    goal_id: str
    owner_agent: BrainAgentId
    kind: KnowledgeGapKind
    question: str
    consequence: str
    blocking: bool = False
    testable: bool = False
    evidence_refs: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.gap_id = _required_text(self.gap_id, "gap_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.kind = _enum(self.kind, KnowledgeGapKind, "kind")
        self.question = _required_text(self.question, "question")
        self.consequence = _required_text(self.consequence, "consequence")
        self.blocking = _strict_bool(self.blocking, "blocking")
        self.testable = _strict_bool(self.testable, "testable")
        self.evidence_refs = _unique_text_list(self.evidence_refs, "evidence_refs")


class GapResolutionDirective(BaseModel):
    """Auditable semantic instruction for how the Brain should reduce one gap."""

    subject_id: str
    strategy: LearningStrategy
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.subject_id = _required_text(self.subject_id, "subject_id")
        self.strategy = _enum(self.strategy, LearningStrategy, "strategy")
        self.rationale = _required_text(self.rationale, "rationale")
        if self.strategy == LearningStrategy.NONE:
            raise ValidationError("gap resolution directives cannot use NONE strategy")


class MetacognitionRequest(BaseModel):
    """Current knowledge state submitted for one exact goal assessment."""

    assessment_id: str
    goal_id: str
    agent_id: BrainAgentId
    gaps: List[KnowledgeGap] = Field(default_factory=list)
    evidence_assessments: List[ClaimEvidenceAssessment] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")

        if not isinstance(self.gaps, list):
            raise ValidationError("gaps must be a list of KnowledgeGap")
        normalized_gaps: List[KnowledgeGap] = []
        gap_ids = set()
        for raw in self.gaps:
            gap = KnowledgeGap(**_model_payload(raw, KnowledgeGap, "gaps"))
            if gap.goal_id != self.goal_id:
                raise ValidationError("knowledge gap goal_id must match request goal_id")
            if gap.gap_id in gap_ids:
                raise ValidationError(f"duplicate knowledge gap id: {gap.gap_id}")
            gap_ids.add(gap.gap_id)
            normalized_gaps.append(gap)
        self.gaps = normalized_gaps

        if not isinstance(self.evidence_assessments, list):
            raise ValidationError(
                "evidence_assessments must be a list of ClaimEvidenceAssessment"
            )
        normalized_assessments: List[ClaimEvidenceAssessment] = []
        assessment_ids = set()
        for raw in self.evidence_assessments:
            assessment = ClaimEvidenceAssessment(
                **_model_payload(raw, ClaimEvidenceAssessment, "evidence_assessments")
            )
            if assessment.goal_id != self.goal_id:
                raise ValidationError(
                    "evidence assessment goal_id must match request goal_id"
                )
            if assessment.assessment_id in assessment_ids:
                raise ValidationError(
                    f"duplicate evidence assessment id: {assessment.assessment_id}"
                )
            assessment_ids.add(assessment.assessment_id)
            normalized_assessments.append(assessment)
        self.evidence_assessments = normalized_assessments


class MetacognitionDecision(BaseModel):
    """Auditable judgement about whether the Brain knows enough to proceed."""

    assessment_id: str
    goal_id: str
    agent_id: BrainAgentId
    knowledge_state: KnowledgeState
    next_strategy: LearningStrategy
    blocking_gap_ids: List[str] = Field(default_factory=list)
    open_gap_ids: List[str] = Field(default_factory=list)
    contested_claim_ids: List[str] = Field(default_factory=list)
    insufficient_claim_ids: List[str] = Field(default_factory=list)
    directives: List[GapResolutionDirective] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.knowledge_state = _enum(
            self.knowledge_state, KnowledgeState, "knowledge_state"
        )
        self.next_strategy = _enum(
            self.next_strategy, LearningStrategy, "next_strategy"
        )
        self.blocking_gap_ids = _unique_text_list(
            self.blocking_gap_ids, "blocking_gap_ids"
        )
        self.open_gap_ids = _unique_text_list(self.open_gap_ids, "open_gap_ids")
        self.contested_claim_ids = _unique_text_list(
            self.contested_claim_ids, "contested_claim_ids"
        )
        self.insufficient_claim_ids = _unique_text_list(
            self.insufficient_claim_ids, "insufficient_claim_ids"
        )

        if not isinstance(self.directives, list):
            raise ValidationError("directives must be a list of GapResolutionDirective")
        normalized_directives: List[GapResolutionDirective] = []
        subjects = set()
        for raw in self.directives:
            directive = GapResolutionDirective(
                **_model_payload(raw, GapResolutionDirective, "directives")
            )
            if directive.subject_id in subjects:
                raise ValidationError(
                    f"duplicate directive subject_id: {directive.subject_id}"
                )
            subjects.add(directive.subject_id)
            normalized_directives.append(directive)
        self.directives = normalized_directives

        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one metacognitive reason")

        if self.knowledge_state == KnowledgeState.SUFFICIENT:
            if self.next_strategy != LearningStrategy.NONE:
                raise ValidationError(
                    "SUFFICIENT knowledge state must use NONE next_strategy"
                )
            if (
                self.blocking_gap_ids
                or self.open_gap_ids
                or self.contested_claim_ids
                or self.insufficient_claim_ids
                or self.directives
            ):
                raise ValidationError(
                    "SUFFICIENT knowledge state cannot carry unresolved gaps"
                )
        elif self.next_strategy == LearningStrategy.NONE:
            raise ValidationError(
                "non-SUFFICIENT knowledge state requires a learning strategy"
            )


def derive_knowledge_gaps(
    *,
    goal_id: str,
    owner_agent: BrainAgentId,
    unknowns: List[UnknownRecord],
    evidence_needs: List[EvidenceNeed],
) -> List[KnowledgeGap]:
    """Convert explicit Brain unknowns/evidence needs into open knowledge gaps."""

    goal_id = _required_text(goal_id, "goal_id")
    owner_agent = _enum(owner_agent, BrainAgentId, "owner_agent")
    if not isinstance(unknowns, list):
        raise ValidationError("unknowns must be a list of UnknownRecord")
    if not isinstance(evidence_needs, list):
        raise ValidationError("evidence_needs must be a list of EvidenceNeed")

    gaps: List[KnowledgeGap] = []
    seen_ids = set()
    for raw in unknowns:
        unknown = UnknownRecord(**_model_payload(raw, UnknownRecord, "unknowns"))
        if unknown.goal_id != goal_id:
            raise ValidationError("unknown goal_id must match requested goal_id")
        gap_id = f"UNKNOWN:{unknown.unknown_id}"
        if gap_id in seen_ids:
            raise ValidationError(f"duplicate derived knowledge gap id: {gap_id}")
        seen_ids.add(gap_id)
        gaps.append(
            KnowledgeGap(
                gap_id=gap_id,
                goal_id=goal_id,
                owner_agent=owner_agent,
                kind=KnowledgeGapKind.UNKNOWN,
                question=unknown.question,
                consequence=unknown.consequence,
                blocking=unknown.blocking,
                testable=False,
            )
        )

    for raw in evidence_needs:
        need = EvidenceNeed(
            **_model_payload(raw, EvidenceNeed, "evidence_needs")
        )
        if need.goal_id != goal_id:
            raise ValidationError("evidence need goal_id must match requested goal_id")
        gap_id = f"EVIDENCE:{need.need_id}"
        if gap_id in seen_ids:
            raise ValidationError(f"duplicate derived knowledge gap id: {gap_id}")
        seen_ids.add(gap_id)
        gaps.append(
            KnowledgeGap(
                gap_id=gap_id,
                goal_id=goal_id,
                owner_agent=owner_agent,
                kind=KnowledgeGapKind.EVIDENCE,
                question=need.question,
                consequence=need.why_needed,
                blocking=need.blocking,
                testable=False,
                evidence_refs=list(need.evidence_refs),
            )
        )
    return gaps


def _strategy_for_gap(gap: KnowledgeGap) -> LearningStrategy:
    if gap.kind in {KnowledgeGapKind.CAUSAL, KnowledgeGapKind.PREDICTIVE}:
        return LearningStrategy.EXPERIMENT if gap.testable else LearningStrategy.RESEARCH
    if gap.kind == KnowledgeGapKind.PROCEDURAL:
        return LearningStrategy.DECOMPOSE
    if gap.kind == KnowledgeGapKind.CONTRADICTION:
        return LearningStrategy.RESOLVE_CONTRADICTION
    return LearningStrategy.RESEARCH


def _strategy_rank(strategy: LearningStrategy) -> int:
    return {
        LearningStrategy.NONE: 0,
        LearningStrategy.RESEARCH: 1,
        LearningStrategy.DECOMPOSE: 2,
        LearningStrategy.EXPERIMENT: 3,
        LearningStrategy.RESOLVE_CONTRADICTION: 4,
    }[strategy]


def assess_metacognition(request: MetacognitionRequest) -> MetacognitionDecision:
    """Judge whether current knowledge is sufficient and choose the next move."""

    if not isinstance(request, MetacognitionRequest):
        raise ValidationError("request must be a MetacognitionRequest")
    request = MetacognitionRequest(**copy.deepcopy(request.model_dump()))

    blocking_gap_ids = [gap.gap_id for gap in request.gaps if gap.blocking]
    open_gap_ids = [gap.gap_id for gap in request.gaps]
    contested_claim_ids: List[str] = []
    insufficient_claim_ids: List[str] = []

    for assessment in request.evidence_assessments:
        if assessment.verdict == ClaimVerdict.CONTESTED:
            if assessment.claim_id not in contested_claim_ids:
                contested_claim_ids.append(assessment.claim_id)
        elif assessment.verdict == ClaimVerdict.INSUFFICIENT:
            if assessment.claim_id not in insufficient_claim_ids:
                insufficient_claim_ids.append(assessment.claim_id)

    directives: List[GapResolutionDirective] = []
    directive_subjects = set()
    for gap in request.gaps:
        strategy = _strategy_for_gap(gap)
        directives.append(
            GapResolutionDirective(
                subject_id=gap.gap_id,
                strategy=strategy,
                rationale=(
                    f"{gap.kind.value} knowledge gap must be reduced before it can be treated as resolved"
                ),
            )
        )
        directive_subjects.add(gap.gap_id)

    for claim_id in contested_claim_ids:
        subject_id = f"CONTESTED:{claim_id}"
        if subject_id not in directive_subjects:
            directives.append(
                GapResolutionDirective(
                    subject_id=subject_id,
                    strategy=LearningStrategy.RESOLVE_CONTRADICTION,
                    rationale="materially conflicting evidence requires explicit contradiction resolution",
                )
            )
            directive_subjects.add(subject_id)

    for claim_id in insufficient_claim_ids:
        subject_id = f"INSUFFICIENT:{claim_id}"
        if subject_id not in directive_subjects:
            directives.append(
                GapResolutionDirective(
                    subject_id=subject_id,
                    strategy=LearningStrategy.RESEARCH,
                    rationale="insufficient evidence requires additional knowledge acquisition",
                )
            )
            directive_subjects.add(subject_id)

    if blocking_gap_ids:
        knowledge_state = KnowledgeState.BLOCKED
        reasons = ["one or more explicit knowledge gaps are blocking safe goal progress"]
    elif contested_claim_ids:
        knowledge_state = KnowledgeState.CONTESTED
        reasons = ["materially conflicting evidence prevents a stable knowledge state"]
    elif open_gap_ids or insufficient_claim_ids:
        knowledge_state = KnowledgeState.INCOMPLETE
        reasons = ["unresolved knowledge gaps or insufficient evidence remain"]
    else:
        knowledge_state = KnowledgeState.SUFFICIENT
        reasons = ["no open knowledge gaps, contested claims, or insufficient evidence remain"]

    if knowledge_state == KnowledgeState.SUFFICIENT:
        next_strategy = LearningStrategy.NONE
    else:
        next_strategy = max(
            (directive.strategy for directive in directives),
            key=_strategy_rank,
        )

    return MetacognitionDecision(
        assessment_id=request.assessment_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        knowledge_state=knowledge_state,
        next_strategy=next_strategy,
        blocking_gap_ids=blocking_gap_ids,
        open_gap_ids=open_gap_ids,
        contested_claim_ids=contested_claim_ids,
        insufficient_claim_ids=insufficient_claim_ids,
        directives=directives,
        reasons=reasons,
    )
