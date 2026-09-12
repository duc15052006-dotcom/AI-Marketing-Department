"""Autonomous semantic coordination above the canonical five-ASI cognitive loop.

V2 composes already-qualified cognitive primitives instead of replacing them.
It may route the next *semantic* move toward research, experiment design,
collective revision/arbitration, or the canonical cognitive cycle. It never
executes experiments, dispatches tools, chooses providers, or persists effects.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional

from brain.cognitive_loop import (
    CognitiveCycle,
    CognitiveCycleRequest,
    CognitivePhase,
    derive_cognitive_cycle,
)
from brain.collective_cognition import (
    CollectiveCognitionDecision,
    CollectiveCognitionDisposition,
    CollectiveCognitionRequest,
    synthesize_collective_cognition,
)
from brain.metacognition import (
    KnowledgeState,
    LearningStrategy,
    MetacognitionDecision,
    MetacognitionRequest,
    assess_metacognition,
)
from schemas.base import BaseModel, Field, ValidationError


class AutonomousCognitiveDirectiveKind(str, Enum):
    """Provider-neutral next move selected by the autonomous semantic loop."""

    FOLLOW_COGNITIVE_CYCLE = "FOLLOW_COGNITIVE_CYCLE"
    REDUCE_KNOWLEDGE_GAP = "REDUCE_KNOWLEDGE_GAP"
    DESIGN_EXPERIMENT = "DESIGN_EXPERIMENT"
    RESEARCH_COLLECTIVE_CANDIDATE = "RESEARCH_COLLECTIVE_CANDIDATE"
    REVISE_COLLECTIVE_CANDIDATE = "REVISE_COLLECTIVE_CANDIDATE"
    ARBITRATE_COLLECTIVE_CANDIDATES = "ARBITRATE_COLLECTIVE_CANDIDATES"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must be a {expected_type.__name__} or serialized mapping"
    )


class AutonomousCognitiveDirective(BaseModel):
    kind: AutonomousCognitiveDirectiveKind
    target_ids: List[str] = Field(default_factory=list)
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.kind, AutonomousCognitiveDirectiveKind):
            try:
                self.kind = AutonomousCognitiveDirectiveKind(str(self.kind).strip().upper())
            except ValueError as exc:
                raise ValidationError("invalid autonomous cognitive directive kind") from exc
        if not isinstance(self.target_ids, list):
            raise ValidationError("target_ids must be a list")
        normalized: List[str] = []
        seen = set()
        for raw in self.target_ids:
            target = _required_text(raw, "target_ids")
            if target not in seen:
                seen.add(target)
                normalized.append(target)
        self.target_ids = normalized
        self.rationale = _required_text(self.rationale, "rationale")


class AutonomousCognitiveLoopRequest(BaseModel):
    """Canonical semantic envelope considered by one autonomous loop turn."""

    loop_id: str
    cognitive_cycle: CognitiveCycleRequest
    metacognition: Optional[MetacognitionRequest] = None
    collective_cognition: Optional[CollectiveCognitionRequest] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.loop_id = _required_text(self.loop_id, "loop_id")
        self.cognitive_cycle = CognitiveCycleRequest(
            **_payload(self.cognitive_cycle, CognitiveCycleRequest, "cognitive_cycle")
        )
        goal_id = self.cognitive_cycle.goal.goal_id

        if self.metacognition is not None:
            self.metacognition = MetacognitionRequest(
                **_payload(self.metacognition, MetacognitionRequest, "metacognition")
            )
            if self.metacognition.goal_id != goal_id:
                raise ValidationError(
                    "metacognition goal_id must exactly match cognitive cycle goal_id"
                )

        if self.collective_cognition is not None:
            self.collective_cognition = CollectiveCognitionRequest(
                **_payload(
                    self.collective_cognition,
                    CollectiveCognitionRequest,
                    "collective_cognition",
                )
            )
            if self.collective_cognition.goal_id != goal_id:
                raise ValidationError(
                    "collective cognition goal_id must exactly match cognitive cycle goal_id"
                )


class AutonomousCognitiveLoopDecision(BaseModel):
    """Detached, auditable semantic result of one autonomous loop turn."""

    loop_id: str
    phase: CognitivePhase
    directive: AutonomousCognitiveDirective
    cognitive_cycle: CognitiveCycle
    metacognition: Optional[MetacognitionDecision] = None
    collective_cognition: Optional[CollectiveCognitionDecision] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.loop_id = _required_text(self.loop_id, "loop_id")
        self.phase = (
            self.phase
            if isinstance(self.phase, CognitivePhase)
            else CognitivePhase(str(self.phase).strip().upper())
        )
        self.directive = AutonomousCognitiveDirective(
            **_payload(self.directive, AutonomousCognitiveDirective, "directive")
        )
        self.cognitive_cycle = CognitiveCycle(
            **_payload(self.cognitive_cycle, CognitiveCycle, "cognitive_cycle")
        )
        if self.metacognition is not None:
            self.metacognition = MetacognitionDecision(
                **_payload(self.metacognition, MetacognitionDecision, "metacognition")
            )
        if self.collective_cognition is not None:
            self.collective_cognition = CollectiveCognitionDecision(
                **_payload(
                    self.collective_cognition,
                    CollectiveCognitionDecision,
                    "collective_cognition",
                )
            )


def _canonical_request(raw: object) -> AutonomousCognitiveLoopRequest:
    if not isinstance(raw, AutonomousCognitiveLoopRequest):
        raise ValidationError("request must be an AutonomousCognitiveLoopRequest")
    return AutonomousCognitiveLoopRequest(**copy.deepcopy(raw.model_dump()))


def _directive(
    kind: AutonomousCognitiveDirectiveKind,
    target_ids: List[str],
    rationale: str,
) -> AutonomousCognitiveDirective:
    return AutonomousCognitiveDirective(
        kind=kind,
        target_ids=list(target_ids),
        rationale=rationale,
    )


def _result(
    *,
    request: AutonomousCognitiveLoopRequest,
    base_cycle: CognitiveCycle,
    phase: CognitivePhase,
    directive: AutonomousCognitiveDirective,
    metacognition: Optional[MetacognitionDecision],
    collective: Optional[CollectiveCognitionDecision],
) -> AutonomousCognitiveLoopDecision:
    return AutonomousCognitiveLoopDecision(
        loop_id=request.loop_id,
        phase=phase,
        directive=directive.model_copy(deep=True),
        cognitive_cycle=base_cycle.model_copy(deep=True),
        metacognition=(metacognition.model_copy(deep=True) if metacognition else None),
        collective_cognition=(collective.model_copy(deep=True) if collective else None),
    )


def derive_autonomous_cognitive_loop(
    raw_request: AutonomousCognitiveLoopRequest,
) -> AutonomousCognitiveLoopDecision:
    """Select one next semantic move while preserving canonical authority."""

    request = _canonical_request(raw_request)
    base_cycle = derive_cognitive_cycle(request.cognitive_cycle)

    # Terminal/base safety authority outranks higher-order progress routing.
    if base_cycle.phase in {CognitivePhase.BLOCKED, CognitivePhase.COMPLETE}:
        return _result(
            request=request,
            base_cycle=base_cycle,
            phase=base_cycle.phase,
            directive=_directive(
                AutonomousCognitiveDirectiveKind.FOLLOW_COGNITIVE_CYCLE,
                [base_cycle.goal.goal_id],
                "canonical terminal or blocked goal authority must be preserved",
            ),
            metacognition=None,
            collective=None,
        )

    meta_decision: Optional[MetacognitionDecision] = None
    if request.metacognition is not None:
        meta_decision = assess_metacognition(request.metacognition)
        if meta_decision.knowledge_state != KnowledgeState.SUFFICIENT:
            targets = list(meta_decision.blocking_gap_ids or meta_decision.open_gap_ids)
            if not targets:
                targets = list(
                    meta_decision.contested_claim_ids
                    or meta_decision.insufficient_claim_ids
                )
            kind = (
                AutonomousCognitiveDirectiveKind.DESIGN_EXPERIMENT
                if meta_decision.next_strategy == LearningStrategy.EXPERIMENT
                else AutonomousCognitiveDirectiveKind.REDUCE_KNOWLEDGE_GAP
            )
            return _result(
                request=request,
                base_cycle=base_cycle,
                phase=CognitivePhase.RESEARCH,
                directive=_directive(
                    kind,
                    targets,
                    "canonical metacognition requires knowledge reduction before normal cognitive progression",
                ),
                metacognition=meta_decision,
                collective=None,
            )

    collective_decision: Optional[CollectiveCognitionDecision] = None
    if request.collective_cognition is not None:
        collective_decision = synthesize_collective_cognition(
            request.collective_cognition
        )
        disposition = collective_decision.disposition
        if disposition == CollectiveCognitionDisposition.NEEDS_RESEARCH:
            return _result(
                request=request,
                base_cycle=base_cycle,
                phase=CognitivePhase.RESEARCH,
                directive=_directive(
                    AutonomousCognitiveDirectiveKind.RESEARCH_COLLECTIVE_CANDIDATE,
                    [item.candidate_id for item in collective_decision.candidate_decisions],
                    "collective cognition requires more evidence before synthesis",
                ),
                metacognition=meta_decision,
                collective=collective_decision,
            )
        if disposition == CollectiveCognitionDisposition.NEEDS_REVISION:
            return _result(
                request=request,
                base_cycle=base_cycle,
                phase=CognitivePhase.DECISION,
                directive=_directive(
                    AutonomousCognitiveDirectiveKind.REVISE_COLLECTIVE_CANDIDATE,
                    [item.candidate_id for item in collective_decision.candidate_decisions],
                    "canonical collective review requires candidate revision",
                ),
                metacognition=meta_decision,
                collective=collective_decision,
            )
        if disposition == CollectiveCognitionDisposition.NEEDS_ARBITRATION:
            targets = list(collective_decision.accepted_candidate_ids)
            if not targets:
                targets = [
                    item.candidate_id for item in collective_decision.candidate_decisions
                ]
            return _result(
                request=request,
                base_cycle=base_cycle,
                phase=CognitivePhase.DECISION,
                directive=_directive(
                    AutonomousCognitiveDirectiveKind.ARBITRATE_COLLECTIVE_CANDIDATES,
                    targets,
                    "unresolved collective alternatives require explicit arbitration rather than majority voting",
                ),
                metacognition=meta_decision,
                collective=collective_decision,
            )

    return _result(
        request=request,
        base_cycle=base_cycle,
        phase=base_cycle.phase,
        directive=_directive(
            AutonomousCognitiveDirectiveKind.FOLLOW_COGNITIVE_CYCLE,
            [directive.directive_id for directive in base_cycle.directives],
            "no higher-order unresolved semantic signal overrides the canonical cognitive cycle",
        ),
        metacognition=meta_decision,
        collective=collective_decision,
    )
