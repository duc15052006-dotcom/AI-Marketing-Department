"""Defensive-copy, scope-aware memory repository."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from memory.lifecycle_models import MemoryLifecycleState
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import MemoryRepository


_INACTIVE_STATUS = {
    MemoryLifecycleState.ARCHIVED.value,
    MemoryLifecycleState.DISPROVEN.value,
    MemoryLifecycleState.RETIRED.value,
    MemoryLifecycleState.SUPERSEDED.value,
    MemoryLifecycleState.EXPIRED.value,
}


class ScopedMemoryRepository(MemoryRepository):
    """In-memory repository that prevents reference mutation and supports strict scopes."""

    def __init__(self) -> None:
        self._memories: Dict[str, MemoryItem] = {}

    @staticmethod
    def _clone(value):
        return copy.deepcopy(value)

    @staticmethod
    def _is_active(memory: MemoryItem, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if str(memory.status).upper() in _INACTIVE_STATUS:
            return False
        if memory.promotion_level == PromotionState.RETIRED:
            return False
        if memory.expiry_or_review_date is not None and now > memory.expiry_or_review_date:
            return False
        return True

    def save_memory(self, memory: MemoryItem) -> MemoryItem:
        stored = self._clone(memory)
        self._memories[stored.memory_id] = stored
        return self._clone(stored)

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        memory = self._memories.get(memory_id)
        return self._clone(memory) if memory is not None else None

    def list_memories(
        self,
        memory_type: Optional[MemoryType] = None,
        agent_source: Optional[str] = None,
        run_id: Optional[str] = None,
        promotion_level: Optional[PromotionState] = None,
        *,
        scope: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[MemoryItem]:
        results = [self._clone(memory) for memory in self._memories.values()]
        if not include_inactive:
            results = [memory for memory in results if self._is_active(memory)]
        if memory_type is not None:
            results = [memory for memory in results if memory.memory_type == memory_type]
        if agent_source:
            results = [memory for memory in results if memory.agent_source.lower() == agent_source.lower()]
        if run_id:
            results = [memory for memory in results if memory.run_id == run_id]
        if promotion_level is not None:
            results = [memory for memory in results if memory.promotion_level == promotion_level]
        if scope is not None:
            results = [memory for memory in results if memory.scope == scope]
        return results

    def query_memories(
        self,
        query: str,
        memory_types: Optional[List[MemoryType]] = None,
        *,
        scope: Optional[str] = None,
        min_confidence: float = 0.0,
        promotion_levels: Optional[List[PromotionState]] = None,
        include_inactive: bool = False,
    ) -> List[MemoryItem]:
        needle = (query or "").strip().lower()
        results = self.list_memories(scope=scope, include_inactive=include_inactive)
        if memory_types:
            results = [memory for memory in results if memory.memory_type in memory_types]
        if promotion_levels:
            results = [memory for memory in results if memory.promotion_level in promotion_levels]
        results = [memory for memory in results if memory.confidence >= min_confidence]
        if not needle:
            return results
        return [
            memory
            for memory in results
            if needle in memory.content.lower()
            or any(needle in str(value).lower() for value in memory.context.values())
        ]

    def mark_state(
        self,
        memory_id: str,
        state: MemoryLifecycleState,
        *,
        reason: str = "",
        changed_by: str = "system",
    ) -> Optional[MemoryItem]:
        memory = self.get_memory(memory_id)
        if memory is None:
            return None
        memory.status = state.value
        memory.metadata["lifecycle_state"] = state.value
        memory.metadata["lifecycle_changed_at"] = datetime.now(timezone.utc).isoformat()
        memory.metadata["lifecycle_changed_by"] = changed_by
        if reason:
            memory.metadata["lifecycle_reason"] = reason
        if state == MemoryLifecycleState.RETIRED:
            memory.promotion_level = PromotionState.RETIRED
        return self.save_memory(memory)

    def purge_expired_working_memories(self) -> int:
        """Compatibility method: expire rather than hard-delete for auditability."""
        now = datetime.now(timezone.utc)
        changed = 0
        for memory in list(self._memories.values()):
            if (
                memory.memory_type == MemoryType.WORKING_MEMORY
                and memory.expiry_or_review_date is not None
                and now > memory.expiry_or_review_date
                and str(memory.status).upper() not in _INACTIVE_STATUS
            ):
                self.mark_state(
                    memory.memory_id,
                    MemoryLifecycleState.EXPIRED,
                    reason="Working-memory retention window elapsed",
                    changed_by="retention_policy",
                )
                changed += 1
        return changed
