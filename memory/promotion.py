"""Memory Promotion Engine (Phase 5.1).

Enforces evidence-backed promotion rules for institutional memory:
Observation -> Hypothesis -> Test -> Measurement -> Analysis -> Evidence -> Promotion.
Guarantees a single model opinion or unverified claim never becomes durable learning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from memory.models import MemoryItem, PromotionState

logger = logging.getLogger("memory_promotion")


class MemoryPromotionEngine:
    """Evaluates and validates promotion transitions for memory assets."""

    @staticmethod
    def promote_memory(
        memory: MemoryItem,
        target_state: PromotionState,
        review_rationale: str = "",
        supporting_evidence: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """Attempt to promote a memory item to a higher verification tier."""
        current = memory.promotion_level

        # 1. Same state check
        if current == target_state:
            return (True, f"Memory already at promotion state {target_state.value}.")

        # 2. Cannot un-retire without explicit re-creation
        if current == PromotionState.RETIRED and target_state != PromotionState.RETIRED:
            return (False, "CANNOT_UNRETIRE: Retired memories cannot be directly promoted.")

        # 3. Transition Rules
        if target_state == PromotionState.CANDIDATE_MEMORY:
            if not memory.content or len(memory.content.strip()) < 10:
                return (False, "INSUFFICIENT_CONTENT: Memory content too brief for candidate evaluation.")
            memory.promotion_level = PromotionState.CANDIDATE_MEMORY
            return (True, "PROMOTED_TO_CANDIDATE")

        if target_state == PromotionState.VERIFIED_MEMORY:
            ev = supporting_evidence or memory.evidence_refs
            if not ev:
                return (
                    False,
                    "EVIDENCE_REQUIRED: Promotion to VERIFIED_MEMORY requires at least 1 verified evidence reference or experiment run ID.",
                )
            if memory.confidence < 0.6:
                return (
                    False,
                    f"CONFIDENCE_TOO_LOW: Verification requires confidence >= 0.60 (current: {memory.confidence:.2f}).",
                )
            memory.evidence_refs = list(set(memory.evidence_refs + ev))
            memory.promotion_level = PromotionState.VERIFIED_MEMORY
            return (True, "PROMOTED_TO_VERIFIED")

        if target_state == PromotionState.PROMOTED_LEARNING:
            if current != PromotionState.VERIFIED_MEMORY:
                return (
                    False,
                    "LIFECYCLE_VIOLATION: Memory must achieve VERIFIED_MEMORY status before becoming PROMOTED_LEARNING.",
                )
            if not memory.evidence_refs:
                return (
                    False,
                    "EVIDENCE_REQUIRED: Promoted institutional learning strictly requires verified evidence references.",
                )
            if memory.confidence < 0.80:
                return (
                    False,
                    f"CONFIDENCE_TOO_LOW: Institutional learning requires confidence >= 0.80 (current: {memory.confidence:.2f}).",
                )
            if not review_rationale:
                return (
                    False,
                    "REVIEW_RATIONALE_REQUIRED: Promoted learning requires explicit institutional review rationale.",
                )
            memory.promotion_level = PromotionState.PROMOTED_LEARNING
            memory.metadata["promoted_at"] = datetime.now(timezone.utc).isoformat()
            memory.metadata["promotion_rationale"] = review_rationale
            return (True, "PROMOTED_TO_INSTITUTIONAL_LEARNING")

        if target_state == PromotionState.RETIRED:
            memory.promotion_level = PromotionState.RETIRED
            memory.status = "ARCHIVED"
            memory.metadata["retired_at"] = datetime.now(timezone.utc).isoformat()
            memory.metadata["retirement_reason"] = review_rationale or "Superseded or stale"
            return (True, "RETIRED")

        return (False, f"UNSUPPORTED_TRANSITION: Cannot transition from {current.value} to {target_state.value}.")

    @staticmethod
    def audit_memory_staleness(memory: MemoryItem) -> bool:
        """Check if a memory item has exceeded its review/expiry threshold."""
        if not memory.expiry_or_review_date:
            return False
        return datetime.now(timezone.utc) > memory.expiry_or_review_date
