"""Evidence-authoritative temporal and causal world modelling for the five-ASI Brain.

Temporal order is not causal authority. This module composes canonical
``WorldStateSnapshot`` objects into an exact lineage, derives belief transitions,
and admits explicit causal links only when an existing causal ``LearningEpisode``
re-validates as a controlled, evidence-backed lesson candidate.

The module is semantic cognition only. It does not create evidence, execute
experiments, select tools/providers, persist state, or infer causality from
correlation/co-movement.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.evidence import ClaimEvidenceRequest, EvidenceSignal
from brain.learning import (
    LearningClaimKind,
    LearningDisposition,
    LearningEpisode,
    LearningMethod,
    analyze_learning_episode,
)
from brain.world_state import BeliefStatus, WorldBelief, WorldStateSnapshot
from schemas.base import BaseModel, Field, ValidationError


class TemporalChangeKind(str, Enum):
    """Status/evidence changes derived from adjacent canonical world states."""

    STABLE = "STABLE"
    EVIDENCE_UPDATED = "EVIDENCE_UPDATED"
    ESTABLISHED = "ESTABLISHED"
    CONTESTED = "CONTESTED"
    REFUTED = "REFUTED"
    BECAME_UNKNOWN = "BECAME_UNKNOWN"
    ADDED = "ADDED"


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


def _canonical_world_state(raw: object) -> WorldStateSnapshot:
    return WorldStateSnapshot(**_payload(raw, WorldStateSnapshot, "state"))


def _canonical_evidence_request(raw: object) -> ClaimEvidenceRequest:
    data = _payload(raw, ClaimEvidenceRequest, "evidence_request")
    raw_evidence = data.pop("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ValidationError("evidence_request evidence must be a list")
    evidence = [
        EvidenceSignal(**_payload(item, EvidenceSignal, "evidence"))
        for item in raw_evidence
    ]
    return ClaimEvidenceRequest(**data, evidence=evidence)


def _canonical_learning_episode(raw: object) -> LearningEpisode:
    if isinstance(raw, LearningEpisode):
        analyze_learning_episode(raw)
    data = _payload(raw, LearningEpisode, "learning_episode")
    evidence_request = _canonical_evidence_request(data.pop("evidence_request"))
    return LearningEpisode(**data, evidence_request=evidence_request)


def _beliefs_by_id(state: WorldStateSnapshot) -> dict[str, WorldBelief]:
    return {
        belief.proposition.proposition_id: belief
        for belief in state.beliefs
    }


class TemporalFrame(BaseModel):
    """One ordinal position in an exact canonical WorldState lineage."""

    frame_id: str
    position: int
    state: WorldStateSnapshot

    def __post_init__(self) -> None:
        super().__post_init__()
        self.frame_id = _required_text(self.frame_id, "frame_id")
        if isinstance(self.position, bool) or not isinstance(self.position, int):
            raise ValidationError("position must be an integer")
        if self.position < 0:
            raise ValidationError("position must be non-negative")
        self.state = _canonical_world_state(self.state)


class BeliefTransition(BaseModel):
    """Derived change for one proposition across two adjacent temporal frames."""

    transition_id: str
    proposition_id: str
    from_snapshot_id: str
    to_snapshot_id: str
    from_status: Optional[BeliefStatus]
    to_status: BeliefStatus
    change_kind: TemporalChangeKind
    new_supporting_evidence_refs: List[str] = Field(default_factory=list)
    new_contradicting_evidence_refs: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.transition_id = _required_text(self.transition_id, "transition_id")
        self.proposition_id = _required_text(self.proposition_id, "proposition_id")
        self.from_snapshot_id = _required_text(
            self.from_snapshot_id, "from_snapshot_id"
        )
        self.to_snapshot_id = _required_text(self.to_snapshot_id, "to_snapshot_id")
        if self.from_snapshot_id == self.to_snapshot_id:
            raise ValidationError("transition snapshots must be different")
        if self.from_status is not None:
            self.from_status = _enum(self.from_status, BeliefStatus, "from_status")
        self.to_status = _enum(self.to_status, BeliefStatus, "to_status")
        self.change_kind = _enum(
            self.change_kind, TemporalChangeKind, "change_kind"
        )
        self.new_supporting_evidence_refs = _unique_text_list(
            self.new_supporting_evidence_refs,
            "new_supporting_evidence_refs",
        )
        self.new_contradicting_evidence_refs = _unique_text_list(
            self.new_contradicting_evidence_refs,
            "new_contradicting_evidence_refs",
        )
        if self.from_status is None and self.change_kind != TemporalChangeKind.ADDED:
            raise ValidationError("new proposition transition must use ADDED change_kind")


class CausalRelationSpec(BaseModel):
    """Explicit proposed cause/effect binding backed by one LearningEpisode."""

    causal_link_id: str
    cause_proposition_id: str
    effect_proposition_id: str
    learning_episode: LearningEpisode

    def __post_init__(self) -> None:
        super().__post_init__()
        self.causal_link_id = _required_text(self.causal_link_id, "causal_link_id")
        self.cause_proposition_id = _required_text(
            self.cause_proposition_id, "cause_proposition_id"
        )
        self.effect_proposition_id = _required_text(
            self.effect_proposition_id, "effect_proposition_id"
        )
        if self.cause_proposition_id == self.effect_proposition_id:
            raise ValidationError("causal link endpoints must be different propositions")
        self.learning_episode = _canonical_learning_episode(self.learning_episode)


class CausalLink(BaseModel):
    """Self-validating causal world-model edge with controlled-learning provenance."""

    causal_link_id: str
    cause_proposition_id: str
    effect_proposition_id: str
    hypothesis_id: str
    learning_episode: LearningEpisode
    lesson_candidate: str
    evidence_refs: List[str] = Field(default_factory=list)
    intervention_id: str = ""
    control_ref: str = ""
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.causal_link_id = _required_text(self.causal_link_id, "causal_link_id")
        self.cause_proposition_id = _required_text(
            self.cause_proposition_id, "cause_proposition_id"
        )
        self.effect_proposition_id = _required_text(
            self.effect_proposition_id, "effect_proposition_id"
        )
        if self.cause_proposition_id == self.effect_proposition_id:
            raise ValidationError("causal link endpoints must be different propositions")
        self.hypothesis_id = _required_text(self.hypothesis_id, "hypothesis_id")
        self.learning_episode = _canonical_learning_episode(self.learning_episode)
        self.lesson_candidate = _required_text(
            self.lesson_candidate, "lesson_candidate"
        )
        self.evidence_refs = _unique_text_list(self.evidence_refs, "evidence_refs")
        self.intervention_id = _required_text(self.intervention_id, "intervention_id")
        self.control_ref = _required_text(self.control_ref, "control_ref")
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one causal-link reason")

        episode = self.learning_episode
        if episode.claim_kind != LearningClaimKind.CAUSAL:
            raise ValidationError("causal link requires a CAUSAL learning episode")
        if episode.method != LearningMethod.EXPERIMENT:
            raise ValidationError("causal link requires an EXPERIMENT learning episode")
        if self.hypothesis_id != episode.hypothesis_id:
            raise ValidationError("hypothesis_id must match causal learning episode")
        if self.cause_proposition_id not in episode.context_refs:
            raise ValidationError("causal episode must bind cause proposition in context_refs")
        if self.effect_proposition_id not in episode.context_refs:
            raise ValidationError("causal episode must bind effect proposition in context_refs")

        decision = analyze_learning_episode(episode)
        if decision.disposition != LearningDisposition.CANDIDATE_LESSON:
            raise ValidationError(
                "causal link requires an evidence-backed controlled candidate lesson"
            )
        if decision.lesson_candidate != self.lesson_candidate:
            raise ValidationError("lesson_candidate must match canonical learning decision")
        if decision.evidence_refs != self.evidence_refs:
            raise ValidationError("evidence_refs must match canonical learning decision")
        if episode.intervention_id != self.intervention_id:
            raise ValidationError("intervention_id must match canonical learning episode")
        if episode.control_ref != self.control_ref:
            raise ValidationError("control_ref must match canonical learning episode")


def _canonical_frames(raw_items: object) -> List[TemporalFrame]:
    if not isinstance(raw_items, list) or len(raw_items) < 2:
        raise ValidationError("frames must contain at least two temporal frames")
    return [
        TemporalFrame(**_payload(raw, TemporalFrame, "frames"))
        for raw in raw_items
    ]


def _canonical_causal_specs(raw_items: object) -> List[CausalRelationSpec]:
    if not isinstance(raw_items, list):
        raise ValidationError("causal_specs must be a list")
    return [
        CausalRelationSpec(**_payload(raw, CausalRelationSpec, "causal_specs"))
        for raw in raw_items
    ]


def _canonical_transitions(raw_items: object) -> List[BeliefTransition]:
    if not isinstance(raw_items, list):
        raise ValidationError("transitions must be a list")
    return [
        BeliefTransition(**_payload(raw, BeliefTransition, "transitions"))
        for raw in raw_items
    ]


def _canonical_causal_links(raw_items: object) -> List[CausalLink]:
    if not isinstance(raw_items, list):
        raise ValidationError("causal_links must be a list")
    return [
        CausalLink(**_payload(raw, CausalLink, "causal_links"))
        for raw in raw_items
    ]


def _validate_frame_lineage(
    frames: List[TemporalFrame],
    *,
    goal_id: str,
    agent_id: BrainAgentId,
) -> None:
    frame_ids = set()
    snapshot_ids = set()
    previous_position: Optional[int] = None
    previous_frame: Optional[TemporalFrame] = None

    for frame in frames:
        if frame.frame_id in frame_ids:
            raise ValidationError(f"duplicate frame_id: {frame.frame_id}")
        frame_ids.add(frame.frame_id)
        if frame.state.snapshot_id in snapshot_ids:
            raise ValidationError(
                f"duplicate temporal snapshot_id: {frame.state.snapshot_id}"
            )
        snapshot_ids.add(frame.state.snapshot_id)
        if frame.state.goal_id != goal_id:
            raise ValidationError("temporal frame goal_id must match model goal_id")
        if frame.state.agent_id != agent_id:
            raise ValidationError("temporal frame agent_id must match model agent_id")
        if previous_position is not None and frame.position <= previous_position:
            raise ValidationError("temporal frame positions must strictly increase")

        if previous_frame is not None:
            if frame.state.previous_snapshot_id != previous_frame.state.snapshot_id:
                raise ValidationError(
                    "temporal frames must form an exact WorldState snapshot lineage"
                )
            previous_beliefs = _beliefs_by_id(previous_frame.state)
            current_beliefs = _beliefs_by_id(frame.state)
            for proposition_id, previous_belief in previous_beliefs.items():
                current_belief = current_beliefs.get(proposition_id)
                if current_belief is None:
                    raise ValidationError(
                        "proposition cannot disappear across temporal lineage: "
                        f"{proposition_id}"
                    )
                if (
                    current_belief.proposition.model_dump()
                    != previous_belief.proposition.model_dump()
                ):
                    raise ValidationError(
                        "proposition identity cannot be rebound across temporal lineage: "
                        f"{proposition_id}"
                    )
                previous_revisions = [
                    item.model_dump() for item in previous_belief.revisions
                ]
                current_revisions = [
                    item.model_dump() for item in current_belief.revisions
                ]
                if current_revisions[: len(previous_revisions)] != previous_revisions:
                    raise ValidationError(
                        "belief revision history must be append-only across temporal lineage: "
                        f"{proposition_id}"
                    )

        previous_position = frame.position
        previous_frame = frame


def _change_kind(
    previous: Optional[WorldBelief],
    current: WorldBelief,
    *,
    new_support: List[str],
    new_contradict: List[str],
) -> TemporalChangeKind:
    if previous is None:
        return TemporalChangeKind.ADDED
    if current.status != previous.status:
        return {
            BeliefStatus.ESTABLISHED: TemporalChangeKind.ESTABLISHED,
            BeliefStatus.CONTESTED: TemporalChangeKind.CONTESTED,
            BeliefStatus.REFUTED: TemporalChangeKind.REFUTED,
            BeliefStatus.UNKNOWN: TemporalChangeKind.BECAME_UNKNOWN,
        }[current.status]
    if new_support or new_contradict:
        return TemporalChangeKind.EVIDENCE_UPDATED
    return TemporalChangeKind.STABLE


def _derive_transitions(frames: List[TemporalFrame]) -> List[BeliefTransition]:
    transitions: List[BeliefTransition] = []
    for previous_frame, current_frame in zip(frames, frames[1:]):
        previous_by_id = _beliefs_by_id(previous_frame.state)
        for current in current_frame.state.beliefs:
            proposition_id = current.proposition.proposition_id
            previous = previous_by_id.get(proposition_id)
            previous_support = (
                previous.supporting_evidence_refs if previous is not None else []
            )
            previous_contradict = (
                previous.contradicting_evidence_refs if previous is not None else []
            )
            new_support = [
                ref
                for ref in current.supporting_evidence_refs
                if ref not in previous_support
            ]
            new_contradict = [
                ref
                for ref in current.contradicting_evidence_refs
                if ref not in previous_contradict
            ]
            transitions.append(
                BeliefTransition(
                    transition_id=(
                        f"{previous_frame.state.snapshot_id}->"
                        f"{current_frame.state.snapshot_id}:{proposition_id}"
                    ),
                    proposition_id=proposition_id,
                    from_snapshot_id=previous_frame.state.snapshot_id,
                    to_snapshot_id=current_frame.state.snapshot_id,
                    from_status=previous.status if previous is not None else None,
                    to_status=current.status,
                    change_kind=_change_kind(
                        previous,
                        current,
                        new_support=new_support,
                        new_contradict=new_contradict,
                    ),
                    new_supporting_evidence_refs=new_support,
                    new_contradicting_evidence_refs=new_contradict,
                )
            )
    return transitions


class TemporalCausalWorldModelRequest(BaseModel):
    """Authority-bearing request for a temporal/causal semantic world model."""

    model_id: str
    goal_id: str
    agent_id: BrainAgentId
    frames: List[TemporalFrame] = Field(default_factory=list)
    causal_specs: List[CausalRelationSpec] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.model_id = _required_text(self.model_id, "model_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.frames = _canonical_frames(self.frames)
        self.causal_specs = _canonical_causal_specs(self.causal_specs)
        _validate_frame_lineage(
            self.frames,
            goal_id=self.goal_id,
            agent_id=self.agent_id,
        )

        causal_ids = set()
        hypothesis_ids = set()
        for spec in self.causal_specs:
            if spec.causal_link_id in causal_ids:
                raise ValidationError(
                    f"duplicate causal_link_id: {spec.causal_link_id}"
                )
            causal_ids.add(spec.causal_link_id)
            hypothesis_id = spec.learning_episode.hypothesis_id
            if hypothesis_id in hypothesis_ids:
                raise ValidationError(
                    f"duplicate causal hypothesis binding: {hypothesis_id}"
                )
            hypothesis_ids.add(hypothesis_id)

        self._semantic_snapshot = copy.deepcopy(self.model_dump())


class TemporalCausalWorldModel(BaseModel):
    """Derived temporal transitions plus explicitly proven causal links."""

    model_id: str
    goal_id: str
    agent_id: BrainAgentId
    frames: List[TemporalFrame] = Field(default_factory=list)
    transitions: List[BeliefTransition] = Field(default_factory=list)
    causal_links: List[CausalLink] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.model_id = _required_text(self.model_id, "model_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.frames = _canonical_frames(self.frames)
        self.transitions = _canonical_transitions(self.transitions)
        self.causal_links = _canonical_causal_links(self.causal_links)
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one world-model reason")
        _validate_frame_lineage(
            self.frames,
            goal_id=self.goal_id,
            agent_id=self.agent_id,
        )

        expected_transitions = _derive_transitions(self.frames)
        if [item.model_dump() for item in self.transitions] != [
            item.model_dump() for item in expected_transitions
        ]:
            raise ValidationError(
                "transitions must be derived exactly from canonical temporal frames"
            )

        latest_beliefs = _beliefs_by_id(self.frames[-1].state)
        causal_ids = set()
        hypothesis_ids = set()
        for link in self.causal_links:
            if link.causal_link_id in causal_ids:
                raise ValidationError(
                    f"duplicate causal_link_id: {link.causal_link_id}"
                )
            causal_ids.add(link.causal_link_id)
            if link.hypothesis_id in hypothesis_ids:
                raise ValidationError(
                    f"duplicate causal hypothesis binding: {link.hypothesis_id}"
                )
            hypothesis_ids.add(link.hypothesis_id)
            if link.learning_episode.goal_id != self.goal_id:
                raise ValidationError("causal learning goal_id must match model goal_id")
            if link.learning_episode.agent_id != self.agent_id:
                raise ValidationError("causal learning agent_id must match model agent_id")
            if link.cause_proposition_id not in latest_beliefs:
                raise ValidationError("causal cause endpoint must exist in latest world state")
            if link.effect_proposition_id not in latest_beliefs:
                raise ValidationError("causal effect endpoint must exist in latest world state")


def _canonical_request(
    request: TemporalCausalWorldModelRequest,
) -> TemporalCausalWorldModelRequest:
    if not isinstance(request, TemporalCausalWorldModelRequest):
        raise ValidationError("request must be a TemporalCausalWorldModelRequest")
    original_snapshot = getattr(request, "_semantic_snapshot", None)
    current_snapshot = copy.deepcopy(request.model_dump())
    if original_snapshot is None or current_snapshot != original_snapshot:
        raise ValidationError(
            "temporal causal world-model request changed after validation"
        )
    return TemporalCausalWorldModelRequest(**current_snapshot)


def _build_causal_link(
    spec: CausalRelationSpec,
    *,
    goal_id: str,
    agent_id: BrainAgentId,
    latest_beliefs: dict[str, WorldBelief],
) -> CausalLink:
    episode = _canonical_learning_episode(spec.learning_episode)
    if episode.goal_id != goal_id:
        raise ValidationError("causal learning goal_id must match model goal_id")
    if episode.agent_id != agent_id:
        raise ValidationError("causal learning agent_id must match model agent_id")
    if spec.cause_proposition_id not in latest_beliefs:
        raise ValidationError("causal cause endpoint must exist in latest world state")
    if spec.effect_proposition_id not in latest_beliefs:
        raise ValidationError("causal effect endpoint must exist in latest world state")
    if episode.claim_kind != LearningClaimKind.CAUSAL:
        raise ValidationError("causal link requires a CAUSAL learning episode")
    if episode.method != LearningMethod.EXPERIMENT:
        raise ValidationError("causal link requires a controlled EXPERIMENT")
    if spec.cause_proposition_id not in episode.context_refs:
        raise ValidationError("causal episode must explicitly bind the cause proposition")
    if spec.effect_proposition_id not in episode.context_refs:
        raise ValidationError("causal episode must explicitly bind the effect proposition")

    decision = analyze_learning_episode(episode)
    if decision.disposition != LearningDisposition.CANDIDATE_LESSON:
        raise ValidationError(
            "causal link requires a controlled evidence-backed candidate lesson"
        )
    if not decision.evidence_refs:
        raise ValidationError("causal link requires explicit canonical evidence refs")
    if episode.intervention_id is None or episode.control_ref is None:
        raise ValidationError("causal link requires intervention and control provenance")

    return CausalLink(
        causal_link_id=spec.causal_link_id,
        cause_proposition_id=spec.cause_proposition_id,
        effect_proposition_id=spec.effect_proposition_id,
        hypothesis_id=episode.hypothesis_id,
        learning_episode=episode,
        lesson_candidate=decision.lesson_candidate or "",
        evidence_refs=decision.evidence_refs,
        intervention_id=episode.intervention_id,
        control_ref=episode.control_ref,
        reasons=[
            "causal authority comes only from a controlled evidence-backed learning episode",
            "temporal co-movement alone is never treated as causal evidence",
        ],
    )


def build_temporal_causal_world_model(
    request: TemporalCausalWorldModelRequest,
) -> TemporalCausalWorldModel:
    """Build a defensive temporal/causal semantic world model."""

    request = _canonical_request(request)
    transitions = _derive_transitions(request.frames)
    latest_beliefs = _beliefs_by_id(request.frames[-1].state)
    causal_links = [
        _build_causal_link(
            spec,
            goal_id=request.goal_id,
            agent_id=request.agent_id,
            latest_beliefs=latest_beliefs,
        )
        for spec in request.causal_specs
    ]

    return TemporalCausalWorldModel(
        model_id=request.model_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        frames=request.frames,
        transitions=transitions,
        causal_links=causal_links,
        reasons=[
            "temporal transitions are derived from exact canonical WorldState lineage",
            "causality is admitted only through controlled evidence-backed learning provenance",
            "coincident belief changes never manufacture causal authority",
        ],
    )
