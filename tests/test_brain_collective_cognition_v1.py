"""Adversarial contract tests for five-ASI Collective Cognition V1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.collective_cognition as collective
from brain.collective_cognition import (
    CollectiveCandidate,
    CollectiveCognitionDisposition,
    CollectiveCognitionRequest,
    synthesize_collective_cognition,
)
from brain.collaboration import CollaborationAssessment, PeerReview
from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from schemas.base import ValidationError


class BrainCollectiveCognitionV1Tests(unittest.TestCase):
    ALL_AGENTS = [
        BrainAgentId.CMO,
        BrainAgentId.INTELLIGENCE,
        BrainAgentId.CONTENT,
        BrainAgentId.CREATIVE,
        BrainAgentId.PERFORMANCE,
    ]

    @staticmethod
    def _evidence_request(
        *,
        assessment_id: str,
        goal_id: str,
        proposal_id: str,
        agent_id: BrainAgentId,
        verdict: ClaimVerdict,
        source_suffix: str,
    ) -> ClaimEvidenceRequest:
        evidence = []
        if verdict == ClaimVerdict.SUPPORTED:
            evidence = [
                EvidenceSignal(
                    evidence_id=f"E-{source_suffix}-S",
                    goal_id=goal_id,
                    claim_id=proposal_id,
                    source_id=f"SRC-{source_suffix}-S",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ]
        elif verdict == ClaimVerdict.REFUTED:
            evidence = [
                EvidenceSignal(
                    evidence_id=f"E-{source_suffix}-R",
                    goal_id=goal_id,
                    claim_id=proposal_id,
                    source_id=f"SRC-{source_suffix}-R",
                    relation=EvidenceRelation.CONTRADICTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ]
        elif verdict == ClaimVerdict.CONTESTED:
            evidence = [
                EvidenceSignal(
                    evidence_id=f"E-{source_suffix}-S",
                    goal_id=goal_id,
                    claim_id=proposal_id,
                    source_id=f"SRC-{source_suffix}-S",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                ),
                EvidenceSignal(
                    evidence_id=f"E-{source_suffix}-R",
                    goal_id=goal_id,
                    claim_id=proposal_id,
                    source_id=f"SRC-{source_suffix}-R",
                    relation=EvidenceRelation.CONTRADICTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                ),
            ]
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id=goal_id,
            claim_id=proposal_id,
            agent_id=agent_id,
            evidence=evidence,
        )

    @classmethod
    def _candidate(
        cls,
        *,
        candidate_id: str = "P-1",
        author: BrainAgentId = BrainAgentId.CONTENT,
        proposal_verdict: ClaimVerdict = ClaimVerdict.SUPPORTED,
        reviewer_agents=None,
        review_verdicts=None,
        include_proposal_evidence: bool = True,
        minimum_supporting_reviewers: int = 1,
        goal_id: str = "G-1",
    ) -> CollectiveCandidate:
        if reviewer_agents is None:
            reviewer_agents = [agent for agent in cls.ALL_AGENTS if agent != author]
        if review_verdicts is None:
            review_verdicts = {
                agent: ClaimVerdict.SUPPORTED for agent in reviewer_agents
            }

        proposal_request = None
        proposal_refs = []
        if include_proposal_evidence:
            proposal_request = cls._evidence_request(
                assessment_id=f"EA-{candidate_id}-PROPOSAL",
                goal_id=goal_id,
                proposal_id=candidate_id,
                agent_id=author,
                verdict=proposal_verdict,
                source_suffix=f"{candidate_id}-PROPOSAL",
            )
            if proposal_verdict == ClaimVerdict.SUPPORTED:
                proposal_refs = [f"E-{candidate_id}-PROPOSAL-S"]
            elif proposal_verdict == ClaimVerdict.REFUTED:
                proposal_refs = [f"E-{candidate_id}-PROPOSAL-R"]
            elif proposal_verdict == ClaimVerdict.CONTESTED:
                proposal_refs = [
                    f"E-{candidate_id}-PROPOSAL-S",
                    f"E-{candidate_id}-PROPOSAL-R",
                ]

        reviews = []
        for index, agent in enumerate(reviewer_agents):
            verdict = review_verdicts.get(agent, ClaimVerdict.SUPPORTED)
            request = cls._evidence_request(
                assessment_id=f"EA-{candidate_id}-R{index}",
                goal_id=goal_id,
                proposal_id=candidate_id,
                agent_id=agent,
                verdict=verdict,
                source_suffix=f"{candidate_id}-R{index}",
            )
            if verdict == ClaimVerdict.SUPPORTED:
                refs = [f"E-{candidate_id}-R{index}-S"]
            elif verdict == ClaimVerdict.REFUTED:
                refs = [f"E-{candidate_id}-R{index}-R"]
            elif verdict == ClaimVerdict.CONTESTED:
                refs = [f"E-{candidate_id}-R{index}-S", f"E-{candidate_id}-R{index}-R"]
            else:
                refs = []
            reviews.append(
                PeerReview(
                    review_id=f"R-{candidate_id}-{index}",
                    goal_id=goal_id,
                    proposal_id=candidate_id,
                    reviewer_agent=agent,
                    verdict=verdict,
                    rationale=f"Canonical review by {agent.value}",
                    evidence_refs=refs,
                    evidence_request=request,
                )
            )

        assessment = CollaborationAssessment(
            assessment_id=f"CA-{candidate_id}",
            goal_id=goal_id,
            proposal_id=candidate_id,
            author_agent=author,
            proposal_verdict=proposal_verdict,
            proposal_evidence_refs=proposal_refs,
            proposal_evidence_request=proposal_request,
            reviews=reviews,
            minimum_supporting_reviewers=minimum_supporting_reviewers,
        )
        return CollectiveCandidate(
            candidate_id=candidate_id,
            goal_id=goal_id,
            author_agent=author,
            collaboration_assessment=assessment,
        )

    @classmethod
    def _request(cls, candidates) -> CollectiveCognitionRequest:
        return CollectiveCognitionRequest(
            cycle_id="CC-1",
            goal_id="G-1",
            candidates=list(candidates),
        )

    def test_all_five_agents_on_one_accepted_candidate_is_ready_for_synthesis(self) -> None:
        result = synthesize_collective_cognition(self._request([self._candidate()]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.READY_FOR_SYNTHESIS
        )
        self.assertEqual(result.selected_candidate_id, "P-1")
        self.assertEqual(result.accepted_candidate_ids, ["P-1"])
        self.assertEqual(result.participant_agents, self.ALL_AGENTS)

    def test_missing_permanent_agent_participation_fails_closed(self) -> None:
        candidate = self._candidate(
            reviewer_agents=[
                BrainAgentId.CMO,
                BrainAgentId.INTELLIGENCE,
                BrainAgentId.CREATIVE,
            ]
        )
        with self.assertRaises(ValidationError):
            synthesize_collective_cognition(self._request([candidate]))

    def test_no_sixth_agent_can_enter_collective_cognition(self) -> None:
        candidate = self._candidate()
        candidate.collaboration_assessment.reviews[0].reviewer_agent = "AGENT_6"
        with self.assertRaises(ValidationError):
            synthesize_collective_cognition(self._request([candidate]))

    def test_multiple_independently_accepted_candidates_require_arbitration_not_vote(self) -> None:
        first = self._candidate(candidate_id="P-1", author=BrainAgentId.CONTENT)
        second = self._candidate(candidate_id="P-2", author=BrainAgentId.CREATIVE)
        result = synthesize_collective_cognition(self._request([first, second]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.NEEDS_ARBITRATION
        )
        self.assertEqual(set(result.accepted_candidate_ids), {"P-1", "P-2"})
        self.assertIsNone(result.selected_candidate_id)

    def test_evidence_backed_dissent_is_preserved_and_routes_to_arbitration(self) -> None:
        review_verdicts = {
            BrainAgentId.CMO: ClaimVerdict.SUPPORTED,
            BrainAgentId.INTELLIGENCE: ClaimVerdict.SUPPORTED,
            BrainAgentId.CREATIVE: ClaimVerdict.REFUTED,
            BrainAgentId.PERFORMANCE: ClaimVerdict.SUPPORTED,
        }
        candidate = self._candidate(review_verdicts=review_verdicts)
        result = synthesize_collective_cognition(self._request([candidate]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.NEEDS_REVISION
        )
        self.assertEqual(result.accepted_candidate_ids, [])
        self.assertEqual(result.candidate_decisions[0].dissenting_review_ids, ["R-P-1-2"])

    def test_contested_evidence_routes_to_arbitration(self) -> None:
        candidate = self._candidate(proposal_verdict=ClaimVerdict.CONTESTED)
        result = synthesize_collective_cognition(self._request([candidate]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.NEEDS_ARBITRATION
        )
        self.assertIsNone(result.selected_candidate_id)

    def test_insufficient_evidence_routes_to_research_even_with_peer_agreement(self) -> None:
        candidate = self._candidate(include_proposal_evidence=False)
        result = synthesize_collective_cognition(self._request([candidate]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.NEEDS_RESEARCH
        )
        self.assertIsNone(result.selected_candidate_id)

    def test_one_accepted_plus_inconclusive_alternative_requires_research(self) -> None:
        accepted = self._candidate(candidate_id="P-1")
        inconclusive = self._candidate(
            candidate_id="P-2",
            author=BrainAgentId.CREATIVE,
            include_proposal_evidence=False,
        )
        result = synthesize_collective_cognition(self._request([accepted, inconclusive]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.NEEDS_RESEARCH
        )
        self.assertIsNone(result.selected_candidate_id)

    def test_one_accepted_plus_refuted_alternative_can_select_only_accepted_candidate(self) -> None:
        accepted = self._candidate(candidate_id="P-1")
        refuted = self._candidate(
            candidate_id="P-2",
            author=BrainAgentId.CREATIVE,
            proposal_verdict=ClaimVerdict.REFUTED,
        )
        result = synthesize_collective_cognition(self._request([accepted, refuted]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.READY_FOR_SYNTHESIS
        )
        self.assertEqual(result.selected_candidate_id, "P-1")

    def test_all_refuted_candidates_route_to_revision(self) -> None:
        first = self._candidate(candidate_id="P-1", proposal_verdict=ClaimVerdict.REFUTED)
        second = self._candidate(
            candidate_id="P-2",
            author=BrainAgentId.CREATIVE,
            proposal_verdict=ClaimVerdict.REFUTED,
        )
        result = synthesize_collective_cognition(self._request([first, second]))
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.NEEDS_REVISION
        )

    def test_candidate_identity_goal_and_author_bind_exactly_to_collaboration(self) -> None:
        candidate = self._candidate()
        with self.assertRaises(ValidationError):
            CollectiveCandidate(
                candidate_id="P-OTHER",
                goal_id=candidate.goal_id,
                author_agent=candidate.author_agent,
                collaboration_assessment=candidate.collaboration_assessment,
            )
        with self.assertRaises(ValidationError):
            CollectiveCandidate(
                candidate_id=candidate.candidate_id,
                goal_id="G-OTHER",
                author_agent=candidate.author_agent,
                collaboration_assessment=candidate.collaboration_assessment,
            )
        with self.assertRaises(ValidationError):
            CollectiveCandidate(
                candidate_id=candidate.candidate_id,
                goal_id=candidate.goal_id,
                author_agent=BrainAgentId.CREATIVE,
                collaboration_assessment=candidate.collaboration_assessment,
            )

    def test_duplicate_candidate_and_assessment_identity_fail_closed(self) -> None:
        first = self._candidate(candidate_id="P-1")
        with self.assertRaises(ValidationError):
            self._request([first, first.model_copy(deep=True)])

        second = self._candidate(candidate_id="P-2", author=BrainAgentId.CREATIVE)
        second.collaboration_assessment.assessment_id = first.collaboration_assessment.assessment_id
        with self.assertRaises(ValidationError):
            synthesize_collective_cognition(self._request([first, second]))

    def test_post_construction_nested_mutation_is_revalidated_at_use_boundary(self) -> None:
        request = self._request([self._candidate()])
        request.candidates[0].collaboration_assessment.proposal_id = "P-FORGED"
        with self.assertRaises(ValidationError):
            synthesize_collective_cognition(request)

    def test_serialized_request_reconstructs_canonical_nested_runtime_types(self) -> None:
        request = self._request([self._candidate()])
        reconstructed = CollectiveCognitionRequest(**request.model_dump())
        result = synthesize_collective_cognition(reconstructed)
        self.assertEqual(
            result.disposition, CollectiveCognitionDisposition.READY_FOR_SYNTHESIS
        )
        self.assertIsInstance(
            reconstructed.candidates[0].collaboration_assessment,
            CollaborationAssessment,
        )
        self.assertIsInstance(
            reconstructed.candidates[0].collaboration_assessment.reviews[0], PeerReview
        )

    def test_result_is_detached_from_caller_mutation(self) -> None:
        request = self._request([self._candidate()])
        result = synthesize_collective_cognition(request)
        request.candidates[0].candidate_id = "P-MUTATED"
        request.candidates[0].collaboration_assessment.reviews[0].rationale = "mutated"
        self.assertEqual(result.selected_candidate_id, "P-1")
        self.assertEqual(result.candidate_decisions[0].candidate_id, "P-1")

    def test_collective_cognition_remains_semantic_only_and_provider_neutral(self) -> None:
        source = inspect.getsource(collective)
        tree = ast.parse(source)
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "providers",
            "memory",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

        serialized = synthesize_collective_cognition(
            self._request([self._candidate()])
        ).model_dump()
        forbidden_output_terms = {
            "provider",
            "model_id",
            "tool",
            "endpoint",
            "execution_authority",
            "confidence",
            "probability",
            "vote_count",
        }
        self.assertEqual(set(serialized) & forbidden_output_terms, set())


if __name__ == "__main__":
    unittest.main()
