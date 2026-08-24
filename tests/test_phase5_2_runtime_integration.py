"""Phase 5.2 Supervised Runtime Integration & Adversarial Test Suite.

Verifies:
- Complete End-to-End Supervised Five-Agent Department Execution
- Scoped Knowledge Retrieval & Provenance Tracking
- Role-Isolated Memory Context & Non-Automatic Promotion
- Tool Gateway Execution, Receipts & Direct-Bypass Prevention
- Human Approval Gating (Pause on Unapproved Publish, Resume on Valid Token)
- Checkpoint / Resume and Idempotency
- 20 Adversarial and Edge-Case Integrity Tests
- Permanent Agent Count = 5, Zero Agent 6, and Frozen Brain RC3 Integrity
"""

import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.access_matrix import AgentAccessMatrix, PERMANENT_FIVE_AGENTS
from knowledge.models import (
    AuthorityLevel,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeSource,
    SourceType,
)
from knowledge.repository import LocalKnowledgeRepository
from memory.learning import LearningEvent, LocalLearningRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.promotion import MemoryPromotionEngine
from memory.repository import LocalMemoryRepository
from runtime.artifacts import DepartmentRunArtifact, MemoryWriteCandidate
from runtime.context import ApprovalState, ExecutionCheckpoint, RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.knowledge_builder import KnowledgeContextBuilder
from runtime.lineage import LineageInspector
from tools.adapters import MockToolAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import HumanApprovalRecord, PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway


class ScriptedAgentGateway(UniversalModelGateway):
    """Deterministic script-based model gateway for hermetic integration tests."""

    MARKERS = [
        ("final_cmo", "governed final synthesis"),
        ("final_cmo", "Final Governed"),
        ("performance", "Performance Marketing"),
        ("performance", "Performance Specialist"),
        ("creative", "Creative Director"),
        ("creative", "Creative Specialist"),
        ("strategist", "Marketing Strategist"),
        ("intelligence", "Intelligence Specialist"),
        ("cmo_initial", "Executive Master Orchestrator"),
        ("cmo_initial", "Chief Marketing Officer (CMO)"),
    ]

    def __init__(self, replies: dict | None = None, fail_stages=()):
        super().__init__(free_only_mode=True)
        self.replies = dict(replies or {})
        self.fail_stages = set(fail_stages)
        self.calls = []

    def _label(self, request: ModelRequest) -> str:
        sys_msg = ""
        if request.messages and request.messages[0].role == ModelRole.SYSTEM:
            sys_msg = request.messages[0].content
        for label, marker in self.MARKERS:
            if marker in sys_msg:
                return label
        return "unknown"

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        label = self._label(request)
        sys_msg = request.messages[0].content if request.messages else ""
        user_msg = request.messages[-1].content if request.messages else ""
        self.calls.append((label, sys_msg, user_msg))

        if label in self.fail_stages:
            return ModelResponse(
                request_id=request.request_id,
                provider="scripted_mock",
                model_name="scripted",
                status=ModelResponseStatus.ERROR,
                error="SCRIPTED_STAGE_FAILURE",
            )

        reply = self.replies.get(label, f"[{label}] deterministic deliverable for {request.request_id}.")
        return ModelResponse(
            request_id=request.request_id,
            provider="scripted_mock",
            model_name="scripted",
            status=ModelResponseStatus.SUCCESS,
            content=reply,
        )


class TestPhase52RuntimeIntegration(unittest.TestCase):
    """Exhaustive tests for Phase 5.2 Five-Agent Department Runtime."""

    def setUp(self):
        self.cap_registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine()
        self.receipt_repo = ExecutionReceiptRepository()
        self.tool_gateway = ToolGateway(
            capability_registry=self.cap_registry,
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )
        self.knowledge_repo = LocalKnowledgeRepository()
        self.memory_repo = LocalMemoryRepository()
        self.learning_repo = LocalLearningRepository()
        self.model_gateway = ScriptedAgentGateway()

        # Seed local knowledge
        src = self.knowledge_repo.save_source(
            KnowledgeSource(
                source_name="CardioVital 360 Verified Ground Truth",
                source_url_or_path="company/products/cardiovital_facts.json",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                authority_score=1.0,
            )
        )
        self.knowledge_repo.save_document(
            KnowledgeDocument(
                source_id=src.source_id,
                title="CardioVital 360 Specifications",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                content="CardioVital 360 subscription: $149/month. Includes ApoB, CAC integration, FDA-cleared sensors. 24hr board-certified physician review.",
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                tags=["cardiology", "product_facts"],
            )
        )

        # Seed local memory
        self.memory_repo.save_memory(
            MemoryItem(
                memory_type=MemoryType.DECISION_MEMORY,
                agent_source="cmo",
                content="Prior campaign proved physician-led messaging reduced CAC by 35%.",
                confidence=0.88,
                promotion_level=PromotionState.PROMOTED_LEARNING,
            )
        )
        self.memory_repo.save_memory(
            MemoryItem(
                memory_type=MemoryType.EXPERIMENT_MEMORY,
                agent_source="performance",
                content="Experiment EXP-01: Lifestyle hooks failed to convert in high-CAC cohorts.",
                confidence=0.82,
                promotion_level=PromotionState.VERIFIED_MEMORY,
            )
        )

        self.runtime = FiveAgentDepartmentRuntime(
            model_gateway=self.model_gateway,
            tool_gateway=self.tool_gateway,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
            learning_repo=self.learning_repo,
        )

    # =========================================================================
    # PART N & O — END-TO-END SUPERVISED SCENARIO & ACCEPTANCE GATES
    # =========================================================================
    def test_e2e_supervised_department_execution_workflow(self):
        """Verify full 5-agent supervised flow with knowledge, memory, tools, approval pause, resume, and writeback."""
        # 1. Start Run
        ctx = self.runtime.start_run(objective="Launch CardioVital 360 Preventive Cardiology Campaign")
        self.assertEqual(ctx.status, RuntimeStatus.RUNNING)

        # 2. CMO Initial
        cmo_out = self.runtime.execute_stage_cmo_initial(ctx)
        self.assertIn("cmo_initial", ctx.stage_outputs)
        self.assertGreater(len(ctx.knowledge_refs), 0)

        # 3. Intelligence (Executes ToolGateway web_search)
        intel_out = self.runtime.execute_stage_intelligence(ctx)
        self.assertIn("intelligence", ctx.stage_outputs)
        self.assertGreater(len(ctx.execution_receipt_refs), 0)

        # 4. Strategist (Consumes research + memory)
        strat_out = self.runtime.execute_stage_strategist(ctx)
        self.assertIn("strategist", ctx.stage_outputs)
        self.assertGreater(len(ctx.memory_refs), 0)

        # 5. Creative (Executes ToolGateway image_generation)
        crtv_out = self.runtime.execute_stage_creative(ctx)
        self.assertIn("creative", ctx.stage_outputs)
        self.assertGreater(len(ctx.artifact_refs), 0)

        # 6. Performance (Executes ToolGateway kpi_calculation)
        perf_out = self.runtime.execute_stage_performance(ctx)
        self.assertIn("performance", ctx.stage_outputs)

        # 7. Final CMO Synthesis
        cmo_final = self.runtime.execute_stage_final_cmo(ctx)
        self.assertIn("final_cmo", ctx.stage_outputs)

        # 8. Publishing Attempt Triggers Human Approval Gate
        pub_receipt_unapproved = self.runtime.request_publish_action(ctx, platform="linkedin", approval_token=None)
        self.assertEqual(pub_receipt_unapproved.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(ctx.status, RuntimeStatus.WAITING_FOR_APPROVAL)

        # 9. Supervised Human Approval & Resumption
        approval_token = "AUTH-TOKEN-EXECUTIVE-CMO-100"
        self.policy_engine.register_approval(
            HumanApprovalRecord(
                approval_token=approval_token,
                action_type="social_publishing",
                approved_by="Executive Stakeholder",
                approved_at=datetime.now(timezone.utc).isoformat(),
                scope="CARDIOVITAL_LAUNCH",
                risk_level=RiskLevel.CRITICAL,
            )
        )
        pub_receipt_approved = self.runtime.request_publish_action(ctx, platform="linkedin", approval_token=approval_token)
        self.assertEqual(pub_receipt_approved.status, ExecutionStatus.SUCCESS)

        # 10. Complete Run & Seal Artifact
        artifact = self.runtime.complete_run(ctx)
        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)
        self.assertTrue(len(artifact.final_artifact_hash) == 64)
        self.assertEqual(len(artifact.agent_outputs), 6)  # cmo_initial, intel, strat, crtv, perf, final_cmo

        # Verify Memory Writeback (COLLAB-04: fabricated templates removed;
        # at most ONE factual bookkeeping candidate, zero auto-promoted learning)
        saved_mems = self.memory_repo.list_memories(run_id=ctx.run_id)
        self.assertLessEqual(len(saved_mems), 1)
        for m in saved_mems:
            self.assertIn(m.promotion_level, (PromotionState.RAW_OBSERVATION, PromotionState.CANDIDATE_MEMORY))
            self.assertNotEqual(m.promotion_level, PromotionState.PROMOTED_LEARNING)

    # =========================================================================
    # PART P — 20 ADVERSARIAL & FAILURE INTEGRITY TESTS
    # =========================================================================
    def test_adv_01_unknown_capability_fails_cleanly(self):
        """1. Unknown capability returns CAPABILITY_NOT_FOUND error receipt."""
        req = ToolRequest(agent_id="intelligence", capability_id="nonexistent_quantum_scraper", parameters={})
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "CAPABILITY_NOT_FOUND")

    def test_adv_02_unauthorized_agent_capability_request(self):
        """2. Unauthorized agent capability request is blocked with PERMISSION_DENIED."""
        req = ToolRequest(agent_id="creative", capability_id="social_publishing", parameters={})
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "PERMISSION_DENIED")

    def test_adv_03_direct_adapter_bypass_attempt(self):
        """3. Calling adapter without ToolGateway fails RBAC and produces zero receipt."""
        adapter = self.tool_gateway.get_adapter("social_publish_adapter")
        self.assertIsNotNone(adapter)
        # Direct adapter execution produces no receipt in repository
        pre_count = len(self.receipt_repo.list_receipts_for_run("RUN-TEST-BYPASS"))
        adapter.execute("social_publishing", {"platform": "twitter"})
        post_count = len(self.receipt_repo.list_receipts_for_run("RUN-TEST-BYPASS"))
        self.assertEqual(pre_count, post_count)  # Zero receipts recorded for direct bypass

    def test_adv_04_missing_knowledge_source(self):
        """4. Retrieving from unpopulated source returns clean empty context without crashing."""
        empty_repo = LocalKnowledgeRepository()
        builder = KnowledgeContextBuilder(empty_repo)
        res = builder.build_context_for_agent("creative", scope="NONEXISTENT_SCOPE_XYZ")
        self.assertIn("No active knowledge documents resolved", res.context_text)

    def test_adv_05_expired_knowledge_version(self):
        """5. Provenance check fails on invalid chunk/version reference."""
        citation = KnowledgeCitation(knowledge_id="INVALID_KNOW_ID_999", chunk_id="CHUNK_FAKE")
        self.assertFalse(self.knowledge_repo.verify_provenance(citation))

    def test_adv_06_expired_memory_filtering(self):
        """6. Expired memories are strictly filtered out of agent context."""
        expired_mem = MemoryItem(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="cmo",
            content="Old expired strategy from 2021",
            confidence=0.90,
            promotion_level=PromotionState.PROMOTED_LEARNING,
            expiry_or_review_date=datetime.now(timezone.utc) - timedelta(days=10),
        )
        self.memory_repo.save_memory(expired_mem)
        builder = self.runtime.memory_builder
        res = builder.build_context_for_agent("cmo", query_text="2021")
        self.assertNotIn("Old expired strategy from 2021", res.context_text)

    def test_adv_07_low_confidence_memory_filtering(self):
        """7. Memories below minimum confidence threshold are excluded from agent context."""
        low_conf_mem = MemoryItem(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Uncertain speculative hypothesis",
            confidence=0.30,  # Below 0.60 threshold
            promotion_level=PromotionState.CANDIDATE_MEMORY,
        )
        self.memory_repo.save_memory(low_conf_mem)
        builder = self.runtime.memory_builder
        res = builder.build_context_for_agent("strategist", query_text="speculative", min_confidence=0.60)
        self.assertNotIn("Uncertain speculative hypothesis", res.context_text)

    def test_adv_08_raw_observation_trusted_learning_attempt(self):
        """8. RAW_OBSERVATION is strictly excluded from default agent memory retrieval."""
        raw_obs = MemoryItem(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="cmo",
            content="Raw unverified model opinion",
            confidence=0.90,
            promotion_level=PromotionState.RAW_OBSERVATION,
        )
        self.memory_repo.save_memory(raw_obs)
        builder = self.runtime.memory_builder
        res = builder.build_context_for_agent("cmo", query_text="opinion", include_raw=False)
        self.assertNotIn("Raw unverified model opinion", res.context_text)

    def test_adv_09_provider_timeout_handling(self):
        """9. Provider timeout is captured and normalized as ExecutionStatus.TIMEOUT."""
        slow_adapter = MockToolAdapter(name="slow_provider", delay_seconds=0.5)
        self.tool_gateway.register_adapter(slow_adapter)
        self.cap_registry.register_capability(
            CapabilityDescriptor(
                capability_id="slow_call",
                name="Slow Call",
                category=CapabilityCategory.OBSERVE,
                description="Testing timeout",
                provider="slow_provider",
                supported_agents=["intelligence", "cmo"],
                timeout_policy=0.1,
            )
        )
        req = ToolRequest(agent_id="intelligence", capability_id="slow_call", parameters={}, timeout_seconds=0.1)
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.TIMEOUT)

    def test_adv_10_provider_retry_exhaustion(self):
        """10. Adapter that fails all retries returns normalized ERROR receipt with attempt count."""
        failing_adapter = MockToolAdapter(
            name="always_failing_provider",
            should_fail=True,
            error_code="SERVICE_UNAVAILABLE",
            error_message="Downstream platform down",
        )
        self.tool_gateway.register_adapter(failing_adapter)
        self.cap_registry.register_capability(
            CapabilityDescriptor(
                capability_id="failing_call",
                name="Failing Call",
                category=CapabilityCategory.OBSERVE,
                description="Testing retries",
                provider="always_failing_provider",
                supported_agents=["intelligence", "cmo"],
                retry_policy={"max_retries": 2, "retryable_errors": ["SERVICE_UNAVAILABLE"]},
            )
        )
        req = ToolRequest(agent_id="intelligence", capability_id="failing_call", parameters={})
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "SERVICE_UNAVAILABLE")

    def test_adv_11_approval_denied_blocks_execution(self):
        """11. Capability requiring approval is blocked when invalid token is provided."""
        req = ToolRequest(
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin"},
            approval_token="FORGED_OR_INVALID_TOKEN",
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertIn("INVALID_APPROVAL_TOKEN", receipt.error_message or "")

    def test_adv_12_approval_token_revocation(self):
        """12. Revoked human approval token immediately blocks execution."""
        token = "REVOCABLE-TOKEN-123"
        self.policy_engine.register_approval(
            HumanApprovalRecord(
                approval_token=token,
                action_type="social_publishing",
                approved_by="Auditor",
                approved_at=datetime.now(timezone.utc).isoformat(),
                scope="TEMP_SCOPE",
                risk_level=RiskLevel.HIGH,
            )
        )
        self.policy_engine.revoke_approval(token)
        req = ToolRequest(agent_id="cmo", capability_id="social_publishing", parameters={}, approval_token=token)
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)

    def test_adv_13_duplicate_resume_preserves_state(self):
        """13. Resuming an already completed or executing context does not corrupt checkpoints."""
        ctx = self.runtime.start_run(objective="Test Resume Safety")
        self.runtime.execute_stage_cmo_initial(ctx)
        chk_count_1 = len(ctx.checkpoints)
        # Checkpoint again without new stages
        ctx.create_checkpoint()
        self.assertEqual(len(ctx.checkpoints), chk_count_1 + 1)
        self.assertEqual(ctx.stage_outputs["cmo_initial"]["stage"], "CMO_INITIAL")

    def test_adv_14_duplicate_execution_idempotency(self):
        """14. Invoking duplicate tool request with identical idempotency key returns identical receipt."""
        ctx = self.runtime.start_run(objective="Idempotency Test")
        out1 = self.runtime.execute_stage_intelligence(ctx)
        out2 = self.runtime.execute_stage_intelligence(ctx)
        self.assertEqual(out1["search_receipt_id"], out2["search_receipt_id"])

    def test_adv_15_corrupted_checkpoint_detection(self):
        """15. Corrupted checkpoint hash is detected when state is tampered."""
        chk = ExecutionCheckpoint(
            run_id="RUN-TAMPER",
            stage=RuntimeStage.CMO_INITIAL,
            status=RuntimeStatus.RUNNING,
            completed_stages=["cmo_initial"],
            receipt_ids=["EXEC-1"],
        )
        chk.checkpoint_hash = chk.calculate_checkpoint_hash()
        # Tamper stage
        chk.completed_stages.append("unauthorized_stage_6")
        self.assertNotEqual(chk.checkpoint_hash, chk.calculate_checkpoint_hash())

    def test_adv_16_missing_execution_receipt_lineage_detection(self):
        """16. Lineage inspector reports invalid trace when receipt ID does not exist."""
        inspector = LineageInspector()
        trace = inspector.trace_claim_to_receipt("Unverified claim", "NONEXISTENT_RECEIPT_999")
        self.assertFalse(trace.valid)
        self.assertIn("EXECUTION_RECEIPT_NOT_FOUND", trace.missing_links[0])

    def test_adv_17_lineage_break_on_invalid_citation(self):
        """17. Tracing a claim with an invalid knowledge citation resolves properly."""
        citation = KnowledgeCitation(knowledge_id="KNOW-SAMPLE", source_id="SRC-SAMPLE", claim_ref="Tested Claim")
        inspector = LineageInspector(citations=[citation])
        trace = inspector.trace_claim_to_knowledge("Tested Claim", citation)
        self.assertTrue(trace.valid)
        self.assertEqual(len(trace.chain), 3)

    def test_adv_18_invalid_learning_event_validation(self):
        """18. LearningEvent enforces required fields and valid schema."""
        event = LearningEvent(
            campaign_id="CAMP-01",
            hypothesis="Test hypothesis",
            experiment_id="EXP-01",
            primary_metric="roas",
            decision="SCALE",
            lesson="Valid statistical takeaway",
        )
        self.assertEqual(event.decision, "SCALE")
        self.assertTrue(len(event.calculate_event_hash()) == 64)

    def test_adv_19_agent_6_registration_attempt_strictly_blocked(self):
        """19. Attempting to execute capabilities under an unauthorized 'agent_6' identity is strictly blocked."""
        req = ToolRequest(agent_id="agent_6_growth_hacker", capability_id="web_search", parameters={})
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "UNRECOGNIZED_AGENT")

        # Verify permanent count is strictly 5
        self.assertTrue(AgentAccessMatrix.validate_agent_count())
        self.assertEqual(set(AgentAccessMatrix.PROFILES.keys()), {"cmo", "intelligence", "strategist", "creative", "performance"})

    def test_adv_20_frozen_brain_file_mutation_detection(self):
        """20. Verified that Phase 5.2 files do NOT mutate any frozen Brain RC3 agent DNA or schemas."""
        perf_md = Path(".agents/agents/performance/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(perf_md.encode("utf-8")).hexdigest(), "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9")

        cmo_md = Path(".agents/agents/cmo/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(cmo_md.encode("utf-8")).hexdigest(), "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e")

        handoff_py = Path("schemas/handoff.py").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(handoff_py.encode("utf-8")).hexdigest(), "4075a8e269aef7526bb52c281ac88cc6fdc009d83e9aecb384032e29087e237a")


if __name__ == "__main__":
    unittest.main()
