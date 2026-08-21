"""Learning Event Operator Services (Phase 6.1).

Enables operator inspection of empirical learning events, approval of verified learnings,
and scheduling of experiment retests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from memory.learning import LearningEvent, LearningRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import MemoryRepository

logger = logging.getLogger("learning_operations")


class LearningOperatorService:
    """Operator interface for reviewing empirical learning events."""

    def __init__(self, learning_repo: LearningRepository, memory_repo: MemoryRepository) -> None:
        self.learning_repo = learning_repo
        self.memory_repo = memory_repo

    def list_learnings_for_operator(
        self,
        campaign_id: Optional[str] = None,
        promotion_status: Optional[PromotionState] = None,
    ) -> List[Dict[str, Any]]:
        """List empirical learning events for operator review."""
        events = self.learning_repo.list_learnings(campaign_id=campaign_id)
        output = []

        for e in events:
            if promotion_status and e.promotion_status != promotion_status:
                continue
            output.append(
                {
                    "event_id": e.learning_event_id,
                    "campaign_id": e.campaign_id,
                    "hypothesis": e.hypothesis,
                    "primary_metric": e.primary_metric,
                    "result": e.observed_result,
                    "decision": e.decision,
                    "confidence": e.confidence,
                    "lesson": e.lesson,
                    "promotion_status": e.promotion_status.value,
                    "retest_required": e.retest_required,
                }
            )
        return output

    def approve_learning_promotion(self, event_id: str, operator_name: str = "operator") -> Optional[MemoryItem]:
        """Promote an empirical learning event into a durable institutional MemoryItem."""
        event = self.learning_repo.get_learning(event_id)
        if not event or event.confidence < 0.70:
            return None

        # Update event state
        event.promotion_status = PromotionState.PROMOTED_LEARNING
        self.learning_repo.record_learning(event)

        # Write durable memory
        mem = MemoryItem(
            memory_type=MemoryType.SUCCESS_FAILURE_MEMORY,
            agent_source="performance",
            content=f"Empirical Takeaway ({event.campaign_id}): {event.lesson}",
            context={
                "learning_event_id": event.learning_event_id,
                "hypothesis": event.hypothesis,
                "metric": event.primary_metric,
                "result": event.observed_result,
                "approved_by": operator_name,
            },
            evidence_refs=[f"EXPERIMENT:{event.experiment_id}"],
            confidence=event.confidence,
            promotion_level=PromotionState.PROMOTED_LEARNING,
        )
        return self.memory_repo.save_memory(mem)

    def schedule_retest(self, event_id: str, reason: str = "Operator requested validation") -> bool:
        """Flag a learning event as requiring retesting."""
        event = self.learning_repo.get_learning(event_id)
        if not event:
            return False
        event.retest_required = True
        self.learning_repo.record_learning(event)
        return True
