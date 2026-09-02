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
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class CountingModeAdapter(BaseCapabilityAdapter):
    def __init__(self, *, name: str, mode: ExecutionMode) -> None:
        self._name = name
        self._mode = mode
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return self._name

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return self._mode

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
            data={"external_side_effect": self._mode == ExecutionMode.REAL},
            execution_mode=self._mode,
        )


class RealConsequentialIdempotencyKeyRequiredV1Tests(unittest.TestCase):
    CAPABILITY_ID = "real_consequential_key_required_publish"

    def _build(self, mode: ExecutionMode):
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        adapter = CountingModeAdapter(
            name=f"key_required_{mode.value.lower()}_adapter",
            mode=mode,
        )
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="REAL consequential idempotency key requirement regression",
                category=CapabilityCategory.PUBLISH,
                description="Regression capability for mandatory REAL-write idempotency authority.",
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

    def _approved_execute(self, gateway: ToolGateway, policy: PolicyEngine, run_id: str):
        params = {"payload": {"caption": "consequential action without key"}}
        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=params,
            run_id=run_id,
            approved_by="real consequential idempotency key regression",
            risk_level=RiskLevel.CRITICAL,
        )
        return gateway.execute(
            ToolRequest(
                request_id=f"REQ-{run_id}",
                run_id=run_id,
                agent_id="cmo",
                capability_id=self.CAPABILITY_ID,
                parameters=params,
                approval_token=approval.approval_token,
            )
        )

    def test_real_consequential_action_without_key_is_blocked_before_dispatch(self) -> None:
        gateway, policy, receipts, adapter = self._build(ExecutionMode.REAL)

        receipt = self._approved_execute(gateway, policy, "RUN-REAL-NO-IDEM-001")

        self.assertEqual(ExecutionStatus.BLOCKED, receipt.status)
        self.assertEqual("IDEMPOTENCY_KEY_REQUIRED", receipt.error_class)
        self.assertEqual(ExecutionMode.REAL, receipt.execution_mode)
        self.assertEqual(0, adapter.call_count)
        self.assertEqual([], receipts.list_execution_intents_for_run("RUN-REAL-NO-IDEM-001"))

    def test_sandbox_consequential_action_without_key_remains_allowed(self) -> None:
        gateway, policy, _, adapter = self._build(ExecutionMode.SANDBOX)

        receipt = self._approved_execute(gateway, policy, "RUN-SANDBOX-NO-IDEM-001")

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(ExecutionMode.SANDBOX, receipt.execution_mode)
        self.assertEqual(1, adapter.call_count)


if __name__ == "__main__":
    unittest.main()
