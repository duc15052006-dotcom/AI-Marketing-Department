"""Learning Event Architecture (Phase 5.1).

Defines structured LearningEvents supporting the iterative growth loop:
Observe -> Research -> Hypothesis -> Create -> Test -> Measure -> Analyze -> Learn -> Retest.
Guarantees learnings modify Memory/Knowledge and never autonomously alter agent DNA.
"""

from __future__ import annotations

import abc
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from memory.models import PromotionState
from schemas.base import BaseModel, Field


class LearningEvent(BaseModel):
    """Structured artifact capturing verified learnings from marketing experiments and campaigns."""
    learning_event_id: str = Field(default_factory=lambda: f"LRN-{uuid.uuid4().hex[:10].upper()}")
    campaign_id: str = Field(..., description="Associated campaign or product initiative ID")
    hypothesis: str = Field(..., description="Original testable hypothesis tested")
    experiment_id: str = Field(..., description="ID of the experiment execution")
    baseline: Dict[str, Any] = Field(default_factory=dict, description="Control / baseline setup and performance")
    treatment: Dict[str, Any] = Field(default_factory=dict, description="Experimental treatment / variant setup")
    primary_metric: str = Field(..., description="North star or primary evaluation KPI (e.g. 'cac', 'cvr_step_1')")
    secondary_metrics: Dict[str, Any] = Field(default_factory=dict, description="Guardrail and secondary metric results")
    observed_result: Dict[str, Any] = Field(default_factory=dict, description="Quantitative Delta and Statistical Significance")
    sample_or_evidence: Dict[str, Any] = Field(default_factory=dict, description="Sample size, traffic volume, telemetry receipts")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Statistical confidence (1 - p_value)")
    decision: str = Field(..., description="SCALE | ITERATE | REVERT | DEPRECATE | HOLD")
    lesson: str = Field(..., description="Distilled qualitative and quantitative strategic lesson")
    applicability_scope: str = Field(default="GLOBAL", description="GLOBAL | BRAND_SPECIFIC | CHANNEL_SPECIFIC | PRODUCT_SPECIFIC")
    promotion_status: PromotionState = Field(default=PromotionState.CANDIDATE_MEMORY)
    retest_required: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def calculate_event_hash(self) -> str:
        """Compute SHA-256 hash of the learning event."""
        raw = f"{self.campaign_id}:{self.experiment_id}:{self.primary_metric}:{self.decision}:{json.dumps(self.observed_result, sort_keys=True, ensure_ascii=False)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LearningRepository(abc.ABC):
    """Abstract interface for learning event storage and retrieval."""

    @abc.abstractmethod
    def record_learning(self, event: LearningEvent) -> LearningEvent:
        pass

    @abc.abstractmethod
    def get_learning(self, learning_event_id: str) -> Optional[LearningEvent]:
        pass

    @abc.abstractmethod
    def list_learnings(
        self,
        campaign_id: Optional[str] = None,
        scope: Optional[str] = None,
        promotion_status: Optional[PromotionState] = None,
    ) -> List[LearningEvent]:
        pass


class LocalLearningRepository(LearningRepository):
    """In-memory and local repository for learning event management."""

    def __init__(self) -> None:
        self._learnings: Dict[str, LearningEvent] = {}

    def record_learning(self, event: LearningEvent) -> LearningEvent:
        self._learnings[event.learning_event_id] = event
        return event

    def get_learning(self, learning_event_id: str) -> Optional[LearningEvent]:
        return self._learnings.get(learning_event_id)

    def list_learnings(
        self,
        campaign_id: Optional[str] = None,
        scope: Optional[str] = None,
        promotion_status: Optional[PromotionState] = None,
    ) -> List[LearningEvent]:
        results = list(self._learnings.values())
        if campaign_id:
            results = [e for e in results if e.campaign_id == campaign_id]
        if scope:
            results = [e for e in results if e.applicability_scope == scope or e.applicability_scope == "GLOBAL"]
        if promotion_status:
            results = [e for e in results if e.promotion_status == promotion_status]
        return results

    def query_learnings_for_context(self, context_tags: List[str]) -> List[LearningEvent]:
        tag_set = set(t.lower() for t in context_tags)
        matched = []
        for e in self._learnings.values():
            if any(t in e.lesson.lower() or t in e.hypothesis.lower() for t in tag_set):
                matched.append(e)
        return matched
