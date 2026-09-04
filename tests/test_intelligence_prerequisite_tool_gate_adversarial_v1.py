"""Adversarial regression for Intelligence prerequisite fail-closed ordering.

Invariant: once the initial CMO stage has FAILED, Intelligence must not invoke
web_search/read_page or create downstream execution receipts. A failed upstream
prerequisite is terminal before research side effects.
"""

from types import SimpleNamespace
import unittest

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionStatus


class _SpyToolGateway:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, _request):
        self.calls += 1
        return SimpleNamespace(
            execution_id="EXEC-SHOULD-NOT-EXIST",
            status=ExecutionStatus.ERROR,
            observation_record=None,
        )


class _NoopLineageInspector:
    def add_receipt(self, _receipt) -> None:
        return None


class _NoopContextCompiler:
    def compile_grounded_package(self, *_args, **_kwargs):
        return SimpleNamespace(provenance_index={})


class IntelligencePrerequisiteToolGateAdversarialV1Tests(unittest.TestCase):
    def test_failed_initial_cmo_prevents_intelligence_tool_execution(self) -> None:
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime.tool_gateway = _SpyToolGateway()
        runtime.lineage_inspector = _NoopLineageInspector()
        runtime.context_compiler = _NoopContextCompiler()
        runtime._executed_tool_idempotency_keys = {}
        runtime._get_emitter = lambda _context: None
        runtime._build_stage_lineage_context = lambda *_args, **_kwargs: (
            SimpleNamespace(citations=[]),
            None,
        )
        runtime._reconcile_grounded_stage_provenance = lambda *_args, **_kwargs: None

        context = RuntimeContext(
            run_id="RUN-INTELLIGENCE-PREREQ-GATE-V1",
            objective="Do not research when the initial CMO stage has failed.",
        )
        context.status = RuntimeStatus.RUNNING
        context.stage_outputs["cmo_initial"] = {
            "stage": "CMO_INITIAL",
            "agent": "cmo",
            "status": "FAILED",
            "error": "MODEL_PROVIDER_FAILURE",
        }

        output = runtime.execute_stage_intelligence(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertEqual(
            runtime.tool_gateway.calls,
            0,
            "Intelligence must fail closed before web_search when initial CMO failed.",
        )
        self.assertEqual(context.execution_receipt_refs, [])


if __name__ == "__main__":
    unittest.main()
