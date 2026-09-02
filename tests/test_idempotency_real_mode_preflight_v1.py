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


class ResultDeclaredRealAdapter(BaseCapabilityAdapter):
    """Valid adapter contract: REAL provenance is declared only in AdapterResult."""

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "result_declared_real_adapter"

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


class IdempotencyRealModePreflightV1Tests(unittest.TestCase):
    CAPABILITY_ID = "result_declared_real_publish"
    PARAMS = {
        "idempotency_key": "idem-real-result-only-0001",
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
        self.adapter = ResultDeclaredRealAdapter()
        self.gateway.register_adapter(self.adapter)
        self.registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Result-declared REAL publish",
                category=CapabilityCategory.PUBLISH,
                description=(
                    "Regression capability whose adapter is REAL according to the "
                    "AdapterResult contract but does not implement an optional "
                    "preflight execution_mode_for hook."
                ),
                provider=self.adapter.adapter_name,
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
            approved_by="real mode preflight regression",
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

    def test_real_result_without_preflight_hook_cannot_bypass_idempotency(self) -> None:
        first = self._approved_execute("RUN-REAL-MODE-PREFLIGHT-001")
        self.assertEqual(ExecutionStatus.SUCCESS, first.status)
        self.assertEqual(ExecutionMode.REAL, first.execution_mode)
        self.assertEqual(1, self.adapter.call_count)

        # Fresh approval/new run represents a legitimate retry boundary. The same
        # governed action and explicit idempotency key must still fail closed even
        # when REAL provenance is only known through AdapterResult.
        second = self._approved_execute("RUN-REAL-MODE-PREFLIGHT-002")

        self.assertEqual(ExecutionStatus.BLOCKED, second.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
        self.assertEqual(1, self.adapter.call_count)
        self.assertEqual(1, len(self.gateway.idempotency_ledger.list_records()))


if __name__ == "__main__":
    unittest.main()
