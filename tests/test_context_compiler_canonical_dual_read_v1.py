from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository
from memory.scoped_repository import ScopedMemoryRepository
from runtime.context import RuntimeContext
from runtime.context_compiler import ContextCompiler


class TrackingKnowledgeRepository(LocalKnowledgeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.requested_scopes = []

    def list_documents(
        self,
        scope=None,
        tags=None,
        authority_level=None,
        source_type=None,
    ):
        if scope is None:
            raise AssertionError("ContextCompiler must never issue an unscoped knowledge read")
        self.requested_scopes.append(scope)
        return super().list_documents(
            scope=scope,
            tags=tags,
            authority_level=authority_level,
            source_type=source_type,
        )


class TrackingLegacyMemoryRepository(LocalMemoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.legacy_list_calls = 0

    def list_memories(
        self,
        memory_type=None,
        agent_source=None,
        run_id=None,
        promotion_level=None,
    ):
        self.legacy_list_calls += 1
        return super().list_memories(
            memory_type=memory_type,
            agent_source=agent_source,
            run_id=run_id,
            promotion_level=promotion_level,
        )


class ExplodingScopedMemoryRepository(ScopedMemoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.unscoped_calls = 0

    def list_memories(
        self,
        memory_type=None,
        agent_source=None,
        run_id=None,
        promotion_level=None,
        *,
        scope=None,
        include_inactive=False,
    ):
        if scope is None:
            self.unscoped_calls += 1
            return super().list_memories(
                memory_type=memory_type,
                agent_source=agent_source,
                run_id=run_id,
                promotion_level=promotion_level,
                scope=scope,
                include_inactive=include_inactive,
            )
        raise TypeError("SCOPED_REPOSITORY_INTERNAL_TYPE_ERROR")


def _knowledge(scope: str, marker: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        source_id=f"SRC-{marker}",
        title=f"Knowledge {marker}",
        source_type=SourceType.BRAND_GUIDELINE,
        content=f"content-{marker}",
        authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
        scope=scope,
    )


def _memory(scope: str, marker: str) -> MemoryItem:
    return MemoryItem(
        memory_id=f"MEM-{marker}",
        memory_type=MemoryType.DECISION_MEMORY,
        agent_source="cmo",
        run_id="RUN-SCOPE-TEST",
        content=f"memory-{marker}",
        confidence=0.9,
        promotion_level=PromotionState.VERIFIED_MEMORY,
        scope=scope,
    )


class ContextCompilerCanonicalDualReadV1Tests(unittest.TestCase):
    def test_project_business_global_and_exact_legacy_aliases_are_read_in_authority_order(self) -> None:
        knowledge_repo = TrackingKnowledgeRepository()
        memory_repo = TrackingLegacyMemoryRepository()

        expected_scopes = [
            "PROJECT:PROJ_ALPHA",
            "SCOPE_PROJ_PROJ_ALPHA",
            "BUSINESS:BIZ_ALPHA",
            "SCOPE_BIZ_ALPHA",
            "GLOBAL",
        ]
        for index, scope in enumerate(expected_scopes):
            knowledge_repo.save_document(_knowledge(scope, f"K{index}"))
            memory_repo.save_memory(_memory(scope, f"M{index}"))

        knowledge_repo.save_document(_knowledge("PROJECT:PROJ_BETA", "FOREIGN-K"))
        memory_repo.save_memory(_memory("BUSINESS:BIZ_BETA", "FOREIGN-M"))

        context = RuntimeContext(
            run_id="RUN-SCOPE-TEST",
            objective="compile exact governed context",
            business_id="BIZ_ALPHA",
            project_id="PROJ_ALPHA",
        )
        context.working_state["knowledge_scope"] = "PROJECT:PROJ_BETA"
        context.working_state["memory_scope"] = "BUSINESS:BIZ_BETA"

        package = ContextCompiler(
            knowledge_repo=knowledge_repo,
            memory_repo=memory_repo,
        ).compile_grounded_package("cmo", context)

        self.assertEqual(knowledge_repo.requested_scopes, expected_scopes)
        self.assertEqual(package.diagnostics["knowledge_read_scopes"], expected_scopes)
        self.assertEqual(package.diagnostics["memory_read_scopes"], expected_scopes)
        self.assertEqual(
            package.diagnostics["canonical_knowledge_scopes"],
            ["PROJECT:PROJ_ALPHA", "BUSINESS:BIZ_ALPHA"],
        )
        self.assertEqual(
            package.diagnostics["canonical_memory_scopes"],
            ["PROJECT:PROJ_ALPHA", "BUSINESS:BIZ_ALPHA"],
        )

        knowledge_scopes_seen = [
            item.scope
            for item in package.evidence_items
            if item.source_type == SourceType.BRAND_GUIDELINE.value
        ]
        memory_scopes_seen = [
            item.scope
            for item in package.evidence_items
            if item.source_type == "INSTITUTIONAL_MEMORY"
        ]
        self.assertEqual(knowledge_scopes_seen, expected_scopes)
        self.assertEqual(memory_scopes_seen, expected_scopes)
        self.assertNotIn("PROJECT:PROJ_BETA", knowledge_scopes_seen)
        self.assertNotIn("BUSINESS:BIZ_BETA", memory_scopes_seen)
        self.assertGreaterEqual(memory_repo.legacy_list_calls, len(expected_scopes))

    def test_default_workspace_reads_global_then_only_its_historical_default_alias(self) -> None:
        knowledge_repo = TrackingKnowledgeRepository()
        memory_repo = TrackingLegacyMemoryRepository()
        knowledge_repo.save_document(_knowledge("GLOBAL", "GLOBAL"))
        knowledge_repo.save_document(_knowledge("SCOPE_BIZ_DEFAULT", "DEFAULT"))
        knowledge_repo.save_document(_knowledge("SCOPE_BIZ_OTHER", "FOREIGN"))
        memory_repo.save_memory(_memory("GLOBAL", "GLOBAL"))
        memory_repo.save_memory(_memory("SCOPE_BIZ_DEFAULT", "DEFAULT"))
        memory_repo.save_memory(_memory("SCOPE_BIZ_OTHER", "FOREIGN"))

        context = RuntimeContext(
            objective="default workspace",
            business_id="BIZ_DEFAULT",
        )
        package = ContextCompiler(
            knowledge_repo=knowledge_repo,
            memory_repo=memory_repo,
        ).compile_grounded_package("cmo", context)

        self.assertEqual(knowledge_repo.requested_scopes, ["GLOBAL", "SCOPE_BIZ_DEFAULT"])
        self.assertEqual(package.diagnostics["knowledge_read_scopes"], ["GLOBAL", "SCOPE_BIZ_DEFAULT"])
        self.assertEqual(package.diagnostics["memory_read_scopes"], ["GLOBAL", "SCOPE_BIZ_DEFAULT"])
        self.assertNotIn(
            "SCOPE_BIZ_OTHER",
            [item.scope for item in package.evidence_items],
        )

    def test_invalid_authoritative_scope_fails_before_repository_reads(self) -> None:
        knowledge_repo = TrackingKnowledgeRepository()
        memory_repo = TrackingLegacyMemoryRepository()
        context = RuntimeContext(
            objective="reject malformed authority",
            business_id="BIZ_A|BUSINESS:BIZ_B",
        )

        with self.assertRaises(ValueError):
            ContextCompiler(
                knowledge_repo=knowledge_repo,
                memory_repo=memory_repo,
            ).compile_grounded_package("cmo", context)

        self.assertEqual(knowledge_repo.requested_scopes, [])
        self.assertEqual(memory_repo.legacy_list_calls, 0)

    def test_scoped_repository_internal_type_error_is_not_downgraded_to_legacy_read(self) -> None:
        knowledge_repo = TrackingKnowledgeRepository()
        memory_repo = ExplodingScopedMemoryRepository()
        context = RuntimeContext(
            objective="propagate repository failure",
            business_id="BIZ_ALPHA",
        )

        with self.assertRaisesRegex(TypeError, "SCOPED_REPOSITORY_INTERNAL_TYPE_ERROR"):
            ContextCompiler(
                knowledge_repo=knowledge_repo,
                memory_repo=memory_repo,
            ).compile_grounded_package("cmo", context)

        self.assertEqual(memory_repo.unscoped_calls, 0)


if __name__ == "__main__":
    unittest.main()
