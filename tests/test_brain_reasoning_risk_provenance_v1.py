"""RED-only adversarial regression for Brain reasoning/risk provenance."""

from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId, DecisionDisposition, DecisionRecord
from brain.decisions import DecisionEvaluationRequest, evaluate_decision
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.reasoning import ReasoningAssessment, Reversibility, SignalLevel


class BrainReasoningRiskProvenanceV1Tests(unittest.TestCase):
    @staticmethod
    def _decision() -> DecisionRecord:
        return DecisionRecord(
            decision_id="D-RISK-1",
            goal_id="G-RISK-1",
            agent_id=BrainAgentId.STRATEGIST,
            statement="Proceed with the evidence-backed decision",
            rationale="The proposal retains canonical supporting evidence.",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["E-RISK-1"],
            confidence=0.9,
        )

    @staticmethod
    def _evidence_request() -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-RISK-1",
            goal_id="G-RISK-1",
            claim_id="D-RISK-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-RISK-1",
                    goal_id="G-RISK-1",
                    claim_id="D-RISK-1",
                    source_id="SRC-RISK-1",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    @staticmethod
    def _reasoning(**updates) -> ReasoningAssessment:
        values = {
            "assessment_id": "RA-RISK-1",
            "goal_id": "G-RISK-1",
            "agent_id": BrainAgentId.STRATEGIST,
            "complexity": SignalLevel.LOW,
            "uncertainty": SignalLevel.LOW,
            "consequence": SignalLevel.LOW,
            "evidence_conflict": SignalLevel.LOW,
            "reversibility": Reversibility.REVERSIBLE,
            "causal_reasoning_required": False,
            "contradiction_resolution_required": False,
        }
        values.update(updates)
        return ReasoningAssessment(**values)

    @classmethod
    def _request(cls, reasoning: ReasoningAssessment) -> DecisionEvaluationRequest:
        return DecisionEvaluationRequest(
            evaluation_id="DE-RISK-1",
            decision=cls._decision(),
            reasoning_assessment=reasoning,
            evidence_request=cls._evidence_request(),
            evidence_assessment=None,
            collaboration_assessment=None,
        )

    def test_self_attested_low_risk_cannot_waive_peer_review_authority(self) -> None:
        """Caller-authored LOW risk must not be authority to skip independent review."""

        result = evaluate_decision(self._request(self._reasoning()))

        self.assertTrue(
            result.peer_review_required,
            "a caller-supplied ReasoningAssessment without authoritative risk provenance must fail closed instead of waiving peer review",
        )
        self.assertNotEqual(
            result.disposition,
            DecisionDisposition.PROCEED,
            "canonical evidence must not combine with self-attested LOW risk to self-authorize PROCEED",
        )

    def test_high_risk_self_attestation_is_already_conservative(self) -> None:
        """Control: the existing policy already blocks an explicitly HIGH consequence."""

        result = evaluate_decision(
            self._request(self._reasoning(consequence=SignalLevel.HIGH))
        )

        self.assertTrue(result.peer_review_required)
        self.assertEqual(result.disposition, DecisionDisposition.ESCALATE)


if __name__ == "__main__":
    unittest.main()
