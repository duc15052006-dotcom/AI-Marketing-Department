"""Memory Repository and Querying Layer (Phase 5.1).

Provides provider-neutral storage, isolation, and querying across all 6 memory types:
WORKING_MEMORY, EPISODIC_MEMORY, DECISION_MEMORY, EXPERIMENT_MEMORY,
SUCCESS_FAILURE_MEMORY, and USER_BRAND_PREFERENCE_MEMORY.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from memory.models import MemoryItem, MemoryType, PromotionState


class MemoryRepository(abc.ABC):
    """Abstract interface for memory persistence and retrieval."""

    @abc.abstractmethod
    def save_memory(self, memory: MemoryItem) -> MemoryItem:
        pass

    @abc.abstractmethod
    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        pass

    @abc.abstractmethod
    def list_memories(
        self,
        memory_type: Optional[MemoryType] = None,
        agent_source: Optional[str] = None,
        run_id: Optional[str] = None,
        promotion_level: Optional[PromotionState] = None,
    ) -> List[MemoryItem]:
        pass

    @abc.abstractmethod
    def query_memories(self, query: str, memory_types: Optional[List[MemoryType]] = None) -> List[MemoryItem]:
        pass


class LocalMemoryRepository(MemoryRepository):
    """In-memory and local repository implementing isolated memory type partitions."""

    def __init__(self) -> None:
        self._memories: Dict[str, MemoryItem] = {}

    def save_memory(self, memory: MemoryItem) -> MemoryItem:
        self._memories[memory.memory_id] = memory
        return memory

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        return self._memories.get(memory_id)

    def list_memories(
        self,
        memory_type: Optional[MemoryType] = None,
        agent_source: Optional[str] = None,
        run_id: Optional[str] = None,
        promotion_level: Optional[PromotionState] = None,
    ) -> List[MemoryItem]:
        results = list(self._memories.values())
        if memory_type:
            results = [m for m in results if m.memory_type == memory_type]
        if agent_source:
            results = [m for m in results if m.agent_source.lower() == agent_source.lower()]
        if run_id:
            results = [m for m in results if m.run_id == run_id]
        if promotion_level:
            results = [m for m in results if m.promotion_level == promotion_level]
        return results

    def query_memories(self, query: str, memory_types: Optional[List[MemoryType]] = None) -> List[MemoryItem]:
        q_lower = query.lower()
        results = list(self._memories.values())
        if memory_types:
            results = [m for m in results if m.memory_type in memory_types]
        matched = []
        for m in results:
            if q_lower in m.content.lower() or any(q_lower in str(v).lower() for v in m.context.values()):
                matched.append(m)
        return matched

    def purge_expired_working_memories(self) -> int:
        """Purge temporary working memories that have exceeded their lifespan."""
        now = datetime.now(timezone.utc)
        to_delete = []
        for mid, m in self._memories.items():
            if m.memory_type == MemoryType.WORKING_MEMORY and m.expiry_or_review_date and now > m.expiry_or_review_date:
                to_delete.append(mid)
        for mid in to_delete:
            del self._memories[mid]
        return len(to_delete)
