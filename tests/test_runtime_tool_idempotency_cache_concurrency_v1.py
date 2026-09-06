from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from typing import Any

from runtime.context import RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.lineage import LineageInspector
from tools.receipts import ExecutionReceipt
from tools.tool_gateway import ToolRequest


class _EmptyKnowledgeBuilder:
    def build_context_for_agent(self, agent_id: str, query_text: str = "") -> Any:
        return SimpleNamespace(citations=[])


class _GroundedPackage:
    provenance_index = {}

    def render_prompt_section(self) -> str:
        return ""


class _ContextCompiler:
    def compile_grounded_package(self, *args: Any, **kwargs: Any) -> _GroundedPackage:
        return _GroundedPackage()


class _CoordinatedToolGateway:
    """Keep the first dispatch in-flight while a second worker reaches the same key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.first_dispatch_entered = threading.Event()
        self.second_dispatch_entered = threading.Event()

    def execute(self, request: Any) -> ExecutionReceipt:
        with self._lock:
            self.calls += 1
            call_number = self.calls

        if call_number == 1:
            self.first_dispatch_entered.set()
            # Pre-fix, worker 2 also sees a cache miss and enters execute(),
            # releasing this wait. A correct single-flight cache makes worker 2
            # wait for worker 1 instead, so this simply times out and returns.
            self.second_dispatch_entered.wait(timeout=0.5)
        else:
            self.second_dispatch_entered.set()

        return ExecutionReceipt(
            execution_id=f"EXEC-CACHE-RACE-{call_number}",
            run_id=request.run_id,
            agent_id=request.agent_id,
            capability_id=request.capability_id,
            provider="test-provider",
            request_hash=f"hash-{call_number}",
            business_id=request.business_id,
            project_id=request.project_id,
            chat_id=request.chat_id,
        )


class _ParallelKeyToolGateway:
    """Require two different-key dispatches to overlap inside ToolGateway."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.barrier = threading.Barrier(2)

    def execute(self, request: Any) -> ExecutionReceipt:
        with self._lock:
            self.calls += 1
            call_number = self.calls

        self.barrier.wait(timeout=2.0)
        return ExecutionReceipt(
            execution_id=f"EXEC-PARALLEL-KEY-{call_number}",
            run_id=request.run_id,
            agent_id=request.agent_id,
            capability_id=request.capability_id,
            provider="test-provider",
            request_hash=f"parallel-hash-{call_number}",
            business_id=request.business_id,
            project_id=request.project_id,
            chat_id=request.chat_id,
        )


class _CreativeRuntime(FiveAgentDepartmentRuntime):
    def __init__(self, tool_gateway: Any) -> None:
        # Deliberately avoid the production composition root: these regressions
        # isolate only the runtime's ToolGateway single-flight boundary.
        self.tool_gateway = tool_gateway
        self.knowledge_builder = _EmptyKnowledgeBuilder()
        self.context_compiler = _ContextCompiler()
        self.lineage_inspector = LineageInspector()
        self._executed_tool_idempotency_keys = {}
        self._lock = threading.Lock()
        self._active_emitters = {}

    def _get_emitter(self, *args: Any, **kwargs: Any) -> None:
        return None

    def _append_governance_block(self, context: Any, prompt: str) -> str:
        return prompt

    def _call_agent_llm(self, *args: Any, **kwargs: Any):
        return "creative output", None

    def _finalize_stage_handoff(
        self,
        context: Any,
        stage_key: str,
        agent_name: str,
        raw_output: str,
        output: dict,
    ):
        return output, None, None


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        run_id="RUN-TOOL-CACHE-RACE",
        objective="Build one hero creative",
        business_id="BIZ-RACE",
        project_id="PROJ-RACE",
        chat_id="CHAT-RACE",
        current_stage=None,
        knowledge_refs=[],
        execution_receipt_refs=[],
        artifact_refs=[],
        working_state={},
        status=RuntimeStatus.RUNNING,
        stage_outputs={
            "strategist": {
                "status": "COMPLETED",
                "positioning": "positioning",
            }
        },
        risk_flags=[],
        create_checkpoint=lambda: None,
    )


def _request(capability_id: str) -> ToolRequest:
    return ToolRequest(
        run_id="RUN-TOOL-CACHE-RACE",
        agent_id="creative",
        capability_id=capability_id,
        parameters={"test": capability_id},
        business_id="BIZ-RACE",
        project_id="PROJ-RACE",
        chat_id="CHAT-RACE",
    )


class RuntimeToolIdempotencyCacheConcurrencyV1Tests(unittest.TestCase):
    def test_same_creative_tool_key_is_dispatched_only_once_under_concurrency(self) -> None:
        tool_gateway = _CoordinatedToolGateway()
        runtime = _CreativeRuntime(tool_gateway)
        context = _context()
        outputs = []
        errors = []
        result_lock = threading.Lock()

        def worker() -> None:
            try:
                output = runtime.execute_stage_creative(context)
                with result_lock:
                    outputs.append(output)
            except BaseException as exc:
                with result_lock:
                    errors.append(exc)

        first = threading.Thread(target=worker, name="creative-cache-worker-1")
        first.start()
        self.assertTrue(
            tool_gateway.first_dispatch_entered.wait(timeout=2.0),
            "first worker must enter the ToolGateway dispatch",
        )

        second = threading.Thread(target=worker, name="creative-cache-worker-2")
        second.start()

        first.join(timeout=3.0)
        second.join(timeout=3.0)
        self.assertFalse(first.is_alive(), "first worker must terminate")
        self.assertFalse(second.is_alive(), "second worker must terminate")
        self.assertEqual(errors, [])
        self.assertEqual(len(outputs), 2)

        self.assertEqual(
            tool_gateway.calls,
            1,
            "same runtime idempotency key must have one in-flight ToolGateway dispatch",
        )
        self.assertEqual(
            len({output["visual_asset_receipt"] for output in outputs}),
            1,
            "both workers must observe the same canonical cached receipt",
        )

    def test_different_tool_keys_remain_parallel(self) -> None:
        tool_gateway = _ParallelKeyToolGateway()
        runtime = _CreativeRuntime(tool_gateway)
        receipts = []
        errors = []
        result_lock = threading.Lock()

        def worker(key: str, request: ToolRequest) -> None:
            try:
                receipt = runtime._execute_tool_singleflight(key, request)
                with result_lock:
                    receipts.append(receipt)
            except BaseException as exc:
                with result_lock:
                    errors.append(exc)

        first = threading.Thread(
            target=worker,
            args=("KEY-A", _request("image_generation")),
            name="different-key-worker-a",
        )
        second = threading.Thread(
            target=worker,
            args=("KEY-B", _request("analytics_retrieval")),
            name="different-key-worker-b",
        )
        first.start()
        second.start()
        first.join(timeout=3.0)
        second.join(timeout=3.0)

        self.assertFalse(first.is_alive(), "different-key worker A must terminate")
        self.assertFalse(second.is_alive(), "different-key worker B must terminate")
        self.assertEqual(errors, [], "different keys must not be serialized behind one global I/O lock")
        self.assertEqual(tool_gateway.calls, 2)
        self.assertEqual(len(receipts), 2)
        self.assertEqual(len({receipt.execution_id for receipt in receipts}), 2)


if __name__ == "__main__":
    unittest.main()
