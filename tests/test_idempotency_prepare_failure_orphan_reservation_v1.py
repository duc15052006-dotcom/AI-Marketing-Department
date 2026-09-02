from __future__ import annotations

import unittest
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import (
    ExecutionMode,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreError,
)
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class FailFirstPrepareRepository(ExecutionReceiptRepository):
    """Inject one pre-dispatch durable-intent failure."""

    def __init__(self) -> None:
        super().__init__()
        self.prepare_calls = 0

    def prepare_execution_intent(self, **kwargs):
        self.prepare_calls += 1
        if self.prepare_calls == 1:
            raise ReceiptStoreError("INJECTED_PREPARE_FAILURE")
        return super().prepare_execution_intent(**kwargs)


class CountingRealAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "prepare_failure_real_adapter"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return ExecutionMode.REAL

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
        return AdapterResult(
            success=True,
            data={"external_side_effect": True, "call_count": self.call_count},
            execution_mode=ExecutionMode.REAL,
        )


class IdempotencyPrepareFailureOrphanReservationV1Tests(unittest.TestCase):
    CAPABILITY_ID = "idempotency_prepare_failure_publish"
    PARAMS = {
        "idempotency_key": "idem-prepare-failure-0001",
        "payload": {"caption": "pre-dispatch reservation regression"},
    }

    def _build_gateway(self):
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = FailFirstPrepareRepository()
        adapter = CountingRealAdapter()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Idempotency prepare failure publish",
                category=CapabilityCategory.PUBLISH,
                description="Regression capability for pre-dispatch reservation cleanup.",
                provider=adapter.adapter_name,
                supported_agents=["cmo"],
                required_permissions=[
                    PermissionLevel.PUBLISH,
                    PermissionLevel.EXTERNAL_WRITE,
                ],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                retry_policy={
                    "max_retries": 0,
                    "backoff_seconds": 0.0,
                    "retryable_errors": [],
                },
            )
        )
        return gateway, policy, receipts, adapter

    def _approved_request(self, policy: PolicyEngine, run_id: str) -> ToolRequest:
        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=self.PARAMS,
            run_id=run_id,
            approved_by="idempotency prepare failure regression",
            risk_level=RiskLevel.CRITICAL,
        )
        return ToolRequest(
            request_id=f"REQ-{run_id}",
            run_id=run_id,
            agent_id="cmo",
            capability_id=self.CAPABILITY_ID,
            parameters=self.PARAMS,
            approval_token=approval.approval_token,
        )

    def test_prepare_failure_before_dispatch_does_not_poison_idempotency_key(self) -> None:
        gateway, policy, _, adapter = self._build_gateway()

        with self.assertRaisesRegex(ReceiptStoreError, "INJECTED_PREPARE_FAILURE"):
            gateway.execute(self._approved_request(policy, "RUN-PREPARE-FAIL-001"))

        # The durable intent failed before DISPATCHING and the adapter was never
        # entered, so this key has not authorized any external side effect.
        self.assertEqual(0, adapter.call_count)

        retry_receipt = gateway.execute(
            self._approved_request(policy, "RUN-PREPARE-FAIL-002")
        )

        # A fresh approval using the same semantic action/key must be able to
        # proceed because the first attempt provably never reached dispatch.
        self.assertEqual(ExecutionStatus.SUCCESS, retry_receipt.status)
        self.assertEqual(ExecutionMode.REAL, retry_receipt.execution_mode)
        self.assertEqual(1, adapter.call_count)


if __name__ == "__main__":
    unittest.main()
