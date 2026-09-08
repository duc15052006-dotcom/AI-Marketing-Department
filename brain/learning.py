"""Provider-neutral causal learning semantics for the five-ASI Brain.

The learning layer converts a hypothesis plus canonical evidence into an
auditable learning decision. It deliberately distinguishes "supported by
observation" from "causally established by a controlled intervention" so the
Brain cannot silently promote correlation into causal knowledge.

This module produces semantic lesson candidates only. Durable promotion remains
owned by ``brain.memory_policy`` and execution remains outside the Brain.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceSignal,
    assess_claim_evidence,
)
from brain.metacognition import LearningStrategy
from schemas.base import BaseModel, Field, ValidationError


class LearningClaimKind(str, Enum):
    FACTUAL = "FACTUAL"
    CAUSAL = "CAUSAL"
    PROCEDURAL = "PROCEDURAL"
    PREDICTIVE = "PREDICTIVE"


class LearningMethod(str, Enum):
    OBSERVATION = "OBSERVATION"
    EXPERIMENT = "EXPERIMENT"
    SIMULATION = "SIMULATION"
    REFLECTION = "REFLECTION"


class LearningDisposition(str, Enum):
    CANDIDATE_LESSON = "CANDIDATE_LESSON"
    REVISE_HYPOTHESIS = "REVISE_HYPOTHESIS"
    RESOLVE_CONTRADICTION = "RESOLVE_CONTRADICTION"
    GATHER_EVIDENCE = "GATHER_EVIDENCE"
    TEST_CAUSALLY = "TEST_CAUSALLY"


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
    cleaned = value.strip()
    return cleaned or None


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


class LearningEpisode(BaseModel):
    """One hypothesis-evaluation episode before any durable memory promotion."""

    episode_id: str
    goal_id: str
    agent_id: BrainAgentId
    hypothesis_id: str
    claim_kind: LearningClaimKind
    method: LearningMethod
    hypothesis: str
    prediction: str
    evidence_request: ClaimEvidenceRequest
    intervention_id: Optional[str] = None
    control_ref: Optional[str] = None
    context_refs: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.episode_id = _required_text(self.episode_id, "episode_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.claim_kind = _enum(self.claim_kind, LearningClaimKind, "claim_kind")
        self.method = _enum(self.method, LearningMethod, "method")
        self.hypothesis = _required_text(self.hypothesis, "hypothesis")
        self.prediction = _required_text(self.prediction, "prediction")
        self.intervention_id = _optional_text(self.intervention_id, "intervention_id")
        self.control_ref = _optional_text(self.control_ref, "control_ref")
        self.context_refs = _unique_text_list(self.context_refs, "context_refs")

        if not isinstance(self.evidence_request, ClaimEvidenceRequest):
            raise ValidationError(
                "evidence_request must be a ClaimEvidenceRequest"
            )
        self.evidence_request = copy.deepcopy(self.evidence_request)
        if self.evidence_request.goal_id != self.goal_id:
            raise ValidationError(
                "evidence_request goal_id must match learning episode goal_id"
            )
        if self.evidence_request.claim_id != self.hypothesis_id:
            raise ValidationError(
                "evidence_request claim_id must match learning episode hypothesis_id"
            )

        if self.method != LearningMethod.EXPERIMENT and (
            self.intervention_id is not None or self.control_ref is not None
        ):
            raise ValidationError(
                "intervention_id/control_ref are valid only for EXPERIMENT method"
            )


class LearningDecision(BaseModel):
    """Auditable result of one hypothesis-evaluation episode."""

    episode_id: str
    goal_id: str
    agent_id: BrainAgentId
    hypothesis_id: str
    disposition: LearningDisposition
    evidence_verdict: ClaimVerdict
    next_strategy: LearningStrategy
    evidence_refs: List[str] = Field(default_factory=list)
    lesson_candidate: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.episode_id = _required_text(self.episode_id, "episode_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.disposition = _enum(
            self.disposition, LearningDisposition, "disposition"
        )
        self.evidence_verdict = _enum(
            self.evidence_verdict, ClaimVerdict, "evidence_verdict"
        )
        self.next_strategy = _enum(
            self.next_strategy, LearningStrategy, "next_strategy"
        )
        self.evidence_refs = _unique_text_list(self.evidence_refs, "evidence_refs")
        self.lesson_candidate = _optional_text(
            self.lesson_candidate, "lesson_candidate"
        )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one learning reason")

        if self.disposition == LearningDisposition.CANDIDATE_LESSON:
            if self.lesson_candidate is None:
                raise ValidationError(
                    "CANDIDATE_LESSON requires lesson_candidate"
                )
            if self.next_strategy != LearningStrategy.NONE:
                raise ValidationError(
                    "CANDIDATE_LESSON must use NONE next_strategy"
                )
        else:
            if self.lesson_candidate is not None:
                raise ValidationError(
                    "non-candidate learning decisions cannot carry lesson_candidate"
                )
            if self.next_strategy == LearningStrategy.NONE:
                raise ValidationError(
                    "non-candidate learning decisions require a next strategy"
                )


def _canonical_evidence_request(request: ClaimEvidenceRequest) -> ClaimEvidenceRequest:
    if not isinstance(request, ClaimEvidenceRequest):
        raise ValidationError("evidence_request must be a ClaimEvidenceRequest")
    if not isinstance(request.evidence, list):
        raise ValidationError("evidence must be a list of EvidenceSignal")
    evidence: List[EvidenceSignal] = []
    for raw in request.evidence:
        if not isinstance(raw, EvidenceSignal):
            raise ValidationError("evidence must contain only EvidenceSignal items")
        evidence.append(EvidenceSignal(**copy.deepcopy(raw.model_dump())))
    return ClaimEvidenceRequest(
        assessment_id=request.assessment_id,
        goal_id=request.goal_id,
        claim_id=request.claim_id,
        agent_id=request.agent_id,
        evidence=evidence,
    )


def _canonical_learning_episode(episode: LearningEpisode) -> LearningEpisode:
    """Revalidate the full mutable learning envelope at its authority boundary."""

    if not isinstance(episode, LearningEpisode):
        raise ValidationError("episode must be a LearningEpisode")
    return LearningEpisode(
        episode_id=episode.episode_id,
        goal_id=episode.goal_id,
        agent_id=episode.agent_id,
        hypothesis_id=episode.hypothesis_id,
        claim_kind=episode.claim_kind,
        method=episode.method,
        hypothesis=episode.hypothesis,
        prediction=episode.prediction,
        evidence_request=_canonical_evidence_request(episode.evidence_request),
        intervention_id=episode.intervention_id,
        control_ref=episode.control_ref,
        context_refs=copy.deepcopy(episode.context_refs),
    )


def analyze_learning_episode(episode: LearningEpisode) -> LearningDecision:
    """Convert canonical evidence into a conservative semantic learning update."""

    episode = _canonical_learning_episode(episode)

    assessment = assess_claim_evidence(episode.evidence_request)
    evidence_refs: List[str] = []
    for ref in (
        assessment.supporting_evidence_refs
        + assessment.contradicting_evidence_refs
    ):
        if ref not in evidence_refs:
            evidence_refs.append(ref)

    common = {
        "episode_id": episode.episode_id,
        "goal_id": episode.goal_id,
        "agent_id": episode.agent_id,
        "hypothesis_id": episode.hypothesis_id,
        "evidence_verdict": assessment.verdict,
        "evidence_refs": evidence_refs,
    }

    if assessment.verdict == ClaimVerdict.CONTESTED:
        return LearningDecision(
            **common,
            disposition=LearningDisposition.RESOLVE_CONTRADICTION,
            next_strategy=LearningStrategy.RESOLVE_CONTRADICTION,
            reasons=[
                "conflicting qualifying evidence prevents a stable lesson"
            ],
        )

    if assessment.verdict == ClaimVerdict.INSUFFICIENT:
        return LearningDecision(
            **common,
            disposition=LearningDisposition.GATHER_EVIDENCE,
            next_strategy=LearningStrategy.RESEARCH,
            reasons=[
                "insufficient evidence cannot create a learning update"
            ],
        )

    if assessment.verdict == ClaimVerdict.REFUTED:
        return LearningDecision(
            **common,
            disposition=LearningDisposition.REVISE_HYPOTHESIS,
            next_strategy=LearningStrategy.RESEARCH,
            reasons=[
                "qualifying observed evidence refutes the current hypothesis"
            ],
        )

    controlled_causal_test = (
        episode.method == LearningMethod.EXPERIMENT
        and episode.intervention_id is not None
        and episode.control_ref is not None
    )
    if (
        episode.claim_kind == LearningClaimKind.CAUSAL
        and not controlled_causal_test
    ):
        return LearningDecision(
            **common,
            disposition=LearningDisposition.TEST_CAUSALLY,
            next_strategy=LearningStrategy.EXPERIMENT,
            reasons=[
                "observational support is not enough to promote a causal lesson",
                "causal learning requires an explicit intervention and control reference",
            ],
        )

    return LearningDecision(
        **common,
        disposition=LearningDisposition.CANDIDATE_LESSON,
        next_strategy=LearningStrategy.NONE,
        lesson_candidate=episode.hypothesis,
        reasons=[
            "qualifying observed evidence supports the hypothesis",
            (
                "causal lesson is backed by an explicit controlled intervention"
                if episode.claim_kind == LearningClaimKind.CAUSAL
                else "lesson remains a semantic candidate pending memory policy"
            ),
        ],
    )
