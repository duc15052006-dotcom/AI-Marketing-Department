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
from schemas.base import ValidationError


class BrainCollaborationQuorumUseBoundaryV1Tests(unittest.TestCase):
    @staticmethod
    def _raw(
        assessment_id: str,
        evidence_id: str,
        source_id: str,
        agent_id: BrainAgentId,
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id="G-QUORUM",
            claim_id="D-QUORUM",
            agent_id=agent_id,
            evidence=[
                EvidenceSignal(
                    evidence_id=evidence_id,
                    goal_id="G-QUORUM",
                    claim_id="D-QUORUM",
                    source_id=source_id,
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    @classmethod
    def _assessment(cls, with_review: bool) -> CollaborationAssessment:
        proposal_raw = cls._raw(
            "EA-PROPOSAL", "E-PROPOSAL", "SRC-PROPOSAL", BrainAgentId.INTELLIGENCE
        )
        reviews = []
        if with_review:
            peer_raw = cls._raw(
                "EA-PEER", "E-PEER", "SRC-PEER", BrainAgentId.PERFORMANCE
            )
            reviews.append(
                PeerReview(
                    review_id="R-PEER",
                    goal_id="G-QUORUM",
                    proposal_id="D-QUORUM",
                    reviewer_agent=BrainAgentId.PERFORMANCE,
                    verdict=ClaimVerdict.SUPPORTED,
                    rationale="Independent canonical support.",
                    evidence_refs=["E-PEER"],
                    evidence_request=peer_raw,
                )
            )
        return CollaborationAssessment(
            assessment_id="CA-QUORUM",
            goal_id="G-QUORUM",
            proposal_id="D-QUORUM",
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-PROPOSAL"],
            proposal_evidence_request=proposal_raw,
            reviews=reviews,
            minimum_supporting_reviewers=1,
        )

    def test_valid_quorum_still_accepts(self) -> None:
        self.assertEqual(
            evaluate_collaboration(self._assessment(with_review=True)).disposition,
            CollaborationDisposition.ACCEPT,
        )

    def test_post_validation_zero_quorum_is_rejected(self) -> None:
        assessment = self._assessment(with_review=False)
        assessment.minimum_supporting_reviewers = 0
        with self.assertRaises(ValidationError):
            evaluate_collaboration(assessment)

    def test_post_validation_quorum_above_four_is_rejected(self) -> None:
        assessment = self._assessment(with_review=True)
        assessment.minimum_supporting_reviewers = 5
        with self.assertRaises(ValidationError):
            evaluate_collaboration(assessment)

    def test_post_validation_fake_author_agent_is_rejected(self) -> None:
        assessment = self._assessment(with_review=True)
        assessment.author_agent = "ASI_6"  # type: ignore[assignment]
        with self.assertRaises(ValidationError):
            evaluate_collaboration(assessment)


if __name__ == "__main__":
    unittest.main()
