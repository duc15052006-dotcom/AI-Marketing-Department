from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.versioned_repository import VersionedKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.scoped_repository import ScopedMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime


class RuntimeBuilderCanonicalLineageScopeV1Tests(unittest.TestCase):
    @staticmethod
    def _save_knowledge(
        repository: VersionedKnowledgeRepository,
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
                authority_score=0.95,
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
        repository: ScopedMemoryRepository,
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
                context={"query": "scope lineage"},
                evidence_refs=[f"EVIDENCE-{scope}"],
                confidence=0.95,
                promotion_level=PromotionState.VERIFIED_MEMORY,
                scope=scope,
            )
        )

    def test_cmo_builder_lineage_uses_immutable_canonical_scope_plan_not_working_state_spoof(self) -> None:
        knowledge_repo = VersionedKnowledgeRepository()
        memory_repo = ScopedMemoryRepository()

        project_a_doc = self._save_knowledge(
            knowledge_repo,
            title="project-a-canonical",
            content="scope lineage PROJECT_A_CANONICAL_KNOWLEDGE",
            scope="PROJECT:PROJ_A",
        )
        business_a_doc = self._save_knowledge(
            knowledge_repo,
            title="business-a-canonical",
            content="scope lineage BUSINESS_A_CANONICAL_KNOWLEDGE",
            scope="BUSINESS:BIZ_A",
        )
        global_doc = self._save_knowledge(
            knowledge_repo,
            title="global-canonical",
            content="scope lineage GLOBAL_CANONICAL_KNOWLEDGE",
            scope="GLOBAL",
        )
        sibling_doc = self._save_knowledge(
            knowledge_repo,
            title="project-b-canonical",
            content="scope lineage PROJECT_B_SIBLING_KNOWLEDGE",
            scope="PROJECT:PROJ_B",
        )

        project_a_memory = self._save_memory(
            memory_repo,
            content="scope lineage PROJECT_A_CANONICAL_MEMORY",
            scope="PROJECT:PROJ_A",
        )
        business_a_memory = self._save_memory(
            memory_repo,
            content="scope lineage BUSINESS_A_CANONICAL_MEMORY",
            scope="BUSINESS:BIZ_A",
        )
        global_memory = self._save_memory(
            memory_repo,
            content="scope lineage GLOBAL_CANONICAL_MEMORY",
            scope="GLOBAL",
        )
        sibling_memory = self._save_memory(
            memory_repo,
            content="scope lineage PROJECT_B_SIBLING_MEMORY",
            scope="PROJECT:PROJ_B",
        )

        runtime = FiveAgentDepartmentRuntime(
            model_gateway=object(),
            knowledge_repo=knowledge_repo,
            memory_repo=memory_repo,
        )
        runtime._call_agent_llm = lambda *args, **kwargs: ("CMO strategic framing", None)

        context = runtime.start_run(
            objective="scope lineage",
            business_id="BIZ_A",
            project_id="PROJ_A",
            campaign_id="CAMP_A",
        )

        # Prove the primary grounding path already follows immutable canonical authority.
        grounded = runtime.context_compiler.compile_grounded_package("cmo", context)
        grounded_knowledge_ids = {
            item.metadata.get("knowledge_id")
            for item in grounded.evidence_items
            if item.metadata.get("knowledge_id")
        }
        self.assertTrue(
            {project_a_doc.knowledge_id, business_a_doc.knowledge_id, global_doc.knowledge_id}
            <= grounded_knowledge_ids
        )
        self.assertNotIn(sibling_doc.knowledge_id, grounded_knowledge_ids)

        # Mutable working-state hints are not execution authority and must not redirect lineage.
        context.working_state["knowledge_scope"] = "PROJECT:PROJ_B"
        context.working_state["memory_scope"] = "PROJECT:PROJ_B"

        runtime.execute_stage_cmo_initial(context)

        lineage_knowledge_ids = {
            citation.knowledge_id for citation in runtime.lineage_inspector.get_all_citations()
        }
        self.assertTrue(
            {project_a_doc.knowledge_id, business_a_doc.knowledge_id, global_doc.knowledge_id}
            <= lineage_knowledge_ids
        )
        self.assertNotIn(sibling_doc.knowledge_id, lineage_knowledge_ids)

        self.assertTrue(
            {project_a_memory.memory_id, business_a_memory.memory_id, global_memory.memory_id}
            <= set(context.memory_refs)
        )
        self.assertNotIn(sibling_memory.memory_id, context.memory_refs)


if __name__ == "__main__":
    unittest.main()
