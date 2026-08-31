"""Adversarial regressions for conditional Final-CMO authorization.

Only an explicit deterministic APPROVED decision may become deployment-ready or
permit autonomous external actions. APPROVED_WITH_CONDITIONS and PENDING are
non-terminal authorization states and must remain human-gated.
"""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from governance.claim_safety import FinalClaimAuditGateResult
from governance.runtime_engine import GovernedExecutionPipeline
from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from schemas.protocol import ActionRequest, AgentRole, ApprovalState, PermissionMode


class TestConditionalApprovalNoDeploy(unittest.TestCase):
    @staticmethod
    def _conditional_audit() -> FinalClaimAuditGateResult:
        return FinalClaimAuditGateResult(
            total_claims=1,
            supported_claims=0,
            unknown_claims=1,
            hypotheses_count=0,
            blocked_claims=0,
            human_input_required_count=1,
            authorization_status="APPROVED_WITH_CONDITIONS",
            blocking_reasons=[],
            claim_actions={"CLM-NEEDS-HUMAN": "REQUEST_HUMAN_INPUT"},
        )

    @staticmethod
    def _action() -> ActionRequest:
        return ActionRequest(
            action_id="ACT-CONDITIONAL-001",
            agent_name=AgentRole.PERFORMANCE,
            product_id="PROD-001",
            campaign_id="CAMP-001",
            platform_target="Meta Ads API",
            requested_action="DEPLOY_AD_SET",
        )

    def test_final_cmo_conditional_authorization_is_not_deployment_ready(self) -> None:
        runtime = FiveAgentDepartmentRuntime()
        context = RuntimeContext(
            objective="Prepare a governed campaign plan",
            business_id="BIZ-001",
            project_id="PROJ-001",
            chat_id="CHAT-001",
            status=RuntimeStatus.RUNNING,
        )
        context.stage_outputs = {
            "cmo_initial": {"status": "COMPLETED", "strategic_intent": "Plan"},
            "intelligence": {"status": "COMPLETED", "market_findings": "Findings"},
            "strategist": {"status": "COMPLETED", "positioning": "Positioning"},
            "creative": {"status": "COMPLETED", "creative_synthesis": "Creative"},
            "performance": {"status": "COMPLETED", "funnel_kpi": "Measurement plan"},
        }
        grounded = SimpleNamespace(provenance_index={}, render_prompt_section=lambda: "")

        with patch.object(runtime.context_compiler, "compile_grounded_package", return_value=grounded), \
             patch.object(runtime, "_call_agent_llm", return_value=("# Governed GTM Plan\nHuman input remains required.", None)), \
             patch.object(runtime, "_evaluate_final_authorization", return_value=self._conditional_audit()), \
             patch.object(runtime, "_finalize_stage_handoff", side_effect=lambda _ctx, _stage, _agent, _raw, output, **_kw: (output, None, "ABSENT")):
            output = runtime.execute_stage_final_cmo(context)

        self.assertEqual(output["approval_status"], "APPROVED_WITH_CONDITIONS")
        self.assertNotEqual(output["status"], "READY_FOR_DEPLOYMENT")
        self.assertEqual(output["status"], "READY_FOR_HUMAN_APPROVAL")
        self.assertNotEqual(context.status, RuntimeStatus.FAILED)

    def test_autonomous_action_cannot_bypass_conditional_authorization(self) -> None:
        pipeline = GovernedExecutionPipeline(register_id="COND-AUTH-001")
        pipeline.final_authorization = "APPROVED_WITH_CONDITIONS"
        pipeline.final_audit_result = self._conditional_audit()

        result = pipeline.validate_action_request(
            self._action(), permission_mode=PermissionMode.AUTONOMOUS
        )

        self.assertEqual(result["decision"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(result["approval_state"], ApprovalState.PENDING_APPROVAL)
        self.assertNotEqual(result["decision"], "AUTHORIZED")

    def test_autonomous_action_cannot_bypass_pending_authorization(self) -> None:
        pipeline = GovernedExecutionPipeline(register_id="PENDING-AUTH-001")
        pipeline.final_authorization = "PENDING"

        result = pipeline.validate_action_request(
            self._action(), permission_mode=PermissionMode.AUTONOMOUS
        )

        self.assertEqual(result["decision"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(result["approval_state"], ApprovalState.PENDING_APPROVAL)
        self.assertNotEqual(result["decision"], "AUTHORIZED")

    def test_explicit_approved_still_allows_autonomous_action(self) -> None:
        pipeline = GovernedExecutionPipeline(register_id="APPROVED-AUTH-001")
        pipeline.final_authorization = "APPROVED"

        result = pipeline.validate_action_request(
            self._action(), permission_mode=PermissionMode.AUTONOMOUS
        )

        self.assertEqual(result["decision"], "AUTHORIZED")
        self.assertEqual(result["approval_state"], ApprovalState.APPROVED)


if __name__ == "__main__":
    unittest.main()
