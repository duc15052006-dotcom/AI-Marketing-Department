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


class RealCountingAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "canonical_external_adapter"

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


class IdempotencyRetiredAliasMigrationV1Tests(unittest.TestCase):
    CAPABILITY_ID = "retired_alias_external_publish"
    PARAMS = {
        "idempotency_key": "idem-retired-alias-0001",
        "payload": {"caption": "same governed action"},
    }

    def test_retired_legacy_alias_reservation_cannot_be_replayed_after_upgrade(self) -> None:
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        adapter = RealCountingAdapter()
        gateway.register_adapter(adapter, aliases=["current_alias_b"])
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Retired alias external publish",
                category=CapabilityCategory.PUBLISH,
                description="Regression for pre-fix idempotency evidence written under a retired alias.",
                provider="current_alias_b",
                supported_agents=["cmo"],
                required_permissions=[PermissionLevel.PUBLISH, PermissionLevel.EXTERNAL_WRITE],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                retry_policy={"max_retries": 0, "backoff_seconds": 0.0, "retryable_errors": []},
            )
        )

        # Simulate durable evidence created by the pre-fix implementation. The old
        # alias is intentionally NOT bound in the upgraded gateway anymore.
        legacy = gateway.idempotency_ledger.reserve(
            capability_id=self.CAPABILITY_ID,
            provider="retired_alias_a",
            idempotency_key=self.PARAMS["idempotency_key"],
            connection_id=None,
            parameters=self.PARAMS,
            business_id=None,
            project_id=None,
            brand_id=None,
        )
        gateway.idempotency_ledger.mark_dispatching(legacy.reservation_id)
        gateway.idempotency_ledger.settle(legacy.reservation_id)

        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=self.PARAMS,
            run_id="RUN-RETIRED-ALIAS-001",
            approved_by="retired alias migration regression",
            risk_level=RiskLevel.CRITICAL,
        )
        replay = gateway.execute(
            ToolRequest(
                run_id="RUN-RETIRED-ALIAS-001",
                agent_id="cmo",
                capability_id=self.CAPABILITY_ID,
                parameters=self.PARAMS,
                approval_token=approval.approval_token,
            )
        )

        self.assertEqual(ExecutionStatus.BLOCKED, replay.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", replay.error_class)
        self.assertEqual(0, adapter.call_count)
        self.assertEqual(1, len(gateway.idempotency_ledger.list_records()))


if __name__ == "__main__":
    unittest.main()
