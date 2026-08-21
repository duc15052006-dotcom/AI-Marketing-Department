"""Knowledge Foundation Models (Phase 5.1).

Defines durable reference knowledge schemas, chunks, sources, versioning,
and citations with full provenance tracking.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field


class AuthorityLevel(str, Enum):
    """Authority and verification tier for knowledge assets."""
    TIER_1_CANONICAL_GROUND_TRUTH = "TIER_1_CANONICAL_GROUND_TRUTH"  # Verified product specs, lab certifications, legal contracts
    TIER_2_VERIFIED_RESEARCH = "TIER_2_VERIFIED_RESEARCH"            # Grounded user interviews, verified analytics, audit reports
    TIER_3_SECONDARY_INDUSTRY_DATA = "TIER_3_SECONDARY_INDUSTRY_DATA"  # Benchmark reports, published trade journals
    TIER_4_UNVERIFIED_OBSERVATION = "TIER_4_UNVERIFIED_OBSERVATION"    # Raw social posts, web snippets


class SourceType(str, Enum):
    """Type of source supplying the knowledge document."""
    PRODUCT_GROUND_TRUTH = "PRODUCT_GROUND_TRUTH"
    BRAND_GUIDELINE = "BRAND_GUIDELINE"
    MARKET_RESEARCH = "MARKET_RESEARCH"
    CUSTOMER_RESEARCH = "CUSTOMER_RESEARCH"
    COMPETITOR_INTELLIGENCE = "COMPETITOR_INTELLIGENCE"
    MARKETING_SOP = "MARKETING_SOP"
    PLATFORM_POLICY = "PLATFORM_POLICY"
    LEGAL_COMPLIANCE = "LEGAL_COMPLIANCE"
    HISTORICAL_REPORT = "HISTORICAL_REPORT"


class KnowledgeSource(BaseModel):
    """Origin and provenance source metadata."""
    source_id: str = Field(default_factory=lambda: f"SRC-{uuid.uuid4().hex[:10].upper()}")
    source_name: str
    source_url_or_path: str
    source_type: SourceType
    verified_at: Optional[datetime] = None
    authority_score: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeChunk(BaseModel):
    """Searchable textual chunk derived from a KnowledgeDocument."""
    chunk_id: str = Field(default_factory=lambda: f"CHK-{uuid.uuid4().hex[:10].upper()}")
    document_id: str
    text: str
    chunk_index: int = 0
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance_ref: str = ""

    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class KnowledgeVersion(BaseModel):
    """Version history snapshot for a KnowledgeDocument."""
    version_id: str = Field(default_factory=lambda: f"VER-{uuid.uuid4().hex[:10].upper()}")
    document_id: str
    version_number: int = 1
    changed_by: str = "system"
    change_summary: str = "Initial creation"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str


class KnowledgeCitation(BaseModel):
    """Verifiable reference linking an assertion to a knowledge chunk/document."""
    citation_id: str = Field(default_factory=lambda: f"CIT-{uuid.uuid4().hex[:10].upper()}")
    knowledge_id: str
    chunk_id: Optional[str] = None
    source_id: str = ""
    claim_ref: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeDocument(BaseModel):
    """Durable reference knowledge asset with full provenance and versioning."""
    knowledge_id: str = Field(default_factory=lambda: f"KNOW-{uuid.uuid4().hex[:10].upper()}")
    source_id: str = Field(..., description="ID of associated KnowledgeSource")
    title: str = Field(..., description="Human-readable title of knowledge document")
    source_type: SourceType = Field(default=SourceType.PRODUCT_GROUND_TRUTH)
    content: str = Field(..., description="Full text or structured body of document")
    version: int = Field(default=1)
    authority_level: AuthorityLevel = Field(default=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH)
    freshness: str = Field(default="FRESH", description="FRESH | STALE | DEPRECATED")
    tags: List[str] = Field(default_factory=list)
    scope: str = Field(default="GLOBAL", description="GLOBAL | BRAND_SPECIFIC | PRODUCT_SPECIFIC | CAMPAIGN_SPECIFIC")
    content_hash: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunks: List[KnowledgeChunk] = Field(default_factory=list)

    def calculate_content_hash(self) -> str:
        """Compute SHA-256 hash of document body."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    def generate_chunks(self, chunk_size: int = 500) -> List[KnowledgeChunk]:
        """Split document into provenance-traceable chunks."""
        text = self.content
        chunks = []
        for idx in range(0, len(text), chunk_size):
            chunk_text = text[idx : idx + chunk_size]
            chk = KnowledgeChunk(
                document_id=self.knowledge_id,
                text=chunk_text,
                chunk_index=len(chunks),
                tags=self.tags,
                provenance_ref=f"{self.knowledge_id}:chunk_{len(chunks)}",
            )
            chunks.append(chk)
        self.chunks = chunks
        return chunks
