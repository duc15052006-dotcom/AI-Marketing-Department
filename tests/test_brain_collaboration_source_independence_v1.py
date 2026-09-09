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
)


class BrainCollaborationSourceIndependenceV1Tests(unittest.TestCase):
    GOAL = "G-SOURCE-INDEPENDENCE"
    PROPOSAL = "D-SOURCE-INDEPENDENCE"

    @classmethod
    def _raw(
        cls,
        assessment_id: str,
        agent_id: BrainAgentId,
        evidence: list[tuple[str, str]],
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id=cls.GOAL,
            claim_id=cls.PROPOSAL,
            agent_id=agent_id,
            evidence=[
                EvidenceSignal(
                    evidence_id=evidence_id,
                    goal_id=cls.GOAL,
                    claim_id=cls.PROPOSAL,
                    source_id=source_id,
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
                for evidence_id, source_id in evidence
            ],
        )

    @classmethod
    def _peer(
        cls,
        reviewer: BrainAgentId,
        review_id: str,
        evidence: list[tuple[str, str]],
    ) -> PeerReview:
        raw = cls._raw(f"EA-{review_id}", reviewer, evidence)
        return PeerReview(
            review_id=review_id,
            goal_id=cls.GOAL,
            proposal_id=cls.PROPOSAL,
            reviewer_agent=reviewer,
            verdict=ClaimVerdict.SUPPORTED,
            rationale="Canonical independent peer evidence.",
            evidence_refs=[evidence_id for evidence_id, _ in evidence],
            evidence_request=raw,
        )

    @classmethod
    def _assessment(
        cls,
        reviews: list[PeerReview],
        *,
        proposal_source: str = "SRC-PROPOSAL",
        quorum: int = 1,
    ) -> CollaborationAssessment:
        proposal_raw = cls._raw(
            "EA-PROPOSAL",
            BrainAgentId.INTELLIGENCE,
            [("E-PROPOSAL", proposal_source)],
        )
        return CollaborationAssessment(
            assessment_id="CA-SOURCE-INDEPENDENCE",
            goal_id=cls.GOAL,
            proposal_id=cls.PROPOSAL,
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-PROPOSAL"],
            proposal_evidence_request=proposal_raw,
            reviews=reviews,
            minimum_supporting_reviewers=quorum,
        )

    def test_same_underlying_source_as_proposal_cannot_manufacture_accept(self) -> None:
        peer = self._peer(
            BrainAgentId.PERFORMANCE,
            "R-SHARED",
            [("E-PEER-SHARED", "SRC-SHARED")],
        )
        decision = evaluate_collaboration(
            self._assessment([peer], proposal_source="SRC-SHARED")
        )
        self.assertEqual(decision.disposition, CollaborationDisposition.INCONCLUSIVE)

    def test_distinct_underlying_source_can_satisfy_single_peer_quorum(self) -> None:
        peer = self._peer(
            BrainAgentId.PERFORMANCE,
            "R-DISTINCT",
            [("E-PEER-DISTINCT", "SRC-PEER")],
        )
        decision = evaluate_collaboration(self._assessment([peer]))
        self.assertEqual(decision.disposition, CollaborationDisposition.ACCEPT)

    def test_two_reviewers_on_one_common_mode_source_cannot_satisfy_quorum_two(self) -> None:
        reviews = [
            self._peer(
                BrainAgentId.PERFORMANCE,
                "R-COMMON-1",
                [("E-COMMON-1", "SRC-COMMON")],
            ),
            self._peer(
                BrainAgentId.CREATIVE,
                "R-COMMON-2",
                [("E-COMMON-2", "SRC-COMMON")],
            ),
        ]
        decision = evaluate_collaboration(self._assessment(reviews, quorum=2))
        self.assertEqual(decision.disposition, CollaborationDisposition.INCONCLUSIVE)

    def test_maximum_matching_is_review_order_invariant(self) -> None:
        flexible = self._peer(
            BrainAgentId.PERFORMANCE,
            "R-FLEX",
            [("E-FLEX-A", "SRC-A"), ("E-FLEX-B", "SRC-B")],
        )
        constrained = self._peer(
            BrainAgentId.CREATIVE,
            "R-CONSTRAINED",
            [("E-CONSTRAINED-A", "SRC-A")],
        )
        forward = evaluate_collaboration(
            self._assessment([flexible, constrained], quorum=2)
        )
        reverse = evaluate_collaboration(
            self._assessment([constrained, flexible], quorum=2)
        )
        self.assertEqual(forward.disposition, CollaborationDisposition.ACCEPT)
        self.assertEqual(reverse.disposition, CollaborationDisposition.ACCEPT)


if __name__ == "__main__":
    unittest.main()
