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
    ExecutionIntentState,
    ExecutionMode,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreError,
)
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class FailBeforeIntentDispatchRepository(ExecutionReceiptRepository):
    """Persist PREPARED, then fail once before the DISPATCHING transition."""

    def __init__(self) -> None:
        super().__init__()
        self.mark_calls = 0

    def mark_execution_intent_dispatching(self, intent_id: str):
        self.mark_calls += 1
        if self.mark_calls == 1:
            raise ReceiptStoreError("INJECTED_MARK_BEFORE_COMMIT_FAILURE")
        return super().mark_execution_intent_dispatching(intent_id)


class CommitThenFailIntentDispatchRepository(ExecutionReceiptRepository):
    """Persist DISPATCHING, then fail once before returning to the gateway."""

    def __init__(self) -> None:
        super().__init__()
        self.mark_calls = 0

    def mark_execution_intent_dispatching(self, intent_id: str):
        self.mark_calls += 1
        stored = super().mark_execution_intent_dispatching(intent_id)
        if self.mark_calls == 1:
            raise ReceiptStoreError("INJECTED_MARK_AFTER_COMMIT_FAILURE")
        return stored


class CountingRealAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "intent_dispatch_transition_real_adapter"

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


class IdempotencyIntentDispatchTransitionFailureV1Tests(unittest.TestCase):
    CAPABILITY_ID = "idempotency_intent_dispatch_transition_publish"
    PARAMS = {
        "idempotency_key": "idem-intent-dispatch-transition-0001",
        "payload": {"caption": "intent dispatch transition regression"},
    }

    def _build_gateway(self, receipts: ExecutionReceiptRepository):
        registry = CapabilityRegistry()
        policy = PolicyEngine()
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
                name="Idempotency intent dispatch transition publish",
                category=CapabilityCategory.PUBLISH,
                description="Regression capability for PREPARED to DISPATCHING failures.",
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
        return gateway, policy, adapter

    def _approved_request(self, policy: PolicyEngine, run_id: str) -> ToolRequest:
        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=self.PARAMS,
            run_id=run_id,
            approved_by="intent dispatch transition regression",
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

    def test_failure_before_dispatch_transition_commit_does_not_poison_key(self) -> None:
        receipts = FailBeforeIntentDispatchRepository()
        gateway, policy, adapter = self._build_gateway(receipts)

        with self.assertRaisesRegex(
            ReceiptStoreError,
            "INJECTED_MARK_BEFORE_COMMIT_FAILURE",
        ):
            gateway.execute(self._approved_request(policy, "RUN-MARK-FAIL-001"))

        self.assertEqual(0, adapter.call_count)
        intents = receipts.list_execution_intents_for_run("RUN-MARK-FAIL-001")
        self.assertEqual(1, len(intents))
        self.assertEqual(ExecutionIntentState.PREPARED, intents[0].state)
        self.assertEqual(0, intents[0].dispatch_count)

        retry_receipt = gateway.execute(
            self._approved_request(policy, "RUN-MARK-FAIL-002")
        )

        self.assertEqual(ExecutionStatus.SUCCESS, retry_receipt.status)
        self.assertEqual(ExecutionMode.REAL, retry_receipt.execution_mode)
        self.assertEqual(1, adapter.call_count)

    def test_failure_after_dispatch_transition_commit_remains_fail_closed(self) -> None:
        receipts = CommitThenFailIntentDispatchRepository()
        gateway, policy, adapter = self._build_gateway(receipts)

        with self.assertRaisesRegex(
            ReceiptStoreError,
            "INJECTED_MARK_AFTER_COMMIT_FAILURE",
        ):
            gateway.execute(self._approved_request(policy, "RUN-MARK-COMMIT-001"))

        self.assertEqual(0, adapter.call_count)
        intents = receipts.list_execution_intents_for_run("RUN-MARK-COMMIT-001")
        self.assertEqual(1, len(intents))
        self.assertEqual(ExecutionIntentState.DISPATCHING, intents[0].state)
        self.assertEqual(1, intents[0].dispatch_count)

        retry_receipt = gateway.execute(
            self._approved_request(policy, "RUN-MARK-COMMIT-002")
        )

        self.assertEqual(ExecutionStatus.BLOCKED, retry_receipt.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", retry_receipt.error_class)
        self.assertEqual(0, adapter.call_count)


if __name__ == "__main__":
    unittest.main()
