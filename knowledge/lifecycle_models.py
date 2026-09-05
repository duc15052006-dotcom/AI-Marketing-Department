"""Structured scope and lifecycle contracts for managed knowledge assets."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from schemas.base import BaseModel, Field


class KnowledgeLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"
    DELETED = "DELETED"


class KnowledgeIndexState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class KnowledgeScope(BaseModel):
    """Explicit isolation scope for one knowledge asset or retrieval request.

    Empty fields mean GLOBAL. Non-global fields are combined into one exact scope
    key so a product/project cannot accidentally retrieve another workspace's
    private knowledge.
    """

    business_id: str = ""
    project_id: str = ""
    brand_id: str = ""
    product_id: str = ""
    campaign_id: str = ""

    def canonical_key(self) -> str:
        values = {
            "BUSINESS": self.business_id,
            "PROJECT": self.project_id,
            "BRAND": self.brand_id,
            "PRODUCT": self.product_id,
            "CAMPAIGN": self.campaign_id,
        }
        parts: List[str] = []
        for name, raw in values.items():
            value = str(raw or "").strip()
            if not value:
                continue
            if any(ch in value for ch in ("|", "\n", "\r")):
                raise ValueError(f"invalid {name.lower()} scope identifier")
            parts.append(f"{name}:{value}")
        return "GLOBAL" if not parts else "|".join(parts)

    @property
    def is_global(self) -> bool:
        return self.canonical_key() == "GLOBAL"


class KnowledgeFileAsset(BaseModel):
    """Metadata for a safely ingested local file without leaking absolute paths."""

    asset_id: str = Field(default_factory=lambda: f"KFILE-{uuid.uuid4().hex[:10].upper()}")
    relative_path: str
    filename: str
    extension: str
    size_bytes: int = Field(default=0, ge=0)
    sha256: str
    scope_key: str
    knowledge_id: str
    index_state: KnowledgeIndexState = KnowledgeIndexState.READY
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None


class KnowledgeImportResult(BaseModel):
    success: bool
    knowledge_id: Optional[str] = None
    source_id: Optional[str] = None
    asset_id: Optional[str] = None
    version: int = 0
    duplicate_of: Optional[str] = None
    error_code: Optional[str] = None
    error: Optional[str] = None
