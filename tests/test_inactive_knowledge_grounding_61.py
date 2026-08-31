"""Regression proof for BUG 2: inactive knowledge must never enter model grounding."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from knowledge.lifecycle_models import KnowledgeLifecycleState
from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class TestInactiveKnowledgeGrounding61(unittest.TestCase):
    PROBE = "INACTIVE_KNOWLEDGE_GROUNDING_61"

    def setUp(self) -> None:
        self.knowledge_repo = LocalKnowledgeRepository()
        self.runtime = FiveAgentDepartmentRuntime(
            knowledge_repo=self.knowledge_repo,
            memory_repo=LocalMemoryRepository(),
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )

    def _save_doc(self, knowledge_id: str, freshness: str) -> None:
        self.knowledge_repo.save_document(
            KnowledgeDocument(
                knowledge_id=knowledge_id,
                source_id=f"SRC-{knowledge_id}",
                title=f"{self.PROBE} {knowledge_id}",
                content=f"{self.PROBE} lifecycle={freshness}",
                scope="SCOPE_BIZ_A",
                freshness=freshness,
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
            )
        )

    def test_superseded_and_deleted_never_enter_grounding_or_lineage(self) -> None:
        # ACTIVE/FRESH are current/legacy active states. STALE remains deliberately
        # retrievable in VersionedKnowledgeRepository, so this regression must not
        # over-tighten that compatibility contract. RETIRED, SUPERSEDED and DELETED
        # are inactive lifecycle states and must never reach the model boundary.
        self._save_doc("KNOW-ACTIVE", KnowledgeLifecycleState.ACTIVE.value)
        self._save_doc("KNOW-FRESH", "FRESH")
        self._save_doc("KNOW-STALE", KnowledgeLifecycleState.STALE.value)
        self._save_doc("KNOW-SUPERSEDED", KnowledgeLifecycleState.SUPERSEDED.value)
        self._save_doc("KNOW-DELETED", KnowledgeLifecycleState.DELETED.value)
        self._save_doc("KNOW-RETIRED", KnowledgeLifecycleState.RETIRED.value)

        ctx = self.runtime.start_run(
            objective=self.PROBE,
            business_id="BIZ_A",
        )

        grounded = self.runtime.context_compiler.compile_grounded_package("cmo", ctx)
        grounded_ids = {
            str(item.metadata.get("knowledge_id"))
            for item in grounded.evidence_items
            if isinstance(item.metadata, dict) and item.metadata.get("knowledge_id")
        }

        expected_allowed = {"KNOW-ACTIVE", "KNOW-FRESH", "KNOW-STALE"}
        forbidden = {"KNOW-SUPERSEDED", "KNOW-DELETED", "KNOW-RETIRED"}

        self.assertTrue(expected_allowed.issubset(grounded_ids))
        self.assertTrue(
            grounded_ids.isdisjoint(forbidden),
            f"inactive knowledge reached GroundedContextPackage: {sorted(grounded_ids & forbidden)}",
        )

        with patch.object(
            self.runtime,
            "_call_agent_llm",
            return_value=("Deterministic CMO output for lifecycle grounding test.", None),
        ):
            out = self.runtime.execute_stage_cmo_initial(ctx)

        self.assertEqual(out["status"], "COMPLETED")
        lineage_ids = {
            citation.knowledge_id
            for citation in self.runtime.lineage_inspector.get_all_citations()
        }
        self.assertTrue(expected_allowed.issubset(lineage_ids))
        self.assertTrue(
            lineage_ids.isdisjoint(forbidden),
            f"inactive knowledge was sealed into lineage: {sorted(lineage_ids & forbidden)}",
        )


if __name__ == "__main__":
    unittest.main()
