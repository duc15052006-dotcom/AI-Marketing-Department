"""Adversarial regression for Creative prerequisite fail-closed ordering.

Invariant: once Strategist has FAILED, Creative must not invoke downstream tools.
A failed prerequisite is a control-flow terminal for the stage, not a condition
that may be checked after image generation or other side effects.
"""

from types import SimpleNamespace
import unittest

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime


class _SpyToolGateway:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, _request):
        self.calls += 1
        return SimpleNamespace(
            execution_id="EXEC-SHOULD-NOT-EXIST",
            artifact_references=[],
        )


class _NoopLineageInspector:
    def add_receipt(self, _receipt) -> None:
        return None


class _NoopContextCompiler:
    def compile_grounded_package(self, *_args, **_kwargs):
        return SimpleNamespace(provenance_index={})


class CreativePrerequisiteToolGateAdversarialV1Tests(unittest.TestCase):
    def test_failed_strategist_prevents_creative_tool_execution(self) -> None:
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
            run_id="RUN-CREATIVE-PREREQ-GATE-V1",
            objective="Do not continue when the strategy prerequisite has failed.",
        )
        context.status = RuntimeStatus.RUNNING
        context.stage_outputs["strategist"] = {
            "stage": "STRATEGIST",
            "agent": "strategist",
            "status": "FAILED",
            "error": "MODEL_PROVIDER_FAILURE",
        }

        output = runtime.execute_stage_creative(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertEqual(
            runtime.tool_gateway.calls,
            0,
            "Creative must fail closed before image_generation when Strategist failed.",
        )
        self.assertEqual(context.execution_receipt_refs, [])
        self.assertEqual(context.artifact_refs, [])


if __name__ == "__main__":
    unittest.main()
