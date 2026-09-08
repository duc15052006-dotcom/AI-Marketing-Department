from __future__ import annotations

import unittest

from brain.collaboration import (
    CollaborationAssessment,
    CollaborationDisposition,
    PeerReview,
    evaluate_collaboration,
)
from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
    assess_claim_evidence,
)
from brain.planning import PlanSnapshot, PlanStep, ready_step_ids
from brain.reasoning import (
    ReasoningAssessment,
    ReasoningDepth,
    Reversibility,
    SignalLevel,
    select_reasoning_depth,
)
from schemas.base import ValidationError


_DEPTH_RANK = {
    ReasoningDepth.FAST: 0,
    ReasoningDepth.BALANCED: 1,
    ReasoningDepth.DEEP: 2,
    ReasoningDepth.VERY_DEEP: 3,
    ReasoningDepth.MAXIMUM: 4,
}


class TestBrainASIOrientedStressV1(unittest.TestCase):
    """Adversarial holdout aimed at epistemic integrity, not benchmark theatre.

    These tests intentionally exercise post-validation mutation, correlated
    evidence, identity confusion, and monotonic reasoning invariants. A RED test
    is useful evidence of a real authority-boundary limitation and must not be
    weakened merely to make CI green.
    """

    @staticmethod
    def _signal(
        evidence_id: str,
        *,
        goal_id: str = "goal-asi",
        claim_id: str = "proposal-asi",
        source_id: str = "source-a",
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        strength: EvidenceStrength = EvidenceStrength.STRONG,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
    ) -> EvidenceSignal:
        return EvidenceSignal(
            evidence_id=evidence_id,
            goal_id=goal_id,
            claim_id=claim_id,
            source_id=source_id,
            relation=relation,
            strength=strength,
            origin=origin,
        )

    def _request(
        self,
        assessment_id: str,
        agent_id: BrainAgentId,
        signal: EvidenceSignal,
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id=signal.goal_id,
            claim_id=signal.claim_id,
            agent_id=agent_id,
            evidence=[signal],
        )

    def _review(
        self,
        review_id: str,
        reviewer: BrainAgentId,
        *,
        evidence_id: str,
        source_id: str,
    ) -> PeerReview:
        request = self._request(
            f"assessment-{review_id}",
            reviewer,
            self._signal(evidence_id, source_id=source_id),
        )
        return PeerReview(
            review_id=review_id,
            goal_id="goal-asi",
            proposal_id="proposal-asi",
            reviewer_agent=reviewer,
            verdict=ClaimVerdict.SUPPORTED,
            rationale="independently reviewed raw evidence",
            evidence_refs=[evidence_id],
            evidence_request=request,
        )

    def _supported_collaboration(
        self,
        *,
        author: BrainAgentId = BrainAgentId.CMO,
        reviews: list[PeerReview],
        quorum: int = 1,
    ) -> CollaborationAssessment:
        proposal_request = self._request(
            "assessment-proposal",
            BrainAgentId.INTELLIGENCE,
            self._signal("proposal-evidence", source_id="proposal-source"),
        )
        return CollaborationAssessment(
            assessment_id="collab-asi",
            goal_id="goal-asi",
            proposal_id="proposal-asi",
            author_agent=author,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["proposal-evidence"],
            proposal_evidence_request=proposal_request,
            reviews=reviews,
            minimum_supporting_reviewers=quorum,
        )

    # --- Epistemic authority / TOCTOU mutation ---

    def test_derived_evidence_cannot_be_upgraded_to_observed_after_validation(self):
        signal = self._signal(
            "ev-derived",
            origin=EvidenceOrigin.DERIVED,
            strength=EvidenceStrength.STRONG,
        )
        request = self._request("assessment-derived", BrainAgentId.INTELLIGENCE, signal)
        request.evidence[0].origin = EvidenceOrigin.OBSERVED

        with self.assertRaises(ValidationError):
            assess_claim_evidence(request)

    def test_invalid_source_identity_mutation_fails_closed_at_evidence_use_boundary(self):
        signal = self._signal("ev-source")
        request = self._request("assessment-source", BrainAgentId.INTELLIGENCE, signal)
        request.evidence[0].source_id = "   "

        with self.assertRaises(ValidationError):
            assess_claim_evidence(request)

    def test_collaboration_author_identity_cannot_be_rewritten_after_validation(self):
        self_review = self._review(
            "review-self",
            BrainAgentId.CMO,
            evidence_id="review-self-evidence",
            source_id="self-source",
        )
        assessment = self._supported_collaboration(reviews=[self_review])
        normal = evaluate_collaboration(assessment)
        self.assertNotEqual(normal.disposition, CollaborationDisposition.ACCEPT)

        assessment.author_agent = "SIXTH_ASI"
        with self.assertRaises(ValidationError):
            evaluate_collaboration(assessment)

    def test_self_review_cannot_be_rebound_into_independent_peer_after_validation(self):
        self_review = self._review(
            "review-rebind",
            BrainAgentId.CMO,
            evidence_id="review-rebind-evidence",
            source_id="rebind-source",
        )
        assessment = self._supported_collaboration(reviews=[self_review])

        stored = assessment.reviews[0]
        stored.reviewer_agent = BrainAgentId.STRATEGIST
        stored.evidence_request.agent_id = BrainAgentId.STRATEGIST

        decision = evaluate_collaboration(assessment)
        self.assertNotEqual(
            decision.disposition,
            CollaborationDisposition.ACCEPT,
            "post-validation identity rebinding manufactured independent quorum",
        )

    # --- Byzantine / correlated-review stress ---

    def test_two_agents_echoing_one_external_source_do_not_manufacture_independent_quorum(self):
        review_a = self._review(
            "review-strategist",
            BrainAgentId.STRATEGIST,
            evidence_id="echo-1",
            source_id="shared-external-source",
        )
        review_b = self._review(
            "review-creative",
            BrainAgentId.CREATIVE,
            evidence_id="echo-2",
            source_id="shared-external-source",
        )
        assessment = self._supported_collaboration(
            reviews=[review_a, review_b], quorum=2
        )
        decision = evaluate_collaboration(assessment)
        self.assertNotEqual(
            decision.disposition,
            CollaborationDisposition.ACCEPT,
            "reviewer diversity must not be mistaken for independent evidence diversity",
        )

    def test_conflicting_reuse_of_evidence_identity_fails_closed(self):
        request = ClaimEvidenceRequest(
            assessment_id="assessment-conflict",
            goal_id="goal-asi",
            claim_id="proposal-asi",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                self._signal("same-id", source_id="source-a"),
                self._signal(
                    "same-id",
                    source_id="source-b",
                    relation=EvidenceRelation.CONTRADICTS,
                ),
            ],
        )
        with self.assertRaises(ValidationError):
            assess_claim_evidence(request)

    def test_repeated_moderate_evidence_from_one_source_never_becomes_corroboration(self):
        request = ClaimEvidenceRequest(
            assessment_id="assessment-echo",
            goal_id="goal-asi",
            claim_id="proposal-asi",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                self._signal(
                    "moderate-1",
                    source_id="same-source",
                    strength=EvidenceStrength.MODERATE,
                ),
                self._signal(
                    "moderate-2",
                    source_id="same-source",
                    strength=EvidenceStrength.MODERATE,
                ),
            ],
        )
        result = assess_claim_evidence(request)
        self.assertEqual(result.verdict, ClaimVerdict.INSUFFICIENT)

    # --- Long-horizon planning integrity ---

    def test_post_validation_dependency_cycle_is_rejected_before_readiness_is_used(self):
        plan = PlanSnapshot(
            plan_id="plan-asi",
            goal_id="goal-asi",
            steps=[
                PlanStep(
                    step_id="a",
                    goal_id="goal-asi",
                    owner_agent=BrainAgentId.STRATEGIST,
                    objective="establish assumptions",
                ),
                PlanStep(
                    step_id="b",
                    goal_id="goal-asi",
                    owner_agent=BrainAgentId.STRATEGIST,
                    objective="act on assumptions",
                    depends_on=["a"],
                ),
            ],
        )
        plan.steps[0].depends_on = ["b"]

        with self.assertRaises(ValidationError):
            ready_step_ids(plan)

    # --- Reasoning monotonicity under combinatorial pressure ---

    def test_reasoning_policy_is_monotonic_across_all_signal_levels_and_minimum_floors(self):
        levels = list(SignalLevel)
        minimums = list(ReasoningDepth)
        for field_name in (
            "complexity",
            "uncertainty",
            "consequence",
            "evidence_conflict",
        ):
            for minimum in minimums:
                previous_rank = -1
                for level in levels:
                    kwargs = {
                        "assessment_id": f"mono-{field_name}-{minimum.value}-{level.value}",
                        "goal_id": "goal-asi",
                        "agent_id": BrainAgentId.CMO,
                        "complexity": SignalLevel.LOW,
                        "uncertainty": SignalLevel.LOW,
                        "consequence": SignalLevel.LOW,
                        "evidence_conflict": SignalLevel.LOW,
                        "reversibility": Reversibility.REVERSIBLE,
                        "minimum_depth": minimum,
                    }
                    kwargs[field_name] = level
                    decision = select_reasoning_depth(ReasoningAssessment(**kwargs))
                    rank = _DEPTH_RANK[decision.depth]
                    self.assertGreaterEqual(rank, _DEPTH_RANK[minimum])
                    self.assertGreaterEqual(
                        rank,
                        previous_rank,
                        f"raising {field_name} reduced reasoning depth",
                    )
                    previous_rank = rank


if __name__ == "__main__":
    unittest.main()
