"""Adversarial RED for fail-closed downstream execution on the adaptive stack.

The adaptive proposal/fan-out stack must preserve the same authority invariant as
the earlier fail-closed hardening: once an upstream model stage is already known
to have failed, the downstream stage must return immediately without starting
new knowledge/memory/tool/provider work or creating new execution receipts.
"""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionMode, ExecutionStatus


class RuntimeUpstreamFailedZeroToolDispatchAdaptiveStackV1Tests(unittest.TestCase):
    def _runtime(self) -> FiveAgentDepartmentRuntime:
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime._lock = threading.Lock()
        runtime._active_emitters = {}
        runtime._executed_tool_idempotency_keys = {}
        runtime._inflight_tool_idempotency_keys = {}
        runtime._get_emitter = lambda *_args, **_kwargs: None
        runtime.knowledge_builder = SimpleNamespace(
            build_context_for_agent=MagicMock(
                return_value=SimpleNamespace(citations=[])
            )
        )
        runtime.memory_builder = SimpleNamespace(
            build_context_for_agent=MagicMock(
                return_value=SimpleNamespace(memories=[])
            )
        )
        runtime.lineage_inspector = MagicMock()
        runtime.context_compiler = SimpleNamespace(
            compile_grounded_package=MagicMock(
                return_value=SimpleNamespace(
                    provenance_index={},
                    evidence_items=[],
                    render_prompt_section=lambda: "",
                )
            )
        )

        def fake_dispatch(_idem_key, request):
            return SimpleNamespace(
                execution_id=f"EXEC-UNEXPECTED-{request.capability_id}",
                capability_id=request.capability_id,
                status=ExecutionStatus.SUCCESS,
                execution_mode=ExecutionMode.REAL,
                error_class=None,
                observation_record=None,
                artifact_references=[],
            )

        runtime._execute_tool_singleflight = MagicMock(side_effect=fake_dispatch)
        runtime._call_agent_llm = MagicMock(return_value=("UNEXPECTED MODEL CALL", None))
        return runtime

    @staticmethod
    def _failed_context(run_id: str, upstream_stage: str) -> RuntimeContext:
        context = RuntimeContext(
            run_id=run_id,
            objective="Fail closed without downstream external work",
            business_id="BIZ-ADAPTIVE-FAIL-CLOSED-V1",
            project_id="PROJ-ADAPTIVE-FAIL-CLOSED-V1",
        )
        context.status = RuntimeStatus.FAILED
        context.stage_outputs[upstream_stage] = {
            "stage": upstream_stage.upper(),
            "status": "FAILED",
            "error": "UPSTREAM_TEST_FAILURE",
        }
        return context

    def test_intelligence_returns_before_knowledge_or_search_after_cmo_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context("RUN-ADAPTIVE-FAILED-INT", "cmo_initial")

        output = runtime.execute_stage_intelligence(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertIsNone(output.get("search_receipt_id"))
        runtime.knowledge_builder.build_context_for_agent.assert_not_called()
        runtime._execute_tool_singleflight.assert_not_called()
        runtime._call_agent_llm.assert_not_called()
        self.assertEqual(context.execution_receipt_refs, [])

    def test_performance_returns_before_knowledge_memory_or_analytics_after_creative_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context("RUN-ADAPTIVE-FAILED-PERF", "creative")

        output = runtime.execute_stage_performance(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertIsNone(output.get("analytics_receipt_id"))
        self.assertEqual(
            output.get("analytics_data_status"),
            "NOT_ATTEMPTED:PREVIOUS_STAGE_FAILED",
        )
        runtime.knowledge_builder.build_context_for_agent.assert_not_called()
        runtime.memory_builder.build_context_for_agent.assert_not_called()
        runtime._execute_tool_singleflight.assert_not_called()
        runtime._call_agent_llm.assert_not_called()
        self.assertEqual(context.execution_receipt_refs, [])


if __name__ == "__main__":
    unittest.main()
