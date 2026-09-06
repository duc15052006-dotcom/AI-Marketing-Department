"""Adversarial RED for live Intelligence research fan-out.

The scheduler core already knows how to execute conflict-free tasks in one wave.
This test proves whether the production Intelligence stage actually uses that
capability for independent market / competitor / customer research dispatches.

The barrier is deterministic: the first fake ToolGateway dispatch waits briefly
for a second dispatch to start. Sequential production code therefore completes
with only one observed dispatch and fails the fan-out invariant; concurrent code
releases the barrier as soon as another worker starts.
"""

from __future__ import annotations

import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from runtime.context import GroundedContextPackage, RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


def _receipt(execution_id: str, request) -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=execution_id,
        run_id=request.run_id,
        agent_id="intelligence",
        capability_id="web_search",
        provider="fanout_test",
        request_hash=f"hash-{execution_id}",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        status=ExecutionStatus.SUCCESS,
        execution_mode=ExecutionMode.REAL,
        error_class=None,
        error_message=None,
        cost_or_token_usage={},
        artifact_references=[],
        approval_reference=None,
        business_id=request.business_id,
        project_id=request.project_id,
        chat_id=request.chat_id,
        result_hash=f"result-{execution_id}",
        data={"query": request.parameters.get("query", ""), "results": [], "result_count": 0},
        output=None,
        observation_record=None,
    )


class RuntimeIntelligenceAdaptiveFanoutV1Tests(unittest.TestCase):
    def _runtime_and_context(self):
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime._lock = threading.Lock()
        runtime._active_emitters = {}
        runtime._executed_tool_idempotency_keys = {}
        runtime._inflight_tool_idempotency_keys = {}
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
        runtime._get_emitter = lambda *_args, **_kwargs: None
        runtime._append_governance_block = lambda _context, prompt: prompt
        runtime._call_agent_llm = lambda *_args, **_kwargs: ("Synthesized intelligence findings", None)
        runtime._finalize_stage_handoff = lambda _context, _stage, _agent, _text, output, **_kwargs: (
            output,
            None,
            "NOT_PROVIDED",
        )

        context = RuntimeContext(
            run_id="RUN-INT-FANOUT-V1",
            objective="Launch a new productivity app for freelance designers",
            business_id="BIZ-INT-FANOUT-V1",
            project_id="PROJ-INT-FANOUT-V1",
        )
        context.status = RuntimeStatus.RUNNING
        context.stage_outputs["cmo_initial"] = {
            "stage": "CMO_INITIAL",
            "agent": "cmo",
            "status": "COMPLETED",
            "strategic_intent": "Research the market before positioning.",
        }
        return runtime, context

    def test_independent_research_dispatches_overlap_before_merge(self) -> None:
        runtime, context = self._runtime_and_context()

        state_lock = threading.Lock()
        second_dispatch_started = threading.Event()
        call_count = 0
        active = 0
        max_active = 0
        context_mutated_inside_worker = False

        def controlled_dispatch(_idem_key, request):
            nonlocal call_count, active, max_active, context_mutated_inside_worker
            with state_lock:
                call_count += 1
                ordinal = call_count
                active += 1
                max_active = max(max_active, active)
                if context.execution_receipt_refs:
                    context_mutated_inside_worker = True
                if call_count >= 2:
                    second_dispatch_started.set()

            # If production remains sequential, this times out and the lone
            # dispatch returns; the assertions below then prove missing fan-out.
            second_dispatch_started.wait(timeout=0.25)
            receipt = _receipt(f"EXEC-FANOUT-{ordinal}", request)
            with state_lock:
                active -= 1
            return receipt

        runtime._execute_tool_singleflight = controlled_dispatch

        output = runtime.execute_stage_intelligence(context)

        self.assertEqual(output["status"], "COMPLETED")
        self.assertFalse(
            context_mutated_inside_worker,
            "parallel workers must return isolated receipts; RuntimeContext merge belongs to the caller thread",
        )
        self.assertGreaterEqual(
            call_count,
            3,
            "Intelligence must decompose independent market/competitor/customer research into multiple dispatches",
        )
        self.assertGreaterEqual(
            max_active,
            2,
            "at least two independent research dispatches must overlap in the same scheduler wave",
        )


if __name__ == "__main__":
    unittest.main()
