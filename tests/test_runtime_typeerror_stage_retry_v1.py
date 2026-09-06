"""Adversarial RED for TypeError compatibility retries around stage execution.

A compatibility fallback may choose a legacy call signature *before* execution,
but it must never catch a TypeError raised by the stage body and execute that
stage a second time. A stage may already have performed provider/tool side
effects before surfacing the TypeError.
"""

from __future__ import annotations

import threading
import unittest
from collections import OrderedDict
from types import SimpleNamespace

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime


class RuntimeTypeErrorStageRetryV1Tests(unittest.TestCase):
    @staticmethod
    def _context(run_id: str) -> RuntimeContext:
        return RuntimeContext(
            run_id=run_id,
            objective="Exercise stage invocation exactly once",
            business_id="BIZ-TYPEERROR-RETRY-V1",
            project_id="PROJ-TYPEERROR-RETRY-V1",
        )

    @staticmethod
    def _runtime() -> FiveAgentDepartmentRuntime:
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime._lock = threading.Lock()
        runtime._active_contexts = {}
        runtime._completed_runs = OrderedDict()
        runtime._active_emitters = {}
        runtime._completed_progress = OrderedDict()
        runtime._reserved_run_ids = set()
        runtime._cancelled_run_ids = set()
        runtime.max_completed_runs_cache = 8
        runtime.complete_run = lambda _context: SimpleNamespace(run_id=_context.run_id)
        return runtime

    @staticmethod
    def _install_successful_pre_final_stages(runtime: FiveAgentDepartmentRuntime) -> None:
        def complete(stage_name: str):
            def _stage(context: RuntimeContext):
                output = {"stage": stage_name.upper(), "status": "COMPLETED"}
                context.stage_outputs[stage_name] = output
                return output
            return _stage

        runtime.execute_stage_cmo_initial = complete("cmo_initial")
        runtime.execute_stage_intelligence = complete("intelligence")
        runtime.execute_stage_strategist = complete("strategist")
        runtime.execute_stage_creative = complete("creative")
        runtime.execute_stage_performance = complete("performance")

    def test_research_internal_typeerror_after_effect_is_not_retried(self) -> None:
        runtime = self._runtime()
        context = self._context("RUN-TYPEERROR-RESEARCH")
        runtime.start_run = lambda **_kwargs: context

        stage_calls = 0
        provider_effects = 0

        def intelligence_stage(_context: RuntimeContext, text_delta_sink=None):
            nonlocal stage_calls, provider_effects
            stage_calls += 1
            provider_effects += 1  # models a provider/tool side effect already issued
            if stage_calls == 1:
                raise TypeError("INTERNAL_INTELLIGENCE_TYPE_ERROR_AFTER_PROVIDER_EFFECT")
            return {
                "stage": "INTELLIGENCE",
                "status": "COMPLETED",
                "market_findings": "second invocation must never happen",
            }

        runtime.execute_stage_intelligence = intelligence_stage

        returned_context, final_output, _artifact = runtime.run_research_inquiry(
            objective=context.objective,
            business_id=context.business_id,
            project_id=context.project_id,
            text_delta_sink=lambda _delta: None,
        )

        self.assertEqual(stage_calls, 1, "internal TypeError must not trigger a second Intelligence execution")
        self.assertEqual(provider_effects, 1, "provider/tool side effect count must remain exactly one")
        self.assertEqual(returned_context.status, RuntimeStatus.FAILED)
        self.assertEqual(final_output["status"], "FAILED")

    def test_final_cmo_internal_typeerror_after_effect_is_not_retried(self) -> None:
        runtime = self._runtime()
        context = self._context("RUN-TYPEERROR-FINAL-CMO")
        self._install_successful_pre_final_stages(runtime)

        stage_calls = 0
        provider_effects = 0

        def final_cmo_stage(_context: RuntimeContext, text_delta_sink=None):
            nonlocal stage_calls, provider_effects
            stage_calls += 1
            provider_effects += 1  # models an LLM/provider request already issued
            if stage_calls == 1:
                raise TypeError("INTERNAL_FINAL_CMO_TYPE_ERROR_AFTER_PROVIDER_EFFECT")
            return {
                "stage": "FINAL_CMO",
                "agent": "cmo",
                "status": "READY_FOR_DEPLOYMENT",
                "master_gtm_plan_markdown": "second invocation must never happen",
            }

        runtime.execute_stage_final_cmo = final_cmo_stage

        returned_context, final_output, _artifact = runtime.execute_run(
            context,
            text_delta_sink=lambda _delta: None,
        )

        self.assertEqual(stage_calls, 1, "internal TypeError must not trigger a second Final CMO execution")
        self.assertEqual(provider_effects, 1, "LLM/provider side effect count must remain exactly one")
        self.assertEqual(returned_context.status, RuntimeStatus.FAILED)
        self.assertEqual(final_output["status"], "FAILED")

    def test_research_legacy_stage_signature_remains_single_call_compatible(self) -> None:
        runtime = self._runtime()
        context = self._context("RUN-TYPEERROR-LEGACY-RESEARCH")
        runtime.start_run = lambda **_kwargs: context
        stage_calls = 0

        def legacy_intelligence_stage(_context: RuntimeContext):
            nonlocal stage_calls
            stage_calls += 1
            return {
                "stage": "INTELLIGENCE",
                "status": "COMPLETED",
                "market_findings": "legacy signature",
            }

        runtime.execute_stage_intelligence = legacy_intelligence_stage
        returned_context, final_output, _artifact = runtime.run_research_inquiry(
            objective=context.objective,
            business_id=context.business_id,
            project_id=context.project_id,
            text_delta_sink=lambda _delta: None,
        )

        self.assertEqual(stage_calls, 1)
        self.assertEqual(returned_context.status, RuntimeStatus.COMPLETED)
        self.assertEqual(final_output["status"], "COMPLETED")

    def test_final_cmo_legacy_stage_signature_remains_single_call_compatible(self) -> None:
        runtime = self._runtime()
        context = self._context("RUN-TYPEERROR-LEGACY-FINAL-CMO")
        self._install_successful_pre_final_stages(runtime)
        stage_calls = 0

        def legacy_final_cmo_stage(_context: RuntimeContext):
            nonlocal stage_calls
            stage_calls += 1
            return {
                "stage": "FINAL_CMO",
                "agent": "cmo",
                "status": "READY_FOR_DEPLOYMENT",
                "master_gtm_plan_markdown": "legacy signature",
            }

        runtime.execute_stage_final_cmo = legacy_final_cmo_stage
        _returned_context, final_output, _artifact = runtime.execute_run(
            context,
            text_delta_sink=lambda _delta: None,
        )

        self.assertEqual(stage_calls, 1)
        self.assertEqual(final_output["status"], "READY_FOR_DEPLOYMENT")


if __name__ == "__main__":
    unittest.main()
