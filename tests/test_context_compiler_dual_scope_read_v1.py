from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge.file_manager import KnowledgeFileManager
from knowledge.lifecycle_models import KnowledgeScope
from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.repository import LocalKnowledgeRepository
from knowledge.versioned_repository import VersionedKnowledgeRepository
from memory.lifecycle_models import MemoryScope
from memory.manager import MemoryManager
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository
from memory.scoped_repository import ScopedMemoryRepository
from runtime.context import RuntimeContext
from runtime.context_compiler import ContextCompiler


class ContextCompilerDualScopeReadV1Tests(unittest.TestCase):
    def test_governed_canonical_project_business_and_global_are_visible_without_sibling_bleed(self) -> None:
        knowledge_repo = VersionedKnowledgeRepository()
        memory_repo = ScopedMemoryRepository()

        with tempfile.TemporaryDirectory() as tmp:
            knowledge = KnowledgeFileManager(Path(tmp), repository=knowledge_repo)
            self.assertTrue(
                knowledge.ingest_text(
                    "PROJECT_A_CANONICAL_KNOWLEDGE",
                    source_name="project-a",
                    scope=KnowledgeScope(project_id="PROJ_A"),
                    source_type=SourceType.MARKET_RESEARCH,
                    authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                ).success
            )
            self.assertTrue(
                knowledge.ingest_text(
                    "BUSINESS_A_CANONICAL_KNOWLEDGE",
                    source_name="business-a",
                    scope=KnowledgeScope(business_id="BIZ_A"),
                    source_type=SourceType.MARKET_RESEARCH,
                    authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                ).success
            )
            self.assertTrue(
                knowledge.ingest_text(
                    "GLOBAL_CANONICAL_KNOWLEDGE",
                    source_name="global",
                    scope=KnowledgeScope(),
                    source_type=SourceType.MARKET_RESEARCH,
                    authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                ).success
            )
            self.assertTrue(
                knowledge.ingest_text(
                    "PROJECT_B_FORBIDDEN_KNOWLEDGE",
                    source_name="project-b",
                    scope=KnowledgeScope(project_id="PROJ_B"),
                    source_type=SourceType.MARKET_RESEARCH,
                    authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                ).success
            )

        memory = MemoryManager(repository=memory_repo)
        for content, scope in (
            ("PROJECT_A_CANONICAL_MEMORY", MemoryScope(project_id="PROJ_A")),
            ("BUSINESS_A_CANONICAL_MEMORY", MemoryScope(business_id="BIZ_A")),
            ("GLOBAL_CANONICAL_MEMORY", MemoryScope()),
            ("PROJECT_B_FORBIDDEN_MEMORY", MemoryScope(project_id="PROJ_B")),
        ):
            result = memory.remember(
                memory_type=MemoryType.DECISION_MEMORY,
                agent_source="strategist",
                content=content,
                scope=scope,
                confidence=0.9,
                promotion_level=PromotionState.CANDIDATE_MEMORY,
            )
            self.assertTrue(result.success)

        ctx = RuntimeContext(
            objective="Compile governed project context.",
            business_id="BIZ_A",
            project_id="PROJ_A",
            campaign_id="CAMP_A",
        )
        pkg = ContextCompiler(
            knowledge_repo=knowledge_repo,
            memory_repo=memory_repo,
        ).compile_grounded_package("cmo", ctx)

        knowledge_text = "\n".join(
            item.content for item in pkg.evidence_items if item.source_type != "INSTITUTIONAL_MEMORY"
        )
        memory_text = "\n".join(
            item.content for item in pkg.evidence_items if item.source_type == "INSTITUTIONAL_MEMORY"
        )

        self.assertIn("PROJECT_A_CANONICAL_KNOWLEDGE", knowledge_text)
        self.assertIn("BUSINESS_A_CANONICAL_KNOWLEDGE", knowledge_text)
        self.assertIn("GLOBAL_CANONICAL_KNOWLEDGE", knowledge_text)
        self.assertNotIn("PROJECT_B_FORBIDDEN_KNOWLEDGE", knowledge_text)

        self.assertIn("PROJECT_A_CANONICAL_MEMORY", memory_text)
        self.assertIn("BUSINESS_A_CANONICAL_MEMORY", memory_text)
        self.assertIn("GLOBAL_CANONICAL_MEMORY", memory_text)
        self.assertNotIn("PROJECT_B_FORBIDDEN_MEMORY", memory_text)

    @staticmethod
    def _save_legacy_knowledge(repository: LocalKnowledgeRepository, *, title: str, content: str, scope: str) -> None:
        source = repository.save_source(
            KnowledgeSource(
                source_name=title,
                source_url_or_path=f"legacy://{title}",
                source_type=SourceType.MARKET_RESEARCH,
                authority_score=0.9,
            )
        )
        repository.save_document(
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
    def _save_legacy_memory(repository: LocalMemoryRepository, *, content: str, scope: str) -> None:
        repository.save_memory(
            MemoryItem(
                memory_type=MemoryType.DECISION_MEMORY,
                agent_source="strategist",
                content=content,
                confidence=0.9,
                promotion_level=PromotionState.CANDIDATE_MEMORY,
                scope=scope,
            )
        )

    def test_legacy_scope_reads_remain_compatible_during_migration(self) -> None:
        knowledge_repo = LocalKnowledgeRepository()
        memory_repo = LocalMemoryRepository()
        self._save_legacy_knowledge(
            knowledge_repo,
            title="legacy-project",
            content="LEGACY_PROJECT_KNOWLEDGE",
            scope="SCOPE_PROJ_PROJ_LEGACY",
        )
        self._save_legacy_knowledge(
            knowledge_repo,
            title="legacy-business",
            content="LEGACY_BUSINESS_KNOWLEDGE",
            scope="SCOPE_BIZ_LEGACY",
        )
        self._save_legacy_knowledge(
            knowledge_repo,
            title="legacy-global",
            content="LEGACY_GLOBAL_KNOWLEDGE",
            scope="GLOBAL",
        )
        self._save_legacy_memory(
            memory_repo,
            content="LEGACY_BUSINESS_MEMORY",
            scope="SCOPE_BIZ_LEGACY",
        )
        self._save_legacy_memory(
            memory_repo,
            content="LEGACY_GLOBAL_MEMORY",
            scope="GLOBAL",
        )

        ctx = RuntimeContext(
            objective="Compile legacy context during migration.",
            business_id="BIZ_LEGACY",
            project_id="PROJ_LEGACY",
        )
        pkg = ContextCompiler(
            knowledge_repo=knowledge_repo,
            memory_repo=memory_repo,
        ).compile_grounded_package("cmo", ctx)
        rendered = "\n".join(item.content for item in pkg.evidence_items)

        self.assertIn("LEGACY_PROJECT_KNOWLEDGE", rendered)
        self.assertIn("LEGACY_BUSINESS_KNOWLEDGE", rendered)
        self.assertIn("LEGACY_GLOBAL_KNOWLEDGE", rendered)
        self.assertIn("LEGACY_BUSINESS_MEMORY", rendered)
        self.assertIn("LEGACY_GLOBAL_MEMORY", rendered)

    def test_default_business_legacy_knowledge_remains_readable_only_as_migration_compatibility(self) -> None:
        knowledge_repo = LocalKnowledgeRepository()
        self._save_legacy_knowledge(
            knowledge_repo,
            title="legacy-default",
            content="LEGACY_DEFAULT_BUSINESS_KNOWLEDGE",
            scope="SCOPE_BIZ_DEFAULT",
        )
        ctx = RuntimeContext(
            objective="Compile default workspace context.",
            business_id="BIZ_DEFAULT",
            campaign_id="CAMP_DEFAULT",
        )

        pkg = ContextCompiler(knowledge_repo=knowledge_repo).compile_grounded_package("cmo", ctx)
        rendered = "\n".join(item.content for item in pkg.evidence_items)

        self.assertIn("LEGACY_DEFAULT_BUSINESS_KNOWLEDGE", rendered)


if __name__ == "__main__":
    unittest.main()
