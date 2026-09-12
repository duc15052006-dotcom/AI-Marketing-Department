from __future__ import annotations

import ast
import inspect
import unittest

from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.learning import LearningClaimKind, LearningEpisode, LearningMethod
from brain.memory_policy import MemoryDisposition, MemoryScopeLevel
from schemas.base import ValidationError


class BrainLearningConsolidationV1Tests(unittest.TestCase):
    @staticmethod
    def _episode(
        index: int,
        *,
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        source_id: str | None = None,
        goal_id: str = "G-CONSOLIDATE",
        agent_id: BrainAgentId = BrainAgentId.PERFORMANCE,
        hypothesis_id: str = "H-CONSOLIDATE",
        hypothesis: str = "Creative A causally improves qualified conversion rate.",
        claim_kind: LearningClaimKind = LearningClaimKind.CAUSAL,
        method: LearningMethod = LearningMethod.EXPERIMENT,
    ) -> LearningEpisode:
        evidence = ClaimEvidenceRequest(
            assessment_id=f"ASSESS-{index}",
            goal_id=goal_id,
            claim_id=hypothesis_id,
            agent_id=agent_id,
            evidence=[
                EvidenceSignal(
                    evidence_id=f"E-{index}",
                    goal_id=goal_id,
                    claim_id=hypothesis_id,
                    source_id=source_id or f"RUN-SOURCE-{index}",
                    relation=relation,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )
        return LearningEpisode(
            episode_id=f"EP-{index}",
            goal_id=goal_id,
            agent_id=agent_id,
            hypothesis_id=hypothesis_id,
            claim_kind=claim_kind,
            method=method,
            hypothesis=hypothesis,
            prediction="Qualified conversion rate should improve versus control.",
            evidence_request=evidence,
            intervention_id=(f"INT-{index}" if method == LearningMethod.EXPERIMENT else None),
            control_ref=(f"CTRL-{index}" if method == LearningMethod.EXPERIMENT else None),
            context_refs=[f"CTX-{index}"],
        )

    @staticmethod
    def _api():
        from brain.learning_consolidation import (
            LearningConsolidationRequest,
            LearningRunRecord,
            consolidate_learning,
        )

        return LearningConsolidationRequest, LearningRunRecord, consolidate_learning

    def _request(self, count: int = 3, **updates):
        LearningConsolidationRequest, LearningRunRecord, _ = self._api()
        values = {
            "consolidation_id": "LC-1",
            "goal_id": "G-CONSOLIDATE",
            "agent_id": BrainAgentId.PERFORMANCE,
            "origin_scope": MemoryScopeLevel.CAMPAIGN,
            "requested_scope": MemoryScopeLevel.CAMPAIGN,
            "runs": [
                LearningRunRecord(run_id=f"RUN-{index}", episode=self._episode(index))
                for index in range(1, count + 1)
            ],
        }
        values.update(updates)
        return LearningConsolidationRequest(**values)

    def test_public_brain_api_exports_learning_consolidation(self) -> None:
        import brain

        for symbol in (
            "LearningRunRecord",
            "LearningConsolidationRequest",
            "LearningConsolidation",
            "consolidate_learning",
        ):
            self.assertTrue(hasattr(brain, symbol), symbol)

    def test_three_independent_supported_controlled_runs_can_promote(self) -> None:
        _, _, consolidate_learning = self._api()
        result = consolidate_learning(self._request(3))

        self.assertEqual(result.memory_decision.disposition, MemoryDisposition.PROMOTED)
        self.assertEqual(result.memory_candidate.independent_run_count, 3)
        self.assertEqual(result.run_ids, ["RUN-1", "RUN-2", "RUN-3"])
        self.assertEqual(result.episode_ids, ["EP-1", "EP-2", "EP-3"])
        self.assertEqual(result.evidence_refs, ["E-1", "E-2", "E-3"])

    def test_one_run_is_candidate_and_two_runs_are_verified(self) -> None:
        _, _, consolidate_learning = self._api()
        single = consolidate_learning(self._request(1))
        double = consolidate_learning(self._request(2))
        self.assertEqual(single.memory_decision.disposition, MemoryDisposition.CANDIDATE)
        self.assertEqual(double.memory_decision.disposition, MemoryDisposition.VERIFIED)

    def test_replayed_source_cannot_manufacture_independent_runs(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        request = LearningConsolidationRequest(
            consolidation_id="LC-REPLAY",
            goal_id="G-CONSOLIDATE",
            agent_id=BrainAgentId.PERFORMANCE,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            runs=[
                LearningRunRecord(
                    run_id=f"RUN-{index}",
                    episode=self._episode(index, source_id="SAME-SOURCE"),
                )
                for index in range(1, 4)
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

    def test_refuted_or_non_candidate_run_blocks_consolidation(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        request = LearningConsolidationRequest(
            consolidation_id="LC-REFUTED",
            goal_id="G-CONSOLIDATE",
            agent_id=BrainAgentId.PERFORMANCE,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            runs=[
                LearningRunRecord(run_id="RUN-1", episode=self._episode(1)),
                LearningRunRecord(
                    run_id="RUN-2",
                    episode=self._episode(2, relation=EvidenceRelation.CONTRADICTS),
                ),
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

    def test_runs_must_share_exact_lesson_semantics(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        request = LearningConsolidationRequest(
            consolidation_id="LC-MISMATCH",
            goal_id="G-CONSOLIDATE",
            agent_id=BrainAgentId.PERFORMANCE,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            runs=[
                LearningRunRecord(run_id="RUN-1", episode=self._episode(1)),
                LearningRunRecord(
                    run_id="RUN-2",
                    episode=self._episode(2, hypothesis="Creative B is better."),
                ),
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

    def test_cross_goal_or_agent_authority_fails_closed(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        foreign_goal = self._request(
            1,
            runs=[
                LearningRunRecord(
                    run_id="RUN-X",
                    episode=self._episode(1, goal_id="G-OTHER"),
                )
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(foreign_goal)

        foreign_agent = self._request(
            1,
            runs=[
                LearningRunRecord(
                    run_id="RUN-Y",
                    episode=self._episode(1, agent_id=BrainAgentId.CONTENT),
                )
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(foreign_agent)

    def test_evidence_assessor_must_match_learning_owner_for_durable_provenance(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        episode = self._episode(1)
        episode.evidence_request.agent_id = BrainAgentId.INTELLIGENCE
        request = LearningConsolidationRequest(
            consolidation_id="LC-FOREIGN-EVIDENCE",
            goal_id="G-CONSOLIDATE",
            agent_id=BrainAgentId.PERFORMANCE,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            runs=[LearningRunRecord(run_id="RUN-1", episode=episode)],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

    def test_duplicate_run_episode_or_assessment_identity_fails_closed(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        with self.assertRaises(ValidationError):
            LearningConsolidationRequest(
                consolidation_id="LC-DUP-RUN",
                goal_id="G-CONSOLIDATE",
                agent_id=BrainAgentId.PERFORMANCE,
                origin_scope=MemoryScopeLevel.CAMPAIGN,
                requested_scope=MemoryScopeLevel.CAMPAIGN,
                runs=[
                    LearningRunRecord(run_id="RUN-1", episode=self._episode(1)),
                    LearningRunRecord(run_id="RUN-1", episode=self._episode(2)),
                ],
            )

        duplicate_episode = self._episode(2)
        duplicate_episode.episode_id = "EP-1"
        request = LearningConsolidationRequest(
            consolidation_id="LC-DUP-EP",
            goal_id="G-CONSOLIDATE",
            agent_id=BrainAgentId.PERFORMANCE,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            runs=[
                LearningRunRecord(run_id="RUN-1", episode=self._episode(1)),
                LearningRunRecord(run_id="RUN-2", episode=duplicate_episode),
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

        duplicate_assessment = self._episode(2)
        duplicate_assessment.evidence_request.assessment_id = "ASSESS-1"
        request = LearningConsolidationRequest(
            consolidation_id="LC-DUP-ASSESS",
            goal_id="G-CONSOLIDATE",
            agent_id=BrainAgentId.PERFORMANCE,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            runs=[
                LearningRunRecord(run_id="RUN-1", episode=self._episode(1)),
                LearningRunRecord(run_id="RUN-2", episode=duplicate_assessment),
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

    def test_observational_support_cannot_consolidate_causal_authority(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        request = LearningConsolidationRequest(
            consolidation_id="LC-OBS-CAUSAL",
            goal_id="G-CONSOLIDATE",
            agent_id=BrainAgentId.PERFORMANCE,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            runs=[
                LearningRunRecord(
                    run_id="RUN-1",
                    episode=self._episode(1, method=LearningMethod.OBSERVATION),
                )
            ],
        )
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

    def test_post_construction_nested_mutation_fails_closed(self) -> None:
        _, _, consolidate_learning = self._api()
        request = self._request(3)
        request.runs[0].episode.hypothesis = "MUTATED AUTHORITY"
        with self.assertRaises(ValidationError):
            consolidate_learning(request)

    def test_scope_broadening_remains_rejected_by_memory_policy(self) -> None:
        _, _, consolidate_learning = self._api()
        result = consolidate_learning(
            self._request(
                3,
                origin_scope=MemoryScopeLevel.CAMPAIGN,
                requested_scope=MemoryScopeLevel.GLOBAL,
            )
        )
        self.assertEqual(result.memory_decision.disposition, MemoryDisposition.REJECTED)
        self.assertEqual(result.memory_decision.effective_scope, MemoryScopeLevel.CAMPAIGN)

    def test_result_does_not_alias_caller_owned_inputs(self) -> None:
        _, _, consolidate_learning = self._api()
        request = self._request(3)
        result = consolidate_learning(request)
        request.runs[0].episode.evidence_request.evidence[0].source_id = "CHANGED-LATER"
        self.assertEqual(
            result.memory_candidate.run_evidence_requests[0].evidence[0].source_id,
            "RUN-SOURCE-1",
        )

    def test_serialized_models_reconstruct_canonical_runtime_types(self) -> None:
        LearningConsolidationRequest, LearningRunRecord, consolidate_learning = self._api()
        request = self._request(3)
        rebuilt = LearningConsolidationRequest(**request.model_dump())
        self.assertIsInstance(rebuilt.runs[0], LearningRunRecord)
        self.assertIsInstance(rebuilt.runs[0].episode, LearningEpisode)
        result = consolidate_learning(rebuilt)
        self.assertEqual(result.memory_decision.disposition, MemoryDisposition.PROMOTED)

    def test_caller_cannot_self_attest_summary_authority(self) -> None:
        request = self._request(3)
        dumped = request.model_dump()
        for forbidden in (
            "evidence_verdict",
            "evidence_refs",
            "independent_run_count",
            "authority",
            "confidence",
            "probability",
            "provider_id",
            "tool_id",
        ):
            self.assertNotIn(forbidden, dumped)

    def test_learning_consolidation_module_is_semantic_only(self) -> None:
        import brain.learning_consolidation as learning_consolidation

        tree = ast.parse(inspect.getsource(learning_consolidation))
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "providers",
            "knowledge",
            "memory",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

    def test_exactly_five_permanent_asi_ids_remain(self) -> None:
        self.assertEqual(len(BrainAgentId), 5)
        self.assertEqual(
            {agent.value for agent in BrainAgentId},
            {"CMO", "INTELLIGENCE", "CONTENT", "CREATIVE", "PERFORMANCE"},
        )


if __name__ == "__main__":
    unittest.main()
