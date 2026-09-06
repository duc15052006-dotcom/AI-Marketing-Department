"""Adversarial RED for Creative tool dispatch before the prior-stage gate.

A failed Strategist stage is authoritative. Creative must not spend quota,
create artifacts, or produce tool receipts after that failure is already known.
"""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from runtime.context import GroundedContextPackage, RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionReceipt


class RuntimeCreativeToolBeforeStageGateV1Tests(unittest.TestCase):
    def test_failed_strategist_blocks_creative_tool_dispatch_and_receipt_mutation(self) -> None:
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime._lock = threading.Lock()
        runtime._active_emitters = {}
        runtime._get_emitter = lambda *_args, **_kwargs: None
        runtime.knowledge_builder = SimpleNamespace(
            build_context_for_agent=lambda *_args, **_kwargs: SimpleNamespace(citations=[])
        )
        runtime.lineage_inspector = MagicMock()
        runtime.context_compiler = SimpleNamespace(
            compile_grounded_package=lambda agent_id, context, tool_receipts=None: GroundedContextPackage(
                objective=context.objective,
                agent_id=agent_id,
            )
        )

        tool_calls = []

        def dispatch(idempotency_key, request):
            tool_calls.append((idempotency_key, request.capability_id))
            return ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider="should-not-run",
                request_hash="should-not-exist",
                artifact_references=["artifact://should-not-exist"],
            )

        runtime._execute_tool_singleflight = dispatch
        model_calls = []
        runtime._call_agent_llm = lambda *args, **kwargs: model_calls.append((args, kwargs)) or ("unexpected", None)

        context = RuntimeContext(
            run_id="RUN-CREATIVE-STAGE-GATE-V1",
            objective="Launch a privacy-first productivity app",
            business_id="BIZ-CREATIVE-STAGE-GATE-V1",
            project_id="PROJ-CREATIVE-STAGE-GATE-V1",
        )
        context.status = RuntimeStatus.RUNNING
        context.stage_outputs["strategist"] = {
            "stage": "STRATEGIST",
            "agent": "strategist",
            "status": "FAILED",
            "error": "MODEL_PROVIDER_FAILURE",
            "positioning": "",
        }

        output = runtime.execute_stage_creative(context)

        self.assertEqual(output["status"], "FAILED")
        self.assertEqual(output["error"], "PREVIOUS_STAGE_FAILED")
        self.assertEqual(tool_calls, [], "Known upstream failure must block image_generation dispatch")
        self.assertEqual(model_calls, [], "Known upstream failure must block the Creative model call")
        self.assertEqual(context.execution_receipt_refs, [])
        self.assertEqual(context.artifact_refs, [])
        runtime.lineage_inspector.add_receipt.assert_not_called()
        self.assertIsNone(
            output.get("visual_asset_receipt"),
            "A blocked Creative stage must not expose a tool receipt that was never authorized to run",
        )


if __name__ == "__main__":
    unittest.main()
