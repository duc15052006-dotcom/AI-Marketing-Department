"""Regression lock for the direct Final CMO -> publishing production seam."""

import unittest
from unittest.mock import patch

from runtime.context import RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionReceipt, ExecutionStatus


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
            execution_id="EXEC-DIRECT-SEAM-001",
            run_id=context.run_id,
            agent_id="cmo",
            capability_id="social_publishing",
            provider="publishing_sandbox",
            status=ExecutionStatus.APPROVAL_REQUIRED,
            request_hash="b" * 64,
            approval_reference="pending_direct_server_001",
        )


class TestFinalCmoDirectPublishSeam(unittest.TestCase):
    def test_engine_calls_provenance_builder_before_tool_request_dispatch(self):
        context = RuntimeContext(
            run_id="RUN-DIRECT-SEAM-001",
            objective="Launch governed campaign",
            business_id="BIZ-DIRECT-001",
            project_id="PROJ-DIRECT-001",
            chat_id="CHAT-DIRECT-001",
            campaign_id="CAMP-DIRECT-001",
            status=RuntimeStatus.RUNNING,
            current_stage=RuntimeStage.INIT,
        )
        runtime = _RuntimeHarness()
        bound_parameters = {
            "platform": "linkedin",
            "content": "# Checkpoint-bound Final GTM\n\nApproved deployment plan.",
            "final_cmo_binding_id": "FCMO-BIND-DIRECT-SEAM",
            "final_cmo_output_hash": "1" * 64,
            "final_cmo_content_hash": "2" * 64,
            "final_cmo_manifest_hash": "3" * 64,
            "final_cmo_checkpoint_id": "CHK-DIRECT-SEAM-001",
            "final_cmo_checkpoint_hash": "4" * 64,
            "deployment_approved": True,
        }

        with patch(
            "runtime.engine.build_final_cmo_publish_parameters",
            return_value=bound_parameters,
        ) as builder:
            receipt = runtime.request_publish_action(context, platform="linkedin")

        builder.assert_called_once_with(context, "linkedin")
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(len(runtime.dispatched), 1)
        request = runtime.dispatched[0]
        self.assertEqual(request.parameters, bound_parameters)
        self.assertNotEqual(request.parameters["content"], "Campaign Go-To-Market Plan")
        self.assertEqual(context.status, RuntimeStatus.WAITING_FOR_APPROVAL)
        self.assertEqual(
            context.checkpoints[-1].pending_approval_id,
            "pending_direct_server_001",
        )

    def test_builder_failure_happens_before_any_tool_dispatch(self):
        context = RuntimeContext(
            run_id="RUN-DIRECT-SEAM-FAIL-001",
            objective="Launch governed campaign",
            business_id="BIZ-DIRECT-001",
            project_id="PROJ-DIRECT-001",
            chat_id="CHAT-DIRECT-001",
            campaign_id="CAMP-DIRECT-001",
            status=RuntimeStatus.RUNNING,
            current_stage=RuntimeStage.INIT,
        )
        runtime = _RuntimeHarness()

        with patch(
            "runtime.engine.build_final_cmo_publish_parameters",
            side_effect=RuntimeError("FINAL_CMO_DEPLOYMENT_PROVENANCE_REQUIRED: invalid binding"),
        ) as builder:
            with self.assertRaisesRegex(
                RuntimeError,
                "FINAL_CMO_DEPLOYMENT_PROVENANCE_REQUIRED",
            ):
                runtime.request_publish_action(context, platform="linkedin")

        builder.assert_called_once_with(context, "linkedin")
        self.assertEqual(runtime.dispatched, [])
        self.assertEqual(context.execution_receipt_refs, [])


if __name__ == "__main__":
    unittest.main()
