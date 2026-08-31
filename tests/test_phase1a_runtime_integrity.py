"""Phase 1A Runtime Integrity & Failure Honesty Test Suite.

Validates:
1. Case A: All model calls fail -> run is NOT READY_FOR_DEPLOYMENT, no fake CMO approval, status is FAILED, 0 empirical LearningEvents recorded.
2. Case B: Intelligence model fails -> Intelligence stage is FAILED, no canned text claiming research completed.
3. Case C: Performance model fails -> Performance stage is FAILED, no fabricated measurement output.
4. Case D: Final CMO fails -> approval_status is NOT approved, no "Sẵn sàng triển khai" fake approval markdown, status is FAILED.
5. Case E: Timeout handling -> timeout produces normalized error, no fake stage completion.
6. Case F: Successful model execution -> real returned content flows through all 6 stages properly and succeeds without regression.
7. Verification that complete_run() never writes fabricated LearningEvents with fake statistical data.
"""

from __future__ import annotations

import unittest
from typing import Dict, Optional

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway
from knowledge.repository import LocalKnowledgeRepository
from memory.learning import LocalLearningRepository
from memory.repository import LocalMemoryRepository
from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionReceiptRepository
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway
from tools.capabilities import CapabilityRegistry


class ControllableMockAdapter(BaseModelAdapter):
    """Mock adapter with per-role failure injection and response control."""

    def __init__(
        self,
        name: str = "mock_provider",
        fail_all: bool = False,
        failing_roles: Optional[set[str]] = None,
        timeout_roles: Optional[set[str]] = None,
        responses: Optional[Dict[str, str]] = None,
    ) -> None:
        self._name = name
        self.fail_all = fail_all
        self.failing_roles = failing_roles or set()
        self.timeout_roles = timeout_roles or set()
        self.responses = responses or {}
        self.invocations: list[ModelRequest] = []

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def default_model(self) -> str:
        return "mock-model-v1"

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.FREE_TIER_ALLOWED

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        self.invocations.append(request)

        # Detect role from system instruction
        sys_content = ""
        for m in request.messages:
            if m.role.value == "system":
                sys_content = m.content.lower()

        detected_role = "unknown"
        if "you are the intelligence specialist" in sys_content:
            detected_role = "intelligence"
        elif "you are the marketing strategist" in sys_content:
            detected_role = "strategist"
        elif "you are the creative director" in sys_content:
            detected_role = "creative"
        elif "you are the performance marketing" in sys_content:
            detected_role = "performance"
        elif "you are the chief marketing officer" in sys_content:
            detected_role = "cmo"

        if self.fail_all or detected_role in self.failing_roles:
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=self.default_model,
                status=ModelResponseStatus.ERROR,
                error=f"INJECTED_FAILURE_FOR_{detected_role.upper()}",
            )

        if detected_role in self.timeout_roles:
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=self.default_model,
                status=ModelResponseStatus.TIMEOUT,
                error="TIMEOUT: Request timed out after configured duration.",
            )

        reply = self.responses.get(detected_role, f"Real generated response for {detected_role}")
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=self.default_model,
            status=ModelResponseStatus.SUCCESS,
            content=reply,
        )


class TestPhase1ARuntimeIntegrity(unittest.TestCase):
    """Deterministic tests for Phase 1A failure honesty and runtime integrity."""

    def setUp(self) -> None:
        self.knowledge_repo = LocalKnowledgeRepository()
        self.memory_repo = LocalMemoryRepository()
        self.learning_repo = LocalLearningRepository()
        self.receipt_repo = ExecutionReceiptRepository()
        self.policy_engine = PolicyEngine()
        self.tool_gateway = ToolGateway(
            capability_registry=CapabilityRegistry(),
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )

    def _create_runtime(self, adapter: BaseModelAdapter) -> FiveAgentDepartmentRuntime:
        gateway = UniversalModelGateway(free_only_mode=True)
        gateway.provider_registry.register_custom_adapter(adapter)
        return FiveAgentDepartmentRuntime(
            model_gateway=gateway,
            tool_gateway=self.tool_gateway,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
            learning_repo=self.learning_repo,
        )

    def test_case_a_all_model_calls_fail(self) -> None:
        """Case A: All model calls fail -> run is NOT ready for deployment, no fake approval, 0 fake learning events."""
        fail_adapter = ControllableMockAdapter(fail_all=True)
        runtime = self._create_runtime(fail_adapter)

        ctx = runtime.start_run(objective="Chiến dịch ra mắt sản phẩm A")
        cmo_init = runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(cmo_init["status"], "FAILED")
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)

        intel_out = runtime.execute_stage_intelligence(ctx)
        self.assertEqual(intel_out["status"], "FAILED")

        strat_out = runtime.execute_stage_strategist(ctx)
        self.assertEqual(strat_out["status"], "FAILED")

        crtv_out = runtime.execute_stage_creative(ctx)
        self.assertEqual(crtv_out["status"], "FAILED")

        perf_out = runtime.execute_stage_performance(ctx)
        self.assertEqual(perf_out["status"], "FAILED")

        cmo_final = runtime.execute_stage_final_cmo(ctx)
        self.assertEqual(cmo_final["status"], "FAILED")
        self.assertEqual(cmo_final.get("approval_status"), "NOT_EVALUATED")
        self.assertNotEqual(cmo_final.get("status"), "READY_FOR_DEPLOYMENT")
        self.assertNotIn("Sẵn sàng triển khai", cmo_final.get("master_gtm_plan_markdown", ""))

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)

        # Zero empirical learning events written to repository
        learnings = self.learning_repo.list_learnings()
        self.assertEqual(len(learnings), 0)

    def test_case_b_intelligence_model_fails(self) -> None:
        """Case B: Intelligence model fails -> stage is FAILED, no canned market research statement."""
        adapter = ControllableMockAdapter(failing_roles={"intelligence"})
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Thâm nhập thị trường Gen Z")
        cmo_init = runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(cmo_init["status"], "COMPLETED")

        intel_out = runtime.execute_stage_intelligence(ctx)
        self.assertEqual(intel_out["status"], "FAILED")
        self.assertEqual(intel_out["market_findings"], "")
        self.assertNotIn("Analyzed market demand", intel_out.get("market_findings", ""))

    def test_case_c_performance_model_fails(self) -> None:
        """Case C: Performance model fails -> stage is FAILED, no fabricated measurement/experiment output."""
        adapter = ControllableMockAdapter(failing_roles={"performance"})
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Tối ưu ROAS kênh TikTok")
        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)

        perf_out = runtime.execute_stage_performance(ctx)
        self.assertEqual(perf_out["status"], "FAILED")
        self.assertEqual(perf_out["funnel_kpi"], "")
        self.assertNotIn("Full-funnel attribution model", perf_out.get("funnel_kpi", ""))

    def test_case_d_final_cmo_fails(self) -> None:
        """Case D: Final CMO model fails -> approval_status is NOT approved, no 'Sẵn sàng triển khai', status is FAILED."""
        adapter = ControllableMockAdapter(failing_roles={"cmo"})
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Kế hoạch tăng trưởng Q4")
        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)
        runtime.execute_stage_performance(ctx)
        cmo_final = runtime.execute_stage_final_cmo(ctx)

        self.assertEqual(cmo_final["status"], "FAILED")
        self.assertEqual(cmo_final["approval_status"], "NOT_EVALUATED")
        self.assertNotIn("Sẵn sàng triển khai (Governed RC3)", cmo_final["master_gtm_plan_markdown"])
        self.assertNotIn("Verified & Ready for Deployment", cmo_final["master_gtm_plan_markdown"])
        self.assertIn("KHÔNG ĐƯỢC PHÊ DUYỆT", cmo_final["master_gtm_plan_markdown"])

    def test_case_e_timeout_handling(self) -> None:
        """Case E: Timeout generates normalized failure and does not cause fake stage completion."""
        timeout_adapter = ControllableMockAdapter(timeout_roles={"intelligence"})
        runtime = self._create_runtime(timeout_adapter)

        ctx = runtime.start_run(objective="Nghiên cứu đối thủ cạnh tranh")
        runtime.execute_stage_cmo_initial(ctx)

        intel_out = runtime.execute_stage_intelligence(ctx)
        self.assertEqual(intel_out["status"], "FAILED")
        self.assertIn("TIMEOUT", intel_out.get("error", ""))
        self.assertEqual(intel_out["market_findings"], "")

    def test_case_f_successful_model_execution(self) -> None:
        """Case F: Successful model execution flows through all 6 stages properly and succeeds."""
        success_adapter = ControllableMockAdapter(
            responses={
                "cmo": "# BÁO CÁO CHIẾN LƯỢC GTM CHÍNH THỨC\n\n1. Định hướng tổng thể: Mở rộng thị trường.",
                "intelligence": "Nghiên cứu thị trường cho thấy nhu cầu phân khúc cao cấp tăng 45%.",
                "strategist": "Định vị sản phẩm: Chất lượng vượt trội với chi phí tối ưu.",
                "creative": "Concept: Bứt phá giới hạn — 3 video hooks cho Meta & TikTok.",
                "performance": "Mục tiêu: CAC < 200k, ROAS > 3.5, 4 thử nghiệm A/B.",
            }
        )
        runtime = self._create_runtime(success_adapter)

        ctx = runtime.start_run(objective="Ra mắt chiến dịch thương hiệu 2026")
        cmo_init = runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(cmo_init["status"], "COMPLETED")
        self.assertIn("Định hướng tổng thể", cmo_init["strategic_intent"])

        intel_out = runtime.execute_stage_intelligence(ctx)
        self.assertEqual(intel_out["status"], "COMPLETED")
        self.assertIn("nhu cầu phân khúc cao cấp", intel_out["market_findings"])

        strat_out = runtime.execute_stage_strategist(ctx)
        self.assertEqual(strat_out["status"], "COMPLETED")
        self.assertIn("Định vị sản phẩm", strat_out["positioning"])

        crtv_out = runtime.execute_stage_creative(ctx)
        self.assertEqual(crtv_out["status"], "COMPLETED")
        self.assertIn("Concept: Bứt phá giới hạn", crtv_out["creative_synthesis"])

        perf_out = runtime.execute_stage_performance(ctx)
        self.assertEqual(perf_out["status"], "COMPLETED")
        self.assertIn("ROAS > 3.5", perf_out["funnel_kpi"])

        cmo_final = runtime.execute_stage_final_cmo(ctx)
        self.assertEqual(cmo_final["status"], "READY_FOR_DEPLOYMENT")
        self.assertEqual(cmo_final["approval_status"], "APPROVED")
        self.assertIn("# BÁO CÁO CHIẾN LƯỢC GTM CHÍNH THỨC", cmo_final["master_gtm_plan_markdown"])

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)
        self.assertEqual(len(artifact.agent_outputs), 6)

    def test_no_fabricated_learning_event_on_normal_run(self) -> None:
        """Verify complete_run() never writes fabricated LearningEvents with fake statistical data."""
        success_adapter = ControllableMockAdapter()
        runtime = self._create_runtime(success_adapter)

        ctx = runtime.start_run(objective="Lập kế hoạch tiếp thị số")
        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)
        runtime.execute_stage_performance(ctx)
        runtime.execute_stage_final_cmo(ctx)
        artifact = runtime.complete_run(ctx)

        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)

        # Confirm 0 empirical learning events in repository
        learnings = self.learning_repo.list_learnings()
        self.assertEqual(len(learnings), 0)

        # COLLAB-04: fabricated template memories (fixed decision/experiment
        # strings with fixed confidences) were removed. At most ONE factual
        # bookkeeping record may exist, always CANDIDATE-tier, never
        # auto-promoted learning.
        saved_mems = self.memory_repo.list_memories(run_id=ctx.run_id)
        self.assertLessEqual(len(saved_mems), 1)
        for mem in saved_mems:
            self.assertNotIn("improves CVR", mem.content)
            self.assertEqual(mem.context.get("record_type"), "RUN_DECISION_BOOKKEEPING")

    def test_fail_fast_exact_model_call_count_when_intelligence_fails(self) -> None:
        """Verify fail-fast behavior stops subsequent model inferences and records exact call count."""
        # Adapter fails only on Intelligence (call #2)
        adapter = ControllableMockAdapter(failing_roles={"intelligence"})
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Chiến dịch test fail-fast call counting")
        s1 = runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(s1["status"], "COMPLETED")
        self.assertEqual(len(adapter.invocations), 1)

        s2 = runtime.execute_stage_intelligence(ctx)
        self.assertEqual(s2["status"], "FAILED")
        self.assertEqual(len(adapter.invocations), 2)

        # Subsequent stages must immediately fail without making model calls
        s3 = runtime.execute_stage_strategist(ctx)
        self.assertEqual(s3["status"], "FAILED")
        self.assertEqual(s3["error"], "PREVIOUS_STAGE_FAILED")
        self.assertEqual(len(adapter.invocations), 2)  # No 3rd call

        s4 = runtime.execute_stage_creative(ctx)
        self.assertEqual(s4["status"], "FAILED")
        self.assertEqual(s4["error"], "PREVIOUS_STAGE_FAILED")
        self.assertEqual(len(adapter.invocations), 2)  # No 4th call

        s5 = runtime.execute_stage_performance(ctx)
        self.assertEqual(s5["status"], "FAILED")
        self.assertEqual(s5["error"], "PREVIOUS_STAGE_FAILED")
        self.assertEqual(len(adapter.invocations), 2)  # No 5th call

        s6 = runtime.execute_stage_final_cmo(ctx)
        self.assertEqual(s6["status"], "FAILED")
        self.assertEqual(s6["approval_status"], "NOT_EVALUATED")
        self.assertEqual(len(adapter.invocations), 2)  # No 6th call

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        self.assertEqual(len(adapter.invocations), 2)  # Strictly exactly 2 model calls total

    def test_unverified_working_state_empirical_dict_rejected(self) -> None:
        """Verify arbitrary working_state dict does NOT create empirical LearningEvent without verified evidence contract."""
        adapter = ControllableMockAdapter()
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Test unverified empirical injection rejection")
        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)
        runtime.execute_stage_performance(ctx)
        runtime.execute_stage_final_cmo(ctx)

        # Arbitrary dict injected into working state (e.g. from model or unverified code)
        ctx.working_state["empirical_learning"] = {
            "impressions": 15000,
            "clicks": 620,
            "p_value": 0.02,
        }

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)

        # Learning repository MUST be empty (0 items created)
        learnings = self.learning_repo.list_learnings()
        self.assertEqual(len(learnings), 0)

    def test_final_cmo_failure_full_artifact_zero_approval_strings(self) -> None:
        """Verify when Final CMO model fails, entire run artifact contains ZERO approval strings."""
        adapter = ControllableMockAdapter()
        call_count = [0]

        def guarded_gen(req: ModelRequest) -> ModelResponse:
            call_count[0] += 1
            if call_count[0] <= 6:
                # Calls 1-6 succeed: CMO initial, Intel, Strategist, Creative,
                # Performance 5A, then Performance 5B.
                return ModelResponse(
                    request_id=req.request_id,
                    provider="mock_provider",
                    model_name="mock-model-v1",
                    status=ModelResponseStatus.SUCCESS,
                    content=f"Stage {call_count[0]} Successful Deliverable",
                )
            # Call 7 is Final CMO and must fail.
            return ModelResponse(
                request_id=req.request_id,
                provider="mock_provider",
                model_name="mock-model-v1",
                status=ModelResponseStatus.ERROR,
                error="FINAL_CMO_PROVIDER_CRASH",
            )

        adapter.generate = guarded_gen
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Test zero approval string on final cmo failure")
        s1 = runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(s1["status"], "COMPLETED")
        s2 = runtime.execute_stage_intelligence(ctx)
        self.assertEqual(s2["status"], "COMPLETED")
        s3 = runtime.execute_stage_strategist(ctx)
        self.assertEqual(s3["status"], "COMPLETED")
        s4 = runtime.execute_stage_creative(ctx)
        self.assertEqual(s4["status"], "COMPLETED")
        s5 = runtime.execute_stage_performance(ctx)
        self.assertEqual(s5["status"], "COMPLETED")
        cmo_final = runtime.execute_stage_final_cmo(ctx)
        self.assertEqual(call_count[0], 7)

        self.assertEqual(cmo_final["status"], "FAILED")
        self.assertEqual(cmo_final["approval_status"], "NOT_EVALUATED")

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)

        # Inspect entire artifact serialized text
        import json
        artifact_data = artifact.model_dump() if hasattr(artifact, "model_dump") else artifact.__dict__
        artifact_json = json.dumps(str(artifact_data), ensure_ascii=False)

        forbidden_strings = [
            "READY_FOR_DEPLOYMENT",
            "Sẵn sàng triển khai",
            "Governed RC3",
            "APPROVED",
        ]
        for forbidden in forbidden_strings:
            self.assertNotIn(forbidden, artifact_json, f"Forbidden approval string '{forbidden}' found in failed run artifact!")

    # =========================================================================
    # PART 1 SEAL — EMPIRICAL LEARNING TRUST BOUNDARY TESTS
    # =========================================================================

    def test_spoofed_verified_dictionary_rejected(self) -> None:
        """Test 1: Spoofed VERIFIED dictionary in working_state produces 0 LearningEvents."""
        adapter = ControllableMockAdapter()
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Test spoofed verified dictionary rejection")
        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)
        runtime.execute_stage_performance(ctx)
        runtime.execute_stage_final_cmo(ctx)

        ctx.working_state["empirical_learning"] = {
            "verification_status": "VERIFIED",
            "measurement_receipt_id": "FAKE-RECEIPT-123",
            "provenance": "REAL_ANALYTICS",
            "observed_result": {"cvr": 0.42},
            "confidence": 0.99,
        }

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)
        self.assertEqual(len(self.learning_repo.list_learnings()), 0)

    def test_fabricated_numerical_payload_rejected(self) -> None:
        """Test 2: Fabricated extreme numerical payload produces 0 LearningEvents."""
        adapter = ControllableMockAdapter()
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Test fabricated numerical payload rejection")
        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)
        runtime.execute_stage_performance(ctx)
        runtime.execute_stage_final_cmo(ctx)

        ctx.working_state["empirical_learning"] = {
            "impressions": 1_000_000,
            "clicks": 999_999,
            "p_value": 0.00001,
        }

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)
        self.assertEqual(len(self.learning_repo.list_learnings()), 0)

    def test_model_stage_working_state_cannot_self_promote(self) -> None:
        """Test 3: Model stage writing empirical-looking data cannot create PROMOTED_LEARNING or LearningEvents."""
        adapter = ControllableMockAdapter()
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Test model self-promotion prevention")
        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)
        runtime.execute_stage_performance(ctx)

        # Simulate stage attempting to self-promote
        ctx.working_state["empirical_learning"] = {
            "hypothesis": "Self-promoted claim",
            "promotion_status": "PROMOTED_LEARNING",
            "verification_status": "VERIFIED",
        }
        runtime.execute_stage_final_cmo(ctx)

        artifact = runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)
        self.assertEqual(len(self.learning_repo.list_learnings()), 0)

        # Check that saved memories are only CandidateMemory (promotion_level != PROMOTED_LEARNING)
        saved_mems = self.memory_repo.list_memories(run_id=ctx.run_id)
        for m in saved_mems:
            self.assertNotEqual(m.promotion_level.value, "PROMOTED_LEARNING")
            self.assertNotEqual(m.promotion_level.value, "VERIFIED_MEMORY")

    # =========================================================================
    # PART 2 SEAL — TIMEOUT SOURCE OF TRUTH TESTS
    # =========================================================================

    def test_timeout_case_a_provider_config_default_used(self) -> None:
        """Case A: When no runtime override is given, ProviderConfig timeout is used."""
        adapter = ControllableMockAdapter()
        runtime = self._create_runtime(adapter)

        ctx = runtime.start_run(objective="Test Case A Timeout")
        runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(len(adapter.invocations), 1)
        req = adapter.invocations[0]
        # When None was passed to _call_agent_llm, gateway uses ProviderConfig / ConfigService timeout (60.0s)
        self.assertAlmostEqual(req.timeout_seconds, 60.0, places=1)

    def test_timeout_case_b_explicit_runtime_override(self) -> None:
        """Case B: Explicit runtime override (e.g. 2.0s) applies strictly for that request."""
        adapter = ControllableMockAdapter()
        runtime = self._create_runtime(adapter)

        # Explicitly call _call_agent_llm with timeout_seconds=2.0
        runtime._call_agent_llm("cmo", "Instruction", "User prompt", timeout_seconds=2.0)
        self.assertEqual(len(adapter.invocations), 1)
        req = adapter.invocations[0]
        self.assertAlmostEqual(req.timeout_seconds, 2.0, places=1)

    def test_timeout_case_c_fallback_providers_share_one_budget(self) -> None:
        """Case C: Fallback candidates share one total request timeout budget."""
        import time
        from integrations.models.registry import ProviderRegistry
        from integrations.models.gateway import UniversalModelGateway

        invocations = []

        class SlowFailingAdapter(BaseModelAdapter):
            def __init__(self, name: str, sleep_dur: float):
                self._name = name
                self.sleep_dur = sleep_dur
            @property
            def provider_name(self) -> str:
                return self._name
            @property
            def default_model(self) -> str:
                return "m1"
            @property
            def cost_policy(self) -> CostPolicy:
                return CostPolicy.FREE_TIER_ALLOWED
            def generate(self, req: ModelRequest) -> ModelResponse:
                invocations.append((self._name, req.timeout_seconds))
                time.sleep(self.sleep_dur)
                return ModelResponse(
                    request_id=req.request_id,
                    provider=self._name,
                    model_name="m1",
                    status=ModelResponseStatus.ERROR,
                    error="TIMEOUT_ERROR",
                )

        p_reg = ProviderRegistry()
        p_reg.register_custom_adapter(SlowFailingAdapter("provider_a", 0.3))
        p_reg.register_custom_adapter(SlowFailingAdapter("provider_b", 0.1))

        gateway = UniversalModelGateway(provider_registry=p_reg, free_only_mode=True)
        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Test budget")],
            timeout_seconds=0.5,
        )
        resp = gateway.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertGreaterEqual(len(invocations), 1)
        if len(invocations) > 1:
            self.assertLess(invocations[1][1], 0.25)

    def test_timeout_case_d_mock_tests_request_small_timeout(self) -> None:
        """Case D: Mock tests can request 0.1s without modifying production defaults."""
        adapter = ControllableMockAdapter()
        runtime = self._create_runtime(adapter)

        runtime._call_agent_llm("intelligence", "Instruction", "Query", timeout_seconds=0.1)
        self.assertEqual(len(adapter.invocations), 1)
        self.assertAlmostEqual(adapter.invocations[0].timeout_seconds, 0.1, places=2)


if __name__ == "__main__":
    unittest.main()

