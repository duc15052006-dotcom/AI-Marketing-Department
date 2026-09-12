"""Canonical semantic Knowledge Graph projection for the Brain layer.

The graph does not decide what is true. ``WorldStateSnapshot`` remains the
canonical epistemic authority for proposition scope, belief status, evidence
references, and revision history.  This module only binds caller-supplied
entity/relation structure to those canonical propositions and copies their
provenance into immutable-by-convention graph views.

No provider, tool, runtime, connector, database, scheduler, or persistence
mechanic belongs here.
"""

from __future__ import annotations

import copy
import re
from typing import Dict, List, Set

from brain.contracts import BrainAgentId
from brain.world_state import BeliefStatus, WorldBelief, WorldStateSnapshot
from schemas.base import BaseModel, Field, ValidationError


_SEMANTIC_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _text_list(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of strings")
    result: List[str] = []
    seen: Set[str] = set()
    for raw in value:
        item = _required_text(raw, field_name)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _semantic_token(value: object, field_name: str) -> str:
    token = _required_text(value, field_name).upper()
    if not _SEMANTIC_TOKEN_RE.fullmatch(token):
        raise ValidationError(
            f"{field_name} must be a semantic UPPER_SNAKE_CASE identifier"
        )
    return token


def _agent_id(value: object) -> BrainAgentId:
    if isinstance(value, BrainAgentId):
        return value
    if isinstance(value, str):
        try:
            return BrainAgentId(value.strip().upper())
        except ValueError:
            pass
    raise ValidationError(
        "agent_id must be one of the five permanent BrainAgentId values"
    )


def _belief_status(value: object) -> BeliefStatus:
    if isinstance(value, BeliefStatus):
        return value
    if isinstance(value, str):
        try:
            return BeliefStatus(value.strip().upper())
        except ValueError:
            pass
    raise ValidationError(
        "belief_status must be one of: "
        + ", ".join(status.value for status in BeliefStatus)
    )


class KnowledgeEntity(BaseModel):
    """One provider-neutral semantic entity in a knowledge projection."""

    entity_id: str
    entity_type: str
    label: str
    aliases: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.entity_id = _required_text(self.entity_id, "entity_id")
        self.entity_type = _semantic_token(self.entity_type, "entity_type")
        self.label = _required_text(self.label, "label")
        self.aliases = _text_list(self.aliases, "aliases")


class KnowledgeRelationSpec(BaseModel):
    """Structural relation explicitly anchored to a canonical proposition.

    It deliberately contains no truth/confidence/evidence fields. Those are
    copied only from the referenced ``WorldBelief`` by ``build_knowledge_graph``.
    """

    relation_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    proposition_id: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.relation_id = _required_text(self.relation_id, "relation_id")
        self.subject_entity_id = _required_text(
            self.subject_entity_id, "subject_entity_id"
        )
        self.predicate = _semantic_token(self.predicate, "predicate")
        self.object_entity_id = _required_text(
            self.object_entity_id, "object_entity_id"
        )
        self.proposition_id = _required_text(self.proposition_id, "proposition_id")


class KnowledgeRelationView(BaseModel):
    """Canonical relation plus epistemic/provenance data copied from World-State."""

    relation_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    proposition_id: str
    goal_id: str
    agent_id: BrainAgentId
    statement: str
    belief_status: BeliefStatus
    supporting_evidence_refs: List[str] = Field(default_factory=list)
    contradicting_evidence_refs: List[str] = Field(default_factory=list)
    ignored_evidence_refs: List[str] = Field(default_factory=list)
    revision_ids: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.relation_id = _required_text(self.relation_id, "relation_id")
        self.subject_entity_id = _required_text(
            self.subject_entity_id, "subject_entity_id"
        )
        self.predicate = _semantic_token(self.predicate, "predicate")
        self.object_entity_id = _required_text(
            self.object_entity_id, "object_entity_id"
        )
        self.proposition_id = _required_text(self.proposition_id, "proposition_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _agent_id(self.agent_id)
        self.statement = _required_text(self.statement, "statement")
        self.belief_status = _belief_status(self.belief_status)
        self.supporting_evidence_refs = _text_list(
            self.supporting_evidence_refs, "supporting_evidence_refs"
        )
        self.contradicting_evidence_refs = _text_list(
            self.contradicting_evidence_refs, "contradicting_evidence_refs"
        )
        self.ignored_evidence_refs = _text_list(
            self.ignored_evidence_refs, "ignored_evidence_refs"
        )
        self.revision_ids = _text_list(self.revision_ids, "revision_ids")


class KnowledgeGraphRequest(BaseModel):
    """Caller-owned structural request awaiting use-boundary canonicalization.

    Nested values are intentionally not trusted merely because this mutable
    request object was constructed successfully. ``build_knowledge_graph``
    reconstructs every nested source/entity/relation at the use boundary.
    """

    graph_id: str
    goal_id: str
    world_states: List[WorldStateSnapshot] = Field(default_factory=list)
    entities: List[KnowledgeEntity] = Field(default_factory=list)
    relations: List[KnowledgeRelationSpec] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.graph_id = _required_text(self.graph_id, "graph_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        for field_name in ("world_states", "entities", "relations"):
            value = getattr(self, field_name)
            if not isinstance(value, list):
                raise ValidationError(f"{field_name} must be a list")
            setattr(self, field_name, copy.deepcopy(value))


class KnowledgeGraphSnapshot(BaseModel):
    """Validated semantic projection over one goal's canonical World-State."""

    graph_id: str
    goal_id: str
    source_snapshot_ids: List[str] = Field(default_factory=list)
    contributing_agents: List[BrainAgentId] = Field(default_factory=list)
    entities: List[KnowledgeEntity] = Field(default_factory=list)
    relations: List[KnowledgeRelationView] = Field(default_factory=list)
    unmapped_proposition_ids: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.graph_id = _required_text(self.graph_id, "graph_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.source_snapshot_ids = _text_list(
            self.source_snapshot_ids, "source_snapshot_ids"
        )
        if not isinstance(self.contributing_agents, list):
            raise ValidationError("contributing_agents must be a list")
        agents: List[BrainAgentId] = []
        seen_agents: Set[BrainAgentId] = set()
        for raw in self.contributing_agents:
            agent = _agent_id(raw)
            if agent not in seen_agents:
                seen_agents.add(agent)
                agents.append(agent)
        self.contributing_agents = agents
        self.entities = _canonical_entities(self.entities)
        self.relations = _canonical_relation_views(self.relations)
        self.unmapped_proposition_ids = _text_list(
            self.unmapped_proposition_ids, "unmapped_proposition_ids"
        )


def _canonical_world_states(raw_values: object) -> List[WorldStateSnapshot]:
    if not isinstance(raw_values, list):
        raise ValidationError("world_states must be a list")
    result: List[WorldStateSnapshot] = []
    for raw in raw_values:
        if isinstance(raw, WorldStateSnapshot):
            payload = raw.model_dump()
        elif isinstance(raw, dict):
            payload = copy.deepcopy(raw)
        else:
            raise ValidationError(
                "world_states must contain WorldStateSnapshot objects or dictionaries"
            )
        result.append(WorldStateSnapshot(**payload))
    return result


def _canonical_entities(raw_values: object) -> List[KnowledgeEntity]:
    if not isinstance(raw_values, list):
        raise ValidationError("entities must be a list")
    result: List[KnowledgeEntity] = []
    for raw in raw_values:
        if isinstance(raw, KnowledgeEntity):
            payload = raw.model_dump()
        elif isinstance(raw, dict):
            payload = copy.deepcopy(raw)
        else:
            raise ValidationError(
                "entities must contain KnowledgeEntity objects or dictionaries"
            )
        result.append(KnowledgeEntity(**payload))
    return result


def _canonical_relations(raw_values: object) -> List[KnowledgeRelationSpec]:
    if not isinstance(raw_values, list):
        raise ValidationError("relations must be a list")
    result: List[KnowledgeRelationSpec] = []
    for raw in raw_values:
        if isinstance(raw, KnowledgeRelationSpec):
            payload = raw.model_dump()
        elif isinstance(raw, dict):
            payload = copy.deepcopy(raw)
        else:
            raise ValidationError(
                "relations must contain KnowledgeRelationSpec objects or dictionaries"
            )
        result.append(KnowledgeRelationSpec(**payload))
    return result


def _canonical_relation_views(raw_values: object) -> List[KnowledgeRelationView]:
    if not isinstance(raw_values, list):
        raise ValidationError("relations must be a list")
    result: List[KnowledgeRelationView] = []
    for raw in raw_values:
        if isinstance(raw, KnowledgeRelationView):
            payload = raw.model_dump()
        elif isinstance(raw, dict):
            payload = copy.deepcopy(raw)
        else:
            raise ValidationError(
                "relations must contain KnowledgeRelationView objects or dictionaries"
            )
        result.append(KnowledgeRelationView(**payload))
    return result


def _canonical_request(
    request: KnowledgeGraphRequest | dict,
) -> tuple[KnowledgeGraphRequest, List[WorldStateSnapshot], List[KnowledgeEntity], List[KnowledgeRelationSpec]]:
    if isinstance(request, KnowledgeGraphRequest):
        payload = request.model_dump()
    elif isinstance(request, dict):
        payload = copy.deepcopy(request)
    else:
        raise ValidationError("request must be a KnowledgeGraphRequest or dictionary")

    top = KnowledgeGraphRequest(**payload)
    world_states = _canonical_world_states(top.world_states)
    entities = _canonical_entities(top.entities)
    relations = _canonical_relations(top.relations)
    return top, world_states, entities, relations


def build_knowledge_graph(
    request: KnowledgeGraphRequest | dict,
) -> KnowledgeGraphSnapshot:
    """Build a semantic graph without inventing or upgrading epistemic truth."""

    canonical, world_states, entities, relations = _canonical_request(request)

    if not world_states:
        raise ValidationError("Knowledge Graph requires at least one World-State source")

    snapshot_ids: Set[str] = set()
    source_snapshot_ids: List[str] = []
    contributing_agents: List[BrainAgentId] = []
    contributing_agent_set: Set[BrainAgentId] = set()
    beliefs_by_proposition: Dict[str, WorldBelief] = {}
    proposition_order: List[str] = []

    for snapshot in world_states:
        if snapshot.goal_id != canonical.goal_id:
            raise ValidationError(
                f"World-State snapshot '{snapshot.snapshot_id}' goal_id must match graph goal_id"
            )
        if snapshot.snapshot_id in snapshot_ids:
            raise ValidationError(f"duplicate World-State snapshot id: {snapshot.snapshot_id}")
        snapshot_ids.add(snapshot.snapshot_id)
        source_snapshot_ids.append(snapshot.snapshot_id)

        if snapshot.agent_id not in contributing_agent_set:
            contributing_agent_set.add(snapshot.agent_id)
            contributing_agents.append(snapshot.agent_id)

        for belief in snapshot.beliefs:
            proposition_id = belief.proposition.proposition_id
            if proposition_id in beliefs_by_proposition:
                raise ValidationError(
                    f"duplicate canonical proposition id across World-State sources: {proposition_id}"
                )
            beliefs_by_proposition[proposition_id] = belief.model_copy(deep=True)
            proposition_order.append(proposition_id)

    entities_by_id: Dict[str, KnowledgeEntity] = {}
    for entity in entities:
        if entity.entity_id in entities_by_id:
            raise ValidationError(f"duplicate Knowledge Entity id: {entity.entity_id}")
        entities_by_id[entity.entity_id] = entity

    relation_ids: Set[str] = set()
    relation_views: List[KnowledgeRelationView] = []
    mapped_propositions: Set[str] = set()

    for relation in relations:
        if relation.relation_id in relation_ids:
            raise ValidationError(
                f"duplicate Knowledge Relation id: {relation.relation_id}"
            )
        relation_ids.add(relation.relation_id)

        if relation.subject_entity_id not in entities_by_id:
            raise ValidationError(
                f"relation '{relation.relation_id}' references unknown subject entity "
                f"'{relation.subject_entity_id}'"
            )
        if relation.object_entity_id not in entities_by_id:
            raise ValidationError(
                f"relation '{relation.relation_id}' references unknown object entity "
                f"'{relation.object_entity_id}'"
            )

        belief = beliefs_by_proposition.get(relation.proposition_id)
        if belief is None:
            raise ValidationError(
                f"relation '{relation.relation_id}' references unknown canonical proposition "
                f"'{relation.proposition_id}'"
            )

        mapped_propositions.add(relation.proposition_id)
        relation_views.append(
            KnowledgeRelationView(
                relation_id=relation.relation_id,
                subject_entity_id=relation.subject_entity_id,
                predicate=relation.predicate,
                object_entity_id=relation.object_entity_id,
                proposition_id=belief.proposition.proposition_id,
                goal_id=belief.proposition.goal_id,
                agent_id=belief.proposition.agent_id,
                statement=belief.proposition.statement,
                belief_status=belief.status,
                supporting_evidence_refs=list(belief.supporting_evidence_refs),
                contradicting_evidence_refs=list(belief.contradicting_evidence_refs),
                ignored_evidence_refs=list(belief.ignored_evidence_refs),
                revision_ids=[revision.revision_id for revision in belief.revisions],
            )
        )

    unmapped = [
        proposition_id
        for proposition_id in proposition_order
        if proposition_id not in mapped_propositions
    ]

    return KnowledgeGraphSnapshot(
        graph_id=canonical.graph_id,
        goal_id=canonical.goal_id,
        source_snapshot_ids=source_snapshot_ids,
        contributing_agents=contributing_agents,
        entities=[entity.model_copy(deep=True) for entity in entities],
        relations=relation_views,
        unmapped_proposition_ids=unmapped,
    )
