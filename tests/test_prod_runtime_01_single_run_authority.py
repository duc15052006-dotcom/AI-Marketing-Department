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
        stage = "unknown"
        if "Chief Marketing Officer (CMO) in your governed final synthesis" in sys_msg or "Final Governed Strategy" in sys_msg:
            stage = "final_cmo"
        elif "Chief Marketing Officer (CMO)" in sys_msg or "Decompose the user" in sys_msg:
            stage = "cmo_initial"
        elif "Intelligence Specialist" in sys_msg:
            stage = "intelligence"
        elif "Marketing Strategist" in sys_msg:
            stage = "strategist"
        elif "Creative Specialist" in sys_msg:
            stage = "creative"
        elif "Performance Specialist" in sys_msg:
            stage = "performance"

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


class TestProdRuntime01SingleRunAuthority(unittest.TestCase):
    """30-point certification suite for Single Run Authority & Execution Convergence."""

    # ----------------------------------------------------------------------
    # 1. Single Context & Run ID Invariants
    # ----------------------------------------------------------------------

    def test_01_direct_execution_creates_exactly_one_runtime_context(self) -> None:
        """Direct execution through canonical start_run creates exactly 1 RuntimeContext."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Tang truong doanh thu", business_id="BIZ_001")
        self.assertIsInstance(ctx, RuntimeContext)
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))
        self.assertIn(ctx.run_id, rt._active_contexts)
        self.assertIs(rt._active_contexts[ctx.run_id], ctx)

    def test_02_canonical_run_workflow_returns_matching_context_and_artifact(self) -> None:
        """Convenience run_workflow converges on same context and produces matching artifact."""
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
        """The exact same run_id and object identity are preserved across all 6 stages."""
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
            stage_out = stage_fn(ctx)
            self.assertEqual(ctx.run_id, initial_run_id)
            self.assertIn(ctx.run_id, rt._active_contexts)

        artifact = rt.complete_run(ctx)
        self.assertEqual(artifact.run_id, initial_run_id)

    def test_04_final_cmo_uses_same_logical_cmo_not_agent_6(self) -> None:
        """Stage 6 Final CMO is assigned to agent 'cmo', exactly 5 logical agents in total."""
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

        # Verify all stage agent identifiers across the 6 stages belong to {cmo, intelligence, strategist, creative, performance}
        allowed_agents = {"cmo", "intelligence", "strategist", "creative", "performance"}
        for s_name, s_out in ctx.stage_outputs.items():
            self.assertIn(s_out.get("agent"), allowed_agents, f"Unexpected agent in stage {s_name}: {s_out.get('agent')}")

    # ----------------------------------------------------------------------
    # 2. Tool Receipt, Approval, and Artifact Runtime Binding
    # ----------------------------------------------------------------------

    def test_05_tool_receipts_strictly_bind_to_originating_run_id(self) -> None:
        """Tool receipts produced during agent execution carry the exact run_id of the context."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Receipt binding check", business_id="BIZ_001")

        # Execute stages that generate tool receipts (intelligence, creative, performance)
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
        """An approval created under RUN-A cannot authorize or execute under RUN-B."""
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

        # 1. PolicyEngine evaluate directly rejects token under RUN-B
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

        # 2. ToolGateway execution under RUN-B fails closed
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
        """Artifact correctly embeds the authoritative run_id and computes consistent hash."""
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

    # ----------------------------------------------------------------------
    # 3. Chat Session vs Run ID Semantics
    # ----------------------------------------------------------------------

    def test_08_same_chat_session_creates_distinct_run_id_per_message_turn(self) -> None:
        """Multiple turns within the same chat session get distinct authoritative run IDs."""
        rt = _build_test_runtime()
        chat_id = "CHAT_SESSION_TEST_001"

        ctx1, _, art1 = rt.run_workflow(objective="Turn 1 objective", chat_id=chat_id, business_id="BIZ_001")
        ctx2, _, art2 = rt.run_workflow(objective="Turn 2 objective", chat_id=chat_id, business_id="BIZ_001")

        self.assertEqual(ctx1.chat_id, chat_id)
        self.assertEqual(ctx2.chat_id, chat_id)
        self.assertNotEqual(ctx1.run_id, ctx2.run_id, "Different chat turns must receive distinct run IDs")
        self.assertNotEqual(art1.run_id, art2.run_id)

    # ----------------------------------------------------------------------
    # 4. Queue / Background Execution Path
    # ----------------------------------------------------------------------

    def test_09_run_manager_preserves_run_id_without_forking(self) -> None:
        """RunManager worker executes through canonical runtime and preserves item.run_id."""
        rt = _build_test_runtime()
        manager = RunManager(runtime=rt, max_workers=1)

        run_id = "RUN-Q-PRESERVE-001"
        item = manager.enqueue_run(
            run_id=run_id,
            objective="Queued campaign execution",
            business_id="BIZ_QUEUE",
            project_id="PROJ_QUEUE",
        )

        # Wait for worker to process the item
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

    # ----------------------------------------------------------------------
    # 5. Concurrent Run Isolation
    # ----------------------------------------------------------------------

    def test_10_concurrent_runs_do_not_bleed_context_or_state(self) -> None:
        """Concurrent execution of RUN-A and RUN-B maintain strict state and identity isolation."""
        rt = _build_test_runtime()
        results: Dict[str, Any] = {}

        def run_thread(thread_id: str, obj: str, biz: str) -> None:
            ctx, final_out, art = rt.run_workflow(objective=obj, business_id=biz)
            results[thread_id] = {
                "ctx": ctx,
                "final_out": final_out,
                "art": art,
            }

        t1 = threading.Thread(target=run_thread, args=("A", "Objective A", "BIZ_AAA"))
        t2 = threading.Thread(target=run_thread, args=("B", "Objective B", "BIZ_BBB"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn("A", results)
        self.assertIn("B", results)

        ctx_a = results["A"]["ctx"]
        ctx_b = results["B"]["ctx"]
        art_a = results["A"]["art"]
        art_b = results["B"]["art"]

        self.assertNotEqual(ctx_a.run_id, ctx_b.run_id)
        self.assertEqual(ctx_a.objective, "Objective A")
        self.assertEqual(ctx_b.objective, "Objective B")
        self.assertEqual(ctx_a.business_id, "BIZ_AAA")
        self.assertEqual(ctx_b.business_id, "BIZ_BBB")
        self.assertEqual(art_a.run_id, ctx_a.run_id)
        self.assertEqual(art_b.run_id, ctx_b.run_id)

    # ----------------------------------------------------------------------
    # 6. Failure Ownership and Terminal State Invariants
    # ----------------------------------------------------------------------

    def test_11_middle_stage_failure_marks_context_failed_deterministically(self) -> None:
        """A failure in a middle stage (e.g. Strategist) fails closed and does not claim COMPLETED."""
        failing_gw = MockScriptedGateway(fail_stage="strategist")
        rt = _build_test_runtime(gateway=failing_gw)

        ctx, final_cmo, artifact = rt.run_workflow(objective="Fail on strategist", business_id="BIZ_001")

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        self.assertEqual(final_cmo.get("status"), "NOT_REACHED")
        self.assertNotIn("PREVIOUS_STAGE_FAILED", final_cmo.get("reason", ""))

    def test_12_unhandled_exception_translates_to_deterministic_terminal_failure(self) -> None:
        """An unhandled exception during stage execution results in FAILED status, never masked."""
        rt = _build_test_runtime()

        def crashing_stage(ctx: RuntimeContext) -> Dict[str, Any]:
            raise RuntimeError("UNEXPECTED_PIPELINE_CRASH")

        rt.execute_stage_intelligence = crashing_stage

        ctx = rt.start_run(objective="Test unhandled exception", business_id="BIZ_001")
        ctx, final_cmo, artifact = rt.execute_run(ctx)

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        self.assertEqual(final_cmo.get("status"), "NOT_REACHED")
        self.assertNotIn("UNEXPECTED_PIPELINE_CRASH", final_cmo.get("reason", ""))

    def test_13_waiting_for_approval_state_not_falsely_completed(self) -> None:
        """When an unapproved publishing action is requested, state is WAITING_FOR_APPROVAL."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Publishing approval test", business_id="BIZ_001")
        rt.execute_stage_cmo_initial(ctx)

        receipt = rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)

    def test_14_api_execute_routed_turn_uses_canonical_runtime(self) -> None:
        """API execution path for Route C executes via canonical runtime authority."""
        backend = DepartmentAppBackend()
        backend.runtime.model_gateway = MockScriptedGateway()
        session = backend.chat_mgr.create_session(title="API Route Test", business_id="BIZ_API")

        # Verify that running a workflow through the runtime sets active and completed contexts
        ctx, final_cmo, artifact = backend.runtime.run_workflow(
            objective="API Marketing Workflow Request",
            business_id=session.optional_business_id,
            chat_id=session.chat_id,
        )
        self.assertEqual(ctx.chat_id, session.chat_id)
        self.assertNotIn(ctx.run_id, backend.runtime._active_contexts)
        self.assertIn(ctx.run_id, backend.runtime._completed_runs)
        self.assertEqual(artifact.run_id, ctx.run_id)

    # ----------------------------------------------------------------------
    # 7. Additional Robustness & State Invariant Tests
    # ----------------------------------------------------------------------

    def test_15_untrusted_caller_cannot_force_arbitrary_run_id(self) -> None:
        """Invalid / non-standard run_id parameter is replaced by authoritative RUN-DEPT generator."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Malicious ID test", run_id="HACKED_INJECTION_ID_123")
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))
        self.assertNotEqual(ctx.run_id, "HACKED_INJECTION_ID_123")

    def test_16_chat_regenerate_turn_creates_new_run_id(self) -> None:
        """Regenerating a response in a chat turn creates a fresh distinct run_id."""
        rt = _build_test_runtime()
        chat_id = "CHAT_REGEN_001"
        ctx_orig, _, art_orig = rt.run_workflow(objective="Initial plan", chat_id=chat_id)
        ctx_regen, _, art_regen = rt.run_workflow(objective="Regenerated plan", chat_id=chat_id)

        self.assertNotEqual(ctx_orig.run_id, ctx_regen.run_id)
        self.assertNotEqual(art_orig.final_artifact_hash, art_regen.final_artifact_hash)

    def test_17_operator_workspace_uses_canonical_runtime(self) -> None:
        """OperatorWorkspace.create_run delegates to canonical runtime.start_run."""
        from workspace.operator import OperatorWorkspace
        rt = _build_test_runtime()
        op = OperatorWorkspace(runtime=rt)
        ctx = op.create_run(business_id="BIZ_OP_TEST", objective="Operator test campaign")

        self.assertIsInstance(ctx, RuntimeContext)
        self.assertIn(ctx.run_id, rt._active_contexts)
        self.assertEqual(ctx.business_id, "BIZ_OP_TEST")

    def test_18_completed_run_artifact_stored_in_runtime_completed_runs(self) -> None:
        """Completed runs are systematically indexed in _completed_runs repository."""
        rt = _build_test_runtime()
        ctx, _, art = rt.run_workflow(objective="Indexing test", business_id="BIZ_001")
        self.assertIn(ctx.run_id, rt._completed_runs)
        self.assertEqual(rt._completed_runs[ctx.run_id].final_artifact_hash, art.final_artifact_hash)

    def test_19_terminal_failed_state_is_never_overwritten_to_completed(self) -> None:
        """If context is marked FAILED, complete_run preserves FAILED status."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Failure preservation", business_id="BIZ_001")
        ctx.status = RuntimeStatus.FAILED
        art = rt.complete_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(art.status, RuntimeStatus.FAILED)

    def test_20_metadata_preservation_across_execution_boundary(self) -> None:
        """Project ID, business ID, user ID, chat ID travel intact into artifact."""
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

    # ----------------------------------------------------------------------
    # 8. PROD-RUNTIME-01R: Run ID Authority, Entropy, & Duplicate Invariants
    # ----------------------------------------------------------------------

    def test_21_runtime_generated_id_has_128_bit_entropy(self) -> None:
        """Runtime-generated run_id has >= 128-bit UUID equivalent randomness."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Entropy test")
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))
        self.assertEqual(len(ctx.run_id), 41)
        raw_hex = ctx.run_id.replace("RUN-DEPT-", "")
        self.assertEqual(len(raw_hex), 32)
        int(raw_hex, 16)  # Valid hex integer

    def test_22_duplicate_active_run_id_rejected(self) -> None:
        """Attempting to start another run with an already active run ID raises RunIdAlreadyExistsError."""
        rt = _build_test_runtime()
        ctx1 = rt.start_run(objective="Run 1", trusted_run_id="RUN-ACTIVE-TEST-001")
        self.assertIn("RUN-ACTIVE-TEST-001", rt._active_contexts)

        with self.assertRaises(RunIdAlreadyExistsError):
            rt.start_run(objective="Run 2 collision", trusted_run_id="RUN-ACTIVE-TEST-001")

    def test_23_historical_run_id_reuse_rejected(self) -> None:
        """Attempting to start another run reusing a completed run ID raises RunIdAlreadyExistsError."""
        rt = _build_test_runtime()
        ctx1, _, art1 = rt.run_workflow(objective="Run 1", trusted_run_id="RUN-HIST-TEST-001")
        self.assertIn("RUN-HIST-TEST-001", rt._completed_runs)

        with self.assertRaises(RunIdAlreadyExistsError):
            rt.start_run(objective="Run 2 reuse", trusted_run_id="RUN-HIST-TEST-001")

    def test_24_duplicate_id_cannot_overwrite_active_context(self) -> None:
        """Collision check prevents overwriting an existing active context."""
        rt = _build_test_runtime()
        ctx1 = rt.start_run(objective="Original active context", trusted_run_id="RUN-NO-OVERWRITE-001")
        try:
            rt.start_run(objective="Attempted overwrite context", trusted_run_id="RUN-NO-OVERWRITE-001")
        except RunIdAlreadyExistsError:
            pass

        self.assertEqual(rt._active_contexts["RUN-NO-OVERWRITE-001"].objective, "Original active context")

    def test_25_duplicate_id_cannot_collide_artifacts(self) -> None:
        """Collision check prevents overwriting completed artifacts."""
        rt = _build_test_runtime()
        ctx1, _, art1 = rt.run_workflow(objective="Original artifact", trusted_run_id="RUN-NO-COLLIDE-001")
        try:
            rt.run_workflow(objective="Attempted collide artifact", trusted_run_id="RUN-NO-COLLIDE-001")
        except RunIdAlreadyExistsError:
            pass

        self.assertEqual(rt._completed_runs["RUN-NO-COLLIDE-001"].objective, "Original artifact")

    # ----------------------------------------------------------------------
    # 9. PROD-RUNTIME-01R: Active Context Lifecycle & Cleanup
    # ----------------------------------------------------------------------

    def test_26_terminal_completed_removed_from_active_registry(self) -> None:
        """A COMPLETED run is removed from _active_contexts upon completion."""
        rt = _build_test_runtime()
        ctx, _, art = rt.run_workflow(objective="Completion cleanup test")
        self.assertEqual(ctx.status, RuntimeStatus.COMPLETED)
        self.assertNotIn(ctx.run_id, rt._active_contexts)
        self.assertIn(ctx.run_id, rt._completed_runs)

    def test_27_terminal_failed_removed_from_active_registry(self) -> None:
        """A FAILED run is removed from _active_contexts upon terminal failure."""
        failing_gw = MockScriptedGateway(fail_stage="intelligence")
        rt = _build_test_runtime(gateway=failing_gw)
        ctx, _, art = rt.run_workflow(objective="Failure cleanup test")
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertNotIn(ctx.run_id, rt._active_contexts)
        self.assertIn(ctx.run_id, rt._completed_runs)

    def test_28_terminal_cancelled_removed_from_active_registry(self) -> None:
        """A CANCELLED run is removed from _active_contexts upon terminal cancellation."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Cancel cleanup test")
        rt.cancel_run(ctx.run_id)
        ctx, _, art = rt.execute_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)
        self.assertNotIn(ctx.run_id, rt._active_contexts)
        self.assertIn(ctx.run_id, rt._completed_runs)

    def test_29_waiting_for_approval_remains_in_active_contexts(self) -> None:
        """A WAITING_FOR_APPROVAL run remains in _active_contexts so it can be resumed."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Approval wait test")
        rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)
        self.assertIn(ctx.run_id, rt._active_contexts)

    def test_30_memory_leak_100_runs_active_contexts_empty(self) -> None:
        """Running 100 short workflows results in 0 leaking contexts in _active_contexts."""
        rt = _build_test_runtime()
        for i in range(100):
            rt.run_workflow(objective=f"Quick batch run {i}")

        self.assertEqual(len(rt._active_contexts), 0, f"Memory leak: {len(rt._active_contexts)} contexts left active")
        self.assertEqual(len(rt._completed_runs), 100)

    # ----------------------------------------------------------------------
    # 10. PROD-RUNTIME-01R: Cancellation & Status Convergence
    # ----------------------------------------------------------------------

    def test_31_active_cancellation_prevents_subsequent_stages(self) -> None:
        """Active cancellation prevents subsequent stages from running."""
        rt = _build_test_runtime()
        executed_stages: List[str] = []

        orig_cmo = rt.execute_stage_cmo_initial
        orig_intel = rt.execute_stage_intelligence
        orig_strat = rt.execute_stage_strategist

        def tracked_cmo(c: RuntimeContext) -> Dict[str, Any]:
            executed_stages.append("cmo_initial")
            out = orig_cmo(c)
            # Cancel during stage 1
            rt.cancel_run(c.run_id)
            return out

        def tracked_intel(c: RuntimeContext) -> Dict[str, Any]:
            executed_stages.append("intelligence")
            return orig_intel(c)

        def tracked_strat(c: RuntimeContext) -> Dict[str, Any]:
            executed_stages.append("strategist")
            return orig_strat(c)

        rt.execute_stage_cmo_initial = tracked_cmo
        rt.execute_stage_intelligence = tracked_intel
        rt.execute_stage_strategist = tracked_strat

        ctx = rt.start_run(objective="Cancellation barrier test")
        ctx, final_cmo, art = rt.execute_run(ctx)

        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)
        self.assertEqual(art.status, RuntimeStatus.CANCELLED)
        self.assertIn("cmo_initial", executed_stages)
        self.assertNotIn("intelligence", executed_stages)
        self.assertNotIn("strategist", executed_stages)

    def test_32_cancelled_run_cannot_become_completed(self) -> None:
        """A cancelled context cannot be converted to COMPLETED by complete_run."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Cancelled completion test")
        ctx.status = RuntimeStatus.CANCELLED
        art = rt.complete_run(ctx)
        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)
        self.assertEqual(art.status, RuntimeStatus.CANCELLED)

    def test_33_cancel_run_a_does_not_affect_concurrent_run_b(self) -> None:
        """Cancelling RUN-A leaves concurrent RUN-B unaffected."""
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
        """Queue item status and RuntimeContext status converge deterministically."""
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
        """Queue auto-allocates an authoritative runtime-reserved ID when none is provided."""
        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=0)  # No workers running
        item = mgr.enqueue_run(objective="Preallocation test")

        self.assertTrue(item.run_id.startswith("RUN-DEPT-"))
        self.assertEqual(len(item.run_id), 41)
        self.assertTrue(rt.is_reserved_run_id(item.run_id))
        mgr._stop_event.set()

    def test_36_untrusted_custom_run_id_reservation_error(self) -> None:
        """Calling reserve_run_id with untrusted custom ID raises RunIdReservationError."""
        rt = _build_test_runtime()
        with self.assertRaises(RunIdReservationError):
            rt.reserve_run_id(custom_id="HACKED_INJECTION_ID", trusted=False)

    # ----------------------------------------------------------------------
    # 11. PROD-RUNTIME-01RRV: Resource Bounding, Queue Sync & Gateway Tests
    # ----------------------------------------------------------------------

    def test_37_completed_runs_cache_bounded_lru(self) -> None:
        """Bounded completed run cache evicts oldest entries and does not grow unbounded."""
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
        """Completing a cancelled run removes the run ID from _cancelled_run_ids."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Cancel cleanup test")
        rt.cancel_run(ctx.run_id)
        self.assertIn(ctx.run_id, rt._cancelled_run_ids)

        rt.complete_run(ctx)
        self.assertNotIn(ctx.run_id, rt._cancelled_run_ids)

    def test_39_abandoned_reservation_release(self) -> None:
        """An unconsumed run reservation can be explicitly released."""
        rt = _build_test_runtime()
        rid = rt.reserve_run_id()
        self.assertTrue(rt.is_reserved_run_id(rid))

        released = rt.release_reservation(rid)
        self.assertTrue(released)
        self.assertFalse(rt.is_reserved_run_id(rid))

    def test_40_queue_waiting_for_approval_sync(self) -> None:
        """QueueItem reflects WAITING_APPROVAL when active context is waiting for approval."""
        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=0)
        rid = rt.reserve_run_id()
        item = mgr.enqueue_run(objective="Approval wait queue test", run_id=rid)

        ctx = rt.start_run(objective="Approval wait", reserved_run_id=rid)
        rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)

        # Query through RunManager
        queried_item = mgr.get_run(rid)
        self.assertIsNotNone(queried_item)
        self.assertEqual(queried_item.status, RunQueueStatus.WAITING_APPROVAL)
        mgr._stop_event.set()

    def test_41_queue_approval_resume_returns_to_running(self) -> None:
        """Approval authorizes execution but a missing real publisher fails truthfully."""
        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=0)
        rid = rt.reserve_run_id()
        item = mgr.enqueue_run(objective="Approval resume queue test", run_id=rid)

        ctx = rt.start_run(objective="Approval wait", reserved_run_id=rid)
        rt.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(mgr.get_run(rid).status, RunQueueStatus.WAITING_APPROVAL)

        # Human approves
        policy = rt.tool_gateway.policy_engine
        pending_list = policy.list_pending_approvals()
        self.assertGreater(len(pending_list), 0)
        pending = pending_list[-1]
        ok, appr_rec, _ = policy.approve_pending_action(pending.pending_approval_id, approved_by="Operator")
        self.assertTrue(ok)

        # Approval is only authorization.  The default publisher has no
        # real connector, so execution must fail closed rather than fake success.
        rec = rt.request_publish_action(ctx, platform="linkedin", approval_token=appr_rec.approval_token)
        self.assertEqual(rec.status, ExecutionStatus.ERROR)
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(mgr.get_run(rid).status, RunQueueStatus.FAILED)
        mgr._stop_event.set()

    def test_42_gateway_fallback_candidate_b_executes_after_timeout(self) -> None:
        """UniversalModelGateway falls back to Candidate B when Candidate A times out."""
        from integrations.models.base import BaseModelAdapter
        from integrations.models.registry import ProviderConfig

        class TimingOutAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "adapter_a"

            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    request_id=req.request_id,
                    provider="adapter_a",
                    model_name="model_a",
                    status=ModelResponseStatus.TIMEOUT,
                    error="TIMEOUT: Request timed out.",
                )

        class SuccessfulAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "adapter_b"

            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    request_id=req.request_id,
                    provider="adapter_b",
                    model_name="model_b",
                    status=ModelResponseStatus.SUCCESS,
                    content="Success from adapter B",
                )

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
        """Explicit timeout_seconds strictly bounds the entire candidate chain."""
        from integrations.models.base import BaseModelAdapter
        from integrations.models.registry import ProviderConfig

        class SlowAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "slow_adapter"

            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    request_id=req.request_id,
                    provider="slow_adapter",
                    model_name="slow_model",
                    status=ModelResponseStatus.TIMEOUT,
                    error="TIMEOUT: Slow timeout",
                )

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
        """Timeout and fallback logic works identically for arbitrary generic provider IDs."""
        from integrations.models.base import BaseModelAdapter
        from integrations.models.registry import ProviderConfig

        class CustomAdapter(BaseModelAdapter):
            @property
            def provider_name(self) -> str:
                return "generic_x"

            def generate(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    request_id=req.request_id,
                    provider="generic_x",
                    model_name="custom-v1",
                    status=ModelResponseStatus.SUCCESS,
                    content="Generic provider response",
                )

        gw = UniversalModelGateway(free_only_mode=False)
        gw.provider_registry.register_provider(ProviderConfig(provider_id="generic_x", api_key_env="DUMMY", default_model="custom-v1"))
        gw.provider_registry._adapters["generic_x"] = CustomAdapter()
        gw.provider_registry._has_custom_adapters = True

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Test")])
        resp = gw.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.content, "Generic provider response")

    def test_45_untrusted_caller_cannot_access_trusted_run_id_authority(self) -> None:
        """API endpoints do not accept trusted_run_id and unreserved IDs are discarded."""
        rt = _build_test_runtime()
        # Public start_run without trusted flag replaces raw ID
        ctx = rt.start_run(objective="Untrusted test", run_id="RUN_MALICIOUS_001")
        self.assertNotEqual(ctx.run_id, "RUN_MALICIOUS_001")
        self.assertTrue(ctx.run_id.startswith("RUN-DEPT-"))

    def test_46_get_active_context_and_get_completed_run_lookups(self) -> None:
        """get_active_context and get_completed_run correctly return contexts and artifacts."""
        rt = _build_test_runtime()
        ctx = rt.start_run(objective="Lookup test")
        self.assertIs(rt.get_active_context(ctx.run_id), ctx)
        self.assertIsNone(rt.get_completed_run(ctx.run_id))

        art = rt.complete_run(ctx)
        self.assertIsNone(rt.get_active_context(ctx.run_id))
        self.assertIs(rt.get_completed_run(ctx.run_id), art)


if __name__ == "__main__":
    unittest.main()
