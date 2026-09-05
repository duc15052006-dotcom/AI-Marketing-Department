from __future__ import annotations

import unittest
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest
from tools.capabilities import CapabilityRegistry


class RealCountingAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "external_publish_adapter"

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


class IdempotencyResolvedProviderAuthorityV1Tests(unittest.TestCase):
    CAPABILITY_ID = "alias_routed_external_publish"
    PARAMS = {
        "idempotency_key": "idem-alias-authority-0001",
        "payload": {"caption": "same governed action"},
    }

    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.policy = PolicyEngine()
        self.receipts = ExecutionReceiptRepository()
        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=self.policy,
            receipt_repository=self.receipts,
        )
        self.adapter = RealCountingAdapter()
        self.gateway.register_adapter(
            self.adapter,
            aliases=["provider_alias_a", "provider_alias_b"],
        )
        self._register_capability("provider_alias_a")

    def _register_capability(self, provider: str) -> None:
        self.registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Alias-routed external publish",
                category=CapabilityCategory.PUBLISH,
                description="Regression capability for provider-alias idempotency authority.",
                provider=provider,
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

    def _approved_execute(self, run_id: str):
        approval = self.policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=self.PARAMS,
            run_id=run_id,
            approved_by="idempotency alias authority regression",
            risk_level=RiskLevel.CRITICAL,
        )
        return self.gateway.execute(
            ToolRequest(
                request_id=f"REQ-{run_id}",
                run_id=run_id,
                agent_id="cmo",
                capability_id=self.CAPABILITY_ID,
                parameters=self.PARAMS,
                approval_token=approval.approval_token,
            )
        )

    def test_same_adapter_authority_cannot_replay_same_key_after_provider_alias_change(self) -> None:
        first = self._approved_execute("RUN-ALIAS-AUTHORITY-001")
        self.assertEqual(ExecutionStatus.SUCCESS, first.status)
        self.assertEqual("external_publish_adapter", first.provider)
        self.assertEqual(1, self.adapter.call_count)

        # The capability is rebound from alias A to alias B, but both names route
        # to the exact same concrete adapter/external execution authority.
        self._register_capability("provider_alias_b")
        second = self._approved_execute("RUN-ALIAS-AUTHORITY-002")

        self.assertEqual(ExecutionStatus.BLOCKED, second.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
        self.assertEqual("external_publish_adapter", second.provider)
        self.assertEqual(1, self.adapter.call_count)
        self.assertEqual(1, len(self.gateway.idempotency_ledger.list_records()))

    def test_legacy_alias_reservation_survives_resolved_authority_upgrade(self) -> None:
        # Simulate durable evidence written by the pre-fix implementation, where
        # the provider alias itself was part of the reservation authority.
        legacy = self.gateway.idempotency_ledger.reserve(
            capability_id=self.CAPABILITY_ID,
            provider="provider_alias_a",
            idempotency_key=self.PARAMS["idempotency_key"],
            connection_id=None,
            parameters=self.PARAMS,
            business_id=None,
            project_id=None,
            brand_id=None,
        )
        self.gateway.idempotency_ledger.mark_dispatching(legacy.reservation_id)
        self.gateway.idempotency_ledger.settle(legacy.reservation_id)

        self._register_capability("provider_alias_b")
        replay = self._approved_execute("RUN-LEGACY-ALIAS-AUTHORITY-001")

        self.assertEqual(ExecutionStatus.BLOCKED, replay.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", replay.error_class)
        self.assertEqual("external_publish_adapter", replay.provider)
        self.assertEqual(0, self.adapter.call_count)
        self.assertEqual(1, len(self.gateway.idempotency_ledger.list_records()))


if __name__ == "__main__":
    unittest.main()
