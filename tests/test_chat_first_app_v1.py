"""Chat-First Application V1 Adversarial & Unit Test Suite.

Verifies:
- Chat session isolation & zero mandatory brand onboarding
- Ephemeral session knowledge with zero auto-persistence into persistent repositories
- Context compiler role-targeted context construction
- Project workspace management & selective promotion to Project / Brand
- Multi-run queue, background workers, and provider resource limiter
- Multi-tenant isolation (Zero cross-chat, cross-project, cross-brand leaks)
- Permanent agent count = 5 & Brain RC3 frozen hash preservation
"""

import hashlib
import json
import time
import unittest
from pathlib import Path

from chat.knowledge import SessionKnowledgeStore
from chat.session import AttachmentType, ChatAttachment, ChatSessionManager
from governance.access_matrix import AgentAccessMatrix, PERMANENT_FIVE_AGENTS
from knowledge.repository import LocalKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository
from runtime.context import RuntimeContext, RuntimeStatus
from runtime.context_compiler import ContextCompiler
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.queue import ProviderResourceState, ResourceLimiter, RunManager, RunQueueStatus
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionReceiptRepository
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway
from workspace.business import BusinessRegistry, BusinessWorkspace
from workspace.project import ClaimOriginType, ProjectRegistry


class TestChatFirstAppV1(unittest.TestCase):
    """Test suite for Chat-First UX, Multi-Run Queue, and Project Architecture."""

    def setUp(self):
        self.chat_mgr = ChatSessionManager()
        self.session_knowledge = SessionKnowledgeStore()
        self.knowledge_repo = LocalKnowledgeRepository()
        self.memory_repo = LocalMemoryRepository()
        self.biz_registry = BusinessRegistry()
        self.project_registry = ProjectRegistry(business_registry=self.biz_registry)

        # Context Compiler
        self.context_compiler = ContextCompiler(
            session_knowledge=self.session_knowledge,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
        )

        # Setup minimal runtime for queue testing
        self.cap_registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine()
        self.receipt_repo = ExecutionReceiptRepository()
        self.tool_gateway = ToolGateway(
            capability_registry=self.cap_registry,
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )
        self.runtime = FiveAgentDepartmentRuntime(
            tool_gateway=self.tool_gateway,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
        )
        self.resource_limiter = ResourceLimiter()
        self.run_manager = RunManager(
            runtime=self.runtime,
            max_workers=2,
            resource_limiter=self.resource_limiter,
        )

    # =========================================================================
    # 1. CHAT-FIRST ENTRYPOINT & ZERO MANDATORY BRAND
    # =========================================================================
    def test_new_chat_without_brand_required(self):
        """Verify chat creation requires no business_id or project_id."""
        session = self.chat_mgr.create_session(title="Ad-Hoc Market Scan")
        self.assertIsNotNone(session.chat_id)
        self.assertIsNone(session.optional_business_id)
        self.assertIsNone(session.optional_project_id)
        self.assertEqual(session.status, "ACTIVE")

    def test_chat_session_isolation(self):
        """Verify Chat A message history is strictly isolated from Chat B."""
        chat_a = self.chat_mgr.create_session(title="Chat A")
        chat_b = self.chat_mgr.create_session(title="Chat B")

        chat_a.add_user_message("Analyze competitor Acme in Chat A.")
        chat_b.add_user_message("Draft creative copy in Chat B.")

        self.assertEqual(len(chat_a.messages), 1)
        self.assertEqual(len(chat_b.messages), 1)
        self.assertIn("Chat A", chat_a.messages[0].content)
        self.assertNotIn("Chat A", chat_b.messages[0].content)

    # =========================================================================
    # 2. INLINE CHAT ATTACHMENTS & EPHEMERAL SESSION KNOWLEDGE
    # =========================================================================
    def test_inline_attachment_indexing_and_search(self):
        """Verify inline attachments are indexed into ephemeral memory."""
        chat = self.chat_mgr.create_session(title="Attachment Test")
        att = ChatAttachment(
            chat_id=chat.chat_id,
            filename_or_url="pricing_sheet.json",
            attachment_type=AttachmentType.JSON,
            content='{"enterprise_tier": "$499/mo", "sla_hours": 4}',
        )
        doc = self.session_knowledge.index_attachment(att)
        self.assertEqual(doc.chat_id, chat.chat_id)
        self.assertEqual(len(doc.chunks), 1)

        # Search session
        results = self.session_knowledge.search_session(chat.chat_id, query="enterprise_tier")
        self.assertEqual(len(results), 1)
        self.assertIn("$499/mo", results[0].text)

    def test_ephemeral_session_knowledge_zero_auto_persistence(self):
        """Verify session attachments do NOT write into persistent LocalKnowledgeRepository."""
        chat = self.chat_mgr.create_session(title="Zero Persistence Test")
        initial_persistent_count = len(self.knowledge_repo.list_documents())

        att = ChatAttachment(
            chat_id=chat.chat_id,
            filename_or_url="confidential_memo.txt",
            attachment_type=AttachmentType.TEXT,
            content="Temporary memo content that must remain ephemeral.",
        )
        self.session_knowledge.index_attachment(att)

        post_persistent_count = len(self.knowledge_repo.list_documents())
        self.assertEqual(initial_persistent_count, post_persistent_count)

    # =========================================================================
    # 3. CONTEXT COMPILER ROLE TARGETING
    # =========================================================================
    def test_context_compiler_role_targeting(self):
        """Verify context compiler builds role-bounded context payloads."""
        chat = self.chat_mgr.create_session(title="Compiler Test")
        att = ChatAttachment(
            chat_id=chat.chat_id,
            filename_or_url="specs.md",
            attachment_type=AttachmentType.MARKDOWN,
            content="Product: SuperCloud Telemetry Core.\nFeatures: 99.99% uptime.",
        )
        self.session_knowledge.index_attachment(att)

        ctx = RuntimeContext(objective="Launch SuperCloud Telemetry")
        cmo_compiled = self.context_compiler.compile_for_agent("cmo", ctx, chat_id=chat.chat_id)
        self.assertEqual(cmo_compiled.agent_id, "cmo")
        self.assertIn("SuperCloud", cmo_compiled.raw_prompt_payload)

    # =========================================================================
    # 4. PROJECT WORKSPACE & CHAT PROMOTION
    # =========================================================================
    def test_promote_chat_to_project(self):
        """Verify creating a project workspace from a chat thread."""
        chat = self.chat_mgr.create_session(title="Exploration Thread")
        proj = self.project_registry.promote_chat_to_project(chat.chat_id, project_name="Q4 Growth Project")
        self.assertEqual(proj.project_name, "Q4 Growth Project")
        self.assertIn(chat.chat_id, proj.chat_ids)

    def test_selective_chat_to_brand_promotion_filters_unverified_facts(self):
        """Verify chat promotion filters out UNVERIFIED or MODEL_INFERENCE facts."""
        chat = self.chat_mgr.create_session(title="Brand Extraction Thread")
        extracted_facts = [
            {"text": "FDA-cleared cardiology sensor", "origin": "SOURCE_VERIFIED"},
            {"text": "Board certified review in 24h", "origin": "USER_PROVIDED"},
            {"text": "Guaranteed 100% cure rate", "origin": "MODEL_INFERENCE"},  # Must be rejected
            {"text": "Unsubstantiated competitor claim", "origin": "UNVERIFIED"},  # Must be rejected
        ]
        brand = self.project_registry.promote_chat_to_brand(
            chat_id=chat.chat_id,
            brand_name="VerifiedHealth",
            industry="Healthcare",
            extracted_facts=extracted_facts,
        )
        self.assertEqual(len(brand.approved_claims), 2)
        self.assertIn("FDA-cleared cardiology sensor", brand.approved_claims)
        self.assertIn("Board certified review in 24h", brand.approved_claims)
        self.assertNotIn("Guaranteed 100% cure rate", brand.approved_claims)

    # =========================================================================
    # 5. MULTI-RUN QUEUE & RESOURCE LIMITER
    # =========================================================================
    def test_run_queue_enqueuing_and_cancellation(self):
        """Verify queue enqueuing and safe cancellation."""
        item = self.run_manager.enqueue_run(
            run_id="RUN-TEST-001",
            objective="Analyze Q4 Ad Spend",
        )
        self.assertIn(item.status, (RunQueueStatus.QUEUED, RunQueueStatus.RUNNING, RunQueueStatus.COMPLETED))

        # Cancel another queued run
        cancel_item = self.run_manager.enqueue_run(
            run_id="RUN-TEST-CANCEL",
            objective="Task to cancel",
        )
        ok = self.run_manager.cancel_run("RUN-TEST-CANCEL")
        self.assertTrue(ok)
        self.assertEqual(cancel_item.status, RunQueueStatus.CANCELLED)

    def test_resource_limiter_rate_limit_and_cooldown(self):
        """Verify per-provider resource limiter blocks during 429 cooldown."""
        limiter = ResourceLimiter()
        # Initial slot acquisition
        self.assertTrue(limiter.acquire_slot("gemini"))
        limiter.release_slot("gemini")

        # Simulate 429
        limiter.record_rate_limit("gemini", cooldown_seconds=5.0)
        self.assertFalse(limiter.acquire_slot("gemini", timeout_seconds=0.2))

    # =========================================================================
    # 6. INVARIANTS & FROZEN BRAIN RC3 HASHE PROTECTION
    # =========================================================================
    def test_permanent_five_agents_and_frozen_hashes_preserved(self):
        """Verify permanent agent count = 5 and frozen Brain RC3 files are bit-for-bit unchanged."""
        self.assertTrue(AgentAccessMatrix.validate_agent_count())
        self.assertEqual(len(PERMANENT_FIVE_AGENTS), 5)

        perf_md = Path(".agents/agents/performance/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(perf_md.encode("utf-8")).hexdigest(), "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9")

        cmo_md = Path(".agents/agents/cmo/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(cmo_md.encode("utf-8")).hexdigest(), "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e")

        handoff_py = Path("schemas/handoff.py").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(handoff_py.encode("utf-8")).hexdigest(), "4075a8e269aef7526bb52c281ac88cc6fdc009d83e9aecb384032e29087e237a")


if __name__ == "__main__":
    unittest.main()
