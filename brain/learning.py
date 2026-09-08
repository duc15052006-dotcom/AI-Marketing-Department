"""Provider-neutral autonomous learning primitives for the five permanent ASIs.

The Brain already contains goals, evidence, planning, decisions, outcomes, memory
policy and stopping semantics.  This module closes the cognitive loop between
those components without teaching the Brain how to call a provider or execute a
tool.

The loop is deliberately explicit and auditable:

    goal -> knowledge gaps -> research / experiment -> observation
         -> expectation delta -> causal lesson -> memory candidate
         -> meta-learning signal -> next learning strategy

No model weights are changed here.  "Learning" means system-level acquisition of
verified knowledge, lessons, procedures and strategy signals that can be handed
to the existing Memory authority boundary.
"""

from __future__ import annotations

import copy
import math
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId, EvidenceNeed, GoalSpec, UnknownRecord
from brain.evidence import ClaimEvidenceRequest, ClaimVerdict, assess_claim_evidence
from schemas.base import BaseModel, Field, ValidationError


class KnowledgeState(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    GAP = "GAP"
    BLOCKED = "BLOCKED"


class LearningAction(str, Enum):
    ACT = "ACT"
    RESEARCH = "RESEARCH"
    EXPERIMENT = "EXPERIMENT"
    REVISE = "REVISE"
    PROMOTE_LESSON = "PROMOTE_LESSON"
    HOLD = "HOLD"


class ExperimentRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LessonDisposition(str, Enum):
    CANDIDATE = "CANDIDATE"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string or None")
    stripped = value.strip()
    return stripped or None


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field_name} must be a boolean")
    return value


def _bounded_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name} must be a number between 0 and 1")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0 or numeric > 1.0:
        raise ValidationError(f"{field_name} must be finite and between 0 and 1")
    return numeric


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


def _text_list(value: object, field_name: str) -> List[str]:
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


class KnowledgeGap(BaseModel):
    """One explicit epistemic gap preventing confident progress on a goal."""

    gap_id: str
    goal_id: str
    owner_agent: BrainAgentId
    question: str
    consequence: str
    blocking: bool = False
    evidence_need_ids: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.gap_id = _required_text(self.gap_id, "gap_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.question = _required_text(self.question, "question")
        self.consequence = _required_text(self.consequence, "consequence")
        self.blocking = _strict_bool(self.blocking, "blocking")
        self.evidence_need_ids = _text_list(self.evidence_need_ids, "evidence_need_ids")


class KnowledgeGapAssessment(BaseModel):
    """Canonical Brain decision about whether knowledge is sufficient to proceed."""

    goal_id: str
    state: KnowledgeState
    gaps: List[KnowledgeGap] = Field(default_factory=list)
    recommended_action: LearningAction = LearningAction.ACT
    rationale: str = "Knowledge is sufficient for the current goal."

    def __post_init__(self) -> None:
        super().__post_init__()
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.state = _enum(self.state, KnowledgeState, "state")
        self.recommended_action = _enum(
            self.recommended_action, LearningAction, "recommended_action"
        )
        self.rationale = _required_text(self.rationale, "rationale")
        if not isinstance(self.gaps, list):
            raise ValidationError("gaps must be a list")
        for gap in self.gaps:
            if not isinstance(gap, KnowledgeGap):
                raise ValidationError("gaps must contain only KnowledgeGap items")
            if gap.goal_id != self.goal_id:
                raise ValidationError("every knowledge gap must belong to assessment goal_id")
        if self.state == KnowledgeState.SUFFICIENT and self.gaps:
            raise ValidationError("SUFFICIENT knowledge state cannot contain unresolved gaps")
        if self.state != KnowledgeState.SUFFICIENT and not self.gaps:
            raise ValidationError("GAP/BLOCKED knowledge state requires at least one gap")


class ResearchDirective(BaseModel):
    """Provider-neutral research request emitted by the Brain."""

    directive_id: str
    goal_id: str
    owner_agent: BrainAgentId
    gap_id: str
    question: str
    required_evidence: List[str] = Field(default_factory=list)
    stop_when: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.directive_id = _required_text(self.directive_id, "directive_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.gap_id = _required_text(self.gap_id, "gap_id")
        self.question = _required_text(self.question, "question")
        self.required_evidence = _text_list(self.required_evidence, "required_evidence")
        self.stop_when = _text_list(self.stop_when, "stop_when")
        if not self.stop_when:
            raise ValidationError("research directive requires at least one stop_when criterion")


class Hypothesis(BaseModel):
    """Explicit falsifiable hypothesis owned by one ASI."""

    hypothesis_id: str
    goal_id: str
    owner_agent: BrainAgentId
    statement: str
    prediction: str
    falsification_criteria: List[str] = Field(default_factory=list)
    prior_confidence: float = 0.5
    evidence_refs: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.statement = _required_text(self.statement, "statement")
        self.prediction = _required_text(self.prediction, "prediction")
        self.falsification_criteria = _text_list(
            self.falsification_criteria, "falsification_criteria"
        )
        if not self.falsification_criteria:
            raise ValidationError("hypothesis requires at least one falsification criterion")
        self.prior_confidence = _bounded_float(
            self.prior_confidence, "prior_confidence"
        )
        self.evidence_refs = _text_list(self.evidence_refs, "evidence_refs")


class ExperimentDesign(BaseModel):
    """Semantic experiment design; execution details remain outside the Brain."""

    experiment_id: str
    goal_id: str
    hypothesis_id: str
    owner_agent: BrainAgentId
    intervention: str
    expected_observation: str
    success_signal: str
    failure_signal: str
    risk: ExperimentRisk = ExperimentRisk.LOW
    reversible: bool = True
    constraints: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.experiment_id = _required_text(self.experiment_id, "experiment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.intervention = _required_text(self.intervention, "intervention")
        self.expected_observation = _required_text(
            self.expected_observation, "expected_observation"
        )
        self.success_signal = _required_text(self.success_signal, "success_signal")
        self.failure_signal = _required_text(self.failure_signal, "failure_signal")
        self.risk = _enum(self.risk, ExperimentRisk, "risk")
        self.reversible = _strict_bool(self.reversible, "reversible")
        self.constraints = _text_list(self.constraints, "constraints")
        if self.risk == ExperimentRisk.CRITICAL and self.reversible:
            raise ValidationError(
                "CRITICAL experiment cannot claim reversible=True without a safer design"
            )


class LearningEpisode(BaseModel):
    """Prediction-versus-observation record for one hypothesis test or action."""

    episode_id: str
    goal_id: str
    owner_agent: BrainAgentId
    hypothesis: Hypothesis
    expected_outcome: str
    observed_outcome: str
    causal_explanation: str
    evidence_request: ClaimEvidenceRequest
    experiment_id: Optional[str] = None
    prediction_matched: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        self.episode_id = _required_text(self.episode_id, "episode_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        if not isinstance(self.hypothesis, Hypothesis):
            raise ValidationError("hypothesis must be a Hypothesis")
        if self.hypothesis.goal_id != self.goal_id:
            raise ValidationError("hypothesis goal_id must match learning episode goal_id")
        if self.hypothesis.owner_agent != self.owner_agent:
            raise ValidationError("hypothesis owner must match learning episode owner")
        self.expected_outcome = _required_text(self.expected_outcome, "expected_outcome")
        self.observed_outcome = _required_text(self.observed_outcome, "observed_outcome")
        self.causal_explanation = _required_text(
            self.causal_explanation, "causal_explanation"
        )
        if not isinstance(self.evidence_request, ClaimEvidenceRequest):
            raise ValidationError("evidence_request must be a ClaimEvidenceRequest")
        self.experiment_id = _optional_text(self.experiment_id, "experiment_id")
        self.prediction_matched = _strict_bool(
            self.prediction_matched, "prediction_matched"
        )


class LessonRecord(BaseModel):
    """Auditable system-level lesson derived from a verified learning episode."""

    lesson_id: str
    goal_id: str
    owner_agent: BrainAgentId
    episode_id: str
    hypothesis_id: str
    lesson: str
    causal_explanation: str
    prediction_matched: bool
    posterior_confidence: float
    evidence_refs: List[str] = Field(default_factory=list)
    disposition: LessonDisposition = LessonDisposition.CANDIDATE

    def __post_init__(self) -> None:
        super().__post_init__()
        self.lesson_id = _required_text(self.lesson_id, "lesson_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.episode_id = _required_text(self.episode_id, "episode_id")
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.lesson = _required_text(self.lesson, "lesson")
        self.causal_explanation = _required_text(
            self.causal_explanation, "causal_explanation"
        )
        self.prediction_matched = _strict_bool(
            self.prediction_matched, "prediction_matched"
        )
        self.posterior_confidence = _bounded_float(
            self.posterior_confidence, "posterior_confidence"
        )
        self.evidence_refs = _text_list(self.evidence_refs, "evidence_refs")
        self.disposition = _enum(self.disposition, LessonDisposition, "disposition")


class MetaLearningSignal(BaseModel):
    """A bounded recommendation for improving how a future learning cycle learns."""

    signal_id: str
    owner_agent: BrainAgentId
    pattern: str
    recommended_change: str
    supporting_lesson_ids: List[str] = Field(default_factory=list)
    confidence: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        self.signal_id = _required_text(self.signal_id, "signal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.pattern = _required_text(self.pattern, "pattern")
        self.recommended_change = _required_text(
            self.recommended_change, "recommended_change"
        )
        self.supporting_lesson_ids = _text_list(
            self.supporting_lesson_ids, "supporting_lesson_ids"
        )
        if not self.supporting_lesson_ids:
            raise ValidationError(
                "meta-learning signal requires at least one supporting lesson"
            )
        self.confidence = _bounded_float(self.confidence, "confidence")


def assess_knowledge_state(
    goal: GoalSpec,
    *,
    unknowns: List[UnknownRecord],
    evidence_needs: List[EvidenceNeed],
) -> KnowledgeGapAssessment:
    """Convert explicit unknowns/evidence needs into a fail-closed epistemic state."""

    if not isinstance(goal, GoalSpec):
        raise ValidationError("goal must be a GoalSpec")
    if not isinstance(unknowns, list) or not isinstance(evidence_needs, list):
        raise ValidationError("unknowns and evidence_needs must be lists")

    goal_copy = copy.deepcopy(goal)
    unknown_copies = copy.deepcopy(unknowns)
    need_copies = copy.deepcopy(evidence_needs)

    needs_by_question = {}
    for need in need_copies:
        if not isinstance(need, EvidenceNeed):
            raise ValidationError("evidence_needs must contain only EvidenceNeed items")
        need = EvidenceNeed(**need.model_dump())
        if need.goal_id != goal_copy.goal_id:
            raise ValidationError("evidence need goal_id must match goal")
        needs_by_question.setdefault(need.question, []).append(need)

    gaps: List[KnowledgeGap] = []
    for index, unknown in enumerate(unknown_copies, start=1):
        if not isinstance(unknown, UnknownRecord):
            raise ValidationError("unknowns must contain only UnknownRecord items")
        unknown = UnknownRecord(**unknown.model_dump())
        if unknown.goal_id != goal_copy.goal_id:
            raise ValidationError("unknown goal_id must match goal")
        matching_needs = needs_by_question.get(unknown.question, [])
        gaps.append(
            KnowledgeGap(
                gap_id=f"KG-{goal_copy.goal_id}-{index}",
                goal_id=goal_copy.goal_id,
                owner_agent=goal_copy.owner_agent,
                question=unknown.question,
                consequence=unknown.consequence,
                blocking=unknown.blocking,
                evidence_need_ids=[need.need_id for need in matching_needs],
            )
        )

    if not gaps:
        return KnowledgeGapAssessment(
            goal_id=goal_copy.goal_id,
            state=KnowledgeState.SUFFICIENT,
            gaps=[],
            recommended_action=LearningAction.ACT,
            rationale="No explicit unresolved knowledge gap blocks the current goal.",
        )

    if any(gap.blocking for gap in gaps):
        return KnowledgeGapAssessment(
            goal_id=goal_copy.goal_id,
            state=KnowledgeState.BLOCKED,
            gaps=gaps,
            recommended_action=LearningAction.RESEARCH,
            rationale="At least one explicit blocking unknown requires evidence before action.",
        )

    return KnowledgeGapAssessment(
        goal_id=goal_copy.goal_id,
        state=KnowledgeState.GAP,
        gaps=gaps,
        recommended_action=LearningAction.RESEARCH,
        rationale="Unresolved knowledge gaps should be reduced before confidence is increased.",
    )


def research_directives_for_gaps(
    assessment: KnowledgeGapAssessment,
) -> List[ResearchDirective]:
    """Produce provider-neutral research work from canonical gaps."""

    if not isinstance(assessment, KnowledgeGapAssessment):
        raise ValidationError("assessment must be a KnowledgeGapAssessment")
    canonical = KnowledgeGapAssessment(**copy.deepcopy(assessment.model_dump()))
    if canonical.state == KnowledgeState.SUFFICIENT:
        return []

    directives: List[ResearchDirective] = []
    for index, gap in enumerate(canonical.gaps, start=1):
        directives.append(
            ResearchDirective(
                directive_id=f"RD-{canonical.goal_id}-{index}",
                goal_id=canonical.goal_id,
                owner_agent=gap.owner_agent,
                gap_id=gap.gap_id,
                question=gap.question,
                required_evidence=gap.evidence_need_ids,
                stop_when=[
                    "the question is supported by independent observed evidence",
                    "material contradictions are explicitly resolved or preserved",
                    "remaining uncertainty no longer changes the decision boundary",
                ],
            )
        )
    return directives


def choose_learning_action(
    *,
    knowledge: KnowledgeGapAssessment,
    hypothesis: Optional[Hypothesis] = None,
    experiment: Optional[ExperimentDesign] = None,
) -> LearningAction:
    """Choose the next semantic learning action without executing anything."""

    if not isinstance(knowledge, KnowledgeGapAssessment):
        raise ValidationError("knowledge must be a KnowledgeGapAssessment")
    canonical = KnowledgeGapAssessment(**copy.deepcopy(knowledge.model_dump()))

    if canonical.state in {KnowledgeState.GAP, KnowledgeState.BLOCKED}:
        return LearningAction.RESEARCH
    if hypothesis is None:
        return LearningAction.ACT
    if not isinstance(hypothesis, Hypothesis):
        raise ValidationError("hypothesis must be a Hypothesis or None")
    if experiment is None:
        return LearningAction.EXPERIMENT
    if not isinstance(experiment, ExperimentDesign):
        raise ValidationError("experiment must be an ExperimentDesign or None")
    if experiment.hypothesis_id != hypothesis.hypothesis_id:
        raise ValidationError("experiment must test the supplied hypothesis")
    if experiment.goal_id != hypothesis.goal_id:
        raise ValidationError("experiment and hypothesis must belong to the same goal")
    if experiment.risk == ExperimentRisk.CRITICAL:
        return LearningAction.HOLD
    return LearningAction.EXPERIMENT


def derive_lesson(episode: LearningEpisode) -> LessonRecord:
    """Derive a bounded lesson only from canonical, re-assessed evidence."""

    if not isinstance(episode, LearningEpisode):
        raise ValidationError("episode must be a LearningEpisode")
    canonical = copy.deepcopy(episode)
    canonical = LearningEpisode(**canonical.model_dump())

    evidence = ClaimEvidenceRequest(**canonical.evidence_request.model_dump())
    if evidence.goal_id != canonical.goal_id:
        raise ValidationError("learning evidence goal_id must match episode goal_id")
    if evidence.agent_id != canonical.owner_agent:
        raise ValidationError("learning evidence agent_id must match episode owner")
    assessment = assess_claim_evidence(evidence)

    if assessment.verdict == ClaimVerdict.REFUTED:
        disposition = LessonDisposition.REJECTED
        posterior = max(0.0, canonical.hypothesis.prior_confidence - 0.35)
        lesson = "The tested hypothesis is contradicted by canonical observed evidence."
    elif assessment.verdict == ClaimVerdict.SUPPORTED:
        disposition = LessonDisposition.VERIFIED
        delta = 0.2 if canonical.prediction_matched else -0.15
        posterior = min(1.0, max(0.0, canonical.hypothesis.prior_confidence + delta))
        if canonical.prediction_matched:
            lesson = "Observed outcome matched the hypothesis prediction under the tested conditions."
        else:
            lesson = "Observed evidence is valid, but the prediction missed; revise the causal model."
    else:
        disposition = LessonDisposition.CANDIDATE
        posterior = canonical.hypothesis.prior_confidence
        lesson = "Evidence is not decisive enough to promote a durable causal lesson."

    refs = list(assessment.supporting_evidence_refs)
    for ref in assessment.refuting_evidence_refs:
        if ref not in refs:
            refs.append(ref)

    return LessonRecord(
        lesson_id=f"LESSON-{canonical.episode_id}",
        goal_id=canonical.goal_id,
        owner_agent=canonical.owner_agent,
        episode_id=canonical.episode_id,
        hypothesis_id=canonical.hypothesis.hypothesis_id,
        lesson=lesson,
        causal_explanation=canonical.causal_explanation,
        prediction_matched=canonical.prediction_matched,
        posterior_confidence=posterior,
        evidence_refs=refs,
        disposition=disposition,
    )


def derive_meta_learning_signal(
    *,
    signal_id: str,
    owner_agent: BrainAgentId,
    lessons: List[LessonRecord],
) -> MetaLearningSignal:
    """Infer how the next learning cycle should change from verified lessons.

    This intentionally adjusts *learning strategy*, not model weights or system
    authority.  A single lesson may suggest a weak signal; repeated verified
    misses increase confidence that the learning process itself needs revision.
    """

    if not isinstance(lessons, list) or not lessons:
        raise ValidationError("lessons must contain at least one LessonRecord")
    canonical_lessons: List[LessonRecord] = []
    for lesson in copy.deepcopy(lessons):
        if not isinstance(lesson, LessonRecord):
            raise ValidationError("lessons must contain only LessonRecord items")
        canonical_lessons.append(LessonRecord(**lesson.model_dump()))

    verified = [
        lesson
        for lesson in canonical_lessons
        if lesson.disposition == LessonDisposition.VERIFIED
    ]
    if not verified:
        raise ValidationError("meta-learning requires at least one VERIFIED lesson")

    misses = [lesson for lesson in verified if not lesson.prediction_matched]
    miss_ratio = len(misses) / len(verified)
    if miss_ratio >= 0.5:
        pattern = "Repeated prediction error indicates a weakness in the current causal/research strategy."
        recommendation = (
            "Increase hypothesis diversity, seek disconfirming evidence earlier, and require an "
            "explicit causal alternative before the next consequential prediction."
        )
    else:
        pattern = "Verified predictions are mostly calibrated under the tested conditions."
        recommendation = (
            "Preserve the current evidence discipline while testing transfer to a different context "
            "before broadening the lesson scope."
        )

    confidence = min(0.95, 0.5 + (0.1 * len(verified)))
    return MetaLearningSignal(
        signal_id=signal_id,
        owner_agent=owner_agent,
        pattern=pattern,
        recommended_change=recommendation,
        supporting_lesson_ids=[lesson.lesson_id for lesson in verified],
        confidence=confidence,
    )
