from __future__ import annotations

import unittest
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class BusinessScopeRecordingPublishAdapter(BaseCapabilityAdapter):
    """Records trusted business scope so cross-tenant dispatch is observable."""

    def __init__(self) -> None:
        self.invocations = 0
        self.business_ids: list[str] = []

    @property
    def adapter_name(self) -> str:
        return "social_publish_adapter"

    def execution_mode_for(self, _capability_id: str) -> ExecutionMode:
        return ExecutionMode.SANDBOX

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
        self.invocations += 1
        self.business_ids.append(business_id)
        return AdapterResult(
            success=True,
            data={"business_id": business_id, "published": True},
            execution_mode=ExecutionMode.SANDBOX,
        )


class RuntimeApprovalBusinessScopeAuthorityV1Tests(unittest.TestCase):
    def test_gateway_rejects_approval_bound_to_different_business_before_io(self) -> None:
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        adapter = BusinessScopeRecordingPublishAdapter()
        gateway.register_adapter(adapter, aliases=["social_publish_adapter"])

        run_id = "RUN-BUSINESS-SCOPE-1"
        approved_business = "BIZ_ALPHA"
        attempted_business = "BIZ_BETA"
        parameters = {
            "platform": "linkedin",
            "content": "tenant-scoped consequential action",
        }
        approval = policy.create_server_approval(
            capability_id="social_publishing",
            parameters=parameters,
            run_id=run_id,
            business_id=approved_business,
            approved_by="Business Scope Authority Regression Test",
        )

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-BUSINESS-SCOPE-1",
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id=attempted_business,
            )
        )

        self.assertEqual(
            ExecutionStatus.APPROVAL_REQUIRED,
            receipt.status,
            "CROSS_BUSINESS_APPROVAL_ACCEPTED: ToolGateway executed a request under a different business than the approval authority",
        )
        self.assertEqual("APPROVAL_BUSINESS_MISMATCH", receipt.error_class)
        self.assertEqual(
            0,
            adapter.invocations,
            "CROSS_BUSINESS_EXTERNAL_IO: provider adapter was invoked before business-scope authority mismatch was rejected",
        )
        self.assertEqual([], adapter.business_ids)

        stored = policy.get_approval(approval.approval_token)
        self.assertIsNotNone(stored)
        self.assertFalse(
            stored.claimed,
            "CROSS_BUSINESS_APPROVAL_SPENT: mismatched business request must fail before one-shot authority is claimed",
        )
        self.assertFalse(stored.consumed)


if __name__ == "__main__":
    unittest.main()
