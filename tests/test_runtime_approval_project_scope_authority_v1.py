from __future__ import annotations

import unittest
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class ProjectScopeRecordingPublishAdapter(BaseCapabilityAdapter):
    """Records trusted project scope so cross-project dispatch is observable."""

    def __init__(self) -> None:
        self.invocations = 0
        self.project_ids: list[str] = []

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
        self.project_ids.append(project_id)
        return AdapterResult(
            success=True,
            data={"project_id": project_id, "published": True},
            execution_mode=ExecutionMode.SANDBOX,
        )


class RuntimeApprovalProjectScopeAuthorityV1Tests(unittest.TestCase):
    def _make_gateway(self) -> tuple[ToolGateway, PolicyEngine, ProjectScopeRecordingPublishAdapter]:
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        adapter = ProjectScopeRecordingPublishAdapter()
        gateway.register_adapter(adapter, aliases=["social_publish_adapter"])
        return gateway, policy, adapter

    def _approve_pending_for_project(
        self,
        *,
        gateway: ToolGateway,
        policy: PolicyEngine,
        request_id: str,
        run_id: str,
        business_id: str,
        project_id: str,
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
                project_id=project_id,
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, pending_receipt.status)
        self.assertTrue(pending_receipt.approval_reference)
        approved, approval, reason = policy.approve_pending_action(
            pending_receipt.approval_reference,
            approved_by="Project Scope Authority Regression Test",
        )
        self.assertTrue(approved, reason)
        self.assertIsNotNone(approval)
        return approval

    def test_same_project_pending_approval_executes(self) -> None:
        gateway, policy, adapter = self._make_gateway()
        run_id = "RUN-PROJECT-SCOPE-CONTROL"
        business_id = "BIZ_PROJECT_SCOPE"
        project_id = "PROJECT_ALPHA"
        parameters = {
            "platform": "linkedin",
            "content": "project-scoped consequential action",
        }
        approval = self._approve_pending_for_project(
            gateway=gateway,
            policy=policy,
            request_id="REQ-PROJECT-SCOPE-CONTROL-PENDING",
            run_id=run_id,
            business_id=business_id,
            project_id=project_id,
            parameters=parameters,
        )

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-PROJECT-SCOPE-CONTROL-EXECUTE",
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id=business_id,
                project_id=project_id,
            )
        )

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.invocations)
        self.assertEqual([project_id], adapter.project_ids)

    def test_gateway_rejects_pending_approval_replayed_into_different_project_before_io(self) -> None:
        gateway, policy, adapter = self._make_gateway()
        run_id = "RUN-PROJECT-SCOPE-ATTACK"
        business_id = "BIZ_PROJECT_SCOPE"
        approved_project = "PROJECT_ALPHA"
        attempted_project = "PROJECT_BETA"
        parameters = {
            "platform": "linkedin",
            "content": "project-scoped consequential action",
        }
        approval = self._approve_pending_for_project(
            gateway=gateway,
            policy=policy,
            request_id="REQ-PROJECT-SCOPE-ATTACK-PENDING",
            run_id=run_id,
            business_id=business_id,
            project_id=approved_project,
            parameters=parameters,
        )

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-PROJECT-SCOPE-ATTACK-EXECUTE",
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id=business_id,
                project_id=attempted_project,
            )
        )

        self.assertEqual(
            ExecutionStatus.APPROVAL_REQUIRED,
            receipt.status,
            "CROSS_PROJECT_APPROVAL_ACCEPTED: approval created from PROJECT_ALPHA pending action authorized PROJECT_BETA",
        )
        self.assertEqual("APPROVAL_PROJECT_MISMATCH", receipt.error_class)
        self.assertEqual(
            0,
            adapter.invocations,
            "CROSS_PROJECT_EXTERNAL_IO: provider adapter was invoked before project-scope authority mismatch was rejected",
        )
        self.assertEqual([], adapter.project_ids)

        stored = policy.get_approval(approval.approval_token)
        self.assertIsNotNone(stored)
        self.assertFalse(
            stored.claimed,
            "CROSS_PROJECT_APPROVAL_SPENT: mismatched project request must fail before one-shot authority is claimed",
        )
        self.assertFalse(stored.consumed)

    def test_blank_or_whitespace_project_scope_is_rejected_before_pending_approval(self) -> None:
        parameters = {
            "platform": "linkedin",
            "content": "malformed project scope must fail closed",
        }
        for project_id in ("", "   "):
            with self.subTest(project_id=repr(project_id)):
                gateway, policy, adapter = self._make_gateway()
                run_id = f"RUN-BLANK-PROJECT-{len(project_id)}"
                receipt = gateway.execute(
                    ToolRequest(
                        request_id=f"REQ-BLANK-PROJECT-{len(project_id)}",
                        run_id=run_id,
                        agent_id="cmo",
                        capability_id="social_publishing",
                        parameters=parameters,
                        business_id="BIZ_PROJECT_SCOPE",
                        project_id=project_id,
                    )
                )

                self.assertEqual(
                    ExecutionStatus.BLOCKED,
                    receipt.status,
                    "EMPTY_PROJECT_SCOPE_ACCEPTED: malformed project scope reached the approval workflow",
                )
                self.assertEqual("PROJECT_SCOPE_INVALID", receipt.error_class)
                self.assertEqual([], policy.list_pending_approvals(run_id=run_id))
                self.assertEqual(0, adapter.invocations)

    def test_unscoped_approval_cannot_authorize_project_scoped_request(self) -> None:
        gateway, policy, adapter = self._make_gateway()
        run_id = "RUN-UNSCOPED-APPROVAL-ATTACK"
        business_id = "BIZ_PROJECT_SCOPE"
        parameters = {
            "platform": "linkedin",
            "content": "unscoped approval must not widen into a project",
        }
        approval = policy.create_server_approval(
            capability_id="social_publishing",
            parameters=parameters,
            run_id=run_id,
            business_id=business_id,
            project_id=None,
            approved_by="Project Scope Authority Regression Test",
        )

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-UNSCOPED-APPROVAL-ATTACK",
                run_id=run_id,
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id=business_id,
                project_id="PROJECT_BETA",
            )
        )

        self.assertEqual(
            ExecutionStatus.APPROVAL_REQUIRED,
            receipt.status,
            "UNSCOPED_APPROVAL_WIDENED: project-scoped action accepted authority that was not project-bound",
        )
        self.assertEqual("APPROVAL_PROJECT_SCOPE_REQUIRED", receipt.error_class)
        self.assertEqual(0, adapter.invocations)
        stored = policy.get_approval(approval.approval_token)
        self.assertIsNotNone(stored)
        self.assertFalse(stored.claimed)
        self.assertFalse(stored.consumed)

    def test_server_approval_rejects_blank_or_whitespace_project_scope(self) -> None:
        policy = PolicyEngine()
        for project_id in ("", "   "):
            with self.subTest(project_id=repr(project_id)):
                with self.assertRaisesRegex(ValueError, "PROJECT_SCOPE_INVALID"):
                    policy.create_server_approval(
                        capability_id="social_publishing",
                        parameters={"content": "scope validation"},
                        run_id="RUN-SERVER-APPROVAL-SCOPE",
                        business_id="BIZ_PROJECT_SCOPE",
                        project_id=project_id,
                    )


if __name__ == "__main__":
    unittest.main()
