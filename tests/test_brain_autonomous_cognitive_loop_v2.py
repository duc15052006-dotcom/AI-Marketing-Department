"""Adversarial contract tests for Autonomous Cognitive Loop V2."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.autonomous_loop as autonomous
from brain.autonomous_loop import (
    AutonomousCognitiveDirectiveKind,
    AutonomousCognitiveLoopRequest,
    derive_autonomous_cognitive_loop,
)
from brain.cognitive_loop import CognitiveCycleRequest, CognitivePhase
from brain.collective_cognition import (
    CollectiveCandidate,
    CollectiveCognitionRequest,
)
from brain.collaboration import CollaborationAssessment, PeerReview
from brain.contracts import BrainAgentId, GoalSpec
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.metacognition import KnowledgeGap, KnowledgeGapKind, MetacognitionRequest
from schemas.base import ValidationError


class BrainAutonomousCognitiveLoopV2Tests(unittest.TestCase):
    ALL_AGENTS = list(BrainAgentId)

    @staticmethod
    def _goal() -> GoalSpec:
        return GoalSpec(
            goal_id="G-1",
            objective="Improve campaign outcome",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Outcome improves"],
        )

    @classmethod
    def _base_cycle(cls) -> CognitiveCycleRequest:
        return CognitiveCycleRequest(cycle_id="C-1", goal=cls._goal())

    @staticmethod
    def _meta(*, blocking: bool = False, testable: bool = False) -> MetacognitionRequest:
        gap = KnowledgeGap(
            gap_id="KG-1",
            goal_id="G-1",
            owner_agent=BrainAgentId.INTELLIGENCE,
            kind=KnowledgeGapKind.CAUSAL if testable else KnowledgeGapKind.EVIDENCE,
            question="What explains the observed outcome?",
            consequence="A wrong explanation can produce a bad plan",
            blocking=blocking,
            testable=testable,
        )
        return MetacognitionRequest(
            assessment_id="M-1",
            goal_id="G-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            gaps=[gap],
        )

    @staticmethod
    def _evidence_request(*, proposal_id: str, agent: BrainAgentId, suffix: str, verdict: ClaimVerdict) -> ClaimEvidenceRequest:
        signals = []
        if verdict == ClaimVerdict.SUPPORTED:
            signals.append(EvidenceSignal(
                evidence_id=f"E-{suffix}-S", goal_id="G-1", claim_id=proposal_id,
                source_id=f"SRC-{suffix}-S", relation=EvidenceRelation.SUPPORTS,
                strength=EvidenceStrength.STRONG, origin=EvidenceOrigin.OBSERVED,
            ))
        elif verdict == ClaimVerdict.REFUTED:
            signals.append(EvidenceSignal(
                evidence_id=f"E-{suffix}-R", goal_id="G-1", claim_id=proposal_id,
                source_id=f"SRC-{suffix}-R", relation=EvidenceRelation.CONTRADICTS,
                strength=EvidenceStrength.STRONG, origin=EvidenceOrigin.OBSERVED,
            ))
        return ClaimEvidenceRequest(
            assessment_id=f"EA-{suffix}", goal_id="G-1", claim_id=proposal_id,
            agent_id=agent, evidence=signals,
        )

    @classmethod
    def _collective_candidate(cls, *, proposal_id: str = "P-1", refuting_peer: bool = False) -> CollectiveCandidate:
        author = BrainAgentId.CONTENT
        proposal_request = cls._evidence_request(
            proposal_id=proposal_id, agent=author, suffix=f"{proposal_id}-P", verdict=ClaimVerdict.SUPPORTED,
        )
        reviews = []
        for index, agent in enumerate(a for a in cls.ALL_AGENTS if a != author):
            verdict = ClaimVerdict.REFUTED if refuting_peer and index == 0 else ClaimVerdict.SUPPORTED
            request = cls._evidence_request(
                proposal_id=proposal_id, agent=agent, suffix=f"{proposal_id}-R{index}", verdict=verdict,
            )
            refs = [f"E-{proposal_id}-R{index}-R"] if verdict == ClaimVerdict.REFUTED else [f"E-{proposal_id}-R{index}-S"]
            reviews.append(PeerReview(
                review_id=f"R-{proposal_id}-{index}", goal_id="G-1", proposal_id=proposal_id,
                reviewer_agent=agent, verdict=verdict, rationale="canonical peer review",
                evidence_refs=refs, evidence_request=request,
            ))
        assessment = CollaborationAssessment(
            assessment_id=f"CA-{proposal_id}", goal_id="G-1", proposal_id=proposal_id,
            author_agent=author, proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=[f"E-{proposal_id}-P-S"],
            proposal_evidence_request=proposal_request, reviews=reviews,
            minimum_supporting_reviewers=1,
        )
        return CollectiveCandidate(
            candidate_id=proposal_id, goal_id="G-1", author_agent=author,
            collaboration_assessment=assessment,
        )

    @classmethod
    def _request(cls, *, meta=None, collective=None) -> AutonomousCognitiveLoopRequest:
        return AutonomousCognitiveLoopRequest(
            loop_id="AUTO-1",
            cognitive_cycle=cls._base_cycle(),
            metacognition=meta,
            collective_cognition=collective,
        )

    def test_no_extra_signals_delegates_to_canonical_cognitive_loop(self) -> None:
        result = derive_autonomous_cognitive_loop(self._request())
        self.assertEqual(result.phase, CognitivePhase.PLANNING)
        self.assertEqual(result.directive.kind, AutonomousCognitiveDirectiveKind.FOLLOW_COGNITIVE_CYCLE)
        self.assertEqual(result.cognitive_cycle.phase, CognitivePhase.PLANNING)

    def test_open_knowledge_gap_routes_to_research_before_planning(self) -> None:
        result = derive_autonomous_cognitive_loop(self._request(meta=self._meta()))
        self.assertEqual(result.phase, CognitivePhase.RESEARCH)
        self.assertEqual(result.directive.kind, AutonomousCognitiveDirectiveKind.REDUCE_KNOWLEDGE_GAP)
        self.assertEqual(result.metacognition.open_gap_ids, ["KG-1"])

    def test_testable_causal_gap_routes_to_experiment_design_semantically(self) -> None:
        result = derive_autonomous_cognitive_loop(self._request(meta=self._meta(testable=True)))
        self.assertEqual(result.phase, CognitivePhase.RESEARCH)
        self.assertEqual(result.directive.kind, AutonomousCognitiveDirectiveKind.DESIGN_EXPERIMENT)
        self.assertEqual(result.directive.target_ids, ["KG-1"])

    def test_collective_refutation_routes_to_revision(self) -> None:
        collective = CollectiveCognitionRequest(
            cycle_id="CC-1", goal_id="G-1",
            candidates=[self._collective_candidate(refuting_peer=True)],
        )
        result = derive_autonomous_cognitive_loop(self._request(collective=collective))
        self.assertEqual(result.phase, CognitivePhase.DECISION)
        self.assertEqual(result.directive.kind, AutonomousCognitiveDirectiveKind.REVISE_COLLECTIVE_CANDIDATE)

    def test_multiple_accepted_collective_candidates_route_to_arbitration(self) -> None:
        collective = CollectiveCognitionRequest(
            cycle_id="CC-1", goal_id="G-1",
            candidates=[self._collective_candidate(proposal_id="P-1"), self._collective_candidate(proposal_id="P-2")],
        )
        result = derive_autonomous_cognitive_loop(self._request(collective=collective))
        self.assertEqual(result.phase, CognitivePhase.DECISION)
        self.assertEqual(result.directive.kind, AutonomousCognitiveDirectiveKind.ARBITRATE_COLLECTIVE_CANDIDATES)
        self.assertEqual(set(result.directive.target_ids), {"P-1", "P-2"})

    def test_single_collectively_accepted_candidate_does_not_override_missing_plan(self) -> None:
        collective = CollectiveCognitionRequest(
            cycle_id="CC-1", goal_id="G-1", candidates=[self._collective_candidate()],
        )
        result = derive_autonomous_cognitive_loop(self._request(collective=collective))
        self.assertEqual(result.phase, CognitivePhase.PLANNING)
        self.assertEqual(result.collective_cognition.selected_candidate_id, "P-1")

    def test_goal_identity_must_bind_across_all_nested_cognitive_inputs(self) -> None:
        meta = self._meta()
        meta.goal_id = "G-FORGED"
        with self.assertRaises(ValidationError):
            derive_autonomous_cognitive_loop(self._request(meta=meta))

    def test_post_construction_mutation_is_revalidated_at_use_boundary(self) -> None:
        request = self._request(meta=self._meta())
        request.metacognition.gaps[0].goal_id = "G-FORGED"
        with self.assertRaises(ValidationError):
            derive_autonomous_cognitive_loop(request)

    def test_serialized_request_reconstructs_nested_canonical_types(self) -> None:
        request = self._request(meta=self._meta())
        reconstructed = AutonomousCognitiveLoopRequest(**request.model_dump())
        result = derive_autonomous_cognitive_loop(reconstructed)
        self.assertIsInstance(result.cognitive_cycle, object)
        self.assertEqual(result.phase, CognitivePhase.RESEARCH)

    def test_result_is_detached_from_caller_mutation(self) -> None:
        request = self._request(meta=self._meta())
        result = derive_autonomous_cognitive_loop(request)
        request.cognitive_cycle.goal.objective = "mutated"
        request.metacognition.gaps[0].question = "mutated"
        self.assertEqual(result.cognitive_cycle.goal.objective, "Improve campaign outcome")
        self.assertNotEqual(result.metacognition.directives[0].rationale, "mutated")

    def test_autonomous_loop_remains_semantic_only_provider_neutral(self) -> None:
        source = inspect.getsource(autonomous)
        tree = ast.parse(source)
        forbidden = {"runtime", "tools", "integrations", "connectors", "providers", "memory"}
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
        self.assertEqual(roots & forbidden, set())
        output = derive_autonomous_cognitive_loop(self._request()).model_dump()
        self.assertFalse(set(output) & {"provider", "tool", "endpoint", "execution_authority", "confidence", "probability"})


if __name__ == "__main__":
    unittest.main()
