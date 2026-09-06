"""Adversarial RED for CMO-proposed adaptive runtime tasks.

The model may propose WHAT work is useful, but it must never become the
scheduling authority. These tests exercise the live runtime boundary:

1. CMO output may carry machine-readable task proposals, but only model-owned
   fields (kind/instruction) survive into structured runtime state.
2. Intelligence executes only compiler-authorized Intelligence kinds; model
   fields such as depends_on/writes/side_effecting/parallel cannot alter the
   runtime-owned scheduling contract.
3. Explicitly present but unusable proposals fail closed to one sequential
   legacy research dispatch instead of silently authorizing parallel work.
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


_PROPOSAL_OPEN = "<ADAPTIVE_TASK_PROPOSALS>"
_PROPOSAL_CLOSE = "</ADAPTIVE_TASK_PROPOSALS>"


def _receipt(execution_id: str, request) -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=execution_id,
        run_id=request.run_id,
        agent_id="intelligence",
        capability_id="web_search",
        provider="adaptive_task_test",
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


class RuntimeCmoAdaptiveTaskProposalsV1Tests(unittest.TestCase):
    def _base_runtime(self) -> FiveAgentDepartmentRuntime:
        runtime = FiveAgentDepartmentRuntime.__new__(FiveAgentDepartmentRuntime)
        runtime._lock = threading.Lock()
        runtime._active_emitters = {}
        runtime._executed_tool_idempotency_keys = {}
        runtime._inflight_tool_idempotency_keys = {}
        runtime.knowledge_builder = SimpleNamespace(
            build_context_for_agent=lambda *_args, **_kwargs: SimpleNamespace(citations=[])
        )
        runtime.memory_builder = SimpleNamespace(
            build_context_for_agent=lambda *_args, **_kwargs: SimpleNamespace(memories=[])
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
        runtime._finalize_stage_handoff = lambda _context, _stage, _agent, _text, output, **_kwargs: (
            output,
            None,
            "NOT_PROVIDED",
        )
        return runtime

    def _intelligence_context(self, proposals) -> RuntimeContext:
        context = RuntimeContext(
            run_id="RUN-CMO-ADAPTIVE-V1",
            objective="Launch a privacy-first productivity app for freelance designers",
            business_id="BIZ-CMO-ADAPTIVE-V1",
            project_id="PROJ-CMO-ADAPTIVE-V1",
        )
        context.status = RuntimeStatus.RUNNING
        context.stage_outputs["cmo_initial"] = {
            "stage": "CMO_INITIAL",
            "agent": "cmo",
            "status": "COMPLETED",
            "strategic_intent": "Research only what is necessary for this objective.",
            "adaptive_task_proposals": proposals,
        }
        return context

    def test_cmo_exposes_only_model_owned_task_proposal_fields(self) -> None:
        runtime = self._base_runtime()
        raw_model_output = f"""Prioritize evidence before creative work.
{_PROPOSAL_OPEN}
[
  {{"kind":"intelligence.market","instruction":"Map category demand","depends_on":["anything"],"writes":["shared.global"],"parallel":true}},
  {{"kind":"creative.angles","instruction":"Develop evidence-backed angles","side_effecting":true,"resource_scope_known":true}}
]
{_PROPOSAL_CLOSE}
"""
        runtime._call_agent_llm = lambda *_args, **_kwargs: (raw_model_output, None)

        context = RuntimeContext(
            run_id="RUN-CMO-PROPOSAL-EXTRACT-V1",
            objective="Launch a privacy-first productivity app for freelance designers",
            business_id="BIZ-CMO-PROPOSAL-EXTRACT-V1",
            project_id="PROJ-CMO-PROPOSAL-EXTRACT-V1",
        )
        context.status = RuntimeStatus.RUNNING

        output = runtime.execute_stage_cmo_initial(context)

        self.assertEqual(output["status"], "COMPLETED")
        self.assertEqual(
            output.get("adaptive_task_proposals"),
            [
                {"kind": "intelligence.market", "instruction": "Map category demand"},
                {"kind": "creative.angles", "instruction": "Develop evidence-backed angles"},
            ],
            "CMO proposal transport must strip model-supplied scheduling/authority fields",
        )
        self.assertNotIn(_PROPOSAL_OPEN, output["strategic_intent"])
        self.assertNotIn(_PROPOSAL_CLOSE, output["strategic_intent"])

    def test_intelligence_uses_only_compiler_authorized_proposals(self) -> None:
        runtime = self._base_runtime()
        runtime._call_agent_llm = lambda *_args, **_kwargs: ("Synthesized intelligence findings", None)
        context = self._intelligence_context(
            [
                {
                    "kind": "intelligence.market",
                    "instruction": "Map category demand and growth",
                    "depends_on": ["invented-model-dependency"],
                    "writes": ["shared.global"],
                    "side_effecting": True,
                    "parallel": False,
                },
                {
                    "kind": "intelligence.customers",
                    "instruction": "Research customer pain points and objections",
                    "depends_on": ["intelligence-market"],
                    "resource_scope_known": False,
                },
                {
                    "kind": "intelligence.untrusted-secret-scan",
                    "instruction": "Do an unregistered task",
                    "agent_id": "performance",
                    "side_effecting": False,
                },
            ]
        )

        state_lock = threading.Lock()
        two_started = threading.Event()
        queries = []
        active = 0
        max_active = 0

        def controlled_dispatch(_idem_key, request):
            nonlocal active, max_active
            with state_lock:
                queries.append(request.parameters.get("query", ""))
                active += 1
                max_active = max(max_active, active)
                ordinal = len(queries)
                if len(queries) >= 2:
                    two_started.set()
            two_started.wait(timeout=0.3)
            receipt = _receipt(f"EXEC-CMO-ADAPTIVE-{ordinal}", request)
            with state_lock:
                active -= 1
            return receipt

        runtime._execute_tool_singleflight = controlled_dispatch

        output = runtime.execute_stage_intelligence(context)

        self.assertEqual(output["status"], "COMPLETED")
        self.assertEqual(
            sorted(queries),
            sorted([
                "Map category demand and growth",
                "Research customer pain points and objections",
            ]),
            "runtime must execute only trusted registered task kinds and must honor model instructions only as data",
        )
        self.assertGreaterEqual(
            max_active,
            2,
            "model-supplied dependency/side-effect claims must not override runtime-owned independence metadata",
        )

    def test_unusable_explicit_proposals_fail_closed_to_one_sequential_search(self) -> None:
        runtime = self._base_runtime()
        runtime._call_agent_llm = lambda *_args, **_kwargs: ("Synthesized intelligence findings", None)
        context = self._intelligence_context(
            [
                {
                    "kind": "intelligence.unregistered-side-effect",
                    "instruction": "Try to gain tool authority",
                    "side_effecting": False,
                    "writes": [],
                    "parallel": True,
                }
            ]
        )

        queries = []

        def dispatch(_idem_key, request):
            queries.append(request.parameters.get("query", ""))
            return _receipt(f"EXEC-CMO-FALLBACK-{len(queries)}", request)

        runtime._execute_tool_singleflight = dispatch

        output = runtime.execute_stage_intelligence(context)

        self.assertEqual(output["status"], "COMPLETED")
        self.assertEqual(
            queries,
            [context.objective],
            "explicit but unusable proposals must fail closed to the single legacy sequential search",
        )


if __name__ == "__main__":
    unittest.main()
