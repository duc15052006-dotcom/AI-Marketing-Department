"""Knowledge Retrieval and Context Builder (Phase 5.2).

Constructs agent-specific, bounded, and verifiable knowledge context sections
for each of the 5 permanent agents with full citation provenance.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from governance.access_matrix import AgentAccessMatrix
from knowledge.models import AuthorityLevel, KnowledgeCitation, KnowledgeDocument, SourceType
from knowledge.repository import KnowledgeRepository
from schemas.base import BaseModel, Field


_INACTIVE_KNOWLEDGE_STATES = {"SUPERSEDED", "RETIRED", "DELETED"}
_KNOWLEDGE_AUTHORITY_RANK = {
    AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH: 0,
    AuthorityLevel.TIER_2_VERIFIED_RESEARCH: 1,
    AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA: 2,
    AuthorityLevel.TIER_4_UNVERIFIED_OBSERVATION: 3,
}


def _knowledge_authority_rank(document: KnowledgeDocument) -> int:
    """Rank higher-authority knowledge first while leaving unknown future tiers last."""
    return _KNOWLEDGE_AUTHORITY_RANK.get(
        document.authority_level,
        len(_KNOWLEDGE_AUTHORITY_RANK),
    )


def _is_retrievable_knowledge(document: KnowledgeDocument) -> bool:
    """Match the governed repository lifecycle contract without blocking STALE."""
    freshness = getattr(document, "freshness", "")
    lifecycle_state = str(getattr(freshness, "value", freshness)).strip().upper()
    return lifecycle_state not in _INACTIVE_KNOWLEDGE_STATES


class KnowledgeQuery(BaseModel):
    """Structured query envelope for retrieving agent-scoped knowledge."""
    agent_id: str
    query_text: str = ""
    allowed_sources: List[SourceType] = Field(default_factory=list)
    scope: Optional[str] = None
    min_authority: AuthorityLevel = AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA
    max_chunks: int = 6
    max_chars: int = 3500


class KnowledgeRetrievalResult(BaseModel):
    """Normalized outcome of knowledge retrieval with citations and provenance."""
    agent_id: str
    documents: List[KnowledgeDocument] = Field(default_factory=list)
    citations: List[KnowledgeCitation] = Field(default_factory=list)
    context_text: str = ""
    retrieved_count: int = 0


class KnowledgeContextBuilder:
    """Retrieves and renders bounded, cited knowledge context tailored to agent roles."""

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def build_context_for_agent(
        self,
        agent_id: str,
        query_text: str = "",
        scope: Optional[str] = None,
        max_chars: int = 3500,
    ) -> KnowledgeRetrievalResult:
        """Retrieve and format role-authorized knowledge with provenance tracking.

        Missing/blank scope is deliberately GLOBAL, never a repository wildcard.
        Callers that need business/project knowledge must provide its exact scope.
        """
        aid = agent_id.lower()
        prof = AgentAccessMatrix.get_profile(aid)
        if not prof:
            return KnowledgeRetrievalResult(
                agent_id=aid,
                context_text=f"=== KNOWLEDGE RETRIEVAL DENIED: Unrecognized agent '{agent_id}' ===",
            )

        # Fail closed at the builder authority boundary. Legacy repositories use
        # scope=None as "all documents", which can cross tenant/project borders.
        effective_scope = str(scope or "GLOBAL").strip() or "GLOBAL"

        # Match the governed repository lifecycle contract. STALE remains
        # retrievable; SUPERSEDED/RETIRED/DELETED must never become context.
        allowed_sources = prof.allowed_knowledge_sources
        all_docs = self.repository.list_documents(scope=effective_scope)
        scoped_docs = [
            d
            for d in all_docs
            if d.source_type in allowed_sources and _is_retrievable_knowledge(d)
        ]
        # Bound selection only after a stable authority sort so earlier low-tier
        # insertion order cannot crowd out higher-authority evidence.
        scoped_docs = sorted(scoped_docs, key=_knowledge_authority_rank)

        # Match by query if provided, or take high-authority scoped docs
        if query_text:
            matched = []
            q_low = query_text.lower()
            for d in scoped_docs:
                if q_low in d.title.lower() or q_low in d.content.lower() or any(q_low in t.lower() for t in d.tags):
                    matched.append(d)
            target_docs = matched if matched else scoped_docs[:4]
        else:
            target_docs = scoped_docs[:4]

        citations: List[KnowledgeCitation] = []
        lines = [f"=== VERIFIED KNOWLEDGE CONTEXT FOR [{aid.upper()}] ==="]
        total_chars = 0

        for doc in target_docs:
            chunk = doc.chunks[0] if doc.chunks else None
            chunk_id = chunk.chunk_id if chunk else "CHUNK-0"
            citation = KnowledgeCitation(
                knowledge_id=doc.knowledge_id,
                chunk_id=chunk_id,
                source_id=doc.source_id,
                claim_ref=doc.title,
                confidence=1.0 if doc.authority_level == AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH else 0.85,
            )
            citations.append(citation)

            doc_header = f"\n[KNOWLEDGE REF: {doc.knowledge_id} | Ver: {doc.version} | Auth: {doc.authority_level.value} | SourceType: {doc.source_type.value}]"
            doc_body = f"Title: {doc.title}\nContent: {doc.content[:600]}..."
            entry = f"{doc_header}\n{doc_body}"

            if total_chars + len(entry) > max_chars:
                lines.append(f"\n[... Knowledge context truncated at {max_chars} chars budget limit ...]")
                break

            lines.append(entry)
            total_chars += len(entry)

        if not target_docs:
            lines.append("No active knowledge documents resolved for this role and scope.")

        return KnowledgeRetrievalResult(
            agent_id=aid,
            documents=target_docs,
            citations=citations,
            context_text="\n".join(lines),
            retrieved_count=len(target_docs),
        )
