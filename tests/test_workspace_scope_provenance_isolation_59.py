import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository
from runtime.knowledge_builder import KnowledgeContextBuilder
from runtime.memory_builder import MemoryContextBuilder


class WorkspaceScopeProvenanceIsolationTests(unittest.TestCase):
    def test_unscoped_knowledge_builder_fails_closed_to_global(self):
        repo = LocalKnowledgeRepository()
        for knowledge_id, scope in (
            ("KNOW-GLOBAL", "GLOBAL"),
            ("KNOW-LOCAL", "SCOPE_BIZ_LOCAL"),
            ("KNOW-FOREIGN", "SCOPE_BIZ_FOREIGN"),
        ):
            repo.save_document(
                KnowledgeDocument(
                    knowledge_id=knowledge_id,
                    source_id=f"SRC-{knowledge_id}",
                    title=f"{scope} market research",
                    source_type=SourceType.MARKET_RESEARCH,
                    content=f"trusted content for {scope}",
                    authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                    scope=scope,
                )
            )

        result = KnowledgeContextBuilder(repo).build_context_for_agent("intelligence")
        retrieved_ids = {doc.knowledge_id for doc in result.documents}

        self.assertEqual(retrieved_ids, {"KNOW-GLOBAL"})
        self.assertNotIn("KNOW-FOREIGN", retrieved_ids)

    def test_unscoped_memory_builder_fails_closed_to_global(self):
        repo = LocalMemoryRepository()
        for memory_id, scope in (
            ("MEM-GLOBAL", "GLOBAL"),
            ("MEM-LOCAL", "SCOPE_BIZ_LOCAL"),
            ("MEM-FOREIGN", "SCOPE_BIZ_FOREIGN"),
        ):
            repo.save_memory(
                MemoryItem(
                    memory_id=memory_id,
                    memory_type=MemoryType.EPISODIC_MEMORY,
                    agent_source="intelligence",
                    run_id="RUN-SCOPE-TEST",
                    content=f"validated learning for {scope}",
                    confidence=0.95,
                    promotion_level=PromotionState.VERIFIED_MEMORY,
                    scope=scope,
                )
            )

        result = MemoryContextBuilder(repo).build_context_for_agent("intelligence")
        retrieved_ids = {memory.memory_id for memory in result.memories}

        self.assertEqual(retrieved_ids, {"MEM-GLOBAL"})
        self.assertNotIn("MEM-FOREIGN", retrieved_ids)


if __name__ == "__main__":
    unittest.main()
