"""Memory Retrieval and Context Builder (Phase 5.2).

Constructs role-isolated, confidence-filtered, and unexpired memory context sections
for each of the 5 permanent agents. Excludes unverified RAW_OBSERVATION from trusted learning.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from governance.access_matrix import AgentAccessMatrix
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.promotion import MemoryPromotionEngine
from memory.repository import MemoryRepository
from schemas.base import BaseModel, Field


class MemoryQuery(BaseModel):
    """Structured query for role-isolated memory retrieval."""
    agent_id: str
    query_text: str = ""
    allowed_types: List[MemoryType] = Field(default_factory=list)
    min_confidence: float = 0.60
    allowed_promotion_states: List[PromotionState] = Field(
        default_factory=lambda: [
            PromotionState.CANDIDATE_MEMORY,
            PromotionState.VERIFIED_MEMORY,
            PromotionState.PROMOTED_LEARNING,
        ]
    )
    max_items: int = 5
    max_chars: int = 2500


class MemoryRetrievalResult(BaseModel):
    """Normalized outcome of memory retrieval."""
    agent_id: str
    memories: List[MemoryItem] = Field(default_factory=list)
    context_text: str = ""
    retrieved_count: int = 0


class MemoryContextBuilder:
    """Retrieves and renders bounded, role-isolated institutional memory."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def build_context_for_agent(
        self,
        agent_id: str,
        query_text: str = "",
        min_confidence: float = 0.60,
        include_raw: bool = False,
        max_chars: int = 2500,
        scope: Optional[str] = None,
    ) -> MemoryRetrievalResult:
        """Retrieve and format unexpired, role-authorized memories.

        Missing/blank scope is deliberately GLOBAL, never a repository wildcard.
        Callers that need business/project memory must provide its exact scope.
        """
        aid = agent_id.lower()
        prof = AgentAccessMatrix.get_profile(aid)
        if not prof:
            return MemoryRetrievalResult(
                agent_id=aid,
                context_text=f"=== MEMORY ACCESS DENIED: Unrecognized agent '{agent_id}' ===",
            )

        allowed_types = prof.allowed_memory_types
        allowed_promotions = {
            PromotionState.CANDIDATE_MEMORY,
            PromotionState.VERIFIED_MEMORY,
            PromotionState.PROMOTED_LEARNING,
        }
        if include_raw:
            allowed_promotions.add(PromotionState.RAW_OBSERVATION)

        # Legacy MemoryRepository has no scope parameter and list_memories()
        # therefore returns every tenant/project. Enforce exact scope here.
        effective_scope = str(scope or "GLOBAL").strip() or "GLOBAL"
        all_memories = [
            memory
            for memory in self.repository.list_memories()
            if getattr(memory, "scope", "GLOBAL") == effective_scope
        ]
        valid_memories: List[MemoryItem] = []

        for m in all_memories:
            # 1. Type isolation
            if m.memory_type not in allowed_types:
                continue
            # 2. Promotion state gate (prohibit treating RAW_OBSERVATION as learning)
            if m.promotion_level not in allowed_promotions:
                continue
            # 3. Confidence threshold
            if m.confidence < min_confidence:
                continue
            # 4. Expiry / staleness check
            if MemoryPromotionEngine.audit_memory_staleness(m):
                continue
            valid_memories.append(m)

        # Match by query if provided
        if query_text:
            matched = []
            q_low = query_text.lower()
            for m in valid_memories:
                if q_low in m.content.lower() or any(q_low in str(v).lower() for v in m.context.values()):
                    matched.append(m)
            target_memories = matched[:4] if matched else valid_memories[:4]
        else:
            target_memories = valid_memories[:4]

        lines = [f"=== INSTITUTIONAL MEMORY FOR [{aid.upper()}] ==="]
        total_chars = 0

        for m in target_memories:
            entry_header = f"\n[MEMORY: {m.memory_id} | Type: {m.memory_type.value} | Tier: {m.promotion_level.value} | Conf: {m.confidence:.2f}]"
            entry_body = f"Originating Agent: {m.agent_source}\nLesson/Context: {m.content}\nEvidence Refs: {', '.join(m.evidence_refs) if m.evidence_refs else 'NONE'}"
            entry = f"{entry_header}\n{entry_body}"

            if total_chars + len(entry) > max_chars:
                lines.append(f"\n[... Memory context truncated at {max_chars} chars limit ...]")
                break

            lines.append(entry)
            total_chars += len(entry)

        if not target_memories:
            lines.append("No active historical memories found for this role and query.")

        return MemoryRetrievalResult(
            agent_id=aid,
            memories=target_memories,
            context_text="\n".join(lines),
            retrieved_count=len(target_memories),
        )
