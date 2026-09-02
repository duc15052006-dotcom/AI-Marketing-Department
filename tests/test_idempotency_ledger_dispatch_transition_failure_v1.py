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
from tools.idempotency import IdempotencyLedger, IdempotencyState, IdempotencyStoreError
from tools.receipts import (
    ExecutionIntentState,
    ExecutionMode,
    ExecutionReceiptRepository,
    ExecutionStatus,
)
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class FailBeforeLedgerDispatch(IdempotencyLedger):
    """Fail once before RESERVED -> DISPATCHING is persisted."""

    def __init__(self) -> None:
        super().__init__()
        self.mark_calls = 0

    def mark_dispatching(self, reservation_id: str):
        self.mark_calls += 1
        if self.mark_calls == 1:
            raise IdempotencyStoreError("INJECTED_LEDGER_MARK_BEFORE_COMMIT_FAILURE")
        return super().mark_dispatching(reservation_id)


class CommitThenFailLedgerDispatch(IdempotencyLedger):
    """Persist DISPATCHING, then fail once before returning to the gateway."""

    def __init__(self) -> None:
        super().__init__()
        self.mark_calls = 0

    def mark_dispatching(self, reservation_id: str):
        self.mark_calls += 1
        stored = super().mark_dispatching(reservation_id)
        if self.mark_calls == 1:
            raise IdempotencyStoreError("INJECTED_LEDGER_MARK_AFTER_COMMIT_FAILURE")
        return stored


class CountingRealAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "ledger_dispatch_transition_real_adapter"

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


class IdempotencyLedgerDispatchTransitionFailureV1Tests(unittest.TestCase):
    CAPABILITY_ID = "idempotency_ledger_dispatch_transition_publish"
    PARAMS = {
        "idempotency_key": "idem-ledger-dispatch-transition-0001",
        "payload": {"caption": "ledger dispatch transition regression"},
    }

    def _build_gateway(self, ledger: IdempotencyLedger):
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository()
        adapter = CountingRealAdapter()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        gateway.idempotency_ledger = ledger
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Idempotency ledger dispatch transition publish",
                category=CapabilityCategory.PUBLISH,
                description="Regression capability for ledger dispatch transition failures.",
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
            approved_by="ledger dispatch transition regression",
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

    def test_failure_before_ledger_dispatch_commit_does_not_poison_key(self) -> None:
        ledger = FailBeforeLedgerDispatch()
        gateway, policy, receipts, adapter = self._build_gateway(ledger)

        first_receipt = gateway.execute(
            self._approved_request(policy, "RUN-LEDGER-MARK-FAIL-001")
        )

        self.assertEqual(ExecutionStatus.ERROR, first_receipt.status)
        self.assertEqual("IDEMPOTENCY_STORE_UNAVAILABLE", first_receipt.error_class)
        self.assertEqual(0, adapter.call_count)
        first_intents = receipts.list_execution_intents_for_run(
            "RUN-LEDGER-MARK-FAIL-001"
        )
        self.assertEqual(1, len(first_intents))
        self.assertEqual(ExecutionIntentState.FINALIZED, first_intents[0].state)
        self.assertEqual(1, first_intents[0].dispatch_count)
        records = ledger.list_records()
        self.assertEqual(1, len(records))
        self.assertEqual(IdempotencyState.RESERVED, records[0].state)

        retry_receipt = gateway.execute(
            self._approved_request(policy, "RUN-LEDGER-MARK-FAIL-002")
        )

        self.assertEqual(ExecutionStatus.SUCCESS, retry_receipt.status)
        self.assertEqual(ExecutionMode.REAL, retry_receipt.execution_mode)
        self.assertEqual(1, adapter.call_count)

    def test_failure_after_ledger_dispatch_commit_remains_fail_closed(self) -> None:
        ledger = CommitThenFailLedgerDispatch()
        gateway, policy, receipts, adapter = self._build_gateway(ledger)

        first_receipt = gateway.execute(
            self._approved_request(policy, "RUN-LEDGER-MARK-COMMIT-001")
        )

        self.assertEqual(ExecutionStatus.ERROR, first_receipt.status)
        self.assertEqual("IDEMPOTENCY_STORE_UNAVAILABLE", first_receipt.error_class)
        self.assertEqual(0, adapter.call_count)
        first_intents = receipts.list_execution_intents_for_run(
            "RUN-LEDGER-MARK-COMMIT-001"
        )
        self.assertEqual(1, len(first_intents))
        self.assertEqual(ExecutionIntentState.FINALIZED, first_intents[0].state)
        records = ledger.list_records()
        self.assertEqual(1, len(records))
        self.assertEqual(IdempotencyState.DISPATCHING, records[0].state)

        retry_receipt = gateway.execute(
            self._approved_request(policy, "RUN-LEDGER-MARK-COMMIT-002")
        )

        self.assertEqual(ExecutionStatus.BLOCKED, retry_receipt.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", retry_receipt.error_class)
        self.assertEqual(0, adapter.call_count)


if __name__ == "__main__":
    unittest.main()
