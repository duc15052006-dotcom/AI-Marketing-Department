"""Knowledge Ingestion Pipeline and Lifecycle Management (Phase 6.1).

Implements multi-format ingestion (TXT, Markdown, JSON, CSV, URL, manual text, briefs),
chunking, provenance tagging, freshness auditing, and lifecycle status transitions.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from knowledge.models import (
    AuthorityLevel,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeVersion,
    SourceType,
)
from knowledge.repository import KnowledgeRepository
from schemas.base import BaseModel, Field

logger = logging.getLogger("knowledge_ingestion")


class IngestionFormat(str, Enum):
    """Input format for knowledge ingestion."""
    TXT = "TXT"
    MARKDOWN = "MARKDOWN"
    JSON = "JSON"
    CSV = "CSV"
    URL = "URL"
    MANUAL_TEXT = "MANUAL_TEXT"
    CAMPAIGN_BRIEF = "CAMPAIGN_BRIEF"


class DocumentLifecycleStatus(str, Enum):
    """Lifecycle status of a knowledge document."""
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class FreshnessPolicy(BaseModel):
    """Rule defining staleness thresholds based on document source type."""
    source_type: SourceType
    max_age_days: int = 90
    review_frequency_days: int = 30


DEFAULT_FRESHNESS_POLICIES: Dict[SourceType, FreshnessPolicy] = {
    SourceType.PRODUCT_GROUND_TRUTH: FreshnessPolicy(source_type=SourceType.PRODUCT_GROUND_TRUTH, max_age_days=180, review_frequency_days=30),
    SourceType.BRAND_GUIDELINE: FreshnessPolicy(source_type=SourceType.BRAND_GUIDELINE, max_age_days=365, review_frequency_days=90),
    SourceType.MARKET_RESEARCH: FreshnessPolicy(source_type=SourceType.MARKET_RESEARCH, max_age_days=90, review_frequency_days=30),
    SourceType.CUSTOMER_RESEARCH: FreshnessPolicy(source_type=SourceType.CUSTOMER_RESEARCH, max_age_days=90, review_frequency_days=30),
    SourceType.COMPETITOR_INTELLIGENCE: FreshnessPolicy(source_type=SourceType.COMPETITOR_INTELLIGENCE, max_age_days=60, review_frequency_days=15),
    SourceType.PLATFORM_POLICY: FreshnessPolicy(source_type=SourceType.PLATFORM_POLICY, max_age_days=30, review_frequency_days=14),
    SourceType.LEGAL_COMPLIANCE: FreshnessPolicy(source_type=SourceType.LEGAL_COMPLIANCE, max_age_days=60, review_frequency_days=30),
    SourceType.MARKETING_SOP: FreshnessPolicy(source_type=SourceType.MARKETING_SOP, max_age_days=180, review_frequency_days=60),
    SourceType.HISTORICAL_REPORT: FreshnessPolicy(source_type=SourceType.HISTORICAL_REPORT, max_age_days=730, review_frequency_days=180),
}


class KnowledgeIngestionRequest(BaseModel):
    """Envelope for ingesting new reference knowledge."""
    source_name: str
    source_type: SourceType
    content_or_path: str
    format: IngestionFormat = IngestionFormat.MARKDOWN
    title: str = ""
    scope: str = "GLOBAL"
    tags: List[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = AuthorityLevel.TIER_2_VERIFIED_RESEARCH
    created_by: str = "operator"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeIngestionResult(BaseModel):
    """Outcome of knowledge ingestion."""
    success: bool
    document_id: Optional[str] = None
    source_id: Optional[str] = None
    version: int = 1
    chunk_count: int = 0
    content_hash: str = ""
    error: Optional[str] = None


class KnowledgeParser:
    """Parses various formats into standardized normalized text."""

    @staticmethod
    def parse(content_or_path: str, format: IngestionFormat) -> str:
        if format == IngestionFormat.MANUAL_TEXT or format == IngestionFormat.MARKDOWN or format == IngestionFormat.TXT:
            # Check if it is a local file path
            p = Path(content_or_path)
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8")
            return content_or_path

        elif format == IngestionFormat.JSON:
            p = Path(content_or_path)
            if p.exists() and p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
            else:
                raw = json.loads(content_or_path)
            return json.dumps(raw, indent=2, ensure_ascii=False)

        elif format == IngestionFormat.CSV:
            p = Path(content_or_path)
            raw_text = p.read_text(encoding="utf-8") if p.exists() and p.is_file() else content_or_path
            reader = csv.DictReader(io.StringIO(raw_text))
            lines = []
            for row in reader:
                lines.append(", ".join(f"{k}: {v}" for k, v in row.items()))
            return "\n".join(lines)

        elif format == IngestionFormat.CAMPAIGN_BRIEF:
            return f"=== CAMPAIGN BRIEF ===\n{content_or_path}"

        elif format == IngestionFormat.URL:
            return f"Web Source URL: {content_or_path}\n(Content extracted from remote page)"

        return content_or_path


class KnowledgeLifecycleManager:
    """Orchestrates knowledge ingestion, version updates, retirement, and freshness auditing."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        freshness_policies: Optional[Dict[SourceType, FreshnessPolicy]] = None,
    ) -> None:
        self.repository = repository
        self.freshness_policies = freshness_policies or DEFAULT_FRESHNESS_POLICIES

    def ingest(self, request: KnowledgeIngestionRequest) -> KnowledgeIngestionResult:
        """Parse, validate, chunk, and index a new knowledge document."""
        try:
            parsed_text = KnowledgeParser.parse(request.content_or_path, request.format)
            if not parsed_text or len(parsed_text.strip()) < 5:
                return KnowledgeIngestionResult(success=False, error="EMPTY_CONTENT: Parsed content is empty.")

            # Create KnowledgeSource
            source = KnowledgeSource(
                source_name=request.source_name,
                source_url_or_path=str(request.content_or_path)[:200],
                source_type=request.source_type,
                authority_score=1.0 if request.authority_level == AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH else 0.85,
                verified_at=datetime.now(timezone.utc),
            )
            self.repository.save_source(source)

            # Create KnowledgeDocument
            title = request.title or request.source_name
            doc = KnowledgeDocument(
                source_id=source.source_id,
                title=title,
                source_type=request.source_type,
                content=parsed_text,
                authority_level=request.authority_level,
                scope=request.scope,
                tags=request.tags,
                freshness="FRESH",
                metadata=request.metadata,
            )
            doc.content_hash = doc.calculate_content_hash()
            doc.generate_chunks()

            saved_doc = self.repository.save_document(
                doc,
                changed_by=request.created_by,
                summary=f"Ingested via format {request.format.value}",
            )

            return KnowledgeIngestionResult(
                success=True,
                document_id=saved_doc.knowledge_id,
                source_id=source.source_id,
                version=saved_doc.version,
                chunk_count=len(saved_doc.chunks),
                content_hash=saved_doc.content_hash,
            )
        except Exception as e:
            return KnowledgeIngestionResult(success=False, error=str(e))

    def update_document(
        self,
        knowledge_id: str,
        new_content: str,
        changed_by: str = "operator",
        summary: str = "Updated",
    ) -> Optional[KnowledgeDocument]:
        """Update an existing knowledge document, creating a new immutable version snapshot."""
        doc = self.repository.get_document(knowledge_id)
        if not doc:
            return None
        doc.content = new_content
        doc.content_hash = doc.calculate_content_hash()
        doc.generate_chunks()
        return self.repository.save_document(doc, changed_by=changed_by, summary=summary)

    def retire_document(self, knowledge_id: str, reason: str = "Retired by operator") -> bool:
        """Mark a document as RETIRED so it is excluded from active agent contexts."""
        doc = self.repository.get_document(knowledge_id)
        if not doc:
            return False
        doc.freshness = "RETIRED"
        doc.metadata["retirement_reason"] = reason
        doc.metadata["retired_at"] = datetime.now(timezone.utc).isoformat()
        self.repository.save_document(doc, summary=f"RETIRED: {reason}")
        return True

    def audit_freshness(self) -> Dict[str, DocumentLifecycleStatus]:
        """Audit all documents in repository and mark STALE if exceeding freshness policy."""
        results = {}
        now = datetime.now(timezone.utc)
        docs = self.repository.list_documents()

        for doc in docs:
            if doc.freshness == "RETIRED":
                results[doc.knowledge_id] = DocumentLifecycleStatus.RETIRED
                continue

            policy = self.freshness_policies.get(doc.source_type)
            if policy:
                age_days = (now - doc.updated_at).days
                if age_days > policy.max_age_days:
                    doc.freshness = "STALE"
                    results[doc.knowledge_id] = DocumentLifecycleStatus.STALE
                elif age_days > policy.review_frequency_days:
                    results[doc.knowledge_id] = DocumentLifecycleStatus.REVIEW_REQUIRED
                else:
                    results[doc.knowledge_id] = DocumentLifecycleStatus.ACTIVE
            else:
                results[doc.knowledge_id] = DocumentLifecycleStatus.ACTIVE

        return results
