"""Adversarial regression for peer-review evidence provenance authority."""

from __future__ import annotations

import unittest

from brain.collaboration import CollaborationAssessment, PeerReview
from brain.contracts import BrainAgentId, DecisionDisposition, DecisionRecord
from brain.decisions import DecisionEvaluationRequest, evaluate_decision
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
    assess_claim_evidence,
)
from brain.reasoning import ReasoningAssessment, Reversibility, SignalLevel


class BrainPeerReviewEvidenceProvenanceV1Tests(unittest.TestCase):
    def test_fabricated_peer_review_evidence_refs_cannot_authorize_high_risk_proceed(self) -> None:
        decision = DecisionRecord(
            decision_id="D-PEER-PROV",
            goal_id="G-PEER-PROV",
            agent_id=BrainAgentId.STRATEGIST,
            statement="Authorize a high-consequence launch.",
            rationale="Primary evidence supports the proposal, but peer evidence must be independently proven.",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["E-PRIMARY"],
            confidence=0.9,
        )
        reasoning = ReasoningAssessment(
            assessment_id="RA-PEER-PROV",
            goal_id="G-PEER-PROV",
            agent_id=BrainAgentId.STRATEGIST,
            complexity=SignalLevel.LOW,
            uncertainty=SignalLevel.LOW,
            consequence=SignalLevel.HIGH,
            evidence_conflict=SignalLevel.LOW,
            reversibility=Reversibility.REVERSIBLE,
            causal_reasoning_required=False,
            contradiction_resolution_required=False,
        )
        raw_primary = ClaimEvidenceRequest(
            assessment_id="EA-PRIMARY",
            goal_id="G-PEER-PROV",
            claim_id="D-PEER-PROV",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-PRIMARY",
                    goal_id="G-PEER-PROV",
                    claim_id="D-PEER-PROV",
                    source_id="SRC-PRIMARY",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )
        primary_assessment = assess_claim_evidence(raw_primary)

        forged_peer_review = PeerReview(
            review_id="R-FORGED",
            goal_id="G-PEER-PROV",
            proposal_id="D-PEER-PROV",
            reviewer_agent=BrainAgentId.CREATIVE,
            verdict=ClaimVerdict.SUPPORTED,
            rationale="Caller asserts independent support without supplying peer raw evidence.",
            evidence_refs=["E-PEER-FORGED"],
        )
        collaboration = CollaborationAssessment(
            assessment_id="CA-PEER-PROV",
            goal_id="G-PEER-PROV",
            proposal_id="D-PEER-PROV",
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=list(primary_assessment.supporting_evidence_refs),
            reviews=[forged_peer_review],
            minimum_supporting_reviewers=1,
        )

        result = evaluate_decision(
            DecisionEvaluationRequest(
                evaluation_id="DE-PEER-PROV",
                decision=decision,
                reasoning_assessment=reasoning,
                evidence_request=raw_primary,
                evidence_assessment=primary_assessment,
                collaboration_assessment=collaboration,
            )
        )

        self.assertNotEqual(
            result.disposition,
            DecisionDisposition.PROCEED,
            "A caller-constructed PeerReview must not satisfy the high-risk gate merely by naming non-empty evidence_refs without raw peer evidence provenance.",
        )


if __name__ == "__main__":
    unittest.main()
