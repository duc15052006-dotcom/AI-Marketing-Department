"""Adversarial tests for provider-neutral Brain collaboration intelligence v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.collaboration as collaboration
from brain.collaboration import (
    CollaborationAssessment,
    CollaborationDisposition,
    PeerReview,
    evaluate_collaboration,
)
from brain.evidence import ClaimVerdict
from schemas.base import ValidationError


class BrainCollaborationIntelligenceV1Tests(unittest.TestCase):
    @staticmethod
    def _review(**updates) -> PeerReview:
        values = {
            "review_id": "R-1",
            "goal_id": "G-1",
            "proposal_id": "P-1",
            "reviewer_agent": "INTELLIGENCE",
            "verdict": ClaimVerdict.SUPPORTED,
            "rationale": "The proposal is consistent with the cited evidence.",
            "evidence_refs": ["E-R1"],
        }
        values.update(updates)
        return PeerReview(**values)

    @staticmethod
    def _assessment(reviews, **updates) -> CollaborationAssessment:
        values = {
            "assessment_id": "CA-1",
            "goal_id": "G-1",
            "proposal_id": "P-1",
            "author_agent": "STRATEGIST",
            "proposal_verdict": ClaimVerdict.SUPPORTED,
            "proposal_evidence_refs": ["E-P1"],
            "reviews": list(reviews),
            "minimum_supporting_reviewers": 1,
        }
        values.update(updates)
        return CollaborationAssessment(**values)

    def test_supported_proposal_with_independent_supported_review_is_accepted(self) -> None:
        decision = evaluate_collaboration(self._assessment([self._review()]))
        self.assertEqual(decision.disposition, CollaborationDisposition.ACCEPT)
        self.assertEqual(decision.supporting_review_ids, ["R-1"])
        self.assertEqual(decision.dissenting_review_ids, [])

    def test_supported_proposal_without_proposal_evidence_fails_closed(self) -> None:
        decision = evaluate_collaboration(
            self._assessment([self._review()], proposal_evidence_refs=[])
        )
        self.assertEqual(decision.disposition, CollaborationDisposition.INCONCLUSIVE)

    def test_self_review_cannot_create_independent_consensus(self) -> None:
        self_review = self._review(reviewer_agent="STRATEGIST")
        decision = evaluate_collaboration(self._assessment([self_review]))
        self.assertEqual(decision.disposition, CollaborationDisposition.INCONCLUSIVE)
        self.assertEqual(decision.supporting_review_ids, [])
        self.assertEqual(decision.ignored_review_ids, ["R-1"])

    def test_cross_goal_and_cross_proposal_reviews_cannot_be_laundered(self) -> None:
        wrong_goal = self._review(review_id="R-G", goal_id="G-OTHER")
        wrong_proposal = self._review(
            review_id="R-P", reviewer_agent="CREATIVE", proposal_id="P-OTHER"
        )
        decision = evaluate_collaboration(
            self._assessment([wrong_goal, wrong_proposal])
        )
        self.assertEqual(decision.disposition, CollaborationDisposition.INCONCLUSIVE)
        self.assertEqual(set(decision.ignored_review_ids), {"R-G", "R-P"})

    def test_duplicate_reviewer_identity_cannot_fake_quorum(self) -> None:
        first = self._review(review_id="R-1")
        duplicate_identity = self._review(review_id="R-2")
        decision = evaluate_collaboration(
            self._assessment(
                [first, duplicate_identity], minimum_supporting_reviewers=2
            )
        )
        self.assertEqual(decision.disposition, CollaborationDisposition.INCONCLUSIVE)
        self.assertEqual(decision.supporting_review_ids, [])
        self.assertEqual(set(decision.ignored_review_ids), {"R-1", "R-2"})

    def test_duplicate_reviewer_identity_cannot_erase_dissent_and_enable_acceptance(self) -> None:
        independent_support = self._review(
            review_id="R-S",
            reviewer_agent="INTELLIGENCE",
        )
        evidence_backed_dissent = self._review(
            review_id="R-D",
            reviewer_agent="CREATIVE",
            verdict=ClaimVerdict.REFUTED,
            rationale="Observed results contradict the proposal.",
            evidence_refs=["E-DISSENT"],
        )
        duplicate_same_reviewer = self._review(
            review_id="R-D2",
            reviewer_agent="CREATIVE",
            verdict=ClaimVerdict.SUPPORTED,
            rationale="A conflicting replay from the same reviewer must not erase dissent.",
            evidence_refs=["E-DUPLICATE"],
        )

        decision = evaluate_collaboration(
            self._assessment(
                [independent_support, evidence_backed_dissent, duplicate_same_reviewer],
                minimum_supporting_reviewers=1,
            )
        )

        self.assertNotEqual(
            decision.disposition,
            CollaborationDisposition.ACCEPT,
            "Conflicting duplicate reviewer records must fail closed instead of laundering dissent.",
        )

    def test_majority_support_cannot_override_refuted_proposal(self) -> None:
        reviews = [
            self._review(review_id="R-1", reviewer_agent="INTELLIGENCE"),
            self._review(review_id="R-2", reviewer_agent="CREATIVE"),
            self._review(review_id="R-3", reviewer_agent="PERFORMANCE"),
        ]
        decision = evaluate_collaboration(
            self._assessment(
                reviews,
                proposal_verdict=ClaimVerdict.REFUTED,
                proposal_evidence_refs=["E-P-REFUTE"],
            )
        )
        self.assertEqual(decision.disposition, CollaborationDisposition.REVISE)

    def test_contested_proposal_escalates_even_when_peers_support(self) -> None:
        reviews = [
            self._review(review_id="R-1", reviewer_agent="INTELLIGENCE"),
            self._review(review_id="R-2", reviewer_agent="CREATIVE"),
        ]
        decision = evaluate_collaboration(
            self._assessment(
                reviews,
                proposal_verdict=ClaimVerdict.CONTESTED,
                proposal_evidence_refs=["E-SUPPORT", "E-CONTRADICT"],
            )
        )
        self.assertEqual(decision.disposition, CollaborationDisposition.ESCALATE)

    def test_evidence_backed_peer_refutation_forces_revision_and_preserves_dissent(self) -> None:
        support = self._review(review_id="R-S", reviewer_agent="INTELLIGENCE")
        refute = self._review(
            review_id="R-D",
            reviewer_agent="CREATIVE",
            verdict=ClaimVerdict.REFUTED,
            rationale="The observed conversion data contradicts the recommendation.",
            evidence_refs=["E-DISSENT"],
        )
        decision = evaluate_collaboration(self._assessment([support, refute]))
        self.assertEqual(decision.disposition, CollaborationDisposition.REVISE)
        self.assertEqual(decision.dissenting_review_ids, ["R-D"])
        self.assertIn("R-S", decision.supporting_review_ids)

    def test_contested_peer_review_escalates_and_is_not_averaged_away(self) -> None:
        support = self._review(review_id="R-S", reviewer_agent="INTELLIGENCE")
        contested = self._review(
            review_id="R-C",
            reviewer_agent="PERFORMANCE",
            verdict=ClaimVerdict.CONTESTED,
            rationale="Two credible observations disagree.",
            evidence_refs=["E-C1", "E-C2"],
        )
        decision = evaluate_collaboration(self._assessment([support, contested]))
        self.assertEqual(decision.disposition, CollaborationDisposition.ESCALATE)
        self.assertEqual(decision.dissenting_review_ids, ["R-C"])

    def test_unsubstantiated_refutation_still_blocks_acceptance_but_does_not_claim_refutation(self) -> None:
        support = self._review(review_id="R-S", reviewer_agent="INTELLIGENCE")
        naked_challenge = self._review(
            review_id="R-N",
            reviewer_agent="CREATIVE",
            verdict=ClaimVerdict.REFUTED,
            rationale="I disagree, but I have no evidence reference.",
            evidence_refs=[],
        )
        decision = evaluate_collaboration(
            self._assessment([support, naked_challenge])
        )
        self.assertEqual(decision.disposition, CollaborationDisposition.ESCALATE)
        self.assertEqual(decision.dissenting_review_ids, ["R-N"])

    def test_insufficient_review_does_not_count_as_support(self) -> None:
        review = self._review(
            verdict=ClaimVerdict.INSUFFICIENT,
            evidence_refs=[],
            rationale="More evidence is required before endorsement.",
        )
        decision = evaluate_collaboration(self._assessment([review]))
        self.assertEqual(decision.disposition, CollaborationDisposition.INCONCLUSIVE)
        self.assertEqual(decision.supporting_review_ids, [])

    def test_configurable_quorum_requires_distinct_supported_reviewers(self) -> None:
        one = self._review(review_id="R-1", reviewer_agent="INTELLIGENCE")
        two = self._review(review_id="R-2", reviewer_agent="CREATIVE")
        insufficient = evaluate_collaboration(
            self._assessment([one], minimum_supporting_reviewers=2)
        )
        enough = evaluate_collaboration(
            self._assessment([one, two], minimum_supporting_reviewers=2)
        )
        self.assertEqual(
            insufficient.disposition, CollaborationDisposition.INCONCLUSIVE
        )
        self.assertEqual(enough.disposition, CollaborationDisposition.ACCEPT)

    def test_invalid_agent_and_impossible_quorum_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._review(reviewer_agent="AGENT_6")
        with self.assertRaises(ValidationError):
            self._assessment([self._review()], author_agent="AGENT_6")
        with self.assertRaises(ValidationError):
            self._assessment([self._review()], minimum_supporting_reviewers=0)
        with self.assertRaises(ValidationError):
            self._assessment([self._review()], minimum_supporting_reviewers=5)

    def test_collaboration_policy_has_no_body_or_provider_dependency(self) -> None:
        source = inspect.getsource(collaboration)
        tree = ast.parse(source)
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "knowledge",
            "memory",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

        serialized = str(
            evaluate_collaboration(self._assessment([self._review()])).model_dump()
        ).lower()
        for forbidden in (
            "provider_id",
            "model_id",
            "openai",
            "astra",
            "gemini",
            "claude",
            "tool_id",
            "connector_id",
            "queue_status",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
