"""Knowledge Conflict Detection and Resolution (Phase 6.1).

Detects contradictory knowledge facts and resolves them using strict authority hierarchies
and timestamp freshness, routing unresolved high-impact conflicts to human/CMO review.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from knowledge.models import AuthorityLevel, KnowledgeDocument
from schemas.base import BaseModel, Field


class ConflictResolutionStatus(str, Enum):
    """Resolution outcome for conflicting knowledge statements."""
    UNRESOLVED = "UNRESOLVED"
    HIGHER_AUTHORITY_WINS = "HIGHER_AUTHORITY_WINS"
    NEWER_VERIFIED_SOURCE_WINS = "NEWER_VERIFIED_SOURCE_WINS"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class KnowledgeConflict(BaseModel):
    """Record of contradictory assertions across knowledge documents."""
    conflict_id: str = Field(default_factory=lambda: f"CONF-{uuid.uuid4().hex[:8].upper()}")
    doc_a_id: str
    doc_b_id: str
    topic: str
    claim_a: str
    claim_b: str
    authority_a: AuthorityLevel
    authority_b: AuthorityLevel
    status: ConflictResolutionStatus = ConflictResolutionStatus.UNRESOLVED
    resolved_doc_id: Optional[str] = None
    resolution_details: str = ""


class KnowledgeConflictResolver:
    """Detects and resolves conflicting knowledge facts deterministically."""

    # Authority rank (Tier 1 > Tier 2 > Tier 3 > Tier 4)
    AUTHORITY_RANKS: Dict[AuthorityLevel, int] = {
        AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH: 100,
        AuthorityLevel.TIER_2_VERIFIED_RESEARCH: 80,
        AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA: 60,
        AuthorityLevel.TIER_4_UNVERIFIED_OBSERVATION: 40,
    }

    @classmethod
    def resolve_conflict(
        cls,
        doc_a: KnowledgeDocument,
        doc_b: KnowledgeDocument,
        topic: str,
        claim_a: str,
        claim_b: str,
    ) -> KnowledgeConflict:
        """Resolve contradiction between two documents."""
        rank_a = cls.AUTHORITY_RANKS.get(doc_a.authority_level, 0)
        rank_b = cls.AUTHORITY_RANKS.get(doc_b.authority_level, 0)

        conflict = KnowledgeConflict(
            doc_a_id=doc_a.knowledge_id,
            doc_b_id=doc_b.knowledge_id,
            topic=topic,
            claim_a=claim_a,
            claim_b=claim_b,
            authority_a=doc_a.authority_level,
            authority_b=doc_b.authority_level,
        )

        if rank_a > rank_b:
            conflict.status = ConflictResolutionStatus.HIGHER_AUTHORITY_WINS
            conflict.resolved_doc_id = doc_a.knowledge_id
            conflict.resolution_details = f"Document '{doc_a.knowledge_id}' wins due to higher authority ({doc_a.authority_level.value} > {doc_b.authority_level.value})."
        elif rank_b > rank_a:
            conflict.status = ConflictResolutionStatus.HIGHER_AUTHORITY_WINS
            conflict.resolved_doc_id = doc_b.knowledge_id
            conflict.resolution_details = f"Document '{doc_b.knowledge_id}' wins due to higher authority ({doc_b.authority_level.value} > {doc_a.authority_level.value})."
        else:
            # Same authority: compare timestamps
            if doc_a.updated_at > doc_b.updated_at:
                conflict.status = ConflictResolutionStatus.NEWER_VERIFIED_SOURCE_WINS
                conflict.resolved_doc_id = doc_a.knowledge_id
                conflict.resolution_details = f"Document '{doc_a.knowledge_id}' wins due to newer verification date ({doc_a.updated_at.isoformat()})."
            elif doc_b.updated_at > doc_a.updated_at:
                conflict.status = ConflictResolutionStatus.NEWER_VERIFIED_SOURCE_WINS
                conflict.resolved_doc_id = doc_b.knowledge_id
                conflict.resolution_details = f"Document '{doc_b.knowledge_id}' wins due to newer verification date ({doc_b.updated_at.isoformat()})."
            else:
                conflict.status = ConflictResolutionStatus.HUMAN_REVIEW_REQUIRED
                conflict.resolution_details = "Identical authority and timestamp. Escalate to human operator / CMO review."

        return conflict
