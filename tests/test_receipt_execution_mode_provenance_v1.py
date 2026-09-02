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
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreIntegrityError,
)
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class ModeFlippingRealAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.mode = ExecutionMode.REAL
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "mode_flipping_external_adapter"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return self.mode

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
        # Simulate a provider/configuration provenance change after the gateway has
        # already classified the consequential dispatch as REAL.
        self.mode = ExecutionMode.MOCK
        return AdapterResult(
            success=True,
            data={"external_side_effect": True, "call_count": self.call_count},
            execution_mode=ExecutionMode.MOCK,
        )


class ReceiptModeTamperingRepository(ExecutionReceiptRepository):
    def finalize_execution_intent(
        self,
        intent_id: str,
        receipt: ExecutionReceipt,
        *,
        ambiguous: bool = False,
    ) -> ExecutionReceipt:
        payload = receipt.model_dump()
        payload["execution_mode"] = ExecutionMode.MOCK
        tampered = ExecutionReceipt(**payload)
        return super().finalize_execution_intent(
            intent_id,
            tampered,
            ambiguous=ambiguous,
        )


class StableRealAdapter(BaseCapabilityAdapter):
    @property
    def adapter_name(self) -> str:
        return "stable_real_external_adapter"

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
        return AdapterResult(
            success=True,
            data={"external_side_effect": True},
            execution_mode=ExecutionMode.REAL,
        )


class ReceiptExecutionModeProvenanceV1Tests(unittest.TestCase):
    CAPABILITY_ID = "execution_mode_provenance_publish"
    PARAMS = {
        "idempotency_key": "idem-execution-mode-provenance-0001",
        "payload": {"caption": "mode provenance regression"},
    }

    def _build_gateway(
        self,
        adapter: BaseCapabilityAdapter,
        *,
        receipts: ExecutionReceiptRepository | None = None,
    ) -> tuple[ToolGateway, PolicyEngine, ExecutionReceiptRepository]:
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipt_repository = receipts or ExecutionReceiptRepository()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipt_repository,
        )
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Execution-mode provenance publish",
                category=CapabilityCategory.PUBLISH,
                description="Regression capability for execution-mode provenance binding.",
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
        return gateway, policy, receipt_repository

    def _approved_request(self, policy: PolicyEngine, run_id: str) -> ToolRequest:
        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=self.PARAMS,
            run_id=run_id,
            approved_by="execution mode provenance regression",
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

    def test_execution_mode_is_pinned_before_consequential_dispatch(self) -> None:
        adapter = ModeFlippingRealAdapter()
        gateway, policy, receipts = self._build_gateway(adapter)

        receipt = gateway.execute(
            self._approved_request(policy, "RUN-MODE-PROVENANCE-001")
        )

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.call_count)
        # The gateway classified the request as REAL before dispatch (which is why
        # durable idempotency was engaged). That provenance must remain pinned for
        # the intent and final receipt even if the adapter later reports MOCK.
        self.assertEqual(ExecutionMode.REAL, receipt.execution_mode)
        intents = receipts.list_execution_intents_for_run("RUN-MODE-PROVENANCE-001")
        self.assertEqual(1, len(intents))
        self.assertEqual(ExecutionMode.REAL, intents[0].execution_mode)

    def test_finalize_rejects_receipt_with_different_execution_mode_than_intent(self) -> None:
        receipts = ReceiptModeTamperingRepository()
        adapter = StableRealAdapter()
        gateway, policy, _ = self._build_gateway(adapter, receipts=receipts)

        with self.assertRaises(ReceiptStoreIntegrityError):
            gateway.execute(
                self._approved_request(policy, "RUN-MODE-PROVENANCE-002")
            )


if __name__ == "__main__":
    unittest.main()
