"""Adversarial RED for Runtime -> ToolGateway canonical Brain authority propagation.

Invariant: Runtime must have one trusted dispatch seam that can carry an exact
canonical ActionIntent + DecisionEvaluationRequest into ToolGateway unchanged.
When that trusted resolver is configured, missing or malformed authority must
fail closed before any adapter dispatch; Runtime must never silently downgrade
back to the legacy ToolGateway path.
"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

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
from runtime.context import RuntimeContext
from runtime.engine import FiveAgentDepartmentRuntime
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


_AUTHORITY_TYPE = getattr(action_policy, "BrainActionAuthority", None)
_RUNTIME_HELPER = getattr(FiveAgentDepartmentRuntime, "_execute_tool_request", None)


class CountingSearchAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.dispatch_count = 0

    @property
    def adapter_name(self) -> str:
        return "counting_runtime_search_adapter"

    def execute(
        self,
        capability_id,
        parameters,
        timeout_seconds=30.0,
        *,
        run_id="",
        business_id="",
        project_id="",
    ):
        self.dispatch_count += 1
        return AdapterResult(
            success=True,
            data={"capability_id": capability_id},
            execution_mode=ExecutionMode.MOCK,
        )


class BrainRuntimeCanonicalActionIntentHandoffV1Tests(unittest.TestCase):
    @staticmethod
    def _signal(evidence_id: str, *, source_id: str = "SRC-RT-1") -> EvidenceSignal:
        return EvidenceSignal(
            evidence_id=evidence_id,
            goal_id="G-RT-1",
            claim_id="D-RT-1",
            source_id=source_id,
            relation=EvidenceRelation.SUPPORTS,
            strength=EvidenceStrength.STRONG,
            origin=EvidenceOrigin.OBSERVED,
        )

    @classmethod
    def _evidence_request(cls) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-RT-1",
            goal_id="G-RT-1",
            claim_id="D-RT-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[cls._signal("E-RT-1")],
        )

    @staticmethod
    def _reasoning() -> ReasoningAssessment:
        return ReasoningAssessment(
            assessment_id="RA-RT-1",
            goal_id="G-RT-1",
            agent_id=BrainAgentId.CONTENT,
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
            decision_id="D-RT-1",
            goal_id="G-RT-1",
            agent_id=BrainAgentId.CONTENT,
            statement="Collect bounded market evidence",
            rationale="Canonical evidence and independent review support research.",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["E-RT-1"],
            confidence=0.9,
        )

    @classmethod
    def _collaboration(cls) -> CollaborationAssessment:
        peer_raw = ClaimEvidenceRequest(
            assessment_id="EA-RT-R1",
            goal_id="G-RT-1",
            claim_id="D-RT-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[cls._signal("E-RT-R1", source_id="SRC-RT-R1")],
        )
        return CollaborationAssessment(
            assessment_id="CA-RT-1",
            goal_id="G-RT-1",
            proposal_id="D-RT-1",
            author_agent=BrainAgentId.CONTENT,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-RT-1"],
            reviews=[
                PeerReview(
                    review_id="R-RT-1",
                    goal_id="G-RT-1",
                    proposal_id="D-RT-1",
                    reviewer_agent=BrainAgentId.INTELLIGENCE,
                    verdict=ClaimVerdict.SUPPORTED,
                    rationale="Independent evidence-backed review supports research.",
                    evidence_refs=["E-RT-R1"],
                    evidence_request=peer_raw,
                )
            ],
            minimum_supporting_reviewers=1,
        )

    @classmethod
    def _decision_request(cls) -> DecisionEvaluationRequest:
        raw = cls._evidence_request()
        return DecisionEvaluationRequest(
            evaluation_id="DE-RT-1",
            decision=cls._decision(),
            reasoning_assessment=cls._reasoning(),
            evidence_request=raw,
            evidence_assessment=assess_claim_evidence(raw),
            collaboration_assessment=cls._collaboration(),
        )

    @staticmethod
    def _intent() -> ActionIntent:
        return ActionIntent(
            intent_id="AI-RT-1",
            goal_id="G-RT-1",
            owner_agent=BrainAgentId.CONTENT,
            purpose="Collect authoritative market evidence",
            capability_need="MARKET_RESEARCH",
            expected_observation="Grounded market observations",
            decision_id="D-RT-1",
            evidence_required=True,
        )

    @staticmethod
    def _request() -> ToolRequest:
        return ToolRequest(
            request_id="REQ-RT-1",
            run_id="RUN-RT-1",
            agent_id="strategist",
            capability_id="web_search",
            parameters={"query": "bounded market evidence"},
            business_id="BIZ-RT-1",
        )

    @staticmethod
    def _context() -> RuntimeContext:
        return RuntimeContext(
            run_id="RUN-RT-1",
            objective="bounded market evidence",
            business_id="BIZ-RT-1",
        )

    def _gateway(self, tmp):
        repo = ExecutionReceiptRepository(database_path=Path(tmp) / "receipts.sqlite3")
        gateway = ToolGateway(
            capability_registry=CapabilityRegistry(),
            receipt_repository=repo,
        )
        adapter = CountingSearchAdapter()
        gateway.bind_adapter_alias("search_adapter", adapter)
        return gateway, repo, adapter

    def test_brain_action_authority_envelope_exists(self):
        self.assertIsNotNone(
            _AUTHORITY_TYPE,
            "STILL_PRESENT: no typed BrainActionAuthority envelope exists for Runtime handoff.",
        )

    def test_runtime_constructor_exposes_trusted_authority_resolver(self):
        parameters = inspect.signature(FiveAgentDepartmentRuntime.__init__).parameters
        self.assertIn(
            "brain_action_authority_resolver",
            parameters,
            "STILL_PRESENT: Runtime has no trusted Brain action authority resolver seam.",
        )

    def test_runtime_routes_all_tool_dispatch_through_one_authority_helper(self):
        self.assertTrue(
            callable(_RUNTIME_HELPER),
            "STILL_PRESENT: Runtime has no canonical tool dispatch helper.",
        )
        source = inspect.getsource(FiveAgentDepartmentRuntime)
        direct_count = source.count("self.tool_gateway.execute(")
        self.assertEqual(
            direct_count,
            1,
            f"STILL_PRESENT: Runtime still contains {direct_count} direct ToolGateway.execute call sites instead of one authority seam.",
        )

    @unittest.skipUnless(_AUTHORITY_TYPE is not None and callable(_RUNTIME_HELPER), "RED authority seam absent")
    def test_valid_authority_is_forwarded_exactly_and_dispatches_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            gateway, repo, adapter = self._gateway(tmp)
            authority = _AUTHORITY_TYPE(
                action_intent=self._intent(),
                decision_request=self._decision_request(),
            )
            seen = []

            def resolver(context, request):
                seen.append((context, request))
                return authority

            runtime = FiveAgentDepartmentRuntime(
                tool_gateway=gateway,
                brain_action_authority_resolver=resolver,
            )
            try:
                receipt = runtime._execute_tool_request(self._context(), self._request())
            finally:
                repo.close()

        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(adapter.dispatch_count, 1)
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0][1].parameters, seen[0][1].parameters)

    @unittest.skipUnless(_AUTHORITY_TYPE is not None and callable(_RUNTIME_HELPER), "RED authority seam absent")
    def test_configured_resolver_missing_authority_fails_before_adapter_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            gateway, repo, adapter = self._gateway(tmp)
            runtime = FiveAgentDepartmentRuntime(
                tool_gateway=gateway,
                brain_action_authority_resolver=lambda _context, _request: None,
            )
            try:
                with self.assertRaisesRegex(RuntimeError, "BRAIN_ACTION_AUTHORITY_REQUIRED"):
                    runtime._execute_tool_request(self._context(), self._request())
            finally:
                repo.close()
        self.assertEqual(adapter.dispatch_count, 0)

    @unittest.skipUnless(_AUTHORITY_TYPE is not None and callable(_RUNTIME_HELPER), "RED authority seam absent")
    def test_configured_resolver_raw_dict_cannot_self_attest_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            gateway, repo, adapter = self._gateway(tmp)
            runtime = FiveAgentDepartmentRuntime(
                tool_gateway=gateway,
                brain_action_authority_resolver=lambda _context, _request: {
                    "action_intent": self._intent(),
                    "decision_request": self._decision_request(),
                },
            )
            try:
                with self.assertRaisesRegex(RuntimeError, "BRAIN_ACTION_AUTHORITY_REQUIRED"):
                    runtime._execute_tool_request(self._context(), self._request())
            finally:
                repo.close()
        self.assertEqual(adapter.dispatch_count, 0)


if __name__ == "__main__":
    unittest.main()
