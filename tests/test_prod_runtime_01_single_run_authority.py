"""Targeted Test Suite for PROD-RUNTIME-01: Single Run Authority & Execution Path Convergence.

Validates that every logical department execution converges on the canonical runtime authority:
- One authoritative RuntimeContext per logical run
- Authoritative run_id generation and non-recreation across all six stages
- Final CMO is the same logical CMO (never Agent 6)
- Tool receipts, approvals, and artifacts strictly bind to the originating run_id
- Chat turns create distinct run IDs under the same chat_id
- Concurrent runs (RUN-A, RUN-B) remain fully isolated
- Middle-stage failures and unhandled exceptions fail closed deterministically
"""

from __future__ import annotations

import threading
import time
import unittest
import uuid
from typing import Any, Dict, List, Optional

from app_api.server import DepartmentAppBackend, GLOBAL_API_SESSION_TOKEN
from chat.session import ChatRole
from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.artifacts import DepartmentRunArtifact
from runtime.context import (
    ApprovalState,
    RunIdAlreadyExistsError,
    RunIdReservationError,
    RuntimeContext,
    RuntimeStage,
    RuntimeStatus,
)
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.queue import RunManager, RunQueueStatus
from tools.capabilities import CapabilityDescriptor, CapabilityRegistry, RiskLevel
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyDecision, PolicyEngine, compute_request_fingerprint
from tools.tool_gateway import ToolGateway, ToolRequest


class MockScriptedGateway(UniversalModelGateway):
    """Deterministic scriptable model gateway for runtime testing."""

    def __init__(self, stage_responses: Optional[Dict[str, str]] = None, fail_stage: Optional[str] = None):
        super().__init__(free_only_mode=True)
        self.stage_responses = stage_responses or {}
        self.fail_stage = fail_stage
        self.calls: List[Dict[str, Any]] = []

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        self.calls.append({
            "messages": [m.content for m in request.messages],
            "role": request.messages[0].role.value if request.messages else "",
        })
        sys_msg = request.messages[0].content if request.messages else ""
        stage_directive = sys_msg.split("=== CURRENT RUNTIME STAGE DIRECTIVE ===", 1)[-1]
        resolved_agent = kwargs.get("agent_id") or (request.metadata or {}).get("agent_id")
        if resolved_agent == "cmo":
            stage = (
                "final_cmo"
                if any(marker in stage_directive for marker in (
                    "Final Governed Go-To-Market",
                    "Final Governed Strategy",
                    "governed final synthesis",
                ))
                else "cmo_initial"
            )
        elif resolved_agent in {"intelligence", "content", "creative", "performance"}:
            stage = resolved_agent
        else:
            stage = "unknown"

        if self.fail_stage and self.fail_stage == stage:
            return ModelResponse(
                request_id=request.request_id,
                provider="mock_provider",
                model_name="mock-deterministic",
                status=ModelResponseStatus.ERROR,
                content="",
                error=f"INJECTED_FAILURE_AT_{stage.upper()}",
            )

        if stage in self.stage_responses:
            resp_text = self.stage_responses[stage]
        else:
            resp_text = f"Default deterministic output for {stage} stage."

        return ModelResponse(
            request_id=request.request_id,
            provider="mock_provider",
            model_name="mock-deterministic",
            status=ModelResponseStatus.SUCCESS,
            content=resp_text,
        )


def _build_test_runtime(gateway: Optional[UniversalModelGateway] = None) -> FiveAgentDepartmentRuntime:
    gw = gateway or MockScriptedGateway()
    return FiveAgentDepartmentRuntime(
        model_gateway=gw,
        tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        knowledge_repo=LocalKnowledgeRepository(),
        memory_repo=LocalMemoryRepository(),
    )


def _bind_deployment_ready_final_cmo(ctx: RuntimeContext) -> None:
    """Prepare the canonical Final CMO deployment prerequisite for publish tests."""
    ctx.current_stage = RuntimeStage.FINAL_CMO
    ctx.status = RuntimeStatus.RUNNING
    ctx.stage_outputs["final_cmo"] = {
        "stage": "FINAL_CMO",
        "agent": "cmo",
        "status": "READY_FOR_DEPLOYMENT",
        "approval_status": "APPROVED",
        "reason": "",
        "claim_audit": {"authorization_status": "APPROVED"},
        "master_gtm_plan": {"objective": ctx.objective},
        "master_gtm_plan_markdown": "# Final GTM\n\nApproved deployment plan.",
    }
    ctx.create_checkpoint()


class TestProdRuntime01SingleRunAuthority(unittest.TestCase):
    """30-point certification suite for Single Run Authority & Execution Convergence."""

    def test_01_direct_execution_creates_exactly_one_runtime_context(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Tang truong doanh thu", business_id="BIZ_001")
        self.assertIsInstance(ctx, RuntimeContext)
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))
        self.assertIn(ctx.run_id, rt._active_contexts)
        self.assertIs(rt._active_contexts[ctx.run_id], ctx)

    def test_02_canonical_run_workflow_returns_matching_context_and_artifact(self) -> None:
        rt = _build_test_runtime()
        ctx, final_cmo, artifact = rt.run_workflow(objective="Test Campaign Launch", business_id="BIZ_TEST")
        self.assertIsInstance(ctx, RuntimeContext)
        self.assertIsInstance(artifact, DepartmentRunArtifact)
        self.assertEqual(ctx.run_id, artifact.run_id)
        self.assertEqual(ctx.objective, "Test Campaign Launch")
        self.assertEqual(ctx.business_id, "BIZ_TEST")
        self.assertIn(ctx.run_id, rt._completed_runs)
        self.assertIs(rt._completed_runs[ctx.run_id], artifact)

    def test_03_same_run_id_propagated_through_all_six_stages(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Multi-stage invariant check", business_id="BIZ_001")
        initial_run_id = ctx.run_id
        stages = [
            rt.execute_stage_cmo_initial,
            rt.execute_stage_intelligence,
            rt.execute_stage_strategist,
            rt.execute_stage_creative,
            rt.execute_stage_performance,
            rt.execute_stage_final_cmo,
        ]
        for stage_fn in stages:
            stage_fn(ctx)
            self.assertEqual(ctx.run_id, initial_run_id)
            self.assertIn(ctx.run_id, rt._active_contexts)
        artifact = rt.complete_run(ctx)
        self.assertEqual(artifact.run_id, initial_run_id)

    def test_04_final_cmo_uses_same_logical_cmo_not_agent_6(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Verify final CMO identity", business_id="BIZ_001")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)
        final_cmo = rt.execute_stage_final_cmo(ctx)
        self.assertEqual(final_cmo.get("agent"), "cmo")
        self.assertEqual(final_cmo.get("stage"), "FINAL_CMO")
        allowed_agents = {"cmo", "intelligence", "content", "creative", "performance"}
        for s_name, s_out in ctx.stage_outputs.items():
            self.assertIn(s_out.get("agent"), allowed_agents, f"Unexpected agent in stage {s_name}: {s_out.get('agent')}")

    def test_05_tool_receipts_strictly_bind_to_originating_run_id(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Receipt binding check", business_id="BIZ_001")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)
        rt.execute_stage_final_cmo(ctx)
        artifact = rt.complete_run(ctx)
        self.assertGreaterEqual(len(ctx.execution_receipt_refs), 1)
        for receipt_id in ctx.execution_receipt_refs:
            receipt = rt.tool_gateway.receipt_repository.get_receipt(receipt_id)
            self.assertIsNotNone(receipt)
            self.assertEqual(receipt.run_id, ctx.run_id, f"Receipt {receipt_id} has mismatched run_id {receipt.run_id} vs {ctx.run_id}")
        for rec in artifact.execution_receipts:
            self.assertEqual(rec.run_id, ctx.run_id)

    def test_06_approval_for_run_a_cannot_authorize_run_b(self) -> None:
        policy = PolicyEngine()
        pending_a = policy.create_pending_approval(
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Post content"},
            risk_level=RiskLevel.HIGH,
            run_id="RUN-A-1111",
            business_id="BIZ_001",
        )
        success, approval_record, err = policy.approve_pending_action(pending_a.pending_approval_id, approved_by="Human Operator")
        self.assertTrue(success)
        self.assertIsNotNone(approval_record)
        self.assertIsNotNone(approval_record.approval_token)
        tool_gw = ToolGateway(capability_registry=CapabilityRegistry(), policy_engine=policy)
        cap = tool_gw.registry.get_capability("social_publishing")
        self.assertIsNotNone(cap)
        decision_b = policy.evaluate(
            agent_id="cmo",
            capability=cap,
            approval_token=approval_record.approval_token,
            run_id="RUN-B-2222",
            business_id="BIZ_001",
            parameters={"platform": "linkedin", "content": "Post content"},
        )
        self.assertFalse(decision_b.allowed)
        self.assertEqual(decision_b.error_code, "APPROVAL_RUN_MISMATCH")
        req_b = ToolRequest(
            run_id="RUN-B-2222",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Post content"},
            approval_token=approval_record.approval_token,
        )
        receipt_b = tool_gw.execute(req_b)
        self.assertEqual(receipt_b.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertIn("APPROVAL_RUN_MISMATCH", receipt_b.error_message)

    def test_07_artifact_lineage_and_hash_bind_to_authoritative_run_id(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Artifact lineage test", business_id="BIZ_001")
        rt.execute_stage_cmo_initial(ctx)
        rt.execute_stage_intelligence(ctx)
        rt.execute_stage_strategist(ctx)
        rt.execute_stage_creative(ctx)
        rt.execute_stage_performance(ctx)
        rt.execute_stage_final_cmo(ctx)
        artifact = rt.complete_run(ctx)
        self.assertEqual(artifact.run_id, ctx.run_id)
        self.assertIsNotNone(artifact.final_artifact_hash)
        self.assertEqual(len(artifact.final_artifact_hash), 64)

    def test_08_same_chat_session_creates_distinct_run_id_per_message_turn(self) -> None:
        rt = _build_test_runtime()
        chat_id = "CHAT_SESSION_TEST_001"
        ctx1, _, art1 = rt.run_workflow(objective="Turn 1 objective", chat_id=chat_id, business_id="BIZ_001")
        ctx2, _, art2 = rt.run_workflow(objective="Turn 2 objective", chat_id=chat_id, business_id="BIZ_001")
        self.assertEqual(ctx1.chat_id, chat_id)
        self.assertEqual(ctx2.chat_id, chat_id)
        self.assertNotEqual(ctx1.run_id, ctx2.run_id, "Different chat turns must receive distinct run IDs")
        self.assertNotEqual(art1.run_id, art2.run_id)

    def test_09_run_manager_preserves_run_id_without_forking(self) -> None:
        rt = _build_test_runtime()
        manager = RunManager(runtime=rt, max_workers=1)
        run_id = "RUN-Q-PRESERVE-001"
        item = manager.enqueue_run(
            run_id=run_id,
            objective="Queued campaign execution",
            business_id="BIZ_QUEUE",
            project_id="PROJ_QUEUE",
        )
        timeout = 5.0
        start = time.time()
        while time.time() - start < timeout:
            if item.status in (RunQueueStatus.COMPLETED, RunQueueStatus.FAILED):
                break
            time.sleep(0.05)
        self.assertEqual(item.status, RunQueueStatus.COMPLETED)
        self.assertEqual(item.run_id, run_id, "item.run_id was corrupted or forked by worker loop")
        self.assertIsNotNone(item.artifact)
        self.assertEqual(item.artifact.run_id, run_id)
        manager._stop_event.set()

    def test_10_concurrent_runs_do_not_bleed_context_or_state(self) -> None:
        rt = _build_test_runtime()
        results: Dict[str, Any] = {}
        def run_thread(thread_id: str, obj: str, biz: str) -> None:
            ctx, final_out, art = rt.run_workflow(objective=obj, business_id=biz)
            results[thread_id] = {"ctx": ctx, "final_out": final_out, "art": art}
        t1 = threading.Thread(target=run_thread, args=("A", "Objective A", "BIZ_AAA"))
        t2 = threading.Thread(target=run_thread, args=("B", "Objective B", "BIZ_BBB"))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertIn("A", results); self.assertIn("B", results)
        ctx_a = results["A"]["ctx"]; ctx_b = results["B"]["ctx"]
        art_a = results["A"]["art"]; art_b = results["B"]["art"]
        self.assertNotEqual(ctx_a.run_id, ctx_b.run_id)
        self.assertEqual(ctx_a.objective, "Objective A")
        self.assertEqual(ctx_b.objective, "Objective B")
        self.assertEqual(ctx_a.business_id, "BIZ_AAA")
        self.assertEqual(ctx_b.business_id, "BIZ_BBB")
        self.assertEqual(art_a.run_id, ctx_a.run_id)
        self.assertEqual(art_b.run_id, ctx_b.run_id)

    def test_11_middle_stage_failure_marks_context_failed_deterministically(self) -> None:
        failing_gw = MockScriptedGateway(fail_stage="content")
        rt = _build_test_runtime(gateway=failing_gw)
        ctx, final_cmo, artifact = rt.run_workflow(objective="Fail on strategist", business_id="BIZ_001")
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        self.assertEqual(final_cmo.get("status"), "NOT_REACHED")
        self.assertEqual(final_cmo.get("failed_stage"), "CONTENT")
        self.assertNotIn("PREVIOUS_STAGE_FAILED", final_cmo.get("reason", ""))

    def test_12_unhandled_exception_translates_to_deterministic_terminal_failure(self) -> None:
        rt = _build_test_runtime()
        def crashing_stage(ctx: RuntimeContext) -> Dict[str, Any]:
            raise RuntimeError("UNEXPECTED_PIPELINE_CRASH")
        rt.execute_stage_intelligence = crashing_stage
        ctx = rt.start_run(objective="Test unhandled exception", business_id="BIZ_001")
        ctx, final_cmo, artifact = rt.execute_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        self.assertEqual(final_cmo.get("status"), "FAILED")
        self.assertIn("UNHANDLED_RUNTIME_EXCEPTION", final_cmo.get("reason", ""))
        self.assertIn("UNEXPECTED_PIPELINE_CRASH", final_cmo.get("reason", ""))

    def test_13_waiting_for_approval_state_not_falsely_completed(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Publishing approval test", business_id="BIZ_001")
        rt.execute_stage_cmo_initial(ctx)
        _bind_deployment_ready_final_cmo(ctx)
        receipt = rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)

    def test_14_api_execute_routed_turn_uses_canonical_runtime(self) -> None:
        backend = DepartmentAppBackend()
        backend.runtime.model_gateway = MockScriptedGateway()
        session = backend.chat_mgr.create_session(title="API Route Test", business_id="BIZ_API")
        ctx, final_cmo, artifact = backend.runtime.run_workflow(
            objective="API Marketing Workflow Request",
            business_id=session.optional_business_id,
            chat_id=session.chat_id,
        )
        self.assertEqual(ctx.chat_id, session.chat_id)
        self.assertNotIn(ctx.run_id, backend.runtime._active_contexts)
        self.assertIn(ctx.run_id, backend.runtime._completed_runs)
        self.assertEqual(artifact.run_id, ctx.run_id)

    def test_15_untrusted_caller_cannot_force_arbitrary_run_id(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Malicious ID test", run_id="HACKED_INJECTION_ID_123")
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))
        self.assertNotEqual(ctx.run_id, "HACKED_INJECTION_ID_123")

    def test_16_chat_regenerate_turn_creates_new_run_id(self) -> None:
        rt = _build_test_runtime()
        chat_id = "CHAT_REGEN_001"
        ctx_orig, _, art_orig = rt.run_workflow(objective="Initial plan", chat_id=chat_id)
        ctx_regen, _, art_regen = rt.run_workflow(objective="Regenerated plan", chat_id=chat_id)
        self.assertNotEqual(ctx_orig.run_id, ctx_regen.run_id)
        self.assertNotEqual(art_orig.final_artifact_hash, art_regen.final_artifact_hash)

    def test_17_operator_workspace_uses_canonical_runtime(self) -> None:
        from workspace.operator import OperatorWorkspace
        rt = _build_test_runtime()
        op = OperatorWorkspace(runtime=rt)
        ctx = op.create_run(business_id="BIZ_OP_TEST", objective="Operator test campaign")
        self.assertIsInstance(ctx, RuntimeContext)
        self.assertIn(ctx.run_id, rt._active_contexts)
        self.assertEqual(ctx.business_id, "BIZ_OP_TEST")

    def test_18_completed_run_artifact_stored_in_runtime_completed_runs(self) -> None:
        rt = _build_test_runtime()
        ctx, _, art = rt.run_workflow(objective="Indexing test", business_id="BIZ_001")
        self.assertIn(ctx.run_id, rt._completed_runs)
        self.assertEqual(rt._completed_runs[ctx.run_id].final_artifact_hash, art.final_artifact_hash)

    def test_19_terminal_failed_state_is_never_overwritten_to_completed(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Failure preservation", business_id="BIZ_001")
        ctx.status = RuntimeStatus.FAILED
        art = rt.complete_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(art.status, RuntimeStatus.FAILED)

    def test_20_metadata_preservation_across_execution_boundary(self) -> None:
        rt = _build_test_runtime()
        ctx, _, art = rt.run_workflow(
            objective="Metadata test",
            business_id="BIZ_PRESERVE_123",
            campaign_id="CAMP_PRESERVE_456",
            user_id="USER_PRESERVE_789",
            chat_id="CHAT_PRESERVE_001",
            project_id="PROJ_PRESERVE_002",
        )
        self.assertEqual(ctx.business_id, "BIZ_PRESERVE_123")
        self.assertEqual(ctx.campaign_id, "CAMP_PRESERVE_456")
        self.assertEqual(ctx.user_id, "USER_PRESERVE_789")
        self.assertEqual(ctx.chat_id, "CHAT_PRESERVE_001")
        self.assertEqual(ctx.project_id, "PROJ_PRESERVE_002")

    def test_21_runtime_generated_id_has_128_bit_entropy(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Entropy test")
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))
        self.assertEqual(len(ctx.run_id), 41)
        raw_hex = ctx.run_id.replace("RUN-DEPT-", "")
        self.assertEqual(len(raw_hex), 32)
        int(raw_hex, 16)

    def test_22_duplicate_active_run_id_rejected(self) -> None:
        rt = _build_test_runtime()
        rt.start_run(objective="Run 1", trusted_run_id="RUN-ACTIVE-TEST-001")
        self.assertIn("RUN-ACTIVE-TEST-001", rt._active_contexts)
        with self.assertRaises(RunIdAlreadyExistsError):
            rt.start_run(objective="Run 2 collision", trusted_run_id="RUN-ACTIVE-TEST-001")

    def test_23_historical_run_id_reuse_rejected(self) -> None:
        rt = _build_test_runtime()
        rt.run_workflow(objective="Run 1", trusted_run_id="RUN-HIST-TEST-001")
        self.assertIn("RUN-HIST-TEST-001", rt._completed_runs)
        with self.assertRaises(RunIdAlreadyExistsError):
            rt.start_run(objective="Run 2 reuse", trusted_run_id="RUN-HIST-TEST-001")

    def test_24_duplicate_id_cannot_overwrite_active_context(self) -> None:
        rt = _build_test_runtime()
        rt.start_run(objective="Original active context", trusted_run_id="RUN-NO-OVERWRITE-001")
        try:
            rt.start_run(objective="Attempted overwrite context", trusted_run_id="RUN-NO-OVERWRITE-001")
        except RunIdAlreadyExistsError:
            pass
        self.assertEqual(rt._active_contexts["RUN-NO-OVERWRITE-001"].objective, "Original active context")

    def test_25_duplicate_id_cannot_collide_artifacts(self) -> None:
        rt = _build_test_runtime()
        rt.run_workflow(objective="Original artifact", trusted_run_id="RUN-NO-COLLIDE-001")
        try:
            rt.run_workflow(objective="Attempted collide artifact", trusted_run_id="RUN-NO-COLLIDE-001")
        except RunIdAlreadyExistsError:
            pass
        self.assertEqual(rt._completed_runs["RUN-NO-COLLIDE-001"].objective, "Original artifact")

    def test_26_terminal_completed_removed_from_active_registry(self) -> None:
        rt = _build_test_runtime()
        ctx, _, _ = rt.run_workflow(objective="Completion cleanup test")
        self.assertEqual(ctx.status, RuntimeStatus.COMPLETED)
        self.assertNotIn(ctx.run_id, rt._active_contexts)
        self.assertIn(ctx.run_id, rt._completed_runs)

    def test_27_terminal_failed_removed_from_active_registry(self) -> None:
        rt = _build_test_runtime(gateway=MockScriptedGateway(fail_stage="intelligence"))
        ctx, _, _ = rt.run_workflow(objective="Failure cleanup test")
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertNotIn(ctx.run_id, rt._active_contexts)
        self.assertIn(ctx.run_id, rt._completed_runs)

    def test_28_terminal_cancelled_removed_from_active_registry(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Cancel cleanup test")
        rt.cancel_run(ctx.run_id)
        ctx, _, _ = rt.execute_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)
        self.assertNotIn(ctx.run_id, rt._active_contexts)
        self.assertIn(ctx.run_id, rt._completed_runs)

    def test_29_waiting_for_approval_remains_in_active_contexts(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Approval wait test")
        _bind_deployment_ready_final_cmo(ctx)
        rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)
        self.assertIn(ctx.run_id, rt._active_contexts)

    def test_30_memory_leak_100_runs_active_contexts_empty(self) -> None:
        rt = _build_test_runtime()
        for i in range(100):
            rt.run_workflow(objective=f"Quick batch run {i}")
        self.assertEqual(len(rt._active_contexts), 0, f"Memory leak: {len(rt._active_contexts)} contexts left active")
        self.assertEqual(len(rt._completed_runs), 100)

    def test_31_active_cancellation_prevents_subsequent_stages(self) -> None:
        rt = _build_test_runtime()
        executed_stages: List[str] = []
        orig_cmo = rt.execute_stage_cmo_initial
        orig_intel = rt.execute_stage_intelligence
        orig_strat = rt.execute_stage_strategist
        def tracked_cmo(c: RuntimeContext) -> Dict[str, Any]:
            executed_stages.append("cmo_initial")
            out = orig_cmo(c)
            rt.cancel_run(c.run_id)
            return out
        def tracked_intel(c: RuntimeContext) -> Dict[str, Any]:
            executed_stages.append("intelligence")
            return orig_intel(c)
        def tracked_strat(c: RuntimeContext) -> Dict[str, Any]:
            executed_stages.append("content")
            return orig_strat(c)
        rt.execute_stage_cmo_initial = tracked_cmo
        rt.execute_stage_intelligence = tracked_intel
        rt.execute_stage_strategist = tracked_strat
        ctx = rt.start_run(objective="Cancellation barrier test")
        ctx, _, art = rt.execute_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)
        self.assertEqual(art.status, RuntimeStatus.CANCELLED)
        self.assertIn("cmo_initial", executed_stages)
        self.assertNotIn("intelligence", executed_stages)
        self.assertNotIn("content", executed_stages)

    def test_32_cancelled_run_cannot_become_completed(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Cancelled completion test")
        ctx.status = RuntimeStatus.CANCELLED
        art = rt.complete_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)
        self.assertEqual(art.status, RuntimeStatus.CANCELLED)

    def test_33_cancel_run_a_does_not_affect_concurrent_run_b(self) -> None:
        rt = _build_test_runtime()
        ctx_a = rt.start_run(objective="Run A to cancel")
        ctx_b = rt.start_run(objective="Run B to complete")
        rt.cancel_run(ctx_a.run_id)
        ctx_a, _, art_a = rt.execute_run(ctx_a)
        ctx_b, _, art_b = rt.execute_run(ctx_b)
        self.assertEqual(ctx_a.status, RuntimeStatus.CANCELLED)
        self.assertEqual(art_a.status, RuntimeStatus.CANCELLED)
        self.assertEqual(ctx_b.status, RuntimeStatus.COMPLETED)
        self.assertEqual(art_b.status, RuntimeStatus.COMPLETED)

    def test_34_queue_and_context_terminal_statuses_agree(self) -> None:
        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=1)
        item = mgr.enqueue_run(objective="Queue convergence test")
        timeout = 5.0
        start = time.time()
        while time.time() - start < timeout:
            if item.status in (RunQueueStatus.COMPLETED, RunQueueStatus.FAILED, RunQueueStatus.CANCELLED):
                break
            time.sleep(0.05)
        self.assertEqual(item.status, RunQueueStatus.COMPLETED)
        self.assertIn(item.run_id, rt._completed_runs)
        self.assertEqual(rt._completed_runs[item.run_id].status, RuntimeStatus.COMPLETED)
        mgr._stop_event.set()

    def test_35_queue_preallocated_id_is_runtime_owned_reservation(self) -> None:
        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=0)
        item = mgr.enqueue_run(objective="Preallocation test")
        self.assertTrue(item.run_id.startswith("RUN-DEPT-"))
        self.assertEqual(len(item.run_id), 41)
        self.assertTrue(rt.is_reserved_run_id(item.run_id))
        mgr._stop_event.set()

    def test_36_untrusted_custom_run_id_reservation_error(self) -> None:
        rt = _build_test_runtime()
        with self.assertRaises(RunIdReservationError):
            rt.reserve_run_id(custom_id="HACKED_INJECTION_ID", trusted=False)

    def test_37_completed_runs_cache_bounded_lru(self) -> None:
        rt = FiveAgentDepartmentRuntime(
            model_gateway=MockScriptedGateway(),
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
            knowledge_repo=LocalKnowledgeRepository(),
            memory_repo=LocalMemoryRepository(),
            max_completed_runs_cache=10,
        )
        for i in range(25):
            rt.run_workflow(objective=f"Run {i}")
        self.assertEqual(len(rt._completed_runs), 10)
        self.assertEqual(len(rt._active_contexts), 0)

    def test_38_cancelled_id_tracking_cleaned_up_on_completion(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Cancel cleanup test")
        rt.cancel_run(ctx.run_id)
        self.assertIn(ctx.run_id, rt._cancelled_run_ids)
        rt.complete_run(ctx)
        self.assertNotIn(ctx.run_id, rt._cancelled_run_ids)

    def test_39_abandoned_reservation_release(self) -> None:
        rt = _build_test_runtime()
        rid = rt.reserve_run_id()
        self.assertTrue(rt.is_reserved_run_id(rid))
        released = rt.release_reservation(rid)
        self.assertTrue(released)
        self.assertFalse(rt.is_reserved_run_id(rid))

    def test_40_queue_waiting_for_approval_sync(self) -> None:
        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=0)
        rid = rt.reserve_run_id()
        mgr.enqueue_run(objective="Approval wait queue test", run_id=rid)
        ctx = rt.start_run(objective="Approval wait", reserved_run_id=rid)
        _bind_deployment_ready_final_cmo(ctx)
        rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)
        queried_item = mgr.get_run(rid)
        self.assertIsNotNone(queried_item)
        self.assertEqual(queried_item.status, RunQueueStatus.WAITING_APPROVAL)
        mgr._stop_event.set()

    def test_41_queue_approval_resume_returns_to_running(self) -> None:
        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=0)
        rid = rt.reserve_run_id()
        mgr.enqueue_run(objective="Approval resume queue test", run_id=rid)
        ctx = rt.start_run(objective="Approval wait", reserved_run_id=rid)
        _bind_deployment_ready_final_cmo(ctx)
        rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(mgr.get_run(rid).status, RunQueueStatus.WAITING_APPROVAL)
        policy = rt.tool_gateway.policy_engine
        pending_list = policy.list_pending_approvals()
        self.assertGreater(len(pending_list), 0)
        pending = pending_list[-1]
        ok, appr_rec, _ = policy.approve_pending_action(pending.pending_approval_id, approved_by="Operator")
        self.assertTrue(ok)
        rec = rt.request_publish_action(ctx, platform="linkedin", approval_token=appr_rec.approval_token)
        self.assertEqual(rec.status, ExecutionStatus.SUCCESS)
        self.assertEqual(ctx.status, RuntimeStatus.RUNNING)
        self.assertEqual(mgr.get_run(rid).status, RunQueueStatus.RUNNING)
        mgr._stop_event.set()

    def test_42_gateway_fallback_candidate_b_executes_after_timeout(self) -> None:
        from integrations.models.base import BaseModelAdapter
        from integrations.models.registry import ProviderConfig
        class TimingOutAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "adapter_a"
            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(request_id=req.request_id, provider="adapter_a", model_name="model_a",
                    status=ModelResponseStatus.TIMEOUT, error="TIMEOUT: Request timed out.")
        class SuccessfulAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "adapter_b"
            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(request_id=req.request_id, provider="adapter_b", model_name="model_b",
                    status=ModelResponseStatus.SUCCESS, content="Success from adapter B")
        gw = UniversalModelGateway(free_only_mode=False)
        gw.provider_registry.register_provider(ProviderConfig(provider_id="adapter_a", api_key_env="DUMMY", default_model="model_a"))
        gw.provider_registry.register_provider(ProviderConfig(provider_id="adapter_b", api_key_env="DUMMY", default_model="model_b"))
        gw.provider_registry._adapters["adapter_a"] = TimingOutAdapter()
        gw.provider_registry._adapters["adapter_b"] = SuccessfulAdapter()
        gw.provider_registry._has_custom_adapters = True
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        resp = gw.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.content, "Success from adapter B")

    def test_43_gateway_overall_fallback_budget_bounded(self) -> None:
        from integrations.models.base import BaseModelAdapter
        from integrations.models.registry import ProviderConfig
        class SlowAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "slow_adapter"
            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(request_id=req.request_id, provider="slow_adapter", model_name="slow_model",
                    status=ModelResponseStatus.TIMEOUT, error="TIMEOUT: Slow timeout")
        gw = UniversalModelGateway(free_only_mode=False)
        gw.provider_registry.register_provider(ProviderConfig(provider_id="slow_1", api_key_env="DUMMY", default_model="slow_1"))
        gw.provider_registry.register_provider(ProviderConfig(provider_id="slow_2", api_key_env="DUMMY", default_model="slow_2"))
        gw.provider_registry._adapters["slow_1"] = SlowAdapter()
        gw.provider_registry._adapters["slow_2"] = SlowAdapter()
        gw.provider_registry._has_custom_adapters = True
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")], timeout_seconds=0.01)
        resp = gw.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.TIMEOUT)

    def test_44_gateway_provider_agnostic_timeout_semantics(self) -> None:
        from integrations.models.base import BaseModelAdapter
        from integrations.models.registry import ProviderConfig
        class CustomAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "generic_x"
            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(request_id=req.request_id, provider="generic_x", model_name="custom-v1",
                    status=ModelResponseStatus.SUCCESS, content="Generic provider response")
        gw = UniversalModelGateway(free_only_mode=False)
        gw.provider_registry.register_provider(ProviderConfig(provider_id="generic_x", api_key_env="DUMMY", default_model="custom-v1"))
        gw.provider_registry._adapters["generic_x"] = CustomAdapter()
        gw.provider_registry._has_custom_adapters = True
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Test")])
        resp = gw.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.content, "Generic provider response")

    def test_45_untrusted_caller_cannot_access_trusted_run_id_authority(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Untrusted test", run_id="RUN_MALICIOUS_001")
        self.assertNotEqual(ctx.run_id, "RUN_MALICIOUS_001")
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))

    def test_46_get_active_context_and_get_completed_run_lookups(self) -> None:
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Lookup test")
        self.assertIs(rt.get_active_context(ctx.run_id), ctx)
        self.assertIsNone(rt.get_completed_run(ctx.run_id))
        art = rt.complete_run(ctx)
        self.assertIsNone(rt.get_active_context(ctx.run_id))
        self.assertIs(rt.get_completed_run(ctx.run_id), art)


if __name__ == "__main__":
    unittest.main()
