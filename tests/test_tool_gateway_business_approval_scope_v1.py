"""Adversarial regression for ToolGateway approval tenant binding."""

import unittest

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    EvidenceRole,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class RecordingAdapter(BaseCapabilityAdapter):
    adapter_name = "recording"

    def __init__(self) -> None:
        self.calls = []

    def execute(
        self,
        capability_id,
        parameters,
        timeout_seconds=30,
        *,
        run_id="",
        business_id="",
        project_id="",
    ):
        self.calls.append((run_id, business_id, project_id))
        return AdapterResult(success=True, execution_mode=ExecutionMode.SANDBOX)


class ToolGatewayBusinessApprovalScopeTests(unittest.TestCase):
    def test_business_a_approval_cannot_dispatch_for_business_b(self) -> None:
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        gateway = ToolGateway(capability_registry=registry, policy_engine=policy)
        adapter = RecordingAdapter()
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id="tenant_write",
                name="Tenant write",
                description="Consequential tenant-scoped test capability",
                category=CapabilityCategory.FILE_DATA,
                evidence_role=EvidenceRole.ACTION,
                required_permissions=[PermissionLevel.EXTERNAL_WRITE],
                risk_level=RiskLevel.HIGH,
                human_approval_required=True,
                supported_agents=["cmo"],
                provider=adapter.adapter_name,
            )
        )
        parameters = {"value": "approved payload"}
        approval = policy.create_server_approval(
            capability_id="tenant_write",
            parameters=parameters,
            run_id="run-1",
            business_id="BIZ_ALPHA",
        )

        receipt = gateway.execute(
            ToolRequest(
                run_id="run-1",
                agent_id="cmo",
                capability_id="tenant_write",
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id="BIZ_BETA",
            )
        )

        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_BUSINESS_MISMATCH")
        self.assertEqual(adapter.calls, [])
        self.assertFalse(approval.claimed)
        self.assertFalse(approval.consumed)


if __name__ == "__main__":
    unittest.main()
