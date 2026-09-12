"""Governed Memory Manager v1.

Separates temporary context from durable learning, enforces exact scope
isolation, retention, evidence-backed promotion, and audit-safe lifecycle
transitions without changing the five-agent core.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from memory.lifecycle_models import (
    DEFAULT_RETENTION_POLICIES,
    MemoryLifecycleState,
    MemoryRetentionPolicy,
    MemoryScope,
)
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.promotion import MemoryPromotionEngine
from memory.scoped_repository import ScopedMemoryRepository
from schemas.base import BaseModel, Field


class MemoryLifecycleEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"MEVT-{uuid.uuid4().hex[:10].upper()}")
    memory_id: str
    action: str
    actor: str
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryWriteResult(BaseModel):
    success: bool
    memory_id: Optional[str] = None
    duplicate_of: Optional[str] = None
    error_code: Optional[str] = None
    error: Optional[str] = None


class MemoryPromotionResult(BaseModel):
    success: bool
    memory_id: str
    from_state: PromotionState
    to_state: PromotionState
    reason: str


class MemoryManager:
    """High-level memory service with retention and promotion governance."""

    _NEXT_PROMOTION = {
        PromotionState.RAW_OBSERVATION: PromotionState.CANDIDATE_MEMORY,
        PromotionState.CANDIDATE_MEMORY: PromotionState.VERIFIED_MEMORY,
        PromotionState.VERIFIED_MEMORY: PromotionState.PROMOTED_LEARNING,
    }

    def __init__(
        self,
        *,
        repository: Optional[ScopedMemoryRepository] = None,
        retention_policies: Optional[Dict[MemoryType, MemoryRetentionPolicy]] = None,
    ) -> None:
        self.repository = repository or ScopedMemoryRepository()
        self.retention_policies = dict(retention_policies or DEFAULT_RETENTION_POLICIES)
        self._events: List[MemoryLifecycleEvent] = []

    def _record_event(
        self,
        memory_id: str,
        action: str,
        *,
        actor: str,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._events.append(
            MemoryLifecycleEvent(
                memory_id=memory_id,
                action=action,
                actor=actor,
                reason=reason,
                metadata=dict(metadata or {}),
            )
        )

    def _apply_retention(self, memory: MemoryItem) -> None:
        if memory.expiry_or_review_date is not None:
            return
        policy = self.retention_policies.get(memory.memory_type)
        if policy is None:
            return
        delta = policy.as_timedelta()
        if delta is not None:
            memory.expiry_or_review_date = memory.timestamp + delta

    def _find_duplicate(self, memory: MemoryItem) -> Optional[MemoryItem]:
        expected_hash = memory.calculate_content_hash()
        for existing in self.repository.list_memories(
            memory_type=memory.memory_type,
            agent_source=memory.agent_source,
            scope=memory.scope,
        ):
            if existing.calculate_content_hash() == expected_hash:
                return existing
        return None

    def remember(
        self,
        *,
        memory_type: MemoryType,
        agent_source: str,
        content: str,
        scope: Optional[MemoryScope] = None,
        run_id: str = "RUN-UNKNOWN",
        context: Optional[Dict[str, Any]] = None,
        evidence_refs: Optional[List[str]] = None,
        confidence: float = 0.5,
        promotion_level: PromotionState = PromotionState.RAW_OBSERVATION,
        expiry_or_review_date: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryWriteResult:
        normalized_content = (content or "").strip()
        if len(normalized_content) < 3:
            return MemoryWriteResult(success=False, error_code="EMPTY_CONTENT", error="Memory content is too short.")
        if not (agent_source or "").strip():
            return MemoryWriteResult(success=False, error_code="AGENT_SOURCE_REQUIRED", error="agent_source is required.")
        if promotion_level in {PromotionState.VERIFIED_MEMORY, PromotionState.PROMOTED_LEARNING}:
            return MemoryWriteResult(
                success=False,
                error_code="PROMOTION_BYPASS_BLOCKED",
                error="New memory must enter as RAW_OBSERVATION or CANDIDATE_MEMORY and pass governed promotion.",
            )

        scope_key = (scope or MemoryScope()).canonical_key()
        sanitized_content = sanitize_sensitive_text(normalized_content)
        sanitized_context = sanitize_sensitive_payload(dict(context or {}))
        sanitized_metadata = sanitize_sensitive_payload(dict(metadata or {}))
        memory = MemoryItem(
            memory_type=memory_type,
            agent_source=agent_source.strip(),
            run_id=run_id,
            context=sanitized_context,
            content=sanitized_content,
            evidence_refs=list(evidence_refs or []),
            confidence=confidence,
            status=MemoryLifecycleState.ACTIVE.value,
            promotion_level=promotion_level,
            scope=scope_key,
            expiry_or_review_date=expiry_or_review_date,
            metadata={**sanitized_metadata, "scope_key": scope_key},
        )
        self._apply_retention(memory)
        duplicate = self._find_duplicate(memory)
        if duplicate is not None:
            return MemoryWriteResult(success=True, memory_id=duplicate.memory_id, duplicate_of=duplicate.memory_id)

        saved = self.repository.save_memory(memory)
        self._record_event(saved.memory_id, "CREATED", actor=agent_source, metadata={"scope": scope_key})
        return MemoryWriteResult(success=True, memory_id=saved.memory_id)

    def retrieve(
        self,
        query: str,
        *,
        scope: Optional[MemoryScope] = None,
        include_global: bool = True,
        memory_types: Optional[List[MemoryType]] = None,
        promotion_levels: Optional[List[PromotionState]] = None,
        min_confidence: float = 0.0,
    ) -> List[MemoryItem]:
        scope_key = (scope or MemoryScope()).canonical_key()
        results = self.repository.query_memories(
            query,
            memory_types,
            scope=scope_key,
            min_confidence=min_confidence,
            promotion_levels=promotion_levels,
        )
        if include_global and scope_key != "GLOBAL":
            global_results = self.repository.query_memories(
                query,
                memory_types,
                scope="GLOBAL",
                min_confidence=min_confidence,
                promotion_levels=promotion_levels,
            )
            seen = {memory.memory_id for memory in results}
            results.extend(memory for memory in global_results if memory.memory_id not in seen)
        return results

    def promote(
        self,
        memory_id: str,
        target_state: PromotionState,
        *,
        actor: str = "operator",
        review_rationale: str = "",
        supporting_evidence: Optional[List[str]] = None,
    ) -> MemoryPromotionResult:
        memory = self.repository.get_memory(memory_id)
        if memory is None:
            return MemoryPromotionResult(
                success=False,
                memory_id=memory_id,
                from_state=PromotionState.RAW_OBSERVATION,
                to_state=target_state,
                reason="MEMORY_NOT_FOUND",
            )
        current = memory.promotion_level
        if current == target_state:
            return MemoryPromotionResult(
                success=True,
                memory_id=memory_id,
                from_state=current,
                to_state=target_state,
                reason="ALREADY_AT_TARGET",
            )
        expected = self._NEXT_PROMOTION.get(current)
        if expected != target_state:
            return MemoryPromotionResult(
                success=False,
                memory_id=memory_id,
                from_state=current,
                to_state=target_state,
                reason=f"PROMOTION_SEQUENCE_REQUIRED: next allowed state is {expected.value if expected else 'none'}",
            )

        success, reason = MemoryPromotionEngine.promote_memory(
            memory,
            target_state,
            review_rationale=review_rationale,
            supporting_evidence=supporting_evidence,
        )
        if success:
            saved = self.repository.save_memory(memory)
            self._record_event(
                memory_id,
                "PROMOTED",
                actor=actor,
                reason=review_rationale,
                metadata={"from": current.value, "to": saved.promotion_level.value, "engine_reason": reason},
            )
        return MemoryPromotionResult(
            success=success,
            memory_id=memory_id,
            from_state=current,
            to_state=target_state,
            reason=reason,
        )

    def retire(self, memory_id: str, *, reason: str, actor: str = "operator") -> bool:
        updated = self.repository.mark_state(
            memory_id,
            MemoryLifecycleState.RETIRED,
            reason=reason,
            changed_by=actor,
        )
        if updated is None:
            return False
        self._record_event(memory_id, "RETIRED", actor=actor, reason=reason)
        return True

    def disprove(self, memory_id: str, *, reason: str, actor: str = "operator") -> bool:
        updated = self.repository.mark_state(
            memory_id,
            MemoryLifecycleState.DISPROVEN,
            reason=reason,
            changed_by=actor,
        )
        if updated is None:
            return False
        self._record_event(memory_id, "DISPROVEN", actor=actor, reason=reason)
        return True

    def supersede(
        self,
        old_memory_id: str,
        new_memory_id: str,
        *,
        reason: str = "Superseded by newer memory",
        actor: str = "operator",
    ) -> bool:
        old = self.repository.get_memory(old_memory_id)
        new = self.repository.get_memory(new_memory_id)
        if old is None or new is None or old_memory_id == new_memory_id:
            return False
        if old.scope != new.scope:
            return False
        old.status = MemoryLifecycleState.SUPERSEDED.value
        old.metadata["superseded_by_id"] = new_memory_id
        old.metadata["lifecycle_reason"] = reason
        new.metadata["supersedes_id"] = old_memory_id
        self.repository.save_memory(old)
        self.repository.save_memory(new)
        self._record_event(old_memory_id, "SUPERSEDED", actor=actor, reason=reason, metadata={"by": new_memory_id})
        return True

    def expire_due(self) -> int:
        before = {
            memory.memory_id
            for memory in self.repository.list_memories(
                memory_type=MemoryType.WORKING_MEMORY,
                include_inactive=True,
            )
            if memory.status == MemoryLifecycleState.ACTIVE.value
        }
        changed = self.repository.purge_expired_working_memories()
        if changed:
            after_active = {
                memory.memory_id
                for memory in self.repository.list_memories(
                    memory_type=MemoryType.WORKING_MEMORY,
                )
            }
            for memory_id in sorted(before - after_active):
                self._record_event(
                    memory_id,
                    "EXPIRED",
                    actor="retention_policy",
                    reason="Working-memory retention window elapsed",
                )
        return changed

    def list_events(self, memory_id: Optional[str] = None) -> List[MemoryLifecycleEvent]:
        import copy

        events = self._events if memory_id is None else [event for event in self._events if event.memory_id == memory_id]
        return copy.deepcopy(events)
