from __future__ import annotations

import unittest
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class RunScopeRecordingPublishAdapter(BaseCapabilityAdapter):
    """Records dispatch so omitted run authority can be observed before external I/O."""

    def __init__(self) -> None:
        self.invocations = 0
        self.run_ids: list[str] = []

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
        del capability_id, parameters, timeout_seconds, business_id, project_id
        self.invocations += 1
        self.run_ids.append(run_id)
        return AdapterResult(
            success=True,
            data={"run_id": run_id, "published": True},
            execution_mode=ExecutionMode.SANDBOX,
        )


class RuntimeApprovalRunScopeRequiredV1Tests(unittest.TestCase):
    """A run-bound one-shot approval must never authorize an unscoped run request."""

    def _make_gateway(self) -> tuple[ToolGateway, PolicyEngine, RunScopeRecordingPublishAdapter]:
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        adapter = RunScopeRecordingPublishAdapter()
        gateway.register_adapter(adapter, aliases=["social_publish_adapter"])
        return gateway, policy, adapter

    def _server_approval(self, *, policy: PolicyEngine, run_id: str, parameters: Dict[str, Any]):
        return policy.create_server_approval(
            capability_id="social_publishing",
            parameters=parameters,
            run_id=run_id,
            approved_by="Run Scope Required Regression Test",
        )

    def test_same_run_server_approval_executes(self) -> None:
        gateway, policy, adapter = self._make_gateway()
        run_id = "RUN_SCOPE_ALPHA"
        parameters = {
            "platform": "linkedin",
            "content": "run-scoped consequential action",
        }
        approval = self._server_approval(policy=policy, run_id=run_id, parameters=parameters)

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-RUN-SCOPE-CONTROL",
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
            )
        )

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.invocations)
        self.assertEqual([run_id], adapter.run_ids)

    def test_gateway_rejects_run_bound_approval_when_request_omits_run_scope_before_io(self) -> None:
        gateway, policy, adapter = self._make_gateway()
        approved_run_id = "RUN_SCOPE_ALPHA"
        parameters = {
            "platform": "linkedin",
            "content": "run-scoped consequential action",
        }
        approval = self._server_approval(
            policy=policy,
            run_id=approved_run_id,
            parameters=parameters,
        )

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-RUN-SCOPE-ATTACK",
                run_id="",
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
            )
        )

        self.assertEqual(
            ExecutionStatus.APPROVAL_REQUIRED,
            receipt.status,
            "MISSING_RUN_SCOPE_APPROVAL_ACCEPTED: run-bound approval authorized an unscoped request",
        )
        self.assertEqual("APPROVAL_RUN_SCOPE_REQUIRED", receipt.error_class)
        self.assertEqual(
            0,
            adapter.invocations,
            "MISSING_RUN_SCOPE_EXTERNAL_IO: provider adapter was invoked before run authority was rejected",
        )
        self.assertEqual([], adapter.run_ids)

        stored = policy.get_approval(approval.approval_token)
        self.assertIsNotNone(stored)
        self.assertFalse(
            stored.claimed,
            "MISSING_RUN_SCOPE_APPROVAL_SPENT: unscoped request must fail before one-shot authority is claimed",
        )
        self.assertFalse(stored.consumed)


if __name__ == "__main__":
    unittest.main()
