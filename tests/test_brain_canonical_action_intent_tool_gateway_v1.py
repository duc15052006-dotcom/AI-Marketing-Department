"""Adversarial RED for canonical semantic ActionIntent -> ToolGateway handoff.

Invariant: when a trusted runtime supplies semantic Brain authority, ToolGateway
must bind the exact ActionIntent to trusted capability metadata and canonical
Decision provenance before its existing structural Brain veto.  It must never
replace that semantic identity with BRAIN-ACTION-{request_id}.

This slice deliberately does not persist ActionIntent provenance into receipts;
that remains a later isolated hardening step after the handoff is trustworthy.
"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from brain.action_policy import ActionAuthorization, ActionDisposition
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
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionReceiptRepository, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class BrainCanonicalActionIntentToolGatewayV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.receipt_repo = ExecutionReceiptRepository(
            database_path=Path(self._tmp.name) / "receipts.sqlite3"
        )

    def tearDown(self) -> None:
        self.receipt_repo.close()
        self._tmp.cleanup()

    @staticmethod
    def _signal(
        evidence_id: str,
        *,
        claim_id: str = "D-GW-1",
        source_id: str = "SRC-GW-1",
    ) -> EvidenceSignal:
        return EvidenceSignal(
            evidence_id=evidence_id,
            goal_id="G-GW-1",
            claim_id=claim_id,
            source_id=source_id,
            relation=EvidenceRelation.SUPPORTS,
            strength=EvidenceStrength.STRONG,
            origin=EvidenceOrigin.OBSERVED,
        )

    @classmethod
    def _evidence_request(cls) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-GW-1",
            goal_id="G-GW-1",
            claim_id="D-GW-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[cls._signal("E-GW-1")],
        )

    @staticmethod
    def _reasoning() -> ReasoningAssessment:
        return ReasoningAssessment(
            assessment_id="RA-GW-1",
            goal_id="G-GW-1",
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
            decision_id="D-GW-1",
            goal_id="G-GW-1",
            agent_id=BrainAgentId.STRATEGIST,
            statement="Collect bounded market evidence",
            rationale="Canonical evidence and independent review support research.",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["E-GW-1"],
            confidence=0.9,
        )

    @classmethod
    def _collaboration(cls) -> CollaborationAssessment:
        peer_raw = ClaimEvidenceRequest(
            assessment_id="EA-GW-R1",
            goal_id="G-GW-1",
            claim_id="D-GW-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[cls._signal("E-GW-R1", source_id="SRC-GW-R1")],
        )
        return CollaborationAssessment(
            assessment_id="CA-GW-1",
            goal_id="G-GW-1",
            proposal_id="D-GW-1",
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-GW-1"],
            reviews=[
                PeerReview(
                    review_id="R-GW-1",
                    goal_id="G-GW-1",
                    proposal_id="D-GW-1",
                    reviewer_agent=BrainAgentId.INTELLIGENCE,
                    verdict=ClaimVerdict.SUPPORTED,
                    rationale="Independent evidence-backed review supports research.",
                    evidence_refs=["E-GW-R1"],
                    evidence_request=peer_raw,
                )
            ],
            minimum_supporting_reviewers=1,
        )

    @classmethod
    def _decision_request(cls) -> DecisionEvaluationRequest:
        raw = cls._evidence_request()
        return DecisionEvaluationRequest(
            evaluation_id="DE-GW-1",
            decision=cls._decision(),
            reasoning_assessment=cls._reasoning(),
            evidence_request=raw,
            evidence_assessment=assess_claim_evidence(raw),
            collaboration_assessment=cls._collaboration(),
        )

    @staticmethod
    def _intent(
        *,
        decision_id: str = "D-GW-1",
        capability_need: str = "MARKET_RESEARCH",
        owner: BrainAgentId = BrainAgentId.STRATEGIST,
    ) -> ActionIntent:
        return ActionIntent(
            intent_id="AI-GW-1",
            goal_id="G-GW-1",
            owner_agent=owner,
            purpose="Collect authoritative market evidence",
            capability_need=capability_need,
            expected_observation="Grounded market observations",
            decision_id=decision_id,
            evidence_required=True,
            constraints=["bounded research"],
        )

    @staticmethod
    def _request(*, agent_id: str = "strategist") -> ToolRequest:
        return ToolRequest(
            request_id="REQ-GW-1",
            run_id="RUN-GW-1",
            agent_id=agent_id,
            capability_id="web_search",
            parameters={"query": "market evidence"},
        )

    def _gateway(self, observed):
        def structural_veto(intent):
            observed.append(intent)
            return ActionAuthorization(
                intent_id=intent.intent_id,
                disposition=ActionDisposition.BLOCK,
                reason="test structural veto after semantic validation",
            )

        return ToolGateway(
            capability_registry=CapabilityRegistry(),
            receipt_repository=self.receipt_repo,
            action_authorizer=structural_veto,
        )

    def test_execute_exposes_keyword_only_semantic_authority_channel(self) -> None:
        parameters = inspect.signature(ToolGateway.execute).parameters
        self.assertIn(
            "action_intent",
            parameters,
            "STILL_PRESENT: ToolGateway.execute has no canonical ActionIntent handoff.",
        )
        self.assertIn(
            "decision_request",
            parameters,
            "STILL_PRESENT: ToolGateway cannot recompute canonical Decision authority at dispatch boundary.",
        )
        self.assertEqual(parameters["action_intent"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(parameters["decision_request"].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_missing_entire_canonical_context_fails_closed_before_structural_veto(self) -> None:
        observed = []
        gateway = self._gateway(observed)
        receipt = gateway.execute(self._request())
        self.assertEqual(
            observed,
            [],
            "STILL_PRESENT: ToolGateway dispatched into structural authorization without canonical semantic ActionIntent authority.",
        )
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "BRAIN_ACTION_DENIED")
        self.assertIn("SEMANTIC_ACTION_CONTEXT", receipt.error_message)

    def test_incomplete_semantic_context_fails_closed_before_structural_veto(self) -> None:
        observed = []
        gateway = self._gateway(observed)
        receipt = gateway.execute(
            self._request(),
            action_intent=self._intent(),
        )
        self.assertEqual(observed, [])
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "BRAIN_ACTION_DENIED")
        self.assertIn("SEMANTIC_ACTION_CONTEXT", receipt.error_message)

    def test_capability_need_mismatch_fails_before_structural_veto(self) -> None:
        observed = []
        gateway = self._gateway(observed)
        receipt = gateway.execute(
            self._request(),
            action_intent=self._intent(capability_need="IMAGE_GENERATE"),
            decision_request=self._decision_request(),
        )
        self.assertEqual(observed, [])
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "BRAIN_ACTION_DENIED")
        self.assertIn("CAPABILITY_NEED_MISMATCH", receipt.error_message)

    def test_request_agent_cannot_borrow_another_agents_action_intent(self) -> None:
        observed = []
        gateway = self._gateway(observed)
        receipt = gateway.execute(
            self._request(agent_id="intelligence"),
            action_intent=self._intent(owner=BrainAgentId.STRATEGIST),
            decision_request=self._decision_request(),
        )
        self.assertEqual(observed, [])
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "BRAIN_ACTION_DENIED")
        self.assertIn("ACTION_INTENT_AGENT_MISMATCH", receipt.error_message)

    def test_wrong_decision_provenance_fails_before_structural_veto(self) -> None:
        observed = []
        gateway = self._gateway(observed)
        receipt = gateway.execute(
            self._request(),
            action_intent=self._intent(decision_id="D-OTHER"),
            decision_request=self._decision_request(),
        )
        self.assertEqual(observed, [])
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "BRAIN_ACTION_DENIED")
        self.assertIn("DECISION_ID_MISMATCH", receipt.error_message)

    def test_valid_semantic_context_preserves_exact_intent_identity_into_structural_veto(self) -> None:
        observed = []
        gateway = self._gateway(observed)
        receipt = gateway.execute(
            self._request(),
            action_intent=self._intent(),
            decision_request=self._decision_request(),
        )
        self.assertEqual(len(observed), 1)
        structural_intent = observed[0]
        self.assertEqual(structural_intent.intent_id, "AI-GW-1")
        self.assertNotEqual(structural_intent.intent_id, "BRAIN-ACTION-REQ-GW-1")
        self.assertEqual(structural_intent.capability_id, "web_search")
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "BRAIN_ACTION_DENIED")
        self.assertIn("test structural veto", receipt.error_message)


if __name__ == "__main__":
    unittest.main()
