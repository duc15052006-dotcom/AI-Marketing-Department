from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.versioned_repository import VersionedKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.scoped_repository import ScopedMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime


class RuntimeTrustedLegacyScopeAuthorityV1Tests(unittest.TestCase):
    @staticmethod
    def _save_knowledge(repository, *, title: str, content: str, scope: str) -> KnowledgeDocument:
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
    def _save_memory(repository, *, content: str, scope: str) -> MemoryItem:
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

    def test_trusted_legacy_scope_alias_is_immutable_and_working_state_spoof_cannot_redirect(self) -> None:
        knowledge_repo = VersionedKnowledgeRepository()
        memory_repo = ScopedMemoryRepository()

        trusted_doc = self._save_knowledge(
            knowledge_repo,
            title="trusted-legacy-scope",
            content="scope lineage TRUSTED_LEGACY_KNOWLEDGE",
            scope="SCOPE_PILOT_CARDIO",
        )
        spoof_doc = self._save_knowledge(
            knowledge_repo,
            title="spoof-legacy-scope",
            content="scope lineage SPOOFED_LEGACY_KNOWLEDGE",
            scope="SCOPE_ATTACKER",
        )
        trusted_memory = self._save_memory(
            memory_repo,
            content="scope lineage TRUSTED_LEGACY_MEMORY",
            scope="SCOPE_PILOT_CARDIO",
        )
        spoof_memory = self._save_memory(
            memory_repo,
            content="scope lineage SPOOFED_LEGACY_MEMORY",
            scope="SCOPE_ATTACKER",
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
            campaign_id="CAMP_A",
            trusted_knowledge_scope="SCOPE_PILOT_CARDIO",
            trusted_memory_scope="SCOPE_PILOT_CARDIO",
        )

        with self.assertRaises(AttributeError):
            context.trusted_knowledge_scope = "SCOPE_ATTACKER"
        with self.assertRaises(AttributeError):
            context.trusted_memory_scope = "SCOPE_ATTACKER"

        context.working_state["knowledge_scope"] = "SCOPE_ATTACKER"
        context.working_state["memory_scope"] = "SCOPE_ATTACKER"

        runtime.execute_stage_cmo_initial(context)

        lineage_knowledge_ids = {
            citation.knowledge_id for citation in runtime.lineage_inspector.get_all_citations()
        }
        self.assertIn(trusted_doc.knowledge_id, lineage_knowledge_ids)
        self.assertNotIn(spoof_doc.knowledge_id, lineage_knowledge_ids)
        self.assertIn(trusted_memory.memory_id, context.memory_refs)
        self.assertNotIn(spoof_memory.memory_id, context.memory_refs)


if __name__ == "__main__":
    unittest.main()
