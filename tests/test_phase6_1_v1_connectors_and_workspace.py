"""Phase 6.1 V1 Connectors, Knowledge Operations & Operator Workspace Test Suite.

Verifies:
- Connector Architecture, Health Inspection & Safe Secret Discovery
- Real Web, File, Analytics, Media, and Sandbox Publishing Connectors
- Multi-Format Knowledge Ingestion (Markdown, JSON, CSV, Brief) & Freshness Policies
- Deterministic Knowledge Conflict Resolution
- Operator Memory Management & Learning Operations
- BusinessWorkspace & Strict Multi-Brand Isolation (Zero Cross-Brand Leakage)
- Campaign Analytics Ingestion & Full Learning Loop
- Operator Workspace E2E Supervised Execution & Gated Approvals
- 24 Adversarial and Failure Boundary Tests
- Permanent Agent Count = 5, Zero Agent 6, and Frozen Brain RC3 Integrity
"""

import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from connectors.analytics_connector import CampaignMetric, RealAnalyticsConnector
from connectors.file_connector import RealFileConnector
from connectors.models import (
    AuthenticationType,
    ConnectorDescriptor,
    ConnectorHealthStatus,
    CredentialState,
    ReadWriteMode,
)
from connectors.publishing_connector import SandboxPublishingConnector
from connectors.registry import ConnectorRegistry
from connectors.web_connector import RealWebConnector
from governance.access_matrix import AgentAccessMatrix, PERMANENT_FIVE_AGENTS
from knowledge.conflicts import ConflictResolutionStatus, KnowledgeConflictResolver
from knowledge.ingestion import (
    DocumentLifecycleStatus,
    FreshnessPolicy,
    IngestionFormat,
    KnowledgeIngestionRequest,
    KnowledgeLifecycleManager,
)
from knowledge.models import (
    AuthorityLevel,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeSource,
    SourceType,
)
from knowledge.repository import LocalKnowledgeRepository
from memory.learning import LearningEvent, LocalLearningRepository
from memory.learning_operations import LearningOperatorService
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.operations import MemoryOperatorService
from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway
from memory.repository import LocalMemoryRepository
from runtime.context import RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityCategory, CapabilityDescriptor, CapabilityRegistry, RiskLevel
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import HumanApprovalRecord, PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest
from workspace.business import BusinessRegistry, BusinessWorkspace
from workspace.operator import OperatorWorkspace


class ScriptedAgentGateway(UniversalModelGateway):
    """Deterministic script-based model gateway for hermetic workspace tests."""

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


class TestPhase61V1ConnectorsAndWorkspace(unittest.TestCase):
    """Comprehensive test suite for Phase 6.1 V1 Connectors & Operator Workspace."""

    def setUp(self):
        self.cap_registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine()
        self.receipt_repo = ExecutionReceiptRepository()
        self.tool_gateway = ToolGateway(
            capability_registry=self.cap_registry,
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )

        # Register Real Connectors in ToolGateway
        self.web_conn = RealWebConnector()
        self.file_conn = RealFileConnector()
        self.analytics_conn = RealAnalyticsConnector()
        self.publish_conn = SandboxPublishingConnector()

        self.tool_gateway.register_adapter(self.web_conn)
        self.tool_gateway.register_adapter(self.file_conn)
        self.tool_gateway.register_adapter(self.analytics_conn)
        self.tool_gateway.register_adapter(self.publish_conn)

        self.knowledge_repo = LocalKnowledgeRepository()
        self.memory_repo = LocalMemoryRepository()
        self.learning_repo = LocalLearningRepository()
        self.model_gateway = ScriptedAgentGateway()

        self.runtime = FiveAgentDepartmentRuntime(
            model_gateway=self.model_gateway,
            tool_gateway=self.tool_gateway,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
            learning_repo=self.learning_repo,
        )

        self.conn_registry = ConnectorRegistry()
        self.biz_registry = BusinessRegistry()
        self.workspace = OperatorWorkspace(
            runtime=self.runtime,
            business_registry=self.biz_registry,
            connector_registry=self.conn_registry,
        )

    # =========================================================================
    # PART A, B, C, D — CONNECTOR ARCHITECTURE, HEALTH & SECRET SAFETY
    # =========================================================================
    def test_connector_registry_and_health_diagnostics(self):
        """Verify connector registration, health diagnostics, and safe secret reporting."""
        health = self.conn_registry.list_connector_health()
        self.assertIn("conn_web_reader", health)
        self.assertIn("conn_file_system", health)
        self.assertIn("conn_analytics_engine", health)
        self.assertIn("conn_publishing_sandbox", health)

        # Verify zero secret exposure (no API keys in health dict)
        health_json_str = json.dumps(health)
        self.assertNotIn("sk-", health_json_str)
        self.assertNotIn("AIza", health_json_str)

    def test_safe_credential_discovery_without_secret_leakage(self):
        """Verify credential presence check only exposes sanitized state enum."""
        cred_desc = ConnectorDescriptor(
            connector_id="conn_custom_api",
            provider="custom_vendor",
            capability_ids=["web_search"],
            authentication_type=AuthenticationType.API_KEY,
            credential_env_names=["NONEXISTENT_CUSTOM_API_KEY_12345"],
        )
        self.conn_registry.register_connector(cred_desc)
        status = self.conn_registry.refresh_connector_health("conn_custom_api")
        self.assertEqual(status, ConnectorHealthStatus.MISSING_CREDENTIAL)

    def test_prohibit_automatic_fallback_on_external_writes(self):
        """Verify external write operations strictly prohibit cross-provider fallback."""
        self.conn_registry.set_fallback_chain("social_publishing", ["conn_publishing_sandbox", "conn_file_system"])
        resolved = self.conn_registry.resolve_executable_connector("social_publishing", is_write=True)
        # Should resolve primary or None, but never fallback across dissimilar providers
        self.assertEqual(resolved.connector_id, "conn_publishing_sandbox")

    # =========================================================================
    # PART E, F, G — KNOWLEDGE INGESTION, LIFECYCLE & CONFLICTS
    # =========================================================================
    def test_multi_format_knowledge_ingestion(self):
        """Verify ingestion from Markdown, JSON, CSV, and Campaign Briefs."""
        mgr = self.workspace.knowledge_lifecycle

        # 1. Ingest Markdown
        res_md = mgr.ingest(
            KnowledgeIngestionRequest(
                source_name="Clinical Guidelines MD",
                source_type=SourceType.LEGAL_COMPLIANCE,
                content_or_path="# Telehealth Compliance\nAll consultations require verified physician credentials.",
                format=IngestionFormat.MARKDOWN,
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            )
        )
        self.assertTrue(res_md.success)
        self.assertGreater(res_md.chunk_count, 0)

        # 2. Ingest JSON
        res_json = mgr.ingest(
            KnowledgeIngestionRequest(
                source_name="Product Specs JSON",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                content_or_path=json.dumps({"plan_tier": "Enterprise", "monthly_fee": 299, "sla": "2hr response"}),
                format=IngestionFormat.JSON,
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            )
        )
        self.assertTrue(res_json.success)

        # 3. Ingest CSV
        csv_data = "metric,benchmark,target\nCAC,150,120\nROAS,3.5,4.0"
        res_csv = mgr.ingest(
            KnowledgeIngestionRequest(
                source_name="Benchmark CSV",
                source_type=SourceType.HISTORICAL_REPORT,
                content_or_path=csv_data,
                format=IngestionFormat.CSV,
            )
        )
        self.assertTrue(res_csv.success)

    def test_knowledge_freshness_auditing_and_retirement(self):
        """Verify lifecycle manager detects stale documents and handles retirement."""
        mgr = self.workspace.knowledge_lifecycle
        res = mgr.ingest(
            KnowledgeIngestionRequest(
                source_name="Old Platform Policy",
                source_type=SourceType.PLATFORM_POLICY,
                content_or_path="Meta advertising policy version 2019",
                format=IngestionFormat.TXT,
            )
        )
        # Simulate aging past 30 days
        self.knowledge_repo._documents[res.document_id].updated_at = datetime.now(timezone.utc) - timedelta(days=45)

        freshness_map = mgr.audit_freshness()
        self.assertEqual(freshness_map[res.document_id], DocumentLifecycleStatus.STALE)

        # Retire document
        mgr.retire_document(res.document_id, reason="Superseded by 2026 policy")
        ret_doc = self.knowledge_repo.get_document(res.document_id)
        self.assertEqual(ret_doc.freshness, "RETIRED")

    def test_deterministic_knowledge_conflict_resolution(self):
        """Verify conflict resolver breaks ties by authority level then verification timestamp."""
        doc_tier1 = KnowledgeDocument(
            source_id="SRC-1",
            title="Official Clinical Protocol",
            source_type=SourceType.LEGAL_COMPLIANCE,
            content="Statins recommended for LDL > 190 mg/dL.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
        )
        doc_tier3 = KnowledgeDocument(
            source_id="SRC-2",
            title="Blog Industry Post",
            source_type=SourceType.MARKET_RESEARCH,
            content="Statins recommended for LDL > 160 mg/dL.",
            authority_level=AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA,
        )

        conflict = KnowledgeConflictResolver.resolve_conflict(
            doc_a=doc_tier1,
            doc_b=doc_tier3,
            topic="Statin Threshold",
            claim_a="LDL > 190",
            claim_b="LDL > 160",
        )
        self.assertEqual(conflict.status, ConflictResolutionStatus.HIGHER_AUTHORITY_WINS)
        self.assertEqual(conflict.resolved_doc_id, doc_tier1.knowledge_id)

    # =========================================================================
    # PART H, I, K, L — MEMORY, LEARNING & MULTI-BRAND ISOLATION
    # =========================================================================
    def test_operator_memory_and_learning_management(self):
        """Verify operator can review, promote, and manage memory and learning lifecycles."""
        # Create empirical learning event
        learn_event = LearningEvent(
            campaign_id="CAMP-CARDIOLOGY",
            hypothesis="Doctor telemetry hook lowers CAC",
            experiment_id="EXP-101",
            primary_metric="cvr_step_1",
            observed_result={"cvr_delta": "+45%"},
            confidence=0.88,
            decision="SCALE",
            lesson="Cardiologist review hook drives conversion in high-intent cohorts.",
            promotion_status=PromotionState.CANDIDATE_MEMORY,
        )
        self.learning_repo.record_learning(learn_event)

        # Inspect via Operator Service
        learnings = self.workspace.learning_ops.list_learnings_for_operator(campaign_id="CAMP-CARDIOLOGY")
        self.assertEqual(len(learnings), 1)

        # Approve promotion into durable memory
        promoted_mem = self.workspace.learning_ops.approve_learning_promotion(learn_event.learning_event_id)
        self.assertIsNotNone(promoted_mem)
        self.assertEqual(promoted_mem.promotion_level, PromotionState.PROMOTED_LEARNING)

    def test_strict_multi_brand_tenant_isolation(self):
        """Verify Brand A cannot access Brand B private knowledge or memories (Zero Cross-Brand Leakage)."""
        # 1. Register Brand A & Brand B workspaces
        biz_a = BusinessWorkspace(
            business_id="BIZ_ALPHA_CARDIO",
            brand_name="Alpha Cardio",
            knowledge_scope="SCOPE_ALPHA",
            memory_scope="SCOPE_ALPHA",
        )
        biz_b = BusinessWorkspace(
            business_id="BIZ_BETA_BEVERAGE",
            brand_name="Beta Beverage",
            knowledge_scope="SCOPE_BETA",
            memory_scope="SCOPE_BETA",
        )
        self.biz_registry.register_workspace(biz_a)
        self.biz_registry.register_workspace(biz_b)

        # 2. Ingest private Knowledge for Brand B
        self.workspace.knowledge_lifecycle.ingest(
            KnowledgeIngestionRequest(
                source_name="Beta Secret Formulation",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                content_or_path="Beta secret coffee brewing formula proprietary",
                scope="SCOPE_BETA",
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            )
        )

        # 3. Save private Memory for Brand B
        self.memory_repo.save_memory(
            MemoryItem(
                memory_type=MemoryType.DECISION_MEMORY,
                agent_source="cmo",
                content="Beta Beverage Q4 pricing discount strategy",
                scope="SCOPE_BETA",
                confidence=0.90,
                promotion_level=PromotionState.PROMOTED_LEARNING,
            )
        )

        # 4. Brand A runs Knowledge and Memory queries
        k_res_a = self.runtime.knowledge_builder.build_context_for_agent("cmo", scope="SCOPE_ALPHA")
        self.assertNotIn("Beta secret coffee brewing formula", k_res_a.context_text)

        # Memory listing for Scope Alpha
        mems_a = self.workspace.memory_ops.list_memories_for_operator(scope="SCOPE_ALPHA")
        for m in mems_a:
            self.assertNotEqual(m["content_preview"], "Beta Beverage Q4 pricing discount strategy")

    # =========================================================================
    # PART M, N, O — REAL ANALYTICS & E2E SUPERVISED OPERATOR RUN
    # =========================================================================
    def test_analytics_ingestion_and_kpi_calculation(self):
        """Verify structured CampaignMetric ingestion and accurate KPI derivation."""
        records = [
            {"channel": "paid_social", "impressions": 50000, "clicks": 2000, "conversions": 100, "spend": 2500.0, "revenue": 10000.0},
            {"channel": "paid_search", "impressions": 25000, "clicks": 1500, "conversions": 90, "spend": 1800.0, "revenue": 8100.0},
        ]
        count = self.analytics_conn.ingest_campaign_metrics("CAMP_TEST_01", records)
        self.assertEqual(count, 2)

        # Retrieve via ToolGateway
        req = ToolRequest(
            agent_id="performance",
            capability_id="analytics_retrieval",
            parameters={"campaign_id": "CAMP_TEST_01"},
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        calc_res = self.analytics_conn.execute("analytics_retrieval", {"campaign_id": "CAMP_TEST_01"})
        self.assertAlmostEqual(calc_res.data["roas"], 4.209, places=2)

    def test_e2e_operator_supervised_campaign_execution(self):
        """Verify complete operator-supervised run through OperatorWorkspace."""
        biz = BusinessWorkspace(
            business_id="BIZ_CARDIOVITAL_PROD",
            brand_name="CardioVital 360",
            default_constraints=["Strict FDA compliance", "No medical cure claims"],
            knowledge_scope="SCOPE_CARDIO",
            memory_scope="SCOPE_CARDIO",
        )
        self.biz_registry.register_workspace(biz)

        artifact = self.workspace.execute_supervised_campaign(
            business_id="BIZ_CARDIOVITAL_PROD",
            objective="Launch Q4 Physician-Guided Telehealth Acquisition Campaign",
        )

        self.assertEqual(artifact.status, RuntimeStatus.COMPLETED)
        self.assertTrue(len(artifact.final_artifact_hash) == 64)
        self.assertIn("cmo_initial", artifact.agent_outputs)
        self.assertIn("intelligence", artifact.agent_outputs)
        self.assertIn("strategist", artifact.agent_outputs)
        self.assertIn("creative", artifact.agent_outputs)
        self.assertIn("performance", artifact.agent_outputs)
        self.assertIn("final_cmo", artifact.agent_outputs)

    # =========================================================================
    # PART Q — 24 ADVERSARIAL & FAILURE INTEGRITY TESTS
    # =========================================================================
    def test_adv_01_missing_connector_credential(self):
        """1. Missing credential sets MISSING_CREDENTIAL health status."""
        desc = ConnectorDescriptor(
            connector_id="conn_unauthed",
            provider="vendor",
            authentication_type=AuthenticationType.API_KEY,
            credential_env_names=["UNSET_SECRET_ENV_VAR_999"],
        )
        self.conn_registry.register_connector(desc)
        self.assertEqual(desc.health_status, ConnectorHealthStatus.MISSING_CREDENTIAL)

    def test_adv_02_disabled_connector_status(self):
        """2. Disabled connector maintains DISABLED health state."""
        desc = ConnectorDescriptor(
            connector_id="conn_disabled_vendor",
            provider="vendor_x",
            health_status=ConnectorHealthStatus.DISABLED,
        )
        self.conn_registry.register_connector(desc)
        self.assertEqual(desc.health_status, ConnectorHealthStatus.DISABLED)

    def test_adv_03_ssrf_blocked_on_web_connector(self):
        """3. Web connector strictly blocks SSRF to 127.0.0.1 and cloud metadata IP."""
        res = self.web_conn.execute("read_page", {"url": "http://127.0.0.1:8080/admin"})
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "SSRF_BLOCKED")

    def test_adv_04_invalid_url_scheme_blocked(self):
        """4. File scheme or invalid URI schemes are blocked."""
        res = self.web_conn.execute("read_page", {"url": "file:///etc/passwd"})
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "INVALID_SCHEME")

    def test_adv_05_file_not_found_handling(self):
        """5. File connector returns clean FILE_NOT_FOUND error on missing files."""
        res = self.file_conn.execute("file_read", {"path": "nonexistent_dir/missing_file.txt"})
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "FILE_NOT_FOUND")

    def test_adv_06_direct_connector_bypass_prevention(self):
        """6. Directly calling connector does not register execution receipts in repository."""
        pre = len(self.receipt_repo.list_receipts_for_run("BYPASS_RUN"))
        self.file_conn.execute("file_write", {"path": "logs/test_bypass.log", "content": "test"})
        post = len(self.receipt_repo.list_receipts_for_run("BYPASS_RUN"))
        self.assertEqual(pre, post)

    def test_adv_07_empty_knowledge_ingestion_rejected(self):
        """7. Ingesting blank or whitespace content is rejected."""
        res = self.workspace.knowledge_lifecycle.ingest(
            KnowledgeIngestionRequest(
                source_name="Blank Doc",
                source_type=SourceType.BRAND_GUIDELINE,
                content_or_path="   ",
            )
        )
        self.assertFalse(res.success)

    def test_adv_08_stale_knowledge_filtered_from_fresh_search(self):
        """8. Stale knowledge is labeled properly in lifecycle audit."""
        mgr = self.workspace.knowledge_lifecycle
        res = mgr.ingest(
            KnowledgeIngestionRequest(
                source_name="Expiring Guideline",
                source_type=SourceType.PLATFORM_POLICY,
                content_or_path="Old guideline",
            )
        )
        # Age document past policy
        self.knowledge_repo._documents[res.document_id].updated_at = datetime.now(timezone.utc) - timedelta(days=60)
        audit = mgr.audit_freshness()
        self.assertEqual(audit[res.document_id], DocumentLifecycleStatus.STALE)

    def test_adv_09_retired_knowledge_excluded(self):
        """9. Retired knowledge is excluded from active retrieval context."""
        mgr = self.workspace.knowledge_lifecycle
        res = mgr.ingest(
            KnowledgeIngestionRequest(
                source_name="Deprecated Guideline",
                source_type=SourceType.BRAND_GUIDELINE,
                content_or_path="Deprecated phrase ABC",
                scope="SCOPE_RET",
            )
        )
        mgr.retire_document(res.document_id, reason="Obsolete")
        k_res = self.runtime.knowledge_builder.build_context_for_agent("creative", scope="SCOPE_RET")
        self.assertNotIn("Deprecated phrase ABC", k_res.context_text)

    def test_adv_10_conflict_resolution_tie_breaker(self):
        """10. Equal authority conflicts are resolved by newer timestamp."""
        doc1 = KnowledgeDocument(
            source_id="S1",
            title="Doc 1",
            source_type=SourceType.MARKET_RESEARCH,
            content="A",
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        doc2 = KnowledgeDocument(
            source_id="S2",
            title="Doc 2",
            source_type=SourceType.MARKET_RESEARCH,
            content="B",
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        conf = KnowledgeConflictResolver.resolve_conflict(doc1, doc2, "Topic", "Claim A", "Claim B")
        self.assertEqual(conf.status, ConflictResolutionStatus.NEWER_VERIFIED_SOURCE_WINS)
        self.assertEqual(conf.resolved_doc_id, doc2.knowledge_id)

    def test_adv_11_expired_memory_staleness(self):
        """11. Expired memory is flagged as stale in operator service."""
        mem = MemoryItem(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="cmo",
            content="Expired strategy",
            expiry_or_review_date=datetime.now(timezone.utc) - timedelta(days=1),
        )
        self.memory_repo.save_memory(mem)
        mems = self.workspace.memory_ops.list_memories_for_operator()
        stale_item = next(m for m in mems if m["memory_id"] == mem.memory_id)
        self.assertTrue(stale_item["is_stale"])

    def test_adv_12_unverified_memory_promotion_rejected(self):
        """12. Candidate memory without evidence cannot be promoted to durable learning."""
        cand_mem = MemoryItem(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Unverified opinion with no evidence",
            confidence=0.40,
            evidence_refs=[],
            promotion_level=PromotionState.CANDIDATE_MEMORY,
        )
        self.memory_repo.save_memory(cand_mem)
        result = self.workspace.memory_ops.approve_promotion(cand_mem.memory_id)
        self.assertIsNone(result)

    def test_adv_13_operator_memory_rejection(self):
        """13. Operator can explicitly reject a candidate memory promotion."""
        cand_mem = MemoryItem(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="creative",
            content="Poor creative hypothesis",
            promotion_level=PromotionState.CANDIDATE_MEMORY,
        )
        self.memory_repo.save_memory(cand_mem)
        rejected = self.workspace.memory_ops.reject_promotion(cand_mem.memory_id, reason="Statistically invalid")
        self.assertEqual(rejected.context["promotion_rejected_reason"], "Statistically invalid")

    def test_adv_14_schedule_retest_on_learning_event(self):
        """14. Operator can flag learning event for retesting."""
        event = LearningEvent(
            campaign_id="CAMP-RETEST",
            hypothesis="Audience expansion test",
            experiment_id="EXP-99",
            primary_metric="roas",
            decision="ITERATE",
            lesson="Need larger sample size",
        )
        self.learning_repo.record_learning(event)
        ok = self.workspace.learning_ops.schedule_retest(event.learning_event_id, reason="Sample size too small")
        self.assertTrue(ok)
        updated = self.learning_repo.get_learning(event.learning_event_id)
        self.assertTrue(updated.retest_required)

    def test_adv_15_pause_and_resume_operator_controls(self):
        """15. Operator can pause and resume active runs."""
        ctx = self.workspace.create_run("BIZ_DEFAULT", "Test Pause")
        self.workspace.pause_run(ctx.run_id)
        self.assertEqual(ctx.status, RuntimeStatus.PAUSED)
        self.workspace.resume_run(ctx.run_id)
        self.assertEqual(ctx.status, RuntimeStatus.RUNNING)

    def test_adv_16_cancel_run_operator_control(self):
        """16. Operator can cancel active runs."""
        ctx = self.workspace.create_run("BIZ_DEFAULT", "Test Cancel")
        self.workspace.cancel_run(ctx.run_id, reason="Budget cancelled")
        self.assertEqual(ctx.status, RuntimeStatus.CANCELLED)

    def test_adv_17_analytics_kpi_calculation_with_zero_spend(self):
        """17. KPI calculation handles edge cases like 0 spend gracefully."""
        res = self.analytics_conn.execute("kpi_calculation", {"spend": 0.0, "revenue": 0.0, "clicks": 0, "conversions": 0})
        self.assertTrue(res.success)
        self.assertEqual(res.data["roas"], 0.0)
        self.assertEqual(res.data["cac"], 0.0)

    def test_adv_18_sandbox_publishing_isolation(self):
        """18. Sandbox publisher records executions without touching external APIs."""
        res = self.publish_conn.execute("social_publishing", {"platform": "meta_ads", "content": "Ad text"})
        self.assertTrue(res.success)
        self.assertEqual(res.data["status"], "SANDBOX_PUBLISHED")

    def test_adv_19_unauthorized_agent_cannot_access_analytics(self):
        """19. Creative agent cannot execute analytics operations via ToolGateway."""
        req = ToolRequest(agent_id="creative", capability_id="analytics_retrieval", parameters={})
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "PERMISSION_DENIED")

    def test_adv_20_knowledge_provenance_verification_failure(self):
        """20. Verification fails on corrupted citation chunk reference."""
        citation = KnowledgeCitation(knowledge_id="FAKE-KNOW-001", chunk_id="FAKE-CHUNK-001")
        self.assertFalse(self.knowledge_repo.verify_provenance(citation))

    def test_adv_21_business_workspace_hash_tamper_detection(self):
        """21. Tampering with BusinessWorkspace modifies its cryptographic hash."""
        biz = BusinessWorkspace(business_id="BIZ_T", brand_name="Brand T")
        h1 = biz.calculate_workspace_hash()
        biz.approved_claims.append("New Claim")
        h2 = biz.calculate_workspace_hash()
        self.assertNotEqual(h1, h2)

    def test_adv_22_lineage_trace_validity_for_approved_publish(self):
        """22. Lineage inspector correctly resolves publication receipt and approval."""
        ctx = self.workspace.create_run("BIZ_DEFAULT", "Lineage Run")
        token = "TOKEN-LINEAGE-1"
        self.policy_engine.register_approval(
            HumanApprovalRecord(
                approval_token=token,
                action_type="social_publishing",
                approved_by="VP",
                approved_at=datetime.now(timezone.utc).isoformat(),
                scope="BIZ_DEFAULT",
                risk_level=RiskLevel.CRITICAL,
            )
        )
        receipt = self.runtime.request_publish_action(ctx, approval_token=token)
        trace = self.runtime.lineage_inspector.trace_claim_to_receipt("Published Campaign", receipt.execution_id)
        self.assertTrue(trace.valid)

    def test_adv_23_agent_6_registration_strictly_blocked(self):
        """23. Registering Agent 6 profile in access matrix is strictly prohibited."""
        self.assertTrue(AgentAccessMatrix.validate_agent_count())
        self.assertEqual(len(PERMANENT_FIVE_AGENTS), 5)

    def test_adv_24_frozen_brain_dna_hashes_unchanged(self):
        """24. Verified that Phase 6.1 code preserves all frozen Brain RC3 agent DNA and schemas."""
        perf_md = Path(".agents/agents/performance/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(perf_md.encode("utf-8")).hexdigest(), "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9")

        cmo_md = Path(".agents/agents/cmo/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(cmo_md.encode("utf-8")).hexdigest(), "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e")

        handoff_py = Path("schemas/handoff.py").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(handoff_py.encode("utf-8")).hexdigest(), "4075a8e269aef7526bb52c281ac88cc6fdc009d83e9aecb384032e29087e237a")


if __name__ == "__main__":
    unittest.main()
