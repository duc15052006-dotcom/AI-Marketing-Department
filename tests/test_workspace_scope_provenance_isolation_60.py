"""Regression proof for BUG 1: sealed lineage must match grounded evidence exactly."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class TestWorkspaceScopeProvenanceIsolation60(unittest.TestCase):
    PROBE = "PROVENANCE_GROUNDED_BOUNDARY_60"

    def setUp(self) -> None:
        self.knowledge_repo = LocalKnowledgeRepository()
        self.runtime = FiveAgentDepartmentRuntime(
            knowledge_repo=self.knowledge_repo,
            memory_repo=LocalMemoryRepository(),
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )

    def _save_doc(self, knowledge_id: str, title: str, content: str) -> None:
        self.knowledge_repo.save_document(
            KnowledgeDocument(
                knowledge_id=knowledge_id,
                source_id=f"SRC-{knowledge_id}",
                title=title,
                content=content,
                scope="SCOPE_BIZ_A",
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
            )
        )

    def test_builder_query_match_cannot_be_sealed_outside_grounded_package(self) -> None:
        # ContextCompiler takes the first four valid docs from this exact legacy
        # business scope. The legacy builder, however, query-matches across all
        # docs and therefore selects the fifth document. Before the production
        # fix, that fifth citation is sealed into lineage even though the model
        # never received it in GroundedContextPackage.
        grounded_ids_expected = set()
        for index in range(4):
            knowledge_id = f"KNOW-GROUNDED-{index}"
            grounded_ids_expected.add(knowledge_id)
            self._save_doc(
                knowledge_id,
                title=f"ordinary grounded document {index}",
                content=f"ordinary grounded content {index}",
            )

        self._save_doc(
            "KNOW-BUILDER-ONLY",
            title=f"exact query match {self.PROBE}",
            content=f"exact query match {self.PROBE}",
        )

        ctx = self.runtime.start_run(
            objective=self.PROBE,
            business_id="BIZ_A",
        )

        preflight_grounded = self.runtime.context_compiler.compile_grounded_package("cmo", ctx)
        preflight_grounded_ids = {
            str(item.metadata.get("knowledge_id"))
            for item in preflight_grounded.evidence_items
            if isinstance(item.metadata, dict) and item.metadata.get("knowledge_id")
        }
        self.assertEqual(preflight_grounded_ids, grounded_ids_expected)
        self.assertNotIn("KNOW-BUILDER-ONLY", preflight_grounded_ids)

        with patch.object(
            self.runtime,
            "_call_agent_llm",
            return_value=("Deterministic CMO output for grounded provenance boundary test.", None),
        ):
            out = self.runtime.execute_stage_cmo_initial(ctx)

        self.assertEqual(out["status"], "COMPLETED")

        lineage_knowledge_ids = {
            citation.knowledge_id
            for citation in self.runtime.lineage_inspector.get_all_citations()
        }

        # The sealed lineage must be exactly the persistent knowledge evidence
        # accepted by ContextCompiler: no builder-only laundering and no missing
        # grounded references.
        self.assertEqual(lineage_knowledge_ids, preflight_grounded_ids)
        self.assertNotIn("KNOW-BUILDER-ONLY", lineage_knowledge_ids)


if __name__ == "__main__":
    unittest.main()
