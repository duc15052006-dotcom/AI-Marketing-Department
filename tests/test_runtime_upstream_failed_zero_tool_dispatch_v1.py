"""Adversarial RED for fail-closed stage tool dispatch.

Once an upstream stage has failed, downstream stages must not start new external
ToolGateway/provider work. The failure result itself is the only allowed stage
transition: no web search, image generation, or analytics retrieval may occur.
"""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionMode, ExecutionStatus


class RuntimeUpstreamFailedZeroToolDispatchV1Tests(unittest.TestCase):
    def _runtime(self) -> FiveAgentDepartmentRuntime:
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime._lock = threading.Lock()
        runtime._active_emitters = {}
        runtime._executed_tool_idempotency_keys = {}
        runtime._inflight_tool_idempotency_keys = {}
        runtime._get_emitter = lambda *_args, **_kwargs: None
        runtime.knowledge_builder = SimpleNamespace(
            build_context_for_agent=lambda *_args, **_kwargs: SimpleNamespace(citations=[])
        )
        runtime.memory_builder = SimpleNamespace(
            build_context_for_agent=lambda *_args, **_kwargs: SimpleNamespace(memories=[])
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
                status=ExecutionStatus.SUCCESS,
                execution_mode=ExecutionMode.REAL,
                error_class=None,
                observation_record=None,
                artifact_references=[],
            )

        runtime._execute_tool_singleflight = MagicMock(side_effect=fake_dispatch)
        return runtime

    @staticmethod
    def _failed_context(run_id: str, upstream_stage: str) -> RuntimeContext:
        context = RuntimeContext(
            run_id=run_id,
            objective="Launch a marketing campaign without side effects after failure",
            business_id="BIZ-UPSTREAM-FAILED-V1",
            project_id="PROJ-UPSTREAM-FAILED-V1",
        )
        context.status = RuntimeStatus.FAILED
        context.stage_outputs[upstream_stage] = {
            "stage": upstream_stage.upper(),
            "status": "FAILED",
            "error": "UPSTREAM_TEST_FAILURE",
        }
        return context

    def test_intelligence_does_not_search_after_cmo_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context("RUN-UPSTREAM-FAILED-INT", "cmo_initial")

        output = runtime.execute_stage_intelligence(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertIsNone(output.get("search_receipt_id"))
        runtime._execute_tool_singleflight.assert_not_called()

    def test_creative_does_not_generate_asset_after_strategist_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context("RUN-UPSTREAM-FAILED-CREATIVE", "strategist")

        output = runtime.execute_stage_creative(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertIsNone(output.get("visual_asset_receipt"))
        runtime._execute_tool_singleflight.assert_not_called()

    def test_performance_does_not_retrieve_analytics_after_creative_failure(self) -> None:
        runtime = self._runtime()
        context = self._failed_context("RUN-UPSTREAM-FAILED-PERF", "creative")

        output = runtime.execute_stage_performance(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertIsNone(output.get("analytics_receipt_id"))
        self.assertEqual(output.get("analytics_data_status"), "NOT_ATTEMPTED:PREVIOUS_STAGE_FAILED")
        runtime._execute_tool_singleflight.assert_not_called()


if __name__ == "__main__":
    unittest.main()
