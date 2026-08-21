"""Memory Foundation Models (Phase 5.1).

Defines memory types, promotion states, and structured memory entities
distinct from factual reference knowledge.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field


class MemoryType(str, Enum):
    """Functional classification of memory objects."""
    WORKING_MEMORY = "WORKING_MEMORY"                        # Temporary session/run context
    EPISODIC_MEMORY = "EPISODIC_MEMORY"                      # Campaign execution event history
    DECISION_MEMORY = "DECISION_MEMORY"                      # Strategic, creative, and performance decisions
    EXPERIMENT_MEMORY = "EXPERIMENT_MEMORY"                  # Hypothesis, intervention, and results
    SUCCESS_FAILURE_MEMORY = "SUCCESS_FAILURE_MEMORY"        # What worked vs what failed with context
    USER_BRAND_PREFERENCE_MEMORY = "USER_BRAND_PREFERENCE_MEMORY"  # Stable brand constraints & preferences


class PromotionState(str, Enum):
    """Lifecycle and verification tier for memory and learning assets."""
    RAW_OBSERVATION = "RAW_OBSERVATION"      # Unverified observation or raw agent note
    CANDIDATE_MEMORY = "CANDIDATE_MEMORY"    # Structured hypothesis or candidate finding
    VERIFIED_MEMORY = "VERIFIED_MEMORY"      # Measured or evidence-backed memory
    PROMOTED_LEARNING = "PROMOTED_LEARNING"  # High-confidence durable institutional learning
    RETIRED = "RETIRED"                      # Stale, disproven, or superseded memory


class MemoryItem(BaseModel):
    """Individual memory object with provenance, evidence linking, and promotion state."""
    memory_id: str = Field(default_factory=lambda: f"MEM-{uuid.uuid4().hex[:10].upper()}")
    memory_type: MemoryType = Field(..., description="Type of memory")
    agent_source: str = Field(..., description="Agent role that originated this memory")
    run_id: str = Field(default="RUN-UNKNOWN", description="Associated campaign or benchmark run ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: Dict[str, Any] = Field(default_factory=dict, description="Contextual tags, product, brand, target audience")
    content: str = Field(..., description="Semantic content or structured lesson")
    evidence_refs: List[str] = Field(default_factory=list, description="IDs of supporting evidence, receipts, or data points")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: str = Field(default="ACTIVE", description="ACTIVE | ARCHIVED | DISPROVEN")
    promotion_level: PromotionState = Field(default=PromotionState.RAW_OBSERVATION)
    scope: str = Field(default="GLOBAL", description="Scope or tenant boundary, e.g. GLOBAL or BIZ_TENANT_ID")
    expiry_or_review_date: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def calculate_content_hash(self) -> str:
        """Compute SHA-256 hash of the memory content and context."""
        raw = f"{self.memory_type.value}:{self.agent_source}:{self.content}:{json.dumps(self.context, sort_keys=True, ensure_ascii=False)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
