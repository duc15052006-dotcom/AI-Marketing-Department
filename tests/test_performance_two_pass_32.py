"""RC3 regressions for the Performance agent's mandatory internal 5A/5B workflow.

Performance remains one permanent logical agent. These tests verify that the
runtime invokes that same agent twice, Pass B consumes Pass A, failures are
fail-closed, and the deterministic handoff merge does not duplicate identical
items emitted by both passes.
"""

import json
import unittest

from integrations.models.base import ModelResponse, ModelResponseStatus
from runtime.context import RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


def _fence(payload: dict) -> str:
    return "=== STRUCTURED HANDOFF ===\n```json\n" + json.dumps(payload) + "\n```"


class SequentialPerformanceGateway:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.provider_registry = None
        self.model_policy = None

    def generate(self, request, **kwargs):
        index = len(self.calls)
        self.calls.append((request, kwargs))
        reply = self.replies[index] if index < len(self.replies) else "unexpected extra call"
        if isinstance(reply, dict) and reply.get("error"):
            return ModelResponse(
                request_id=request.request_id,
                provider="performance_two_pass_test",
                model_name="performance_two_pass_test",
                status=ModelResponseStatus.ERROR,
                error=reply["error"],
            )
        if isinstance(reply, dict):
            text = reply.get("text", "")
            payload = reply.get("payload")
            content = text + (("\n\n" + _fence(payload)) if payload is not None else "")
        else:
            content = str(reply)
        return ModelResponse(
            request_id=request.request_id,
            provider="performance_two_pass_test",
            model_name="performance_two_pass_test",
            status=ModelResponseStatus.SUCCESS,
            content=content,
        )


class PerformanceTwoPass32Tests(unittest.TestCase):
    def _build(self, replies):
        gateway = SequentialPerformanceGateway(replies)
        runtime = FiveAgentDepartmentRuntime(
            model_gateway=gateway,
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )
        context = runtime.start_run(
            objective="Evaluate campaign performance without inventing observed results",
            campaign_id="CAMP-PERF-32",
        )
        # This suite isolates Performance orchestration rather than run-pinned
        # ModelPolicy reconstruction, which has its own dedicated regressions.
        context.model_policy = {}
        context.stage_outputs["strategist"] = {
            "status": "COMPLETED",
            "positioning": "Grounded positioning",
        }
        context.stage_outputs["creative"] = {
            "status": "COMPLETED",
            "creative_synthesis": "Grounded creative synthesis",
        }
        return runtime, context, gateway

    def test_success_calls_same_performance_agent_twice_and_pass_b_consumes_pass_a(self):
        pass_a = "PASS_A_MEASUREMENT: funnel and attribution map."
        pass_b = "PASS_B_GOVERNANCE: experiment and approval plan."
        runtime, context, gateway = self._build([pass_a, pass_b])

        output = runtime.execute_stage_performance(context)

        self.assertEqual(output["status"], "COMPLETED")
        self.assertEqual(output["performance_pass_protocol"], "5A_5B")
        self.assertEqual(output["performance_passes_completed"], 2)
        self.assertEqual(output["measurement_attribution"], pass_a)
        self.assertEqual(output["experimentation_governance"], pass_b)
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual([call[1]["agent_id"] for call in gateway.calls], ["performance", "performance"])

        first_request = gateway.calls[0][0]
        second_request = gateway.calls[1][0]
        self.assertIn("INTERNAL PASS 5A ONLY", first_request.messages[0].content)
        self.assertIn("INTERNAL PASS 5B ONLY", second_request.messages[0].content)
        second_user_prompt = second_request.messages[-1].content
        self.assertIn("PERFORMANCE PASS 5A COMPACT PAYLOAD", second_user_prompt)
        self.assertIn(pass_a, second_user_prompt)
        self.assertIn("NON_REAL_TELEMETRY_IGNORED:MOCK", second_user_prompt)

        self.assertLess(output["funnel_kpi"].find(pass_a), output["funnel_kpi"].find(pass_b))
        self.assertEqual(context.status, RuntimeStatus.RUNNING)

    def test_pass_a_failure_is_fail_closed_and_never_runs_pass_b(self):
        runtime, context, gateway = self._build([
            {"error": "PASS_A_PROVIDER_FAILURE"},
            "MUST_NOT_RUN",
        ])

        output = runtime.execute_stage_performance(context)

        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["failed_pass"], "PASS_5A")
        self.assertEqual(output["performance_passes_completed"], 0)
        self.assertEqual(output["measurement_attribution"], "")
        self.assertEqual(output["experimentation_governance"], "")
        self.assertEqual(context.status, RuntimeStatus.FAILED)
        self.assertTrue(any("PASS_5A" in flag for flag in context.risk_flags))

    def test_pass_b_failure_is_fail_closed_not_partial_success(self):
        pass_a = "MEASUREMENT_COMPLETE_BUT_NOT_A_COMPLETE_PERFORMANCE_STAGE"
        runtime, context, gateway = self._build([
            pass_a,
            {"error": "PASS_B_PROVIDER_FAILURE"},
        ])

        output = runtime.execute_stage_performance(context)

        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["failed_pass"], "PASS_5B")
        self.assertEqual(output["performance_passes_completed"], 1)
        self.assertEqual(output["measurement_attribution"], pass_a)
        self.assertEqual(output["experimentation_governance"], "")
        self.assertEqual(context.status, RuntimeStatus.FAILED)
        self.assertNotIn("handoff", output, "Partial 5A output must not be promoted as a completed Performance handoff")

    def test_handoff_merge_is_a_then_b_deduplicated_and_b_owns_evaluation(self):
        shared_observation = {"text": "Observed telemetry is unavailable in this run."}
        pass_a_payload = {
            "observations": [shared_observation],
            "unknowns": [{"text": "Baseline conversion rate is unknown."}],
        }
        pass_b_payload = {
            "observations": [shared_observation],
            "recommendations": [{"text": "Run a controlled test after baseline collection."}],
            "evaluation": {"evaluation_status": "INCONCLUSIVE"},
        }
        runtime, context, gateway = self._build([
            {"text": "Measurement pass.", "payload": pass_a_payload},
            {"text": "Governance pass.", "payload": pass_b_payload},
        ])

        output = runtime.execute_stage_performance(context)

        handoff = output["handoff"]
        self.assertEqual(output["status"], "COMPLETED")
        self.assertEqual(len(handoff["observations"]), 1)
        self.assertEqual(len(handoff["unknowns"]), 1)
        self.assertEqual(len(handoff["recommendations"]), 1)
        self.assertEqual(handoff["observations"][0]["text"], shared_observation["text"])
        self.assertEqual(output["evaluation"]["evaluation_status"], "INCONCLUSIVE")
        self.assertEqual(handoff["evaluation_status"], "INCONCLUSIVE")
        self.assertEqual(output["pass_5a_handoff_parse_status"], "OK")
        self.assertEqual(output["pass_5b_handoff_parse_status"], "OK")
        self.assertEqual(len(gateway.calls), 2)


if __name__ == "__main__":
    unittest.main()
