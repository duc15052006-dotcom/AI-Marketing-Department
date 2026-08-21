"""Memory Operator Services and Lifecycle Operations (Phase 6.1).

Enables human operators to inspect, filter, archive, retire, and approve/reject
promotions of institutional memories through the MemoryPromotionEngine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from memory.models import MemoryItem, MemoryType, PromotionState
from memory.promotion import MemoryPromotionEngine
from memory.repository import MemoryRepository

logger = logging.getLogger("memory_operations")


class MemoryOperatorService:
    """Operator service for managing institutional memory entries."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def list_memories_for_operator(
        self,
        memory_type: Optional[MemoryType] = None,
        promotion_level: Optional[PromotionState] = None,
        scope: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Return formatted summary list of memories for operator inspection."""
        all_mems = self.repository.list_memories(memory_type=memory_type)
        output = []

        for m in all_mems:
            if promotion_level and m.promotion_level != promotion_level:
                continue
            if scope and m.scope != scope and m.scope != "GLOBAL":
                continue
            if m.confidence < min_confidence:
                continue

            output.append(
                {
                    "memory_id": m.memory_id,
                    "memory_type": m.memory_type.value,
                    "agent_source": m.agent_source,
                    "promotion_level": m.promotion_level.value,
                    "confidence": m.confidence,
                    "content_preview": m.content[:120],
                    "evidence_count": len(m.evidence_refs),
                    "created_at": m.timestamp.isoformat(),
                    "review_date": m.expiry_or_review_date.isoformat() if m.expiry_or_review_date else None,
                    "is_stale": MemoryPromotionEngine.audit_memory_staleness(m),
                }
            )
        return output

    def approve_promotion(self, memory_id: str, operator_notes: str = "Operator approved") -> Optional[MemoryItem]:
        """Approve promoting a CANDIDATE_MEMORY to VERIFIED_MEMORY / PROMOTED_LEARNING."""
        mem = self.repository.get_memory(memory_id)
        if not mem:
            return None

        # Determine next target state
        if mem.promotion_level == PromotionState.CANDIDATE_MEMORY:
            target_state = PromotionState.VERIFIED_MEMORY
        elif mem.promotion_level == PromotionState.VERIFIED_MEMORY:
            target_state = PromotionState.PROMOTED_LEARNING
        else:
            return None

        success, reason = MemoryPromotionEngine.promote_memory(
            memory=mem,
            target_state=target_state,
            review_rationale=operator_notes or "Operator approved",
        )
        if success:
            mem.context["operator_approved_by"] = "operator"
            mem.context["operator_notes"] = operator_notes
            self.repository.save_memory(mem)
            return mem

        return None

    def reject_promotion(self, memory_id: str, reason: str = "Rejected by operator") -> Optional[MemoryItem]:
        """Reject promotion of a candidate memory."""
        mem = self.repository.get_memory(memory_id)
        if not mem:
            return None
        mem.context["promotion_rejected_reason"] = reason
        mem.context["promotion_rejected_at"] = datetime.now(timezone.utc).isoformat()
        self.repository.save_memory(mem)
        return mem

    def retire_memory(self, memory_id: str, reason: str = "Retire requested") -> Optional[MemoryItem]:
        """Retire a memory item permanently."""
        mem = self.repository.get_memory(memory_id)
        if not mem:
            return None
        mem.promotion_level = PromotionState.RETIRED
        mem.context["retirement_reason"] = reason
        self.repository.save_memory(mem)
        return mem
