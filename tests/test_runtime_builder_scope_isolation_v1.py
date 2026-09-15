from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository
from runtime.knowledge_builder import KnowledgeContextBuilder
from runtime.memory_builder import MemoryContextBuilder


class RuntimeBuilderScopeIsolationV1Tests(unittest.TestCase):
    @staticmethod
    def _save_knowledge(
        repository: LocalKnowledgeRepository,
        *,
        title: str,
        content: str,
        scope: str,
    ) -> KnowledgeDocument:
        source = repository.save_source(
            KnowledgeSource(
                source_name=title,
                source_url_or_path=f"manual://{title}",
                source_type=SourceType.MARKET_RESEARCH,
                authority_score=0.9,
            )
        )
        return repository.save_document(
            KnowledgeDocument(
                source_id=source.source_id,
                title=title,
                source_type=SourceType.MARKET_RESEARCH,
                content=content,
                authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                scope=scope,
            )
        )

    @staticmethod
    def _save_memory(
        repository: LocalMemoryRepository,
        *,
        content: str,
        scope: str,
    ) -> MemoryItem:
        return repository.save_memory(
            MemoryItem(
                memory_type=MemoryType.EPISODIC_MEMORY,
                agent_source="intelligence",
                run_id=f"RUN-{scope}",
                content=content,
                evidence_refs=[f"EVIDENCE-{scope}"],
                confidence=0.9,
                promotion_level=PromotionState.VERIFIED_MEMORY,
                scope=scope,
            )
        )

    def test_unscoped_knowledge_builder_reads_global_only_not_all_projects(self) -> None:
        repository = LocalKnowledgeRepository()
        global_doc = self._save_knowledge(
            repository,
            title="global-shared",
            content="shared market observation global",
            scope="GLOBAL",
        )
        foreign_doc = self._save_knowledge(
            repository,
            title="project-b-shared",
            content="shared market observation private project b",
            scope="SCOPE_PROJ_B",
        )

        result = KnowledgeContextBuilder(repository).build_context_for_agent(
            "cmo",
            query_text="shared",
        )

        ids = {doc.knowledge_id for doc in result.documents}
        citation_ids = {citation.knowledge_id for citation in result.citations}
        self.assertEqual(ids, {global_doc.knowledge_id})
        self.assertEqual(citation_ids, {global_doc.knowledge_id})
        self.assertNotIn(foreign_doc.knowledge_id, ids)
        self.assertNotIn(foreign_doc.knowledge_id, citation_ids)

    def test_explicit_knowledge_scope_is_exact(self) -> None:
        repository = LocalKnowledgeRepository()
        project_a = self._save_knowledge(
            repository,
            title="project-a-shared",
            content="shared customer insight project a",
            scope="SCOPE_PROJ_A",
        )
        project_b = self._save_knowledge(
            repository,
            title="project-b-shared",
            content="shared customer insight project b",
            scope="SCOPE_PROJ_B",
        )

        result = KnowledgeContextBuilder(repository).build_context_for_agent(
            "cmo",
            query_text="shared",
            scope="SCOPE_PROJ_A",
        )

        ids = {doc.knowledge_id for doc in result.documents}
        self.assertEqual(ids, {project_a.knowledge_id})
        self.assertNotIn(project_b.knowledge_id, ids)

    def test_unscoped_memory_builder_reads_global_only_not_all_projects(self) -> None:
        repository = LocalMemoryRepository()
        global_memory = self._save_memory(
            repository,
            content="shared campaign lesson global",
            scope="GLOBAL",
        )
        foreign_memory = self._save_memory(
            repository,
            content="shared campaign lesson private project b",
            scope="SCOPE_PROJ_B",
        )

        result = MemoryContextBuilder(repository).build_context_for_agent(
            "cmo",
            query_text="shared",
        )

        ids = {memory.memory_id for memory in result.memories}
        self.assertEqual(ids, {global_memory.memory_id})
        self.assertNotIn(foreign_memory.memory_id, ids)

    def test_explicit_memory_scope_is_exact(self) -> None:
        repository = LocalMemoryRepository()
        project_a = self._save_memory(
            repository,
            content="shared experiment lesson project a",
            scope="SCOPE_PROJ_A",
        )
        project_b = self._save_memory(
            repository,
            content="shared experiment lesson project b",
            scope="SCOPE_PROJ_B",
        )

        result = MemoryContextBuilder(repository).build_context_for_agent(
            "cmo",
            query_text="shared",
            scope="SCOPE_PROJ_A",
        )

        ids = {memory.memory_id for memory in result.memories}
        self.assertEqual(ids, {project_a.memory_id})
        self.assertNotIn(project_b.memory_id, ids)

    def test_blank_scope_is_global_not_wildcard(self) -> None:
        knowledge_repository = LocalKnowledgeRepository()
        global_doc = self._save_knowledge(
            knowledge_repository,
            title="global-blank-scope",
            content="blank scope guard",
            scope="GLOBAL",
        )
        self._save_knowledge(
            knowledge_repository,
            title="foreign-blank-scope",
            content="blank scope guard foreign",
            scope="SCOPE_PROJ_FOREIGN",
        )
        knowledge_result = KnowledgeContextBuilder(knowledge_repository).build_context_for_agent(
            "cmo",
            query_text="blank scope guard",
            scope="   ",
        )
        self.assertEqual(
            {doc.knowledge_id for doc in knowledge_result.documents},
            {global_doc.knowledge_id},
        )

        memory_repository = LocalMemoryRepository()
        global_memory = self._save_memory(
            memory_repository,
            content="blank scope memory guard",
            scope="GLOBAL",
        )
        self._save_memory(
            memory_repository,
            content="blank scope memory guard foreign",
            scope="SCOPE_PROJ_FOREIGN",
        )
        memory_result = MemoryContextBuilder(memory_repository).build_context_for_agent(
            "cmo",
            query_text="blank scope memory guard",
            scope="   ",
        )
        self.assertEqual(
            {memory.memory_id for memory in memory_result.memories},
            {global_memory.memory_id},
        )


if __name__ == "__main__":
    unittest.main()
