"""Regression tests for ToolGateway side-effect-safe retry semantics.

FIX-TOOLGATEWAY-IDEMPOTENCY-01
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class SequenceAdapter(BaseCapabilityAdapter):
    """Adapter returning/raising a deterministic sequence while recording calls."""

    def __init__(self, name: str, outcomes: List[Any]) -> None:
        self._name = name
        self._outcomes = list(outcomes)
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        self.call_count += 1
        self.calls.append(
            {
                "capability_id": capability_id,
                "parameters": dict(parameters),
                "timeout_seconds": timeout_seconds,
                "run_id": run_id,
                "business_id": business_id,
                "project_id": project_id,
            }
        )
        if not self._outcomes:
            raise AssertionError("SequenceAdapter exhausted configured outcomes")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class TestToolGatewayIdempotency01(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.policy = PolicyEngine()
        self.receipts = ExecutionReceiptRepository()
        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=self.policy,
            receipt_repository=self.receipts,
        )

    @staticmethod
    def _success(data: Dict[str, Any] | None = None) -> AdapterResult:
        return AdapterResult(success=True, data=data or {"ok": True})

    @staticmethod
    def _failure(code: str, message: str = "deterministic failure") -> AdapterResult:
        return AdapterResult(success=False, error_code=code, error_message=message)

    def _register_safe_capability(self, capability_id: str, adapter: SequenceAdapter) -> None:
        self.gateway.register_adapter(adapter)
        self.registry.register_capability(
            CapabilityDescriptor(
                capability_id=capability_id,
                name="Safe Retry Test Capability",
                category=CapabilityCategory.OBSERVE,
                description="Read-only deterministic retry test.",
                provider=adapter.adapter_name,
                supported_agents=["intelligence"],
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                retry_policy={
                    "max_retries": 2,
                    "backoff_seconds": 0.0,
                    "retryable_errors": ["NETWORK_ERROR", "TIMEOUT"],
                },
            )
        )

    def _approved_request(
        self,
        capability_id: str,
        adapter: SequenceAdapter,
        *,
        parameters: Dict[str, Any] | None = None,
        run_id: str = "RUN-IDEMPOTENCY-001",
    ) -> tuple[ToolRequest, str]:
        params = parameters or {"payload": "approved external action"}
        self.gateway.register_adapter(adapter)
        approval = self.policy.create_server_approval(
            capability_id=capability_id,
            parameters=params,
            run_id=run_id,
            approved_by="ToolGateway regression test",
            risk_level=RiskLevel.CRITICAL,
        )
        req = ToolRequest(
            request_id="REQ-IDEMPOTENCY-001",
            run_id=run_id,
            agent_id="cmo",
            capability_id=capability_id,
            parameters=params,
            approval_token=approval.approval_token,
        )
        return req, approval.approval_token

    def test_publish_exception_does_not_retry_and_records_ambiguous_outcome(self) -> None:
        adapter = SequenceAdapter(
            "social_publish_adapter",
            [TimeoutError("remote response lost"), self._success()],
        )
        req, token = self._approved_request("social_publishing", adapter)

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME")
        self.assertIn("automatic retry was suppressed", receipt.error_message or "")
        self.assertNotEqual(receipt.approval_reference, token)
        self.assertTrue((receipt.approval_reference or "").startswith("approval_ref_"))
        self.assertEqual(len(self.receipts.list_receipts_for_run(req.run_id)), 1)
        approval = self.policy.get_approval(token)
        self.assertIsNotNone(approval)
        self.assertTrue(approval.consumed)

    def test_scheduling_exception_does_not_retry(self) -> None:
        adapter = SequenceAdapter(
            "schedule_adapter",
            [ConnectionError("connection reset after dispatch"), self._success()],
        )
        req, _ = self._approved_request("content_scheduling", adapter)

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME")

    def test_platform_operation_exception_does_not_retry(self) -> None:
        adapter = SequenceAdapter(
            "ad_platform_adapter",
            [ConnectionError("connection reset after campaign update"), self._success()],
        )
        req, _ = self._approved_request("platform_operations", adapter)

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME")

    def test_safe_read_retries_explicit_network_error_then_succeeds(self) -> None:
        adapter = SequenceAdapter(
            "safe_network_adapter",
            [self._failure("NETWORK_ERROR"), self._success({"attempt": 2})],
        )
        self._register_safe_capability("safe_network_search", adapter)
        req = ToolRequest(
            request_id="REQ-SAFE-NETWORK",
            run_id="RUN-SAFE-001",
            agent_id="intelligence",
            capability_id="safe_network_search",
            parameters={"query": "market"},
        )

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 2)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.data, {"attempt": 2})

    def test_safe_read_retries_explicit_timeout_then_succeeds(self) -> None:
        adapter = SequenceAdapter(
            "safe_timeout_adapter",
            [self._failure("TIMEOUT"), self._success({"attempt": 2})],
        )
        self._register_safe_capability("safe_timeout_search", adapter)
        req = ToolRequest(
            request_id="REQ-SAFE-TIMEOUT",
            run_id="RUN-SAFE-002",
            agent_id="intelligence",
            capability_id="safe_timeout_search",
            parameters={"query": "market"},
        )

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 2)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)

    def test_safe_read_generic_exception_does_not_blindly_retry(self) -> None:
        adapter = SequenceAdapter(
            "safe_generic_exception_adapter",
            [RuntimeError("unexpected adapter defect"), self._success()],
        )
        self._register_safe_capability("safe_generic_exception_search", adapter)
        req = ToolRequest(
            request_id="REQ-SAFE-GENERIC",
            run_id="RUN-SAFE-003",
            agent_id="intelligence",
            capability_id="safe_generic_exception_search",
            parameters={"query": "market"},
        )

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "EXECUTION_EXCEPTION")

    def test_safe_read_non_retryable_structured_error_does_not_retry(self) -> None:
        adapter = SequenceAdapter(
            "safe_invalid_adapter",
            [self._failure("INVALID_PARAMETERS"), self._success()],
        )
        self._register_safe_capability("safe_invalid_search", adapter)
        req = ToolRequest(
            request_id="REQ-SAFE-INVALID",
            run_id="RUN-SAFE-004",
            agent_id="intelligence",
            capability_id="safe_invalid_search",
            parameters={"query": "market"},
        )

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "INVALID_PARAMETERS")

    def test_approval_is_one_shot_after_ambiguous_publish_exception(self) -> None:
        adapter = SequenceAdapter(
            "social_publish_adapter",
            [ConnectionError("response lost"), self._success()],
        )
        req, token = self._approved_request("social_publishing", adapter)

        first = self.gateway.execute(req)
        second = self.gateway.execute(req)

        self.assertEqual(first.error_class, "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME")
        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(second.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertIn(
            second.error_class,
            {"APPROVAL_ALREADY_CONSUMED", "APPROVAL_ALREADY_CLAIMED"},
        )
        approval = self.policy.get_approval(token)
        self.assertIsNotNone(approval)
        self.assertTrue(approval.consumed)

    def test_safe_retry_preserves_logical_request_identity_and_hash(self) -> None:
        adapter = SequenceAdapter(
            "safe_identity_adapter",
            [self._failure("NETWORK_ERROR"), self._success({"attempt": 2})],
        )
        self._register_safe_capability("safe_identity_search", adapter)
        params = {"query": "identity test", "page": 1}
        req = ToolRequest(
            request_id="REQ-STABLE-IDENTITY",
            run_id="RUN-STABLE-IDENTITY",
            agent_id="intelligence",
            capability_id="safe_identity_search",
            parameters=params,
        )
        expected_hash = req.calculate_request_hash()

        receipt = self.gateway.execute(req)

        self.assertEqual(adapter.call_count, 2)
        self.assertEqual(receipt.request_hash, expected_hash)
        self.assertEqual(adapter.calls[0]["run_id"], req.run_id)
        self.assertEqual(adapter.calls[1]["run_id"], req.run_id)
        self.assertEqual(adapter.calls[0]["parameters"], params)
        self.assertEqual(adapter.calls[1]["parameters"], params)


if __name__ == "__main__":
    unittest.main()