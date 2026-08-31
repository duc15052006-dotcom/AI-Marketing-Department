"""Phase 5.1 Capability/Tool Gateway & Knowledge/Memory Foundation Test Suite.

Verifies:
- Capability Registration & Discovery
- Permission Enforcement & RBAC
- Human Approval Gate Blocking & Authorization
- Immutable Execution Receipts & Hashing
- Provider Adapter Failures, Timeouts, and Retries
- Knowledge Versioning & Provenance Citations
- Memory Isolation, Promotion Engine, and Stale Retirement
- LearningEvent Lifecycle and Repository Querying
- Agent Access Matrix (5 Permanent Agents, Zero Agent 6)
- Model Gateway Decoupling & Brain RC3 Frozen Hash Protection
"""

import hashlib
import json
import time
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
from tools.adapters import MockToolAdapter, SearchAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    CostPolicy,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import HumanApprovalRecord, PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class TestPhase51CapabilityGatewayAndFoundation(unittest.TestCase):
    """Exhaustive tests for Phase 5.1 foundation."""

    def setUp(self):
        self.cap_registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine()
        self.receipt_repo = ExecutionReceiptRepository()
        self.gateway = ToolGateway(
            capability_registry=self.cap_registry,
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )
        self.knowledge_repo = LocalKnowledgeRepository()
        self.memory_repo = LocalMemoryRepository()
        self.learning_repo = LocalLearningRepository()

    # 1. Capability Registration & Discovery
    def test_capability_registration_and_discovery(self):
        """Verify built-in capabilities across all 5 categories are registered and discoverable."""
        caps = self.cap_registry.list_capabilities()
        self.assertGreaterEqual(len(caps), 15)

        categories = {c.category for c in caps}
        self.assertIn(CapabilityCategory.OBSERVE, categories)
        self.assertIn(CapabilityCategory.CREATE, categories)
        self.assertIn(CapabilityCategory.PUBLISH, categories)
        self.assertIn(CapabilityCategory.ANALYZE, categories)
        self.assertIn(CapabilityCategory.FILE_DATA, categories)

        # Query by category
        publish_caps = self.cap_registry.list_capabilities(CapabilityCategory.PUBLISH)
        self.assertTrue(all(c.category == CapabilityCategory.PUBLISH for c in publish_caps))
        self.assertIn("social_publishing", [c.capability_id for c in publish_caps])

        # Query for specific agent
        intel_caps = self.cap_registry.list_capabilities_for_agent("intelligence")
        intel_ids = [c.capability_id for c in intel_caps]
        self.assertIn("web_search", intel_ids)
        self.assertNotIn("social_publishing", intel_ids)

    # 2. Permission Enforcement & RBAC
    def test_permission_enforcement_blocks_unauthorized_agent(self):
        """Verify Intelligence and Strategist agents cannot execute publishing or financial actions."""
        req = ToolRequest(
            agent_id="intelligence",
            capability_id="social_publishing",
            parameters={"platform": "twitter", "content": "Live ad launch"},
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "PERMISSION_DENIED")
        self.assertIn("lacks required permissions", receipt.error_message or "")

    def test_creative_agent_permission_boundaries(self):
        """Verify Creative agent can execute local creation but cannot execute external analytics or publish."""
        # Allowed local image creation
        req_allowed = ToolRequest(
            agent_id="creative",
            capability_id="image_generation",
            parameters={"prompt": "High-contrast clinical sensor mockup"},
        )
        receipt_allowed = self.gateway.execute(req_allowed)
        self.assertEqual(receipt_allowed.status, ExecutionStatus.SUCCESS)

        # Blocked analytics retrieval
        req_blocked = ToolRequest(
            agent_id="creative",
            capability_id="attribution_data_access",
            parameters={},
        )
        receipt_blocked = self.gateway.execute(req_blocked)
        self.assertEqual(receipt_blocked.status, ExecutionStatus.BLOCKED)

    # 3. Human Approval Gate
    def test_human_approval_gate_blocks_without_token(self):
        """Verify CMO requests for publishing or financial actions block with APPROVAL_REQUIRED when no token is supplied."""
        req = ToolRequest(
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "message": "Campaign launch"},
            approval_token=None,
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "HUMAN_APPROVAL_REQUIRED")

    def test_human_approval_gate_passes_with_valid_token(self):
        """Verify CMO requests succeed when authorized with a verified human approval token."""
        token = "AUTH-TOKEN-HUMAN-9999"
        self.policy_engine.register_approval(
            HumanApprovalRecord(
                approval_token=token,
                action_type="social_publishing",
                approved_by="Executive CMO Reviewer",
                approved_at=datetime.now(timezone.utc).isoformat(),
                scope="CARDIOVITAL_CAMPAIGN_LAUNCH",
                risk_level=RiskLevel.CRITICAL,
            )
        )

        req = ToolRequest(
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "message": "Authorized campaign launch"},
            approval_token=token,
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertNotEqual(receipt.approval_reference, token)
        self.assertTrue((receipt.approval_reference or "").startswith("approval_ref_"))

    # 4. Immutable Execution Receipts
    def test_immutable_execution_receipt_generation_and_hashing(self):
        """Verify every tool execution produces an immutable receipt with verifiable request and result hashes."""
        req = ToolRequest(
            run_id="RUN-TEST-001",
            agent_id="intelligence",
            capability_id="web_search",
            parameters={"query": "Telehealth preventive cardiology market size"},
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertTrue(receipt.execution_id.startswith("EXEC-"))
        self.assertTrue(len(receipt.request_hash) == 64)
        self.assertTrue(len(receipt.result_hash) == 64)
        self.assertIsNotNone(receipt.data)

        # Stored in repository
        stored = self.receipt_repo.get_receipt(receipt.execution_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.result_hash, receipt.result_hash)

    # 5. Provider Failures, Timeouts, and Retries
    def test_provider_failure_and_retry_boundaries(self):
        """Verify gateway executes retry logic on transient errors and normalizes timeout/failure receipts."""
        mock_adapter = MockToolAdapter(
            name="flaky_mock_adapter",
            should_fail=False,
            error_code="NETWORK_ERROR",
            error_message="Transient connection dropped",
            fail_attempts=1,  # Fails on attempt 1, succeeds on attempt 2
        )
        self.gateway.register_adapter(mock_adapter)

        # Register custom test capability
        self.cap_registry.register_capability(
            CapabilityDescriptor(
                capability_id="flaky_search",
                name="Flaky Search",
                category=CapabilityCategory.OBSERVE,
                description="Testing retries",
                provider="flaky_mock_adapter",
                supported_agents=["intelligence", "cmo"],
                retry_policy={"max_retries": 2, "retryable_errors": ["NETWORK_ERROR"]},
            )
        )

        req = ToolRequest(
            agent_id="intelligence",
            capability_id="flaky_search",
            parameters={"query": "test query"},
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.data.get("attempts"), 2)

    def test_provider_timeout_handling(self):
        """Verify gateway catches timeout errors and sets ExecutionStatus.TIMEOUT."""
        timeout_adapter = MockToolAdapter(
            name="slow_adapter",
            delay_seconds=0.5,
        )
        self.gateway.register_adapter(timeout_adapter)

        self.cap_registry.register_capability(
            CapabilityDescriptor(
                capability_id="slow_task",
                name="Slow Task",
                category=CapabilityCategory.OBSERVE,
                description="Testing timeout",
                provider="slow_adapter",
                supported_agents=["intelligence", "cmo"],
                timeout_policy=0.1,  # Timeout is 0.1s while delay is 0.5s
            )
        )

        req = ToolRequest(
            agent_id="intelligence",
            capability_id="slow_task",
            parameters={},
            timeout_seconds=0.1,
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.TIMEOUT)
        self.assertEqual(receipt.error_class, "TIMEOUT")

    # 6. Knowledge Versioning & Provenance
    def test_knowledge_document_chunking_and_versioning(self):
        """Verify KnowledgeDocuments create chunks, increment version numbers, and track source provenance."""
        source = self.knowledge_repo.save_source(
            KnowledgeSource(
                source_name="CardioVital 360 Verified Ground Truth",
                source_url_or_path="company/products/cardiovital_facts.json",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                authority_score=1.0,
            )
        )

        doc = KnowledgeDocument(
            source_id=source.source_id,
            title="CardioVital 360 Core Clinical Ground Truth",
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
            content="CardioVital 360 provides ApoB testing, CAC scoring integration, and FDA-cleared continuous sensor monitoring. Subscription price is $149/month. Board certified cardiologists review telemetry within 24 hours.",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            tags=["cardiology", "pricing", "clinical_spec"],
            scope="PRODUCT_SPECIFIC",
        )

        saved = self.knowledge_repo.save_document(doc, changed_by="Dr. Clinical Lead", summary="Initial Ground Truth Spec")
        self.assertEqual(saved.version, 1)
        self.assertGreater(len(saved.chunks), 0)

        # Update document
        saved.content += " Anti-cure marketing compliance is strictly mandatory."
        updated = self.knowledge_repo.save_document(saved, changed_by="Legal Compliance", summary="Added compliance clause")
        self.assertEqual(updated.version, 2)

        history = self.knowledge_repo.get_version_history(saved.knowledge_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].version_number, 1)
        self.assertEqual(history[1].version_number, 2)

        # Test Provenance Verification
        citation = KnowledgeCitation(
            knowledge_id=saved.knowledge_id,
            chunk_id=saved.chunks[0].chunk_id,
            claim_ref="ApoB biomarker testing",
        )
        self.assertTrue(self.knowledge_repo.verify_provenance(citation))

    # 7. Memory Foundation, Isolation, and Promotion Engine
    def test_memory_promotion_rules_require_evidence(self):
        """Verify raw observations cannot skip directly to Promoted Learning without evidence."""
        mem = MemoryItem(
            memory_type=MemoryType.EXPERIMENT_MEMORY,
            agent_source="performance",
            run_id="RUN-CAMPAIGN-001",
            content="Hook variant B (CLINICAL_DISCLOSURE) increased step-1 conversion by 28% compared to lifestyle hook.",
            confidence=0.5,
            promotion_level=PromotionState.RAW_OBSERVATION,
        )
        self.memory_repo.save_memory(mem)

        # 1. Direct promotion to PROMOTED_LEARNING without verification must fail
        ok, reason = MemoryPromotionEngine.promote_memory(mem, PromotionState.PROMOTED_LEARNING)
        self.assertFalse(ok)
        self.assertIn("LIFECYCLE_VIOLATION", reason)

        # 2. Promote to CANDIDATE_MEMORY
        ok_cand, _ = MemoryPromotionEngine.promote_memory(mem, PromotionState.CANDIDATE_MEMORY)
        self.assertTrue(ok_cand)
        self.assertEqual(mem.promotion_level, PromotionState.CANDIDATE_MEMORY)

        # 3. Promote to VERIFIED_MEMORY requires evidence + confidence
        ok_ver_fail, reason_fail = MemoryPromotionEngine.promote_memory(mem, PromotionState.VERIFIED_MEMORY)
        self.assertFalse(ok_ver_fail)
        self.assertIn("EVIDENCE_REQUIRED", reason_fail)

        # Provide evidence and confidence
        mem.confidence = 0.85
        ok_ver, _ = MemoryPromotionEngine.promote_memory(
            mem,
            PromotionState.VERIFIED_MEMORY,
            supporting_evidence=["EVID-CHI-SQ-001", "RECEIPT-ANALYTICS-442"],
        )
        self.assertTrue(ok_ver)
        self.assertEqual(mem.promotion_level, PromotionState.VERIFIED_MEMORY)

        # 4. Promote to PROMOTED_LEARNING with institutional review rationale
        ok_prom, _ = MemoryPromotionEngine.promote_memory(
            mem,
            PromotionState.PROMOTED_LEARNING,
            review_rationale="Statistically significant across n=14,200 sample; approved by Performance & CMO for scaling.",
        )
        self.assertTrue(ok_prom)
        self.assertEqual(mem.promotion_level, PromotionState.PROMOTED_LEARNING)
        self.assertIn("promoted_at", mem.metadata)

    def test_working_memory_expiry_purge(self):
        """Verify temporary working memory expires and is cleanly purgable."""
        expired_mem = MemoryItem(
            memory_type=MemoryType.WORKING_MEMORY,
            agent_source="intelligence",
            content="Temporary intermediate scraping state",
            expiry_or_review_date=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        active_mem = MemoryItem(
            memory_type=MemoryType.WORKING_MEMORY,
            agent_source="intelligence",
            content="Active session note",
            expiry_or_review_date=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        self.memory_repo.save_memory(expired_mem)
        self.memory_repo.save_memory(active_mem)

        purged_count = self.memory_repo.purge_expired_working_memories()
        self.assertEqual(purged_count, 1)
        self.assertIsNone(self.memory_repo.get_memory(expired_mem.memory_id))
        self.assertIsNotNone(self.memory_repo.get_memory(active_mem.memory_id))

    # 8. LearningEvent Schema & Repository
    def test_learning_event_lifecycle(self):
        """Verify LearningEvent stores full empirical experiment loops and is queryable."""
        event = LearningEvent(
            campaign_id="CAMP-CARDIO-001",
            hypothesis="ApoB risk education in video hooks drives higher CTR than generic wellness copy.",
            experiment_id="EXP-HOOK-04",
            baseline={"hook": "GENERIC_WELLNESS", "cvr": 0.021, "spend": 500.0},
            treatment={"hook": "APOB_CLINICAL_RISK", "cvr": 0.038, "spend": 500.0},
            primary_metric="cvr_step_1",
            observed_result={"delta_relative": "+80.9%", "p_value": 0.004, "stat_sig": True},
            sample_or_evidence={"impressions": 45000, "clicks": 1820},
            confidence=0.96,
            decision="SCALE",
            lesson="Biomarker-specific risk awareness outperforms generic heart health claims in high-intent cohorts.",
            applicability_scope="BRAND_SPECIFIC",
            promotion_status=PromotionState.PROMOTED_LEARNING,
        )

        saved = self.learning_repo.record_learning(event)
        self.assertEqual(saved.decision, "SCALE")

        fetched = self.learning_repo.get_learning(event.learning_event_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.confidence, 0.96)

        query_res = self.learning_repo.query_learnings_for_context(["apob", "biomarker"])
        self.assertEqual(len(query_res), 1)

    # 9. Agent Access Matrix (Permanent Agent Count = 5, Zero Agent 6)
    def test_agent_access_matrix_enforces_five_permanent_agents(self):
        """Verify strict RBAC access matrix covers exactly the 5 permanent agents with zero 6th agent."""
        self.assertTrue(AgentAccessMatrix.validate_agent_count())
        self.assertEqual(len(AgentAccessMatrix.PROFILES), 5)
        self.assertEqual(set(AgentAccessMatrix.PROFILES.keys()), {"cmo", "intelligence", "strategist", "creative", "performance"})

        # Verify access boundaries
        self.assertTrue(AgentAccessMatrix.can_access_knowledge_source("cmo", SourceType.LEGAL_COMPLIANCE))
        self.assertFalse(AgentAccessMatrix.can_access_knowledge_source("creative", SourceType.LEGAL_COMPLIANCE))

        self.assertTrue(AgentAccessMatrix.can_access_memory_type("performance", MemoryType.EXPERIMENT_MEMORY))
        self.assertFalse(AgentAccessMatrix.can_access_memory_type("creative", MemoryType.EXPERIMENT_MEMORY))

    # 10. Direct Tool Bypass Blocked
    def test_direct_tool_bypass_blocked_for_unregistered_agent(self):
        """Verify unauthorized external agent identities are strictly rejected by ToolGateway."""
        req = ToolRequest(
            agent_id="autonomous_agent_6",
            capability_id="web_search",
            parameters={"query": "test query"},
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "UNRECOGNIZED_AGENT")

    # 11. Frozen Brain RC3 Hash Protection
    def test_frozen_brain_rc3_hashes_intact(self):
        """Verify Phase 5.1 changes have not modified any frozen Brain RC3 agent DNA or contracts."""
        perf_md = Path(".agents/agents/performance/agent.md").read_text(encoding="utf-8")
        perf_hash = hashlib.sha256(perf_md.encode("utf-8")).hexdigest()
        self.assertEqual(perf_hash, "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9")

        cmo_md = Path(".agents/agents/cmo/agent.md").read_text(encoding="utf-8")
        cmo_hash = hashlib.sha256(cmo_md.encode("utf-8")).hexdigest()
        self.assertEqual(cmo_hash, "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e")

        handoff_py = Path("schemas/handoff.py").read_text(encoding="utf-8")
        handoff_hash = hashlib.sha256(handoff_py.encode("utf-8")).hexdigest()
        self.assertEqual(handoff_hash, "4075a8e269aef7526bb52c281ac88cc6fdc009d83e9aecb384032e29087e237a")


if __name__ == "__main__":
    unittest.main()