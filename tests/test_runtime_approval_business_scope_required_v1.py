from __future__ import annotations

import unittest
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class BusinessScopeRecordingPublishAdapter(BaseCapabilityAdapter):
    """Records trusted business scope so missing-scope dispatch is observable."""

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


class RuntimeApprovalBusinessScopeRequiredV1Tests(unittest.TestCase):
    def _make_gateway(self) -> tuple[ToolGateway, PolicyEngine, BusinessScopeRecordingPublishAdapter]:
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
        return gateway, policy, adapter

    def _approve_pending_for_business(
        self,
        *,
        gateway: ToolGateway,
        policy: PolicyEngine,
        request_id: str,
        run_id: str,
        business_id: str,
        parameters: Dict[str, Any],
    ):
        pending_receipt = gateway.execute(
            ToolRequest(
                request_id=request_id,
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                business_id=business_id,
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, pending_receipt.status)
        self.assertTrue(pending_receipt.approval_reference)
        approved, approval, reason = policy.approve_pending_action(
            pending_receipt.approval_reference,
            approved_by="Business Scope Required Regression Test",
        )
        self.assertTrue(approved, reason)
        self.assertIsNotNone(approval)
        return approval

    def test_same_business_pending_approval_executes(self) -> None:
        gateway, policy, adapter = self._make_gateway()
        run_id = "RUN-BUSINESS-SCOPE-REQUIRED-CONTROL"
        business_id = "BIZ_ALPHA"
        parameters = {
            "platform": "linkedin",
            "content": "business-scoped consequential action",
        }
        approval = self._approve_pending_for_business(
            gateway=gateway,
            policy=policy,
            request_id="REQ-BUSINESS-SCOPE-REQUIRED-CONTROL-PENDING",
            run_id=run_id,
            business_id=business_id,
            parameters=parameters,
        )

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-BUSINESS-SCOPE-REQUIRED-CONTROL-EXECUTE",
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id=business_id,
            )
        )

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.invocations)
        self.assertEqual([business_id], adapter.business_ids)

    def test_gateway_rejects_business_bound_approval_when_request_omits_business_scope_before_io(self) -> None:
        gateway, policy, adapter = self._make_gateway()
        run_id = "RUN-BUSINESS-SCOPE-REQUIRED-ATTACK"
        business_id = "BIZ_ALPHA"
        parameters = {
            "platform": "linkedin",
            "content": "business-scoped consequential action",
        }
        approval = self._approve_pending_for_business(
            gateway=gateway,
            policy=policy,
            request_id="REQ-BUSINESS-SCOPE-REQUIRED-ATTACK-PENDING",
            run_id=run_id,
            business_id=business_id,
            parameters=parameters,
        )

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-BUSINESS-SCOPE-REQUIRED-ATTACK-EXECUTE",
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id=None,
            )
        )

        self.assertEqual(
            ExecutionStatus.APPROVAL_REQUIRED,
            receipt.status,
            "MISSING_BUSINESS_SCOPE_APPROVAL_ACCEPTED: business-bound approval authorized an unscoped request",
        )
        self.assertEqual("APPROVAL_BUSINESS_SCOPE_REQUIRED", receipt.error_class)
        self.assertEqual(
            0,
            adapter.invocations,
            "MISSING_BUSINESS_SCOPE_EXTERNAL_IO: provider adapter was invoked before business-scope authority was rejected",
        )
        self.assertEqual([], adapter.business_ids)

        stored = policy.get_approval(approval.approval_token)
        self.assertIsNotNone(stored)
        self.assertFalse(
            stored.claimed,
            "MISSING_BUSINESS_SCOPE_APPROVAL_SPENT: unscoped request must fail before one-shot authority is claimed",
        )
        self.assertFalse(stored.consumed)


if __name__ == "__main__":
    unittest.main()
