import types
import unittest

from governance.claim_safety import FinalClaimAuditGateResult
from runtime.context import RuntimeStatus
from runtime.deployment_binding import build_final_cmo_publish_parameters
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.progress import ProgressEventType


class _FakeGateway:
    pass


class _RecordingMemoryRepo:
    def __init__(self):
        self.saved = []

    def save_memory(self, item):
        self.saved.append(item)


class _GroundedPackage:
    provenance_index = {}

    def render_prompt_section(self):
        return ""


class _Compiler:
    def compile_grounded_package(self, agent_id, context):
        return _GroundedPackage()


class FinalCmoBlockedSemanticsTests(unittest.TestCase):
    def test_governance_block_completes_technical_run_but_keeps_deployment_closed(self):
        memory_repo = _RecordingMemoryRepo()
        runtime = FiveAgentDepartmentRuntime(
            model_gateway=_FakeGateway(),
            memory_repo=memory_repo,
        )
        runtime.context_compiler = _Compiler()

        logical_model_requests = {"count": 0}

        def fake_stage(key, output, request_count=1):
            def _run(self, context, *args, **kwargs):
                logical_model_requests["count"] += request_count
                result = {
                    "stage": key.upper(),
                    "agent": output.get("agent", key),
                    "status": "COMPLETED",
                    **output,
                }
                context.stage_outputs[key] = result
                return result
            return types.MethodType(_run, runtime)

        runtime.execute_stage_cmo_initial = fake_stage(
            "cmo_initial",
            {"agent": "cmo", "strategic_intent": "test strategy"},
        )
        runtime.execute_stage_intelligence = fake_stage(
            "intelligence",
            {"agent": "intelligence", "market_findings": "test findings"},
        )
        runtime.execute_stage_content = fake_stage(
            "content",
            {"agent": "content", "content_strategy": "test content"},
        )
        runtime.execute_stage_creative = fake_stage(
            "creative",
            {"agent": "creative", "creative_synthesis": "test creative"},
        )
        runtime.execute_stage_performance = fake_stage(
            "performance",
            {"agent": "performance", "funnel_kpi": "test KPI"},
            request_count=2,
        )

        def fake_llm(*args, **kwargs):
            logical_model_requests["count"] += 1
            return "# Final CMO report\n\nTechnically successful synthesis.", None

        runtime._call_agent_llm = fake_llm
        runtime._finalize_stage_handoff = (
            lambda context, stage_key, agent_id, raw_output, output, **kwargs:
            (output, {}, "TEST")
        )
        runtime._evaluate_final_authorization = lambda *args, **kwargs: FinalClaimAuditGateResult(
            total_claims=1,
            supported_claims=0,
            unknown_claims=0,
            hypotheses_count=0,
            blocked_claims=1,
            human_input_required_count=0,
            authorization_status="BLOCKED",
            blocking_reasons=["TEST_GOVERNANCE_BLOCK"],
            claim_actions={"test_claim": "BLOCK"},
        )

        context, final_cmo, artifact = runtime.run_workflow(
            "Regression: governance block must not become technical failure"
        )

        self.assertEqual(RuntimeStatus.COMPLETED, context.status)
        self.assertEqual(RuntimeStatus.COMPLETED, artifact.status)
        self.assertEqual("NOT_READY", final_cmo["status"])
        self.assertIs(False, final_cmo["approved_for_deployment"])
        self.assertEqual("BLOCKED", final_cmo["approval_status"])
        self.assertIn(
            "TEST_GOVERNANCE_BLOCK",
            final_cmo["claim_audit"]["blocking_reasons"],
        )
        self.assertTrue(
            any(
                flag.startswith("FINAL_CMO_NOT_AUTHORIZED:")
                for flag in context.risk_flags
            )
        )

        canonical_stages = {
            "cmo_initial",
            "intelligence",
            "content",
            "creative",
            "performance",
            "final_cmo",
        }
        self.assertEqual(canonical_stages, set(context.stage_outputs))
        self.assertEqual(6, len(context.stage_outputs))
        self.assertEqual(7, logical_model_requests["count"])

        events = runtime.get_progress_events(context.run_id)
        event_types = [event.event_type for event in events]
        self.assertNotIn(ProgressEventType.RUN_FAILED, event_types)
        self.assertIn(ProgressEventType.RUN_COMPLETED, event_types)

        self.assertEqual([], artifact.learning_candidates)
        self.assertEqual([], memory_repo.saved)

        with self.assertRaisesRegex(RuntimeError, "not READY_FOR_DEPLOYMENT"):
            build_final_cmo_publish_parameters(context, "linkedin")


if __name__ == "__main__":
    unittest.main()
