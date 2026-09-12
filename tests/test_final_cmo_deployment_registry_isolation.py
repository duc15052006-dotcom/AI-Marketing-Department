"""Adversarial isolation regressions for Final CMO deployment binding registry."""

import unittest

from runtime.context import RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.deployment_binding import (
    DEPLOYMENT_BINDING_STATE_KEY,
    DEPLOYMENT_ERROR_PREFIX,
    DEPLOYMENT_PROVENANCE_FIELD,
    LEGACY_RUNTIME_PUBLISH_PLACEHOLDER,
    clear_deployment_binding_registry_for_tests,
)
from tools.tool_gateway import ToolRequest


class TestFinalCmoDeploymentRegistryIsolation(unittest.TestCase):
    def setUp(self) -> None:
        clear_deployment_binding_registry_for_tests()

    @staticmethod
    def _context(
        run_id: str,
        *,
        business_id: str = "BIZ-REGISTRY-001",
        project_id: str = "PROJ-REGISTRY-001",
        chat_id: str = "CHAT-REGISTRY-001",
    ) -> RuntimeContext:
        return RuntimeContext(
            run_id=run_id,
            objective="Launch governed campaign",
            business_id=business_id,
            project_id=project_id,
            chat_id=chat_id,
            campaign_id="CAMP-REGISTRY-001",
            status=RuntimeStatus.RUNNING,
            current_stage=RuntimeStage.FINAL_CMO,
        )

    @staticmethod
    def _ready_output(markdown: str = "# Final GTM\n\nApproved deployment plan.") -> dict:
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

    def _bind(self, context: RuntimeContext, markdown: str = "# Final GTM\n\nApproved deployment plan.") -> dict:
        output = self._ready_output(markdown)
        context.stage_outputs["final_cmo"] = output
        context.create_checkpoint()
        self.assertIn(DEPLOYMENT_PROVENANCE_FIELD, output)
        return output

    def test_different_live_context_cannot_reuse_registered_run_id(self) -> None:
        run_id = "RUN-DEPLOY-REGISTRY-COLLISION"
        first = self._context(run_id)
        self._bind(first)

        second = self._context(
            run_id,
            business_id="BIZ-REGISTRY-OTHER",
            project_id="PROJ-REGISTRY-OTHER",
            chat_id="CHAT-REGISTRY-OTHER",
        )
        second_output = self._ready_output("# Other Final GTM\n\nDifferent deployment plan.")
        second.stage_outputs["final_cmo"] = second_output

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            second.create_checkpoint()

        self.assertEqual(second.checkpoints, [])
        self.assertNotIn(DEPLOYMENT_BINDING_STATE_KEY, second.working_state)
        self.assertNotIn(DEPLOYMENT_PROVENANCE_FIELD, second_output)

    def test_placeholder_publish_request_scope_mismatch_fails_closed(self) -> None:
        context = self._context("RUN-DEPLOY-REGISTRY-SCOPE")
        self._bind(context)

        canonical_scope = {
            "business_id": context.business_id,
            "project_id": context.project_id,
            "chat_id": context.chat_id,
        }
        mismatches = {
            "business_id": "BIZ-WRONG",
            "project_id": "PROJ-WRONG",
            "chat_id": "CHAT-WRONG",
        }

        for field_name, bad_value in mismatches.items():
            request_scope = dict(canonical_scope)
            request_scope[field_name] = bad_value
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
                    ToolRequest(
                        run_id=context.run_id,
                        agent_id="cmo",
                        capability_id="social_publishing",
                        parameters={
                            "platform": "linkedin",
                            "content": LEGACY_RUNTIME_PUBLISH_PLACEHOLDER,
                        },
                        **request_scope,
                    )

    def test_matching_scope_rewrites_placeholder_to_bound_final_cmo_artifact(self) -> None:
        context = self._context("RUN-DEPLOY-REGISTRY-MATCH")
        output = self._bind(context)

        request = ToolRequest(
            run_id=context.run_id,
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={
                "platform": "linkedin",
                "content": LEGACY_RUNTIME_PUBLISH_PLACEHOLDER,
            },
            business_id=context.business_id,
            project_id=context.project_id,
            chat_id=context.chat_id,
        )

        self.assertEqual(request.parameters["content"], output["master_gtm_plan_markdown"])
        self.assertIs(request.parameters["deployment_approved"], True)
        self.assertEqual(
            request.parameters["final_cmo_checkpoint_id"],
            output[DEPLOYMENT_PROVENANCE_FIELD]["checkpoint_id"],
        )
        self.assertEqual(
            request.parameters["final_cmo_checkpoint_hash"],
            output[DEPLOYMENT_PROVENANCE_FIELD]["checkpoint_hash"],
        )


if __name__ == "__main__":
    unittest.main()
