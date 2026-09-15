"""Regression proof for BUG 4: bounded knowledge selection must prefer authority."""

from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class TestKnowledgeAuthorityOrdering62(unittest.TestCase):
    SCOPE = "SCOPE_BIZ_A"

    def setUp(self) -> None:
        self.knowledge_repo = LocalKnowledgeRepository()
        self.runtime = FiveAgentDepartmentRuntime(
            knowledge_repo=self.knowledge_repo,
            memory_repo=LocalMemoryRepository(),
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )

    def _save_doc(self, knowledge_id: str, authority: AuthorityLevel) -> None:
        self.knowledge_repo.save_document(
            KnowledgeDocument(
                knowledge_id=knowledge_id,
                source_id=f"SRC-{knowledge_id}",
                title=f"Authority ordering {knowledge_id}",
                content=f"Authority ordering evidence for {knowledge_id}",
                scope=self.SCOPE,
                freshness="ACTIVE",
                authority_level=authority,
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
            )
        )

    def test_tier2_displaces_tier4_at_compiler_and_builder_bounded_selection(self) -> None:
        # Adversarial insertion order: fill the four bounded slots with Tier 4 first,
        # then append a later Tier 2 document. Retrieval order must not allow lower-
        # authority evidence to crowd out higher-authority evidence merely because it
        # was stored earlier.
        tier4_ids = []
        for index in range(4):
            knowledge_id = f"KNOW-TIER4-{index}"
            tier4_ids.append(knowledge_id)
            self._save_doc(knowledge_id, AuthorityLevel.TIER_4_UNVERIFIED_OBSERVATION)

        tier2_id = "KNOW-TIER2-VERIFIED"
        self._save_doc(tier2_id, AuthorityLevel.TIER_2_VERIFIED_RESEARCH)

        ctx = self.runtime.start_run(
            objective="Compare evidence authority under bounded retrieval",
            business_id="BIZ_A",
        )

        grounded = self.runtime.context_compiler.compile_grounded_package("cmo", ctx)
        grounded_ids = [
            str(item.metadata.get("knowledge_id"))
            for item in grounded.evidence_items
            if isinstance(item.metadata, dict) and item.metadata.get("knowledge_id")
        ]

        self.assertEqual(len(grounded_ids), 4)
        self.assertIn(
            tier2_id,
            grounded_ids,
            "Tier 2 verified research was crowded out by earlier Tier 4 documents in ContextCompiler",
        )
        self.assertLess(
            len(set(tier4_ids).intersection(grounded_ids)),
            4,
            "all four Tier 4 documents occupied the bounded compiler selection ahead of Tier 2",
        )

        builder = self.runtime.knowledge_builder.build_context_for_agent(
            "cmo",
            scope=self.SCOPE,
        )
        builder_ids = [doc.knowledge_id for doc in builder.documents]

        self.assertEqual(len(builder_ids), 4)
        self.assertIn(
            tier2_id,
            builder_ids,
            "Tier 2 verified research was crowded out by earlier Tier 4 documents in KnowledgeContextBuilder",
        )
        self.assertLess(
            len(set(tier4_ids).intersection(builder_ids)),
            4,
            "all four Tier 4 documents occupied the bounded builder selection ahead of Tier 2",
        )


if __name__ == "__main__":
    unittest.main()
