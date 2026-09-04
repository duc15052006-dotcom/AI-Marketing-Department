"""Provider-neutral semantic memory policy for the Brain layer.

This module decides whether a memory candidate is safe to keep only ephemerally,
retain as a candidate, verify, promote into durable learning, or reject. Storage,
retrieval, retention databases, runtime state, tools, connectors, and model
providers remain Body concerns.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.evidence import ClaimVerdict
from schemas.base import BaseModel, Field, ValidationError


class MemoryKind(str, Enum):
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    DECISION = "DECISION"
    EXPERIMENT = "EXPERIMENT"
    SUCCESS_FAILURE = "SUCCESS_FAILURE"
    USER_BRAND_PREFERENCE = "USER_BRAND_PREFERENCE"


class MemoryAuthority(str, Enum):
    AGENT_INFERRED = "AGENT_INFERRED"
    OBSERVED = "OBSERVED"
    USER_CONFIRMED = "USER_CONFIRMED"


class MemoryScopeLevel(str, Enum):
    GLOBAL = "GLOBAL"
    BUSINESS = "BUSINESS"
    PROJECT = "PROJECT"
    BRAND = "BRAND"
    PRODUCT = "PRODUCT"
    CAMPAIGN = "CAMPAIGN"


class MemoryDisposition(str, Enum):
    EPHEMERAL = "EPHEMERAL"
    CANDIDATE = "CANDIDATE"
    VERIFIED = "VERIFIED"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _enum(value: object, enum_cls: Type[E], field_name: str) -> E:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().upper())
        except ValueError:
            pass
    raise ValidationError(
        f"{field_name} must be one of: {', '.join(member.value for member in enum_cls)}"
    )


def _unique_refs(value: object) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError("evidence_refs must be a list of strings")
    result: List[str] = []
    seen = set()
    for raw in value:
        ref = _required_text(raw, "evidence_refs")
        if ref not in seen:
            seen.add(ref)
            result.append(ref)
    return result


_SCOPE_RANK = {
    MemoryScopeLevel.GLOBAL: 0,
    MemoryScopeLevel.BUSINESS: 1,
    MemoryScopeLevel.PROJECT: 2,
    MemoryScopeLevel.BRAND: 3,
    MemoryScopeLevel.PRODUCT: 4,
    MemoryScopeLevel.CAMPAIGN: 5,
}


class MemoryCandidate(BaseModel):
    """Semantic proposal to retain a lesson, event, decision, or preference."""

    candidate_id: str
    goal_id: str
    claim_id: str
    agent_id: BrainAgentId
    memory_kind: MemoryKind
    authority: MemoryAuthority
    origin_scope: MemoryScopeLevel
    requested_scope: MemoryScopeLevel
    evidence_verdict: ClaimVerdict
    evidence_refs: List[str] = Field(default_factory=list)
    independent_run_count: int = Field(default=1, ge=1)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.candidate_id = _required_text(self.candidate_id, "candidate_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.claim_id = _required_text(self.claim_id, "claim_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.memory_kind = _enum(self.memory_kind, MemoryKind, "memory_kind")
        self.authority = _enum(self.authority, MemoryAuthority, "authority")
        self.origin_scope = _enum(self.origin_scope, MemoryScopeLevel, "origin_scope")
        self.requested_scope = _enum(
            self.requested_scope, MemoryScopeLevel, "requested_scope"
        )
        self.evidence_verdict = _enum(
            self.evidence_verdict, ClaimVerdict, "evidence_verdict"
        )
        self.evidence_refs = _unique_refs(self.evidence_refs)
        if (
            not isinstance(self.independent_run_count, int)
            or isinstance(self.independent_run_count, bool)
            or self.independent_run_count < 1
        ):
            raise ValidationError("independent_run_count must be an integer >= 1")


class MemoryDecision(BaseModel):
    """Auditable Brain decision about memory durability and semantic scope."""

    candidate_id: str
    disposition: MemoryDisposition
    effective_scope: MemoryScopeLevel
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.candidate_id = _required_text(self.candidate_id, "candidate_id")
        self.disposition = _enum(self.disposition, MemoryDisposition, "disposition")
        self.effective_scope = _enum(
            self.effective_scope, MemoryScopeLevel, "effective_scope"
        )
        if not isinstance(self.reasons, list):
            raise ValidationError("reasons must be a list of strings")
        normalized: List[str] = []
        seen = set()
        for raw in self.reasons:
            reason = _required_text(raw, "reasons")
            if reason not in seen:
                seen.add(reason)
                normalized.append(reason)
        if not normalized:
            raise ValidationError("reasons must contain at least one decision reason")
        self.reasons = normalized


def _would_broaden_scope(candidate: MemoryCandidate) -> bool:
    return _SCOPE_RANK[candidate.requested_scope] < _SCOPE_RANK[candidate.origin_scope]


def evaluate_memory_candidate(candidate: MemoryCandidate) -> MemoryDecision:
    """Classify a semantic memory candidate using fail-closed durability rules."""

    if not isinstance(candidate, MemoryCandidate):
        raise ValidationError("candidate must be a MemoryCandidate")

    if _would_broaden_scope(candidate):
        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            disposition=MemoryDisposition.REJECTED,
            effective_scope=candidate.origin_scope,
            reasons=[
                "memory scope cannot be broadened beyond the scope in which it was established"
            ],
        )

    effective_scope = candidate.requested_scope

    if candidate.memory_kind == MemoryKind.WORKING:
        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            disposition=MemoryDisposition.EPHEMERAL,
            effective_scope=effective_scope,
            reasons=["working memory is session/run context and is not durable learning"],
        )

    if candidate.memory_kind == MemoryKind.USER_BRAND_PREFERENCE:
        if candidate.authority == MemoryAuthority.USER_CONFIRMED:
            return MemoryDecision(
                candidate_id=candidate.candidate_id,
                disposition=MemoryDisposition.PROMOTED,
                effective_scope=effective_scope,
                reasons=[
                    "explicit user confirmation is authoritative for user/brand preference memory"
                ],
            )
        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            disposition=MemoryDisposition.EPHEMERAL,
            effective_scope=effective_scope,
            reasons=[
                "agent-inferred or merely observed preference cannot become durable user authority"
            ],
        )

    if candidate.evidence_verdict == ClaimVerdict.REFUTED:
        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            disposition=MemoryDisposition.REJECTED,
            effective_scope=effective_scope,
            reasons=["refuted claims cannot be retained as valid memory"],
        )

    if candidate.evidence_verdict in {
        ClaimVerdict.CONTESTED,
        ClaimVerdict.INSUFFICIENT,
    }:
        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            disposition=MemoryDisposition.EPHEMERAL,
            effective_scope=effective_scope,
            reasons=[
                "contested or insufficient evidence cannot create durable memory authority"
            ],
        )

    if candidate.authority != MemoryAuthority.OBSERVED:
        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            disposition=MemoryDisposition.CANDIDATE,
            effective_scope=effective_scope,
            reasons=[
                "supported but non-observed memory remains a candidate until independently observed"
            ],
        )

    if not candidate.evidence_refs:
        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            disposition=MemoryDisposition.EPHEMERAL,
            effective_scope=effective_scope,
            reasons=[
                "observed durable memory requires explicit evidence references"
            ],
        )

    if candidate.independent_run_count == 1:
        disposition = MemoryDisposition.CANDIDATE
        reason = "a single supported run is not enough for durable generalization"
    elif candidate.independent_run_count == 2:
        disposition = MemoryDisposition.VERIFIED
        reason = "two independent supported runs are enough to verify the scoped memory"
    elif candidate.memory_kind in {
        MemoryKind.EXPERIMENT,
        MemoryKind.SUCCESS_FAILURE,
    }:
        disposition = MemoryDisposition.PROMOTED
        reason = "repeated independent supported runs justify scoped institutional learning"
    else:
        disposition = MemoryDisposition.VERIFIED
        reason = "the memory is verified but its kind is not an institutional learning class"

    return MemoryDecision(
        candidate_id=candidate.candidate_id,
        disposition=disposition,
        effective_scope=effective_scope,
        reasons=[reason],
    )
