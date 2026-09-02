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
from tools.idempotency import IdempotencyState
from tools.receipts import (
    ExecutionIntentState,
    ExecutionMode,
    ExecutionReceiptRepository,
    ExecutionStatus,
)
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class ReturnedFailureRealAdapter(BaseCapabilityAdapter):
    def __init__(self, *, error_code: str, simulate_external_acceptance: bool) -> None:
        self.error_code = error_code
        self.simulate_external_acceptance = simulate_external_acceptance
        self.call_count = 0
        self.external_accept_count = 0

    @property
    def adapter_name(self) -> str:
        return "returned_failure_real_adapter"

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
        if self.simulate_external_acceptance:
            self.external_accept_count += 1
        return AdapterResult(
            success=False,
            error_code=self.error_code,
            error_message=(
                "response lost after remote acceptance"
                if self.simulate_external_acceptance
                else "request rejected before external acceptance"
            ),
            execution_mode=ExecutionMode.REAL,
        )


class ConsequentialAdapterResultAmbiguityV1Tests(unittest.TestCase):
    CAPABILITY_ID = "returned_failure_real_publish"

    def _build(self, *, error_code: str, simulate_external_acceptance: bool):
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        adapter = ReturnedFailureRealAdapter(
            error_code=error_code,
            simulate_external_acceptance=simulate_external_acceptance,
        )
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Returned consequential failure ambiguity regression",
                category=CapabilityCategory.PUBLISH,
                description=(
                    "Regression capability for transport-uncertain AdapterResult failures "
                    "after consequential dispatch."
                ),
                provider=adapter.adapter_name,
                supported_agents=["cmo"],
                required_permissions=[
                    PermissionLevel.PUBLISH,
                    PermissionLevel.EXTERNAL_WRITE,
                ],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                retry_policy={
                    "max_retries": 2,
                    "backoff_seconds": 0.0,
                    "retryable_errors": ["NETWORK_ERROR", "TIMEOUT"],
                },
            )
        )
        return gateway, policy, receipts, adapter

    def _execute(
        self,
        gateway: ToolGateway,
        policy: PolicyEngine,
        *,
        run_id: str,
        idempotency_key: str,
    ):
        params = {
            "payload": {"caption": "publish exactly once"},
            "idempotency_key": idempotency_key,
        }
        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=params,
            run_id=run_id,
            approved_by="consequential returned-failure ambiguity regression",
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

    def test_returned_timeout_after_possible_external_acceptance_is_ambiguous(self) -> None:
        gateway, policy, receipts, adapter = self._build(
            error_code="TIMEOUT",
            simulate_external_acceptance=True,
        )

        receipt = self._execute(
            gateway,
            policy,
            run_id="RUN-RETURNED-TIMEOUT-001",
            idempotency_key="idem-returned-timeout-001",
        )

        self.assertEqual(1, adapter.call_count)
        self.assertEqual(1, adapter.external_accept_count)
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("AMBIGUOUS_EXTERNAL_ACTION_OUTCOME", receipt.error_class)
        intents = receipts.list_execution_intents_for_run("RUN-RETURNED-TIMEOUT-001")
        self.assertEqual(1, len(intents))
        self.assertEqual(ExecutionIntentState.AMBIGUOUS, intents[0].state)
        records = gateway.idempotency_ledger.list_records()
        self.assertEqual(1, len(records))
        self.assertEqual(IdempotencyState.AMBIGUOUS, records[0].state)

    def test_deterministic_returned_failure_remains_finalized(self) -> None:
        gateway, policy, receipts, adapter = self._build(
            error_code="INVALID_PARAMETERS",
            simulate_external_acceptance=False,
        )

        receipt = self._execute(
            gateway,
            policy,
            run_id="RUN-RETURNED-DETERMINISTIC-001",
            idempotency_key="idem-returned-deterministic-001",
        )

        self.assertEqual(1, adapter.call_count)
        self.assertEqual(0, adapter.external_accept_count)
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("INVALID_PARAMETERS", receipt.error_class)
        intents = receipts.list_execution_intents_for_run("RUN-RETURNED-DETERMINISTIC-001")
        self.assertEqual(1, len(intents))
        self.assertEqual(ExecutionIntentState.FINALIZED, intents[0].state)
        records = gateway.idempotency_ledger.list_records()
        self.assertEqual(1, len(records))
        self.assertEqual(IdempotencyState.FINALIZED, records[0].state)


if __name__ == "__main__":
    unittest.main()
