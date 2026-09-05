"""Adversarial tests for provider-neutral Brain decision intelligence v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.decisions as decisions
from brain.collaboration import CollaborationAssessment, PeerReview
from brain.contracts import BrainAgentId, DecisionDisposition, DecisionRecord
from brain.decisions import DecisionEvaluationRequest, evaluate_decision
from brain.evidence import (
    ClaimEvidenceAssessment,
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
    assess_claim_evidence,
)
from brain.reasoning import ReasoningAssessment, Reversibility, SignalLevel
from schemas.base import ValidationError


class BrainDecisionIntelligenceV1Tests(unittest.TestCase):
    @staticmethod
    def _decision(**updates) -> DecisionRecord:
        values = {
            "decision_id": "D-1",
            "goal_id": "G-1",
            "agent_id": BrainAgentId.STRATEGIST,
            "statement": "Proceed with a bounded acquisition experiment",
            "rationale": "The tested hypothesis currently has supporting evidence.",
            "disposition": DecisionDisposition.PROCEED,
            "evidence_refs": ["E-1"],
            "confidence": 0.9,
        }
        values.update(updates)
        return DecisionRecord(**values)

    @staticmethod
    def _signal(
        evidence_id: str,
        relation: EvidenceRelation,
        *,
        source_id: str,
        strength: EvidenceStrength = EvidenceStrength.STRONG,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
        goal_id: str = "G-1",
        claim_id: str = "D-1",
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

    @classmethod
    def _evidence_request(cls, **updates) -> ClaimEvidenceRequest:
        values = {
            "assessment_id": "EA-1",
            "goal_id": "G-1",
            "claim_id": "D-1",
            "agent_id": BrainAgentId.INTELLIGENCE,
            "evidence": [
                cls._signal(
                    "E-1",
                    EvidenceRelation.SUPPORTS,
                    source_id="SRC-1",
                )
            ],
        }
        values.update(updates)
        return ClaimEvidenceRequest(**values)

    @staticmethod
    def _fabricated_assessment(**updates) -> ClaimEvidenceAssessment:
        values = {
            "assessment_id": "EA-FORGED",
            "goal_id": "G-1",
            "claim_id": "D-1",
            "agent_id": BrainAgentId.INTELLIGENCE,
            "verdict": ClaimVerdict.SUPPORTED,
            "supporting_evidence_refs": ["E-FORGED"],
            "contradicting_evidence_refs": [],
            "ignored_evidence_refs": [],
            "reasons": ["Caller fabricated a structurally valid evidence assessment."],
        }
        values.update(updates)
        return ClaimEvidenceAssessment(**values)

    @staticmethod
    def _reasoning(**updates) -> ReasoningAssessment:
        values = {
            "assessment_id": "RA-1",
            "goal_id": "G-1",
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
    def _collaboration(**updates) -> CollaborationAssessment:
        values = {
            "assessment_id": "CA-1",
            "goal_id": "G-1",
            "proposal_id": "D-1",
            "author_agent": BrainAgentId.STRATEGIST,
            "proposal_verdict": ClaimVerdict.SUPPORTED,
            "proposal_evidence_refs": ["E-1"],
            "reviews": [
                PeerReview(
                    review_id="R-1",
                    goal_id="G-1",
                    proposal_id="D-1",
                    reviewer_agent=BrainAgentId.INTELLIGENCE,
                    verdict=ClaimVerdict.SUPPORTED,
                    rationale="Independent evidence-backed review supports the proposal.",
                    evidence_refs=["E-R1"],
                )
            ],
            "minimum_supporting_reviewers": 1,
        }
        values.update(updates)
        return CollaborationAssessment(**values)

    @classmethod
    def _request(cls, **updates) -> DecisionEvaluationRequest:
        raw = cls._evidence_request()
        values = {
            "evaluation_id": "DE-1",
            "decision": cls._decision(),
            "reasoning_assessment": cls._reasoning(),
            "evidence_request": raw,
            "evidence_assessment": assess_claim_evidence(raw),
            "collaboration_assessment": None,
        }
        values.update(updates)
        if "evidence_request" in updates and "evidence_assessment" not in updates:
            supplied_raw = updates["evidence_request"]
            values["evidence_assessment"] = (
                assess_claim_evidence(supplied_raw)
                if supplied_raw is not None
                else None
            )
        return DecisionEvaluationRequest(**values)

    def test_low_risk_supported_decision_can_proceed_without_peer_review(self) -> None:
        result = evaluate_decision(self._request())
        self.assertEqual(result.disposition, DecisionDisposition.PROCEED)
        self.assertFalse(result.peer_review_required)
        self.assertEqual(result.verified_evidence_refs, ["E-1"])

    def test_confidence_one_without_raw_evidence_cannot_self_authorize(self) -> None:
        result = evaluate_decision(
            self._request(
                decision=self._decision(confidence=1.0),
                evidence_request=None,
                evidence_assessment=None,
            )
        )
        self.assertEqual(result.disposition, DecisionDisposition.REVISE)
        self.assertEqual(result.verified_evidence_refs, [])

    def test_self_declared_evidence_ref_not_verified_from_raw_evidence_blocks_proceed(self) -> None:
        result = evaluate_decision(
            self._request(decision=self._decision(evidence_refs=["E-INVENTED"]))
        )
        self.assertEqual(result.disposition, DecisionDisposition.REVISE)
        self.assertEqual(result.unverified_evidence_refs, ["E-INVENTED"])

    def test_fabricated_supported_assessment_cannot_authorize_proceed(self) -> None:
        result = evaluate_decision(
            self._request(
                decision=self._decision(evidence_refs=["E-FORGED"]),
                evidence_request=None,
                evidence_assessment=self._fabricated_assessment(),
            )
        )
        self.assertNotEqual(
            result.disposition,
            DecisionDisposition.PROCEED,
            "Decision authorization must not trust a caller-constructed evidence verdict without the raw evidence request that produced it.",
        )
        self.assertEqual(result.verified_evidence_refs, [])
        self.assertEqual(result.unverified_evidence_refs, ["E-FORGED"])

    def test_fabricated_assessment_cannot_disagree_with_raw_evidence(self) -> None:
        raw = self._evidence_request(evidence=[])
        with self.assertRaises(ValidationError):
            self._request(
                evidence_request=raw,
                evidence_assessment=self._fabricated_assessment(
                    assessment_id="EA-1",
                    supporting_evidence_refs=["E-1"],
                ),
            )

    def test_weak_raw_support_cannot_authorize_proceed(self) -> None:
        raw = self._evidence_request(
            evidence=[
                self._signal(
                    "E-1",
                    EvidenceRelation.SUPPORTS,
                    source_id="SRC-1",
                    strength=EvidenceStrength.WEAK,
                )
            ]
        )
        result = evaluate_decision(self._request(evidence_request=raw))
        self.assertEqual(result.disposition, DecisionDisposition.REVISE)
        self.assertEqual(result.verified_evidence_refs, ["E-1"])

    def test_refuted_decision_is_revised_despite_high_confidence(self) -> None:
        raw = self._evidence_request(
            evidence=[
                self._signal(
                    "E-X",
                    EvidenceRelation.CONTRADICTS,
                    source_id="SRC-X",
                )
            ]
        )
        result = evaluate_decision(
            self._request(
                decision=self._decision(evidence_refs=["E-X"], confidence=1.0),
                evidence_request=raw,
            )
        )
        self.assertEqual(result.disposition, DecisionDisposition.REVISE)

    def test_contested_decision_escalates_instead_of_averaging_evidence(self) -> None:
        raw = self._evidence_request(
            evidence=[
                self._signal(
                    "E-S",
                    EvidenceRelation.SUPPORTS,
                    source_id="SRC-S",
                ),
                self._signal(
                    "E-X",
                    EvidenceRelation.CONTRADICTS,
                    source_id="SRC-X",
                ),
            ]
        )
        result = evaluate_decision(
            self._request(
                decision=self._decision(evidence_refs=["E-S"]),
                evidence_request=raw,
            )
        )
        self.assertEqual(result.disposition, DecisionDisposition.ESCALATE)

    def test_insufficient_evidence_requires_revision(self) -> None:
        raw = self._evidence_request(evidence=[])
        result = evaluate_decision(
            self._request(
                decision=self._decision(evidence_refs=[]),
                evidence_request=raw,
            )
        )
        self.assertEqual(result.disposition, DecisionDisposition.REVISE)

    def test_cross_goal_or_wrong_claim_raw_evidence_cannot_be_laundered(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(evidence_request=self._evidence_request(goal_id="G-OTHER"))
        with self.assertRaises(ValidationError):
            self._request(evidence_request=self._evidence_request(claim_id="D-OTHER"))

    def test_cross_goal_or_wrong_claim_audit_assessment_cannot_be_laundered(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                evidence_request=None,
                evidence_assessment=self._fabricated_assessment(goal_id="G-OTHER"),
            )
        with self.assertRaises(ValidationError):
            self._request(
                evidence_request=None,
                evidence_assessment=self._fabricated_assessment(claim_id="D-OTHER"),
            )

    def test_reasoning_identity_must_match_decision_owner_and_goal(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(reasoning_assessment=self._reasoning(goal_id="G-OTHER"))
        with self.assertRaises(ValidationError):
            self._request(
                reasoning_assessment=self._reasoning(agent_id=BrainAgentId.CREATIVE)
            )

    def test_high_consequence_requires_independent_peer_review(self) -> None:
        result = evaluate_decision(
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH)
            )
        )
        self.assertTrue(result.peer_review_required)
        self.assertEqual(result.disposition, DecisionDisposition.ESCALATE)

    def test_irreversible_decision_requires_independent_peer_review(self) -> None:
        result = evaluate_decision(
            self._request(
                reasoning_assessment=self._reasoning(
                    reversibility=Reversibility.IRREVERSIBLE
                )
            )
        )
        self.assertTrue(result.peer_review_required)
        self.assertEqual(result.disposition, DecisionDisposition.ESCALATE)

    def test_high_risk_exact_peer_acceptance_can_authorize_proceed(self) -> None:
        result = evaluate_decision(
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                collaboration_assessment=self._collaboration(),
            )
        )
        self.assertTrue(result.peer_review_required)
        self.assertEqual(result.disposition, DecisionDisposition.PROCEED)
        self.assertEqual(result.collaboration_assessment_id, "CA-1")

    def test_collaboration_requires_raw_primary_evidence_provenance(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                evidence_request=None,
                evidence_assessment=self._fabricated_assessment(
                    supporting_evidence_refs=["E-1"]
                ),
                collaboration_assessment=self._collaboration(),
            )

    def test_collaboration_must_bind_exact_goal_decision_author_and_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                collaboration_assessment=self._collaboration(goal_id="G-OTHER"),
            )
        with self.assertRaises(ValidationError):
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                collaboration_assessment=self._collaboration(proposal_id="D-OTHER"),
            )
        with self.assertRaises(ValidationError):
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                collaboration_assessment=self._collaboration(
                    author_agent=BrainAgentId.CREATIVE
                ),
            )
        with self.assertRaises(ValidationError):
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                collaboration_assessment=self._collaboration(
                    proposal_evidence_refs=["E-OTHER"]
                ),
            )

    def test_peer_refutation_on_high_risk_decision_forces_revision(self) -> None:
        refuting_review = PeerReview(
            review_id="R-D",
            goal_id="G-1",
            proposal_id="D-1",
            reviewer_agent=BrainAgentId.INTELLIGENCE,
            verdict=ClaimVerdict.REFUTED,
            rationale="Independent observed evidence contradicts the proposal.",
            evidence_refs=["E-DISSENT"],
        )
        result = evaluate_decision(
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                collaboration_assessment=self._collaboration(reviews=[refuting_review]),
            )
        )
        self.assertEqual(result.disposition, DecisionDisposition.REVISE)

    def test_peer_contestation_on_high_risk_decision_escalates(self) -> None:
        contested_review = PeerReview(
            review_id="R-C",
            goal_id="G-1",
            proposal_id="D-1",
            reviewer_agent=BrainAgentId.INTELLIGENCE,
            verdict=ClaimVerdict.CONTESTED,
            rationale="Credible observations remain contradictory.",
            evidence_refs=["E-C1", "E-C2"],
        )
        result = evaluate_decision(
            self._request(
                reasoning_assessment=self._reasoning(consequence=SignalLevel.HIGH),
                collaboration_assessment=self._collaboration(reviews=[contested_review]),
            )
        )
        self.assertEqual(result.disposition, DecisionDisposition.ESCALATE)

    def test_conservative_requested_disposition_is_never_silently_upgraded(self) -> None:
        revise = evaluate_decision(
            self._request(decision=self._decision(disposition=DecisionDisposition.REVISE))
        )
        escalate = evaluate_decision(
            self._request(decision=self._decision(disposition=DecisionDisposition.ESCALATE))
        )
        self.assertEqual(revise.disposition, DecisionDisposition.REVISE)
        self.assertEqual(escalate.disposition, DecisionDisposition.ESCALATE)

    def test_self_declared_stop_is_not_goal_completion_authority(self) -> None:
        result = evaluate_decision(
            self._request(decision=self._decision(disposition=DecisionDisposition.STOP))
        )
        self.assertEqual(result.disposition, DecisionDisposition.ESCALATE)

    def test_decision_policy_has_no_body_or_provider_dependency(self) -> None:
        source = inspect.getsource(decisions)
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
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

        serialized = str(evaluate_decision(self._request()).model_dump()).lower()
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
