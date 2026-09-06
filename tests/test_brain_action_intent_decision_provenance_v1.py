"""Adversarial RED for semantic ActionIntent -> canonical Decision provenance.

This slice hardens Brain semantics only. Runtime/ToolGateway wiring is a separate
integration slice so this test must not weaken or bypass the validated V1 runtime
Brain veto seam.
"""

from __future__ import annotations

import unittest

import brain.action_policy as action_policy
from brain.collaboration import CollaborationAssessment, PeerReview
from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
)
from brain.decisions import DecisionEvaluationRequest
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


_HAS_SEMANTIC_AUTHORIZER = callable(
    getattr(action_policy, "authorize_action_intent", None)
)


class BrainActionIntentDecisionProvenanceV1Tests(unittest.TestCase):
    @staticmethod
    def _signal(
        evidence_id: str,
        *,
        claim_id: str = "D-1",
        source_id: str = "SRC-1",
    ) -> EvidenceSignal:
        return EvidenceSignal(
            evidence_id=evidence_id,
            goal_id="G-1",
            claim_id=claim_id,
            source_id=source_id,
            relation=EvidenceRelation.SUPPORTS,
            strength=EvidenceStrength.STRONG,
            origin=EvidenceOrigin.OBSERVED,
        )

    @classmethod
    def _evidence_request(cls) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-1",
            goal_id="G-1",
            claim_id="D-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[cls._signal("E-1")],
        )

    @staticmethod
    def _reasoning() -> ReasoningAssessment:
        return ReasoningAssessment(
            assessment_id="RA-1",
            goal_id="G-1",
            agent_id=BrainAgentId.STRATEGIST,
            complexity=SignalLevel.LOW,
            uncertainty=SignalLevel.LOW,
            consequence=SignalLevel.LOW,
            evidence_conflict=SignalLevel.LOW,
            reversibility=Reversibility.REVERSIBLE,
            causal_reasoning_required=False,
            contradiction_resolution_required=False,
        )

    @classmethod
    def _decision(cls) -> DecisionRecord:
        return DecisionRecord(
            decision_id="D-1",
            goal_id="G-1",
            agent_id=BrainAgentId.STRATEGIST,
            statement="Proceed with a bounded acquisition experiment",
            rationale="The exact proposal has canonical supporting evidence.",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["E-1"],
            confidence=0.9,
        )

    @classmethod
    def _collaboration(cls) -> CollaborationAssessment:
        peer_raw = ClaimEvidenceRequest(
            assessment_id="EA-R1",
            goal_id="G-1",
            claim_id="D-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                cls._signal(
                    "E-R1",
                    source_id="SRC-R1",
                )
            ],
        )
        return CollaborationAssessment(
            assessment_id="CA-1",
            goal_id="G-1",
            proposal_id="D-1",
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-1"],
            reviews=[
                PeerReview(
                    review_id="R-1",
                    goal_id="G-1",
                    proposal_id="D-1",
                    reviewer_agent=BrainAgentId.INTELLIGENCE,
                    verdict=ClaimVerdict.SUPPORTED,
                    rationale="Independent evidence-backed review supports the proposal.",
                    evidence_refs=["E-R1"],
                    evidence_request=peer_raw,
                )
            ],
            minimum_supporting_reviewers=1,
        )

    @classmethod
    def _decision_request(cls, *, with_peer_review: bool) -> DecisionEvaluationRequest:
        raw = cls._evidence_request()
        return DecisionEvaluationRequest(
            evaluation_id="DE-1",
            decision=cls._decision(),
            reasoning_assessment=cls._reasoning(),
            evidence_request=raw,
            evidence_assessment=assess_claim_evidence(raw),
            collaboration_assessment=(
                cls._collaboration() if with_peer_review else None
            ),
        )

    @staticmethod
    def _intent(*, decision_id=None, goal_id: str = "G-1", owner=BrainAgentId.STRATEGIST):
        values = {
            "intent_id": "AI-1",
            "goal_id": goal_id,
            "owner_agent": owner,
            "purpose": "Run the evidence-backed acquisition experiment",
            "capability_need": "MARKET_RESEARCH",
            "expected_observation": "Observed acquisition response",
            "evidence_required": True,
            "constraints": ["bounded experiment"],
        }
        if decision_id is not None:
            values["decision_id"] = decision_id
        return ActionIntent(**values)

    def test_semantic_action_authorizer_contract_exists(self) -> None:
        self.assertTrue(
            _HAS_SEMANTIC_AUTHORIZER,
            "STILL_PRESENT: Brain has no semantic ActionIntent authorization boundary bound to canonical Decision provenance.",
        )

    @unittest.skipUnless(
        _HAS_SEMANTIC_AUTHORIZER,
        "RED contract absent until production implementation exists",
    )
    def test_unbound_action_intent_cannot_self_authorize(self) -> None:
        result = action_policy.authorize_action_intent(
            self._intent(),
            self._decision_request(with_peer_review=True),
        )
        self.assertEqual(result.disposition, action_policy.ActionDisposition.BLOCK)
        self.assertIn("DECISION_PROVENANCE_REQUIRED", result.reason)

    @unittest.skipUnless(
        _HAS_SEMANTIC_AUTHORIZER,
        "RED contract absent until production implementation exists",
    )
    def test_mismatched_decision_id_cannot_launder_authority(self) -> None:
        result = action_policy.authorize_action_intent(
            self._intent(decision_id="D-OTHER"),
            self._decision_request(with_peer_review=True),
        )
        self.assertEqual(result.disposition, action_policy.ActionDisposition.BLOCK)
        self.assertIn("DECISION_ID_MISMATCH", result.reason)

    @unittest.skipUnless(
        _HAS_SEMANTIC_AUTHORIZER,
        "RED contract absent until production implementation exists",
    )
    def test_non_proceed_canonical_decision_cannot_authorize_action(self) -> None:
        result = action_policy.authorize_action_intent(
            self._intent(decision_id="D-1"),
            self._decision_request(with_peer_review=False),
        )
        self.assertEqual(result.disposition, action_policy.ActionDisposition.BLOCK)
        self.assertIn("DECISION_NOT_AUTHORIZED", result.reason)

    @unittest.skipUnless(
        _HAS_SEMANTIC_AUTHORIZER,
        "RED contract absent until production implementation exists",
    )
    def test_goal_or_owner_mismatch_cannot_reuse_proceed_authority(self) -> None:
        for intent in (
            self._intent(decision_id="D-1", goal_id="G-OTHER"),
            self._intent(decision_id="D-1", owner=BrainAgentId.CREATIVE),
        ):
            with self.subTest(goal_id=intent.goal_id, owner=intent.owner_agent):
                result = action_policy.authorize_action_intent(
                    intent,
                    self._decision_request(with_peer_review=True),
                )
                self.assertEqual(
                    result.disposition,
                    action_policy.ActionDisposition.BLOCK,
                )
                self.assertIn("DECISION_CONTEXT_MISMATCH", result.reason)

    @unittest.skipUnless(
        _HAS_SEMANTIC_AUTHORIZER,
        "RED contract absent until production implementation exists",
    )
    def test_exact_canonical_proceed_authorizes_bound_action_intent(self) -> None:
        result = action_policy.authorize_action_intent(
            self._intent(decision_id="D-1"),
            self._decision_request(with_peer_review=True),
        )
        self.assertEqual(result.disposition, action_policy.ActionDisposition.ALLOW)
        self.assertEqual(result.intent_id, "AI-1")
        self.assertIn("CANONICAL_DECISION_PROCEED", result.reason)


if __name__ == "__main__":
    unittest.main()
