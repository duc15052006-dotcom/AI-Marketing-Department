from __future__ import annotations

import inspect
import unittest

import brain
from brain.contracts import BrainAgentId
from brain.evidence import ClaimEvidenceAssessment, ClaimVerdict
from brain.world_state import (
    BeliefRevision,
    BeliefStatus,
    WorldBelief,
    WorldProposition,
    WorldStateSnapshot,
)
from schemas.base import ValidationError

try:
    import brain.knowledge_graph as knowledge_graph_module
    from brain.knowledge_graph import (
        KnowledgeEntity,
        KnowledgeGraphRequest,
        KnowledgeGraphSnapshot,
        KnowledgeRelationSpec,
        KnowledgeRelationView,
        build_knowledge_graph,
    )

    KNOWLEDGE_GRAPH_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability does not exist yet.
    KNOWLEDGE_GRAPH_IMPORT_ERROR = exc


class BrainKnowledgeGraphV1Tests(unittest.TestCase):
    GOAL_ID = "goal-growth"

    def _require_capability(self) -> None:
        if KNOWLEDGE_GRAPH_IMPORT_ERROR is not None:
            self.fail(
                "KNOWLEDGE_GRAPH_CAPABILITY_MISSING: "
                f"{KNOWLEDGE_GRAPH_IMPORT_ERROR}"
            )

    def _assessment(
        self,
        proposition_id: str,
        *,
        agent_id: BrainAgentId,
        status: BeliefStatus,
    ) -> ClaimEvidenceAssessment | None:
        if status == BeliefStatus.UNKNOWN:
            return None
        verdict_by_status = {
            BeliefStatus.ESTABLISHED: ClaimVerdict.SUPPORTED,
            BeliefStatus.CONTESTED: ClaimVerdict.CONTESTED,
            BeliefStatus.REFUTED: ClaimVerdict.REFUTED,
        }
        support = []
        contradict = []
        if status in (BeliefStatus.ESTABLISHED, BeliefStatus.CONTESTED):
            support = [f"ev-support-{proposition_id}"]
        if status in (BeliefStatus.CONTESTED, BeliefStatus.REFUTED):
            contradict = [f"ev-contradict-{proposition_id}"]
        return ClaimEvidenceAssessment(
            assessment_id=f"assessment-{proposition_id}",
            goal_id=self.GOAL_ID,
            claim_id=proposition_id,
            agent_id=agent_id,
            verdict=verdict_by_status[status],
            supporting_evidence_refs=support,
            contradicting_evidence_refs=contradict,
            ignored_evidence_refs=[],
            reasons=["canonical evidence assessment"],
        )

    def _belief(
        self,
        proposition_id: str,
        *,
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
        statement: str | None = None,
        status: BeliefStatus = BeliefStatus.ESTABLISHED,
        revision_id: str | None = None,
    ) -> WorldBelief:
        proposition = WorldProposition(
            proposition_id=proposition_id,
            goal_id=self.GOAL_ID,
            agent_id=agent_id,
            statement=statement or f"Canonical statement for {proposition_id}",
        )
        assessment = self._assessment(
            proposition_id,
            agent_id=agent_id,
            status=status,
        )
        support = [] if assessment is None else assessment.supporting_evidence_refs
        contradict = [] if assessment is None else assessment.contradicting_evidence_refs
        ignored = [] if assessment is None else assessment.ignored_evidence_refs
        revision = BeliefRevision(
            revision_id=revision_id or f"revision-{proposition_id}",
            snapshot_id=f"snapshot-{agent_id.value.lower()}",
            status=status,
            assessment=assessment,
            reasons=["canonical world-state revision"],
        )
        return WorldBelief(
            proposition=proposition,
            status=status,
            supporting_evidence_refs=list(support),
            contradicting_evidence_refs=list(contradict),
            ignored_evidence_refs=list(ignored),
            revisions=[revision],
        )

    def _snapshot(
        self,
        snapshot_id: str = "snapshot-intelligence",
        *,
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
        beliefs: list[WorldBelief] | None = None,
        goal_id: str | None = None,
    ) -> WorldStateSnapshot:
        canonical_beliefs = beliefs or [
            self._belief(
                "prop-product-category",
                agent_id=agent_id,
                statement="Product belongs to the SMART_CHARGER category",
            ),
            self._belief(
                "prop-market-demand",
                agent_id=agent_id,
                statement="SMART_CHARGER demand is increasing",
                status=BeliefStatus.CONTESTED,
            ),
        ]
        return WorldStateSnapshot(
            snapshot_id=snapshot_id,
            goal_id=goal_id or self.GOAL_ID,
            agent_id=agent_id,
            beliefs=canonical_beliefs,
            reasons=["canonical world-state snapshot"],
        )

    def _entity(
        self,
        entity_id: str,
        *,
        entity_type: str = "CONCEPT",
        label: str | None = None,
        aliases: list[str] | None = None,
    ):
        self._require_capability()
        return KnowledgeEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            label=label or entity_id.replace("-", " ").title(),
            aliases=aliases or [],
        )

    def _relation(
        self,
        relation_id: str = "rel-product-category",
        *,
        subject: str = "entity-product",
        predicate: str = "BELONGS_TO",
        object_: str = "entity-category",
        proposition_id: str = "prop-product-category",
    ):
        self._require_capability()
        return KnowledgeRelationSpec(
            relation_id=relation_id,
            subject_entity_id=subject,
            predicate=predicate,
            object_entity_id=object_,
            proposition_id=proposition_id,
        )

    def _request(
        self,
        *,
        world_states=None,
        entities=None,
        relations=None,
        goal_id: str | None = None,
    ):
        self._require_capability()
        if world_states is None:
            world_states = [self._snapshot()]
        if entities is None:
            entities = [
                self._entity("entity-product", entity_type="PRODUCT"),
                self._entity("entity-category", entity_type="CATEGORY"),
                self._entity("entity-market", entity_type="MARKET"),
            ]
        if relations is None:
            relations = [self._relation()]
        return KnowledgeGraphRequest(
            graph_id="graph-growth",
            goal_id=goal_id or self.GOAL_ID,
            world_states=world_states,
            entities=entities,
            relations=relations,
        )

    def test_valid_graph_is_canonical_projection_of_world_state(self) -> None:
        self._require_capability()
        graph = build_knowledge_graph(self._request())
        self.assertIsInstance(graph, KnowledgeGraphSnapshot)
        self.assertEqual(graph.graph_id, "graph-growth")
        self.assertEqual(graph.goal_id, self.GOAL_ID)
        self.assertEqual(graph.source_snapshot_ids, ["snapshot-intelligence"])
        self.assertEqual(graph.contributing_agents, [BrainAgentId.INTELLIGENCE])
        self.assertEqual(len(graph.relations), 1)
        relation = graph.relations[0]
        self.assertIsInstance(relation, KnowledgeRelationView)
        self.assertEqual(relation.proposition_id, "prop-product-category")
        self.assertEqual(relation.belief_status, BeliefStatus.ESTABLISHED)

    def test_public_brain_api_exports_knowledge_graph_capability(self) -> None:
        self._require_capability()
        for name in (
            "KnowledgeEntity",
            "KnowledgeGraphRequest",
            "KnowledgeGraphSnapshot",
            "KnowledgeRelationSpec",
            "KnowledgeRelationView",
            "build_knowledge_graph",
        ):
            self.assertTrue(hasattr(brain, name), name)

    def test_requires_at_least_one_world_state(self) -> None:
        self._require_capability()
        request = self._request(world_states=[])
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_world_state_goal_must_match_graph_goal(self) -> None:
        self._require_capability()
        snapshot = self._snapshot()
        snapshot.goal_id = "goal-other-after-construction"
        request = self._request(world_states=[snapshot])
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_duplicate_snapshot_ids_fail_closed(self) -> None:
        self._require_capability()
        first = self._snapshot("snapshot-shared")
        second = self._snapshot(
            "snapshot-shared",
            agent_id=BrainAgentId.STRATEGIST,
            beliefs=[
                self._belief(
                    "prop-strategy",
                    agent_id=BrainAgentId.STRATEGIST,
                )
            ],
        )
        request = self._request(world_states=[first, second])
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_duplicate_proposition_ids_across_snapshots_fail_closed(self) -> None:
        self._require_capability()
        first = self._snapshot(
            "snapshot-intelligence",
            beliefs=[self._belief("prop-shared")],
        )
        second = self._snapshot(
            "snapshot-strategist",
            agent_id=BrainAgentId.STRATEGIST,
            beliefs=[
                self._belief(
                    "prop-shared",
                    agent_id=BrainAgentId.STRATEGIST,
                )
            ],
        )
        request = self._request(world_states=[first, second], relations=[])
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_multi_agent_world_states_share_one_goal_without_collapsing_ownership(self) -> None:
        self._require_capability()
        intelligence = self._snapshot(
            "snapshot-intelligence",
            beliefs=[self._belief("prop-intelligence")],
        )
        strategy = self._snapshot(
            "snapshot-strategy",
            agent_id=BrainAgentId.STRATEGIST,
            beliefs=[
                self._belief(
                    "prop-strategy",
                    agent_id=BrainAgentId.STRATEGIST,
                )
            ],
        )
        request = self._request(
            world_states=[intelligence, strategy],
            entities=[
                self._entity("entity-a"),
                self._entity("entity-b"),
                self._entity("entity-c"),
            ],
            relations=[
                self._relation(
                    "rel-a",
                    subject="entity-a",
                    object_="entity-b",
                    proposition_id="prop-intelligence",
                ),
                self._relation(
                    "rel-b",
                    subject="entity-b",
                    predicate="INFORMS",
                    object_="entity-c",
                    proposition_id="prop-strategy",
                ),
            ],
        )
        graph = build_knowledge_graph(request)
        self.assertEqual(
            graph.contributing_agents,
            [BrainAgentId.INTELLIGENCE, BrainAgentId.STRATEGIST],
        )
        self.assertEqual(
            [relation.agent_id for relation in graph.relations],
            [BrainAgentId.INTELLIGENCE, BrainAgentId.STRATEGIST],
        )

    def test_duplicate_entity_ids_fail_closed(self) -> None:
        self._require_capability()
        request = self._request(
            entities=[self._entity("entity-a"), self._entity("entity-a")],
            relations=[],
        )
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_duplicate_relation_ids_fail_closed(self) -> None:
        self._require_capability()
        relation = self._relation()
        request = self._request(relations=[relation, relation.model_copy(deep=True)])
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_relation_endpoints_must_reference_known_entities(self) -> None:
        self._require_capability()
        request = self._request(
            relations=[self._relation(object_="entity-missing")]
        )
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_relation_must_reference_known_canonical_proposition(self) -> None:
        self._require_capability()
        request = self._request(
            relations=[self._relation(proposition_id="prop-invented")]
        )
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_relation_copies_statement_status_evidence_and_revision_lineage(self) -> None:
        self._require_capability()
        belief = self._belief(
            "prop-product-category",
            statement="Canonical source statement",
            status=BeliefStatus.CONTESTED,
            revision_id="revision-source-1",
        )
        snapshot = self._snapshot(
            beliefs=[belief, self._belief("prop-unmapped", status=BeliefStatus.UNKNOWN)]
        )
        graph = build_knowledge_graph(self._request(world_states=[snapshot]))
        relation = graph.relations[0]
        self.assertEqual(relation.statement, "Canonical source statement")
        self.assertEqual(relation.belief_status, BeliefStatus.CONTESTED)
        self.assertEqual(
            relation.supporting_evidence_refs,
            belief.supporting_evidence_refs,
        )
        self.assertEqual(
            relation.contradicting_evidence_refs,
            belief.contradicting_evidence_refs,
        )
        self.assertEqual(relation.ignored_evidence_refs, belief.ignored_evidence_refs)
        self.assertEqual(relation.revision_ids, ["revision-source-1"])

    def test_all_world_state_epistemic_statuses_are_preserved_not_promoted(self) -> None:
        self._require_capability()
        statuses = [
            BeliefStatus.ESTABLISHED,
            BeliefStatus.CONTESTED,
            BeliefStatus.REFUTED,
            BeliefStatus.UNKNOWN,
        ]
        beliefs = [
            self._belief(f"prop-{status.value.lower()}", status=status)
            for status in statuses
        ]
        snapshot = self._snapshot(beliefs=beliefs)
        entities = [
            self._entity(f"entity-{index}") for index in range(len(statuses) + 1)
        ]
        relations = [
            self._relation(
                f"rel-{index}",
                subject=f"entity-{index}",
                object_=f"entity-{index + 1}",
                proposition_id=beliefs[index].proposition.proposition_id,
            )
            for index in range(len(statuses))
        ]
        graph = build_knowledge_graph(
            self._request(
                world_states=[snapshot],
                entities=entities,
                relations=relations,
            )
        )
        self.assertEqual(
            [relation.belief_status for relation in graph.relations],
            statuses,
        )

    def test_knowledge_relation_cycles_are_allowed(self) -> None:
        self._require_capability()
        snapshot = self._snapshot(
            beliefs=[
                self._belief("prop-a"),
                self._belief("prop-b"),
            ]
        )
        request = self._request(
            world_states=[snapshot],
            entities=[self._entity("entity-a"), self._entity("entity-b")],
            relations=[
                self._relation(
                    "rel-a-b",
                    subject="entity-a",
                    predicate="RELATED_TO",
                    object_="entity-b",
                    proposition_id="prop-a",
                ),
                self._relation(
                    "rel-b-a",
                    subject="entity-b",
                    predicate="RELATED_TO",
                    object_="entity-a",
                    proposition_id="prop-b",
                ),
            ],
        )
        graph = build_knowledge_graph(request)
        self.assertEqual([relation.relation_id for relation in graph.relations], ["rel-a-b", "rel-b-a"])

    def test_same_canonical_proposition_may_support_multiple_semantic_relations(self) -> None:
        self._require_capability()
        request = self._request(
            relations=[
                self._relation("rel-primary"),
                self._relation(
                    "rel-secondary",
                    subject="entity-product",
                    predicate="ASSOCIATED_WITH",
                    object_="entity-market",
                ),
            ]
        )
        graph = build_knowledge_graph(request)
        self.assertEqual(len(graph.relations), 2)
        self.assertEqual(
            {relation.proposition_id for relation in graph.relations},
            {"prop-product-category"},
        )

    def test_unmapped_canonical_propositions_are_reported_explicitly(self) -> None:
        self._require_capability()
        graph = build_knowledge_graph(self._request())
        self.assertEqual(graph.unmapped_proposition_ids, ["prop-market-demand"])

    def test_empty_relation_projection_is_valid_and_reports_all_unmapped_knowledge(self) -> None:
        self._require_capability()
        graph = build_knowledge_graph(self._request(relations=[]))
        self.assertEqual(graph.relations, [])
        self.assertEqual(
            graph.unmapped_proposition_ids,
            ["prop-product-category", "prop-market-demand"],
        )

    def test_nested_world_state_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.world_states[0].beliefs[0].proposition.goal_id = "goal-laundered"
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_nested_relation_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.relations[0].predicate = "invalid predicate after construction"
        with self.assertRaises(ValidationError):
            build_knowledge_graph(request)

    def test_serialized_request_reconstructs_canonical_runtime_types(self) -> None:
        self._require_capability()
        payload = self._request().model_dump()
        graph = build_knowledge_graph(payload)
        self.assertIsInstance(graph, KnowledgeGraphSnapshot)
        self.assertTrue(all(isinstance(entity, KnowledgeEntity) for entity in graph.entities))
        self.assertTrue(
            all(isinstance(relation, KnowledgeRelationView) for relation in graph.relations)
        )
        self.assertTrue(
            all(isinstance(agent, BrainAgentId) for agent in graph.contributing_agents)
        )

    def test_output_does_not_alias_caller_owned_nested_inputs(self) -> None:
        self._require_capability()
        request = self._request()
        original_label = request.entities[0].label
        original_statement = request.world_states[0].beliefs[0].proposition.statement
        graph = build_knowledge_graph(request)
        graph.entities[0].label = "output mutation"
        graph.relations[0].statement = "output relation mutation"
        self.assertEqual(request.entities[0].label, original_label)
        self.assertEqual(
            request.world_states[0].beliefs[0].proposition.statement,
            original_statement,
        )

    def test_entity_type_and_predicate_are_semantic_upper_snake_case(self) -> None:
        self._require_capability()
        with self.assertRaises(ValidationError):
            self._entity("entity-invalid", entity_type="provider model")
        with self.assertRaises(ValidationError):
            self._relation(predicate="calls.tool")

    def test_semantic_contract_has_no_probability_confidence_or_runtime_authority(self) -> None:
        self._require_capability()
        model_fields = (
            set(KnowledgeEntity.__dataclass_fields__)
            | set(KnowledgeRelationSpec.__dataclass_fields__)
            | set(KnowledgeRelationView.__dataclass_fields__)
            | set(KnowledgeGraphRequest.__dataclass_fields__)
            | set(KnowledgeGraphSnapshot.__dataclass_fields__)
        )
        self.assertFalse({"confidence", "probability"} & model_fields)
        source = inspect.getsource(knowledge_graph_module)
        forbidden_import_fragments = (
            "import runtime",
            "from runtime",
            "import providers",
            "from providers",
            "import tools",
            "from tools",
            "import connectors",
            "from connectors",
            "import persistence",
            "from persistence",
        )
        for fragment in forbidden_import_fragments:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
