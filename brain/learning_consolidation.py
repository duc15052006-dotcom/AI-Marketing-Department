"""Evidence-authoritative learning consolidation for the five-ASI Brain.

This module turns repeated canonical ``LearningEpisode`` objects into one
scoped ``MemoryCandidate``. It does not trust caller-authored run counts,
evidence summaries, confidence scores, or promotion decisions. Every run is
revalidated through ``analyze_learning_episode`` and durable disposition remains
owned by ``brain.memory_policy``.

The module is semantic-only: it performs no persistence, provider calls, tool
execution, connector access, or runtime effects.
"""

from __future__ import annotations

import copy
from typing import List

from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceSignal,
)
from brain.learning import (
    LearningClaimKind,
    LearningDisposition,
    LearningEpisode,
    LearningMethod,
    analyze_learning_episode,
)
from brain.memory_policy import (
    MemoryAuthority,
    MemoryCandidate,
    MemoryDecision,
    MemoryKind,
    MemoryScopeLevel,
    evaluate_memory_candidate,
)
from schemas.base import BaseModel, Field, ValidationError


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _canonical_evidence_request(request: ClaimEvidenceRequest) -> ClaimEvidenceRequest:
    if not isinstance(request, ClaimEvidenceRequest):
        raise ValidationError("evidence_request must be a ClaimEvidenceRequest")
    evidence: List[EvidenceSignal] = []
    if not isinstance(request.evidence, list):
        raise ValidationError("evidence must be a list of EvidenceSignal")
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


class LearningRunRecord(BaseModel):
    """One explicit independent-run identity bound to one learning episode."""

    run_id: str
    episode: LearningEpisode

    def __post_init__(self) -> None:
        super().__post_init__()
        self.run_id = _required_text(self.run_id, "run_id")
        if isinstance(self.episode, dict):
            self.episode = LearningEpisode(**copy.deepcopy(self.episode))
        if not isinstance(self.episode, LearningEpisode):
            raise ValidationError("episode must be a LearningEpisode")
        self.episode = copy.deepcopy(self.episode)
        self._semantic_snapshot = copy.deepcopy(self.model_dump())


class LearningConsolidationRequest(BaseModel):
    """Raw semantic runs from which consolidation authority must be derived."""

    consolidation_id: str
    goal_id: str
    agent_id: BrainAgentId
    origin_scope: MemoryScopeLevel
    requested_scope: MemoryScopeLevel
    runs: List[LearningRunRecord] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.consolidation_id = _required_text(self.consolidation_id, "consolidation_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        if not isinstance(self.agent_id, BrainAgentId):
            try:
                self.agent_id = BrainAgentId(str(self.agent_id).strip().upper())
            except (TypeError, ValueError):
                raise ValidationError("agent_id must be a permanent BrainAgentId")
        if not isinstance(self.origin_scope, MemoryScopeLevel):
            try:
                self.origin_scope = MemoryScopeLevel(str(self.origin_scope).strip().upper())
            except (TypeError, ValueError):
                raise ValidationError("origin_scope must be a MemoryScopeLevel")
        if not isinstance(self.requested_scope, MemoryScopeLevel):
            try:
                self.requested_scope = MemoryScopeLevel(
                    str(self.requested_scope).strip().upper()
                )
            except (TypeError, ValueError):
                raise ValidationError("requested_scope must be a MemoryScopeLevel")
        if not isinstance(self.runs, list) or not self.runs:
            raise ValidationError("runs must contain at least one LearningRunRecord")

        normalized: List[LearningRunRecord] = []
        seen_run_ids = set()
        for raw in self.runs:
            if isinstance(raw, dict):
                raw = LearningRunRecord(**copy.deepcopy(raw))
            if not isinstance(raw, LearningRunRecord):
                raise ValidationError("runs must contain only LearningRunRecord items")
            record = copy.deepcopy(raw)
            if record.run_id in seen_run_ids:
                raise ValidationError("duplicate run_id cannot represent independent runs")
            seen_run_ids.add(record.run_id)
            normalized.append(record)
        self.runs = normalized
        self._semantic_snapshot = copy.deepcopy(self.model_dump())


class LearningConsolidation(BaseModel):
    """Auditable consolidation output; persistence remains outside the Brain."""

    consolidation_id: str
    goal_id: str
    agent_id: BrainAgentId
    hypothesis_id: str
    run_ids: List[str] = Field(default_factory=list)
    episode_ids: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    memory_candidate: MemoryCandidate
    memory_decision: MemoryDecision

    def __post_init__(self) -> None:
        super().__post_init__()
        self.consolidation_id = _required_text(self.consolidation_id, "consolidation_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        if not self.run_ids or not self.episode_ids:
            raise ValidationError("consolidation must retain run and episode provenance")
        self.run_ids = [_required_text(item, "run_ids") for item in self.run_ids]
        self.episode_ids = [_required_text(item, "episode_ids") for item in self.episode_ids]
        self.evidence_refs = [_required_text(item, "evidence_refs") for item in self.evidence_refs]
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValidationError("run_ids must be unique")
        if len(set(self.episode_ids)) != len(self.episode_ids):
            raise ValidationError("episode_ids must be unique")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValidationError("evidence_refs must be unique")
        if not isinstance(self.memory_candidate, MemoryCandidate):
            raise ValidationError("memory_candidate must be a MemoryCandidate")
        if not isinstance(self.memory_decision, MemoryDecision):
            raise ValidationError("memory_decision must be a MemoryDecision")
        self.memory_candidate = copy.deepcopy(self.memory_candidate)
        self.memory_decision = copy.deepcopy(self.memory_decision)


def _validate_request_snapshot(request: LearningConsolidationRequest) -> None:
    if not isinstance(request, LearningConsolidationRequest):
        raise ValidationError("request must be a LearningConsolidationRequest")
    original = getattr(request, "_semantic_snapshot", None)
    current = copy.deepcopy(request.model_dump())
    if original is None or current != original:
        raise ValidationError(
            "learning consolidation request semantic state changed after validation"
        )
    for record in request.runs:
        original_record = getattr(record, "_semantic_snapshot", None)
        current_record = copy.deepcopy(record.model_dump())
        if original_record is None or current_record != original_record:
            raise ValidationError(
                "learning run record semantic state changed after validation"
            )


def consolidate_learning(request: LearningConsolidationRequest) -> LearningConsolidation:
    """Derive one memory-policy decision from repeated canonical learning runs."""

    _validate_request_snapshot(request)

    run_ids: List[str] = []
    episode_ids: List[str] = []
    assessment_ids = set()
    used_observed_sources = set()
    evidence_refs: List[str] = []
    seen_evidence_refs = set()
    canonical_requests: List[ClaimEvidenceRequest] = []

    canonical_semantics = None
    hypothesis_id = None
    all_experimental = True

    for record in request.runs:
        episode = record.episode
        if episode.goal_id != request.goal_id:
            raise ValidationError("learning run goal_id must match consolidation goal_id")
        if episode.agent_id != request.agent_id:
            raise ValidationError("learning run agent_id must match consolidation agent_id")
        if episode.evidence_request.agent_id != request.agent_id:
            raise ValidationError(
                "evidence assessor must match the learning consolidation owner"
            )

        decision = analyze_learning_episode(episode)
        if decision.disposition != LearningDisposition.CANDIDATE_LESSON:
            raise ValidationError(
                "only canonical CANDIDATE_LESSON runs may contribute to consolidation"
            )
        if decision.evidence_verdict != ClaimVerdict.SUPPORTED:
            raise ValidationError("consolidated learning requires supported evidence")

        semantics = (
            episode.hypothesis_id,
            episode.claim_kind,
            episode.method,
            episode.hypothesis,
            episode.prediction,
            decision.lesson_candidate,
        )
        if canonical_semantics is None:
            canonical_semantics = semantics
            hypothesis_id = episode.hypothesis_id
        elif semantics != canonical_semantics:
            raise ValidationError(
                "all consolidated runs must share exact lesson semantics and method"
            )

        if episode.claim_kind == LearningClaimKind.CAUSAL:
            if (
                episode.method != LearningMethod.EXPERIMENT
                or episode.intervention_id is None
                or episode.control_ref is None
            ):
                raise ValidationError(
                    "causal learning consolidation requires controlled experiments"
                )

        if episode.episode_id in episode_ids:
            raise ValidationError("duplicate episode_id cannot establish independent learning")
        if episode.evidence_request.assessment_id in assessment_ids:
            raise ValidationError(
                "duplicate evidence assessment_id cannot establish independent learning"
            )

        observed_sources = {
            signal.source_id
            for signal in episode.evidence_request.evidence
            if signal.origin == EvidenceOrigin.OBSERVED
        }
        if not observed_sources:
            raise ValidationError("each consolidated run requires observed evidence")
        if used_observed_sources & observed_sources:
            raise ValidationError(
                "replayed observed source cannot manufacture independent runs"
            )
        used_observed_sources.update(observed_sources)

        run_ids.append(record.run_id)
        episode_ids.append(episode.episode_id)
        assessment_ids.add(episode.evidence_request.assessment_id)
        all_experimental = all_experimental and episode.method == LearningMethod.EXPERIMENT

        for ref in decision.evidence_refs:
            if ref not in seen_evidence_refs:
                seen_evidence_refs.add(ref)
                evidence_refs.append(ref)
        canonical_requests.append(_canonical_evidence_request(episode.evidence_request))

    if hypothesis_id is None:
        raise ValidationError("no canonical learning hypothesis was available")

    memory_candidate = MemoryCandidate(
        candidate_id=request.consolidation_id,
        goal_id=request.goal_id,
        claim_id=hypothesis_id,
        agent_id=request.agent_id,
        memory_kind=(MemoryKind.EXPERIMENT if all_experimental else MemoryKind.SUCCESS_FAILURE),
        authority=MemoryAuthority.OBSERVED,
        origin_scope=request.origin_scope,
        requested_scope=request.requested_scope,
        evidence_verdict=ClaimVerdict.SUPPORTED,
        evidence_refs=copy.deepcopy(evidence_refs),
        independent_run_count=len(run_ids),
        run_evidence_requests=copy.deepcopy(canonical_requests),
    )
    memory_decision = evaluate_memory_candidate(memory_candidate)

    return LearningConsolidation(
        consolidation_id=request.consolidation_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        hypothesis_id=hypothesis_id,
        run_ids=copy.deepcopy(run_ids),
        episode_ids=copy.deepcopy(episode_ids),
        evidence_refs=copy.deepcopy(evidence_refs),
        memory_candidate=copy.deepcopy(memory_candidate),
        memory_decision=copy.deepcopy(memory_decision),
    )
