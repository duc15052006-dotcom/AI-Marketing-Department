"""Regression proof for BUG 1: runtime provenance refs must follow grounded scope rules."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class TestWorkspaceScopeProvenanceIsolation60(unittest.TestCase):
    """Ensure legacy reference collection cannot launder foreign-scope provenance."""

    PROBE = "PROVENANCE_SCOPE_PROBE_60"

    def setUp(self) -> None:
        self.knowledge_repo = LocalKnowledgeRepository()
        self.memory_repo = LocalMemoryRepository()
        self.runtime = FiveAgentDepartmentRuntime(
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )

    def _save_doc(self, knowledge_id: str, scope: str, label: str) -> None:
        self.knowledge_repo.save_document(
            KnowledgeDocument(
                knowledge_id=knowledge_id,
                source_id=f"SRC-{knowledge_id}",
                title=f"{label} scope document",
                content=f"{self.PROBE} {label}",
                scope=scope,
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
            )
        )

    def _save_memory(self, memory_id: str, scope: str, label: str) -> None:
        self.memory_repo.save_memory(
            MemoryItem(
                memory_id=memory_id,
                memory_type=MemoryType.DECISION_MEMORY,
                agent_source="cmo",
                content=f"{self.PROBE} {label}",
                confidence=0.95,
                promotion_level=PromotionState.VERIFIED_MEMORY,
                scope=scope,
            )
        )

    def test_project_a_runtime_refs_and_sealed_artifact_exclude_project_b(self) -> None:
        # ContextCompiler's current trust boundary for this run is:
        # knowledge => GLOBAL + SCOPE_BIZ_A + SCOPE_PROJ_PROJECT_A
        # memory    => GLOBAL + SCOPE_BIZ_A
        # Project-scoped memory grounding is BUG 3 and intentionally not changed here.
        self._save_doc("KNOW-GLOBAL", "GLOBAL", "global allowed")
        self._save_doc("KNOW-BIZ-A", "SCOPE_BIZ_A", "business A allowed")
        self._save_doc("KNOW-PROJ-A", "SCOPE_PROJ_PROJECT_A", "project A allowed")
        self._save_doc("KNOW-BIZ-B", "SCOPE_BIZ_B", "business B foreign")
        self._save_doc("KNOW-PROJ-B", "SCOPE_PROJ_PROJECT_B", "project B foreign")

        self._save_memory("MEM-GLOBAL", "GLOBAL", "global allowed")
        self._save_memory("MEM-BIZ-A", "SCOPE_BIZ_A", "business A allowed")
        self._save_memory("MEM-PROJ-A", "SCOPE_PROJ_PROJECT_A", "project A deferred to BUG 3")
        self._save_memory("MEM-BIZ-B", "SCOPE_BIZ_B", "business B foreign")
        self._save_memory("MEM-PROJ-B", "SCOPE_PROJ_PROJECT_B", "project B foreign")

        ctx = self.runtime.start_run(
            objective=self.PROBE,
            business_id="BIZ_A",
            project_id="PROJECT_A",
        )

        with patch.object(
            self.runtime,
            "_call_agent_llm",
            return_value=("Deterministic CMO output for provenance isolation test.", None),
        ):
            out = self.runtime.execute_stage_cmo_initial(ctx)

        self.assertEqual(out["status"], "COMPLETED")

        citations = {
            c.citation_id: c
            for c in self.runtime.lineage_inspector.get_all_citations()
        }
        citation_ids_by_knowledge = {
            c.knowledge_id: cid for cid, c in citations.items()
        }

        allowed_knowledge = {"KNOW-GLOBAL", "KNOW-BIZ-A", "KNOW-PROJ-A"}
        foreign_knowledge = {"KNOW-BIZ-B", "KNOW-PROJ-B"}
        allowed_citation_ids = {
            citation_ids_by_knowledge[kid]
            for kid in allowed_knowledge
            if kid in citation_ids_by_knowledge
        }
        foreign_citation_ids = {
            citation_ids_by_knowledge[kid]
            for kid in foreign_knowledge
            if kid in citation_ids_by_knowledge
        }

        # Guard usefulness: all legitimate knowledge scopes must still be represented.
        self.assertEqual(len(allowed_citation_ids), 3)
        self.assertTrue(allowed_citation_ids.issubset(set(ctx.knowledge_refs)))

        # BUG 1 RED proof: foreign citations/memories must never enter audit refs.
        self.assertTrue(
            set(ctx.knowledge_refs).isdisjoint(foreign_citation_ids),
            "foreign Project/Business B knowledge citation leaked into RuntimeContext.knowledge_refs",
        )
        self.assertIn("MEM-GLOBAL", ctx.memory_refs)
        self.assertIn("MEM-BIZ-A", ctx.memory_refs)
        self.assertNotIn("MEM-PROJ-A", ctx.memory_refs)  # preserve current compiler semantics; BUG 3 is separate
        self.assertNotIn("MEM-BIZ-B", ctx.memory_refs)
        self.assertNotIn("MEM-PROJ-B", ctx.memory_refs)

        artifact = self.runtime.complete_run(ctx)
        self.assertTrue(set(artifact.knowledge_used).isdisjoint(foreign_citation_ids))
        self.assertNotIn("MEM-BIZ-B", artifact.memory_used)
        self.assertNotIn("MEM-PROJ-B", artifact.memory_used)
        self.assertEqual(set(artifact.knowledge_used), set(ctx.knowledge_refs))
        self.assertEqual(set(artifact.memory_used), set(ctx.memory_refs))


if __name__ == "__main__":
    unittest.main()
