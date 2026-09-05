"""Adversarial regression for Brain reasoning/risk provenance."""

from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId, DecisionDisposition, DecisionRecord
from brain.decisions import (
    DecisionEvaluationRequest,
    DecisionRiskRequest,
    DecisionRiskSignal,
    assess_decision_risk,
    evaluate_decision,
)
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.reasoning import ReasoningAssessment, Reversibility, SignalLevel
from schemas.base import ValidationError


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

    @staticmethod
    def _risk_signal(**updates) -> DecisionRiskSignal:
        values = {
            "signal_id": "RS-RISK-1",
            "goal_id": "G-RISK-1",
            "agent_id": BrainAgentId.STRATEGIST,
            "source_id": "POLICY-RISK-1",
            "consequence": SignalLevel.LOW,
            "evidence_conflict": SignalLevel.LOW,
            "reversibility": Reversibility.REVERSIBLE,
        }
        values.update(updates)
        return DecisionRiskSignal(**values)

    @classmethod
    def _risk_request(cls, signals=None) -> DecisionRiskRequest:
        return DecisionRiskRequest(
            assessment_id="RA-RISK-1",
            goal_id="G-RISK-1",
            agent_id=BrainAgentId.STRATEGIST,
            signals=list(signals) if signals is not None else [cls._risk_signal()],
        )

    @classmethod
    def _request(
        cls,
        reasoning: ReasoningAssessment,
        *,
        risk_request: DecisionRiskRequest | None = None,
    ) -> DecisionEvaluationRequest:
        return DecisionEvaluationRequest(
            evaluation_id="DE-RISK-1",
            decision=cls._decision(),
            reasoning_assessment=reasoning,
            risk_request=risk_request,
            evidence_request=cls._evidence_request(),
            evidence_assessment=None,
            collaboration_assessment=None,
        )

    def test_self_attested_low_risk_cannot_waive_peer_review_authority(self) -> None:
        """Caller-authored LOW risk without raw provenance must fail closed."""

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

    def test_canonical_low_risk_provenance_can_waive_peer_review(self) -> None:
        result = evaluate_decision(
            self._request(self._reasoning(), risk_request=self._risk_request())
        )

        self.assertFalse(result.peer_review_required)
        self.assertEqual(result.disposition, DecisionDisposition.PROCEED)

    def test_raw_high_risk_cannot_be_downgraded_by_low_reasoning_summary(self) -> None:
        raw_high = self._risk_request(
            [self._risk_signal(consequence=SignalLevel.HIGH)]
        )

        with self.assertRaises(ValidationError):
            self._request(self._reasoning(consequence=SignalLevel.LOW), risk_request=raw_high)

    def test_multiple_raw_risk_signals_aggregate_worst_case_monotonically(self) -> None:
        request = self._risk_request(
            [
                self._risk_signal(signal_id="RS-LOW", source_id="POLICY-LOW"),
                self._risk_signal(
                    signal_id="RS-HIGH",
                    source_id="POLICY-HIGH",
                    consequence=SignalLevel.HIGH,
                    evidence_conflict=SignalLevel.CRITICAL,
                    reversibility=Reversibility.IRREVERSIBLE,
                ),
            ]
        )

        assessment = assess_decision_risk(request)

        self.assertEqual(assessment.consequence, SignalLevel.HIGH)
        self.assertEqual(assessment.evidence_conflict, SignalLevel.CRITICAL)
        self.assertEqual(assessment.reversibility, Reversibility.IRREVERSIBLE)
        self.assertEqual(assessment.source_ids, ["POLICY-LOW", "POLICY-HIGH"])

    def test_canonical_high_risk_requires_independent_peer_review(self) -> None:
        raw_high = self._risk_request(
            [self._risk_signal(consequence=SignalLevel.HIGH)]
        )
        result = evaluate_decision(
            self._request(
                self._reasoning(consequence=SignalLevel.HIGH),
                risk_request=raw_high,
            )
        )

        self.assertTrue(result.peer_review_required)
        self.assertEqual(result.disposition, DecisionDisposition.ESCALATE)


if __name__ == "__main__":
    unittest.main()
