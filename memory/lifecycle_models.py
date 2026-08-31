"""Scope and retention contracts for governed memory management."""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Dict, List, Optional

from memory.models import MemoryType
from schemas.base import BaseModel, Field


class MemoryLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DISPROVEN = "DISPROVEN"
    RETIRED = "RETIRED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MemoryScope(BaseModel):
    """Exact tenant/workspace boundary for memory storage and retrieval."""

    business_id: str = ""
    project_id: str = ""
    brand_id: str = ""
    product_id: str = ""
    campaign_id: str = ""

    def canonical_key(self) -> str:
        fields = {
            "BUSINESS": self.business_id,
            "PROJECT": self.project_id,
            "BRAND": self.brand_id,
            "PRODUCT": self.product_id,
            "CAMPAIGN": self.campaign_id,
        }
        parts: List[str] = []
        for name, raw in fields.items():
            value = str(raw or "").strip()
            if not value:
                continue
            if any(ch in value for ch in ("|", "\n", "\r")):
                raise ValueError(f"invalid {name.lower()} memory scope identifier")
            parts.append(f"{name}:{value}")
        return "GLOBAL" if not parts else "|".join(parts)


class MemoryRetentionPolicy(BaseModel):
    """Default retention/review horizon for one memory class.

    `ttl_days=None` means no automatic expiry. It does not mean the memory is
    permanently trusted; promotion and evidence rules remain separate.
    """

    memory_type: MemoryType
    ttl_days: Optional[int] = Field(default=None, ge=1)

    def as_timedelta(self) -> Optional[timedelta]:
        return timedelta(days=self.ttl_days) if self.ttl_days is not None else None


DEFAULT_RETENTION_POLICIES: Dict[MemoryType, MemoryRetentionPolicy] = {
    MemoryType.WORKING_MEMORY: MemoryRetentionPolicy(memory_type=MemoryType.WORKING_MEMORY, ttl_days=1),
    MemoryType.EPISODIC_MEMORY: MemoryRetentionPolicy(memory_type=MemoryType.EPISODIC_MEMORY, ttl_days=365),
    MemoryType.DECISION_MEMORY: MemoryRetentionPolicy(memory_type=MemoryType.DECISION_MEMORY, ttl_days=365),
    MemoryType.EXPERIMENT_MEMORY: MemoryRetentionPolicy(memory_type=MemoryType.EXPERIMENT_MEMORY, ttl_days=730),
    MemoryType.SUCCESS_FAILURE_MEMORY: MemoryRetentionPolicy(memory_type=MemoryType.SUCCESS_FAILURE_MEMORY, ttl_days=730),
    MemoryType.USER_BRAND_PREFERENCE_MEMORY: MemoryRetentionPolicy(
        memory_type=MemoryType.USER_BRAND_PREFERENCE_MEMORY,
        ttl_days=None,
    ),
}
