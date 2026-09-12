"""Regression tests for Final CMO deployment provenance binding."""

import hashlib
import unittest
from types import SimpleNamespace

from runtime.context import RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.deployment_binding import (
    DEPLOYMENT_ERROR_PREFIX,
    DEPLOYMENT_PROVENANCE_FIELD,
    clear_deployment_binding_registry_for_tests,
)
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionReceipt, ExecutionStatus
from tools.tool_gateway import ToolRequest


class _LineageSpy:
    def __init__(self):
        self.receipts = []

    def add_receipt(self, receipt):
        self.receipts.append(receipt)


class _RuntimeHarness(FiveAgentDepartmentRuntime):
    def __init__(self):
        self.dispatched = []
        self.lineage_inspector = _LineageSpy()

    def _execute_tool_request(self, context, request):
        self.dispatched.append(request)
        return ExecutionReceipt(
            execution_id="EXEC-PUBLISH-001",
            run_id=context.run_id,
            agent_id="cmo",
            capability_id="social_publishing",
            provider="publishing_sandbox",
            status=ExecutionStatus.APPROVAL_REQUIRED,
            request_hash="a" * 64,
            approval_reference="pending_appr_server_001",
        )


class TestFinalCmoDeploymentProvenance(unittest.TestCase):
    def setUp(self):
        clear_deployment_binding_registry_for_tests()

    def _context(self, suffix="001"):
        return RuntimeContext(
            run_id=f"RUN-DEPLOY-BIND-{suffix}",
            objective="Launch governed campaign",
            business_id="BIZ-DEPLOY-001",
            project_id="PROJ-DEPLOY-001",
            chat_id="CHAT-DEPLOY-001",
            campaign_id="CAMP-DEPLOY-001",
            status=RuntimeStatus.RUNNING,
            current_stage=RuntimeStage.FINAL_CMO,
        )

    @staticmethod
    def _ready_output(markdown="# Final GTM\n\nApproved deployment plan."):
        return {
            "stage": "FINAL_CMO",
            "agent": "cmo",
            "status": "READY_FOR_DEPLOYMENT",
            "approval_status": "APPROVED",
            "reason": "",
            "claim_audit": {"authorization_status": "APPROVED"},
            "master_gtm_plan": {"objective": "Launch governed campaign"},
            "master_gtm_plan_markdown": markdown,
        }

    def _bind_ready_output(self, ctx):
        output = self._ready_output()
        ctx.stage_outputs["final_cmo"] = output
        checkpoint = ctx.create_checkpoint()
        self.assertIn(DEPLOYMENT_PROVENANCE_FIELD, output)
        return output, checkpoint

    def test_publish_before_final_cmo_fails_closed_without_tool_dispatch(self):
        ctx = self._context("PRE")
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(runtime.dispatched, [])
        self.assertEqual(ctx.execution_receipt_refs, [])

    def test_not_ready_final_cmo_fails_closed_without_tool_dispatch(self):
        ctx = self._context("NOTREADY")
        ctx.stage_outputs["final_cmo"] = {
            "stage": "FINAL_CMO",
            "status": "NOT_READY",
            "master_gtm_plan_markdown": "# Not deployable",
        }
        ctx.create_checkpoint()
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(runtime.dispatched, [])

    def test_ready_publish_uses_actual_final_markdown_and_bound_checkpoint(self):
        ctx = self._context("READY")
        final_output, final_checkpoint = self._bind_ready_output(ctx)
        runtime = _RuntimeHarness()

        receipt = runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(len(runtime.dispatched), 1)
        request = runtime.dispatched[0]
        self.assertEqual(request.parameters["content"], final_output["master_gtm_plan_markdown"])
        self.assertNotEqual(request.parameters["content"], "Campaign Go-To-Market Plan")
        self.assertIs(request.parameters["deployment_approved"], True)
        self.assertEqual(request.parameters["final_cmo_checkpoint_id"], final_checkpoint.checkpoint_id)
        self.assertEqual(request.parameters["final_cmo_checkpoint_hash"], final_checkpoint.checkpoint_hash)
        self.assertEqual(
            request.parameters["final_cmo_output_hash"],
            final_output[DEPLOYMENT_PROVENANCE_FIELD]["output_hash"],
        )
        self.assertEqual(
            request.parameters["final_cmo_content_hash"],
            hashlib.sha256(final_output["master_gtm_plan_markdown"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            request.parameters["final_cmo_content_hash"],
            final_output[DEPLOYMENT_PROVENANCE_FIELD]["content_hash"],
        )
        self.assertEqual(
            request.parameters["final_cmo_manifest_hash"],
            final_output[DEPLOYMENT_PROVENANCE_FIELD]["manifest_hash"],
        )
        self.assertIs(final_output[DEPLOYMENT_PROVENANCE_FIELD]["deployment_approved"], True)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)
        self.assertEqual(ctx.checkpoints[-1].pending_approval_id, "pending_appr_server_001")

    def test_explicitly_unapproved_ready_output_cannot_bind_or_dispatch(self):
        ctx = self._context("UNAPPROVED")
        output = self._ready_output()
        output["approval_status"] = "REJECTED"
        output["claim_audit"]["authorization_status"] = "REJECTED"
        ctx.stage_outputs["final_cmo"] = output
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            ctx.create_checkpoint()

        self.assertNotIn(DEPLOYMENT_PROVENANCE_FIELD, output)
        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")
        self.assertEqual(runtime.dispatched, [])
        self.assertEqual(ctx.execution_receipt_refs, [])

    def test_approval_tamper_after_checkpoint_fails_closed_without_dispatch(self):
        ctx = self._context("APPROVALTAMPER")
        final_output, _ = self._bind_ready_output(ctx)
        final_output["approval_status"] = "REJECTED"
        final_output["claim_audit"]["authorization_status"] = "REJECTED"
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(runtime.dispatched, [])
        self.assertEqual(ctx.execution_receipt_refs, [])

    def test_provenance_deployment_approval_tamper_fails_closed_without_dispatch(self):
        ctx = self._context("PROVAPPROVALTAMPER")
        final_output, _ = self._bind_ready_output(ctx)
        final_output[DEPLOYMENT_PROVENANCE_FIELD]["deployment_approved"] = False
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(runtime.dispatched, [])
        self.assertEqual(ctx.execution_receipt_refs, [])

    def test_markdown_tamper_after_checkpoint_fails_closed(self):
        ctx = self._context("TAMPER")
        final_output, _ = self._bind_ready_output(ctx)
        final_output["master_gtm_plan_markdown"] += "\nTAMPERED"
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(runtime.dispatched, [])

    def test_missing_bound_checkpoint_fails_closed(self):
        ctx = self._context("MISSING")
        self._bind_ready_output(ctx)
        ctx.checkpoints.clear()
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(runtime.dispatched, [])

    def test_checkpoint_or_live_binding_tamper_fails_closed(self):
        ctx = self._context("BINDTAMPER")
        _, checkpoint = self._bind_ready_output(ctx)
        ctx.working_state["final_cmo_deployment_binding"]["output_hash"] = "0" * 64
        runtime = _RuntimeHarness()

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            runtime.request_publish_action(ctx, platform="linkedin")

        self.assertEqual(runtime.dispatched, [])
        self.assertNotEqual(checkpoint.working_state_snapshot["final_cmo_deployment_binding"]["output_hash"], "0" * 64)

    def test_non_runtime_placeholder_publishing_request_remains_compatible(self):
        request = ToolRequest(
            run_id="RUN-DIRECT-PUBLISH-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Explicit direct content"},
        )
        self.assertEqual(request.parameters["content"], "Explicit direct content")


if __name__ == "__main__":
    unittest.main()
