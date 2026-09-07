"""Continuity Runtime Mission and Commitment domain contracts.

This module is intentionally deterministic runtime infrastructure.  It does not
perform Brain reasoning or decide marketing strategy.  Its first trust-boundary
invariant is fail-closed: a Mission cannot enter executable READY state without
an active, non-expired Commitment bound to the same mission and authoritative
scope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from schemas.base import BaseModel, Field


class MissionCommitmentError(ValueError):
    """Raised when a Mission cannot safely bind an executable Commitment."""


class CommitmentMutationError(ValueError):
    """Raised when immutable Commitment identity or scope is rebound."""


class MissionTransitionError(ValueError):
    """Raised when a Mission lifecycle transition violates runtime authority."""


class MissionStatus(str, Enum):
    """Durable lifecycle states for a long-lived Continuity Runtime Mission."""

    CREATED = "CREATED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    WAITING_FOR_TIME = "WAITING_FOR_TIME"
    WAITING_FOR_EVENT = "WAITING_FOR_EVENT"
    WAITING_FOR_CONDITION = "WAITING_FOR_CONDITION"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_FOR_RESULT = "WAITING_FOR_RESULT"
    SLEEPING = "SLEEPING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


TERMINAL_MISSION_STATUSES = frozenset(
    {
        MissionStatus.COMPLETED,
        MissionStatus.CANCELLED,
        MissionStatus.FAILED,
        MissionStatus.EXPIRED,
    }
)


class CommitmentRecord(BaseModel):
    """Runtime-enforceable authority and limit envelope for one Mission."""

    commitment_id: str = Field(..., min_length=1)
    mission_id: str = Field(..., min_length=1)
    business_id: str = Field(..., min_length=1)
    project_id: Optional[str] = None
    user_id: str = Field(..., min_length=1)
    authority_mode: str = Field(..., min_length=1)
    active: bool = True
    deadline_at: Optional[datetime] = None
    budget_limits: Dict[str, float] = Field(default_factory=dict)
    stop_conditions: List[str] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __setattr__(self, name: str, value: object) -> None:
        """Keep Commitment identity and authoritative scope bound after creation.

        Authority-envelope mutation/revision semantics are intentionally outside
        this slice. Same-value assignment remains idempotent.
        """

        immutable_fields = {
            "commitment_id",
            "mission_id",
            "business_id",
            "project_id",
            "user_id",
        }
        if name in immutable_fields and name in self.__dict__:
            current_value = self.__dict__[name]
            if value != current_value:
                raise CommitmentMutationError(
                    f"COMMITMENT_IDENTITY_SCOPE_IMMUTABLE: {name}"
                )

        object.__setattr__(self, name, value)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Return whether this Commitment is past its absolute deadline.

        Naive deadlines are rejected fail-closed because comparing them against
        an authoritative UTC clock would otherwise depend on ambient timezone.
        """

        if self.deadline_at is None:
            return False
        if self.deadline_at.tzinfo is None or self.deadline_at.utcoffset() is None:
            return True
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None or reference.utcoffset() is None:
            raise MissionCommitmentError("COMMITMENT_REFERENCE_TIME_MUST_BE_TIMEZONE_AWARE")
        return self.deadline_at <= reference


class MissionRecord(BaseModel):
    """Durable responsibility record independent of a single RuntimeContext run."""

    mission_id: str = Field(..., min_length=1)
    objective: str = Field(..., min_length=1)
    business_id: str = Field(..., min_length=1)
    project_id: Optional[str] = None
    user_id: str = Field(..., min_length=1)
    status: MissionStatus = MissionStatus.CREATED
    commitment_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __setattr__(self, name: str, value: object) -> None:
        """Protect Mission lifecycle and authoritative scope from unsafe mutation.

        This slice deliberately does not define the complete non-terminal FSM.
        It establishes two one-way invariants: terminal Missions can never be
        revived, and executable Mission identity/scope cannot be rebound after
        the Mission leaves CREATED. Re-assigning the same value remains
        idempotent.
        """

        if name in {"mission_id", "business_id", "project_id", "user_id"} and name in self.__dict__:
            current_value = self.__dict__[name]
            status_raw = self.__dict__.get("status", MissionStatus.CREATED)
            try:
                status = status_raw if isinstance(status_raw, MissionStatus) else MissionStatus(status_raw)
            except (TypeError, ValueError):
                status = status_raw

            if status != MissionStatus.CREATED and value != current_value:
                raise MissionTransitionError(
                    f"MISSION_AUTHORITATIVE_SCOPE_IMMUTABLE: {name}"
                )

        if name == "status" and "status" in self.__dict__:
            current_raw = self.__dict__["status"]
            try:
                current = (
                    current_raw
                    if isinstance(current_raw, MissionStatus)
                    else MissionStatus(current_raw)
                )
            except (TypeError, ValueError):
                current = current_raw

            try:
                target = value if isinstance(value, MissionStatus) else MissionStatus(value)
            except (TypeError, ValueError):
                target = value

            if current in TERMINAL_MISSION_STATUSES and target != current:
                current_label = current.value if isinstance(current, MissionStatus) else str(current)
                target_label = target.value if isinstance(target, MissionStatus) else str(target)
                raise MissionTransitionError(
                    f"MISSION_TERMINAL_STATE_IMMUTABLE: {current_label}->{target_label}"
                )

        object.__setattr__(self, name, value)

    def _validate_executable_commitment(
        self,
        commitment: Optional[CommitmentRecord],
        *,
        now: Optional[datetime] = None,
    ) -> CommitmentRecord:
        """Validate the canonical trust boundary without mutating Mission state."""

        if commitment is None:
            raise MissionCommitmentError("MISSION_COMMITMENT_REQUIRED")
        if not isinstance(commitment, CommitmentRecord):
            raise MissionCommitmentError("MISSION_COMMITMENT_INVALID_TYPE")
        if not commitment.active:
            raise MissionCommitmentError("MISSION_COMMITMENT_INACTIVE")
        if commitment.is_expired(now=now):
            raise MissionCommitmentError("MISSION_COMMITMENT_EXPIRED")
        if commitment.mission_id != self.mission_id:
            raise MissionCommitmentError("MISSION_COMMITMENT_MISSION_MISMATCH")
        if commitment.business_id != self.business_id:
            raise MissionCommitmentError("MISSION_COMMITMENT_BUSINESS_SCOPE_MISMATCH")
        if commitment.project_id != self.project_id:
            raise MissionCommitmentError("MISSION_COMMITMENT_PROJECT_SCOPE_MISMATCH")
        if commitment.user_id != self.user_id:
            raise MissionCommitmentError("MISSION_COMMITMENT_USER_SCOPE_MISMATCH")
        return commitment

    def mark_ready(
        self,
        commitment: Optional[CommitmentRecord],
        *,
        now: Optional[datetime] = None,
    ) -> None:
        """Enter executable READY state only after the Commitment passes all gates.

        Validation happens before either field is changed so every rejection is
        atomic from the caller's perspective: the Mission remains non-executable
        and unbound after a failed attempt.
        """

        if self.status != MissionStatus.CREATED:
            raise MissionCommitmentError(
                f"MISSION_READY_TRANSITION_INVALID_FROM_{self.status.value}"
            )

        validated = self._validate_executable_commitment(commitment, now=now)
        self.commitment_id = validated.commitment_id
        self.status = MissionStatus.READY
