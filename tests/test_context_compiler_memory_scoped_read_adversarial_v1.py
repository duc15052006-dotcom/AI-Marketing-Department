from __future__ import annotations

import unittest
from typing import List, Optional

from knowledge.versioned_repository import VersionedKnowledgeRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import MemoryRepository
from runtime.context import RuntimeContext
from runtime.context_compiler import ContextCompiler


class _FailOnUnscopedMemoryRepository(MemoryRepository):
    """Spy repository that makes a broad tenant read executable evidence."""

    def __init__(self) -> None:
        self.requested_scopes: List[str] = []

    def save_memory(self, memory: MemoryItem) -> MemoryItem:
        return memory

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        return None

    def list_memories(
        self,
        memory_type: Optional[MemoryType] = None,
        agent_source: Optional[str] = None,
        run_id: Optional[str] = None,
        promotion_level: Optional[PromotionState] = None,
        *,
        scope: Optional[str] = None,
    ) -> List[MemoryItem]:
        if scope is None:
            raise AssertionError(
                "ContextCompiler must not materialize Memory across all scopes before caller filtering"
            )
        self.requested_scopes.append(scope)
        return []

    def query_memories(
        self,
        query: str,
        memory_types: Optional[List[MemoryType]] = None,
        *,
        scope: Optional[str] = None,
    ) -> List[MemoryItem]:
        return []


class ContextCompilerMemoryScopedReadAdversarialV1Tests(unittest.TestCase):
    def test_private_context_reads_only_exact_authorized_memory_scopes(self) -> None:
        memory_repo = _FailOnUnscopedMemoryRepository()
        ctx = RuntimeContext(
            objective="Compile private tenant context without broad Memory reads.",
            business_id="BIZ_A",
            project_id="PROJ_A",
            campaign_id="CAMP_A",
        )

        ContextCompiler(
            knowledge_repo=VersionedKnowledgeRepository(),
            memory_repo=memory_repo,
        ).compile_grounded_package("cmo", ctx)

        self.assertEqual(
            memory_repo.requested_scopes,
            [
                "PROJECT:PROJ_A",
                "BUSINESS:BIZ_A",
                "SCOPE_BIZ_A",
                "GLOBAL",
            ],
        )


if __name__ == "__main__":
    unittest.main()
