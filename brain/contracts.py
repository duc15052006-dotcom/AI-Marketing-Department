"""Clean cognitive contracts for the five permanent marketing agents.

The brain expresses *what it believes it needs to do*, never *how an external
system executes it*.  Consequently these contracts contain no provider IDs,
tool IDs, queue state, connector details, credentials, or persistence concerns.

BRAIN-1 deliberately stops before planning implementation.  Planning/replanning
will build on these stable primitives rather than turning this module into a
monolithic "god schema".
"""

from __future__ import annotations

import math
import re
from enum import Enum
from typing import List, Optional, Type, TypeVar

from schemas.base import BaseModel, Field, ValidationError


class BrainAgentId(str, Enum):
    """Exactly five permanent logical agents. Ephemeral workers are not agents."""

    CMO = "CMO"
    INTELLIGENCE = "INTELLIGENCE"
    STRATEGIST = "STRATEGIST"
    CREATIVE = "CREATIVE"
    PERFORMANCE = "PERFORMANCE"


class GoalStatus(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    SATISFIED = "SATISFIED"
    ABANDONED = "ABANDONED"


class DecisionDisposition(str, Enum):
    PROCEED = "PROCEED"
    REVISE = "REVISE"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


class StopReason(str, Enum):
    CONTINUE = "CONTINUE"
    GOAL_SATISFIED = "GOAL_SATISFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BLOCKED = "BLOCKED"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    POLICY_BOUNDARY = "POLICY_BOUNDARY"
    FAILED = "FAILED"


E = TypeVar("E", bound=Enum)
_CAPABILITY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string or None")
    stripped = value.strip()
    return stripped or None


def _text_list(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of strings")
    seen = set()
    result: List[str] = []
    for raw in value:
        item = _required_text(raw, field_name)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _enum(value: object, enum_cls: Type[E], field_name: str) -> E:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().upper())
        except ValueError as exc:
            pass
    raise ValidationError(
        f"{field_name} must be one of: {', '.join(member.value for member in enum_cls)}"
    )


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field_name} must be a boolean")
    return value


def _confidence(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("confidence must be a number between 0 and 1 or None")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0 or numeric > 1.0:
        raise ValidationError("confidence must be finite and between 0 and 1")
    return numeric


class GoalSpec(BaseModel):
    """A semantic goal owned by one of the five permanent agents."""

    goal_id: str
    objective: str
    owner_agent: BrainAgentId
    success_criteria: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    parent_goal_id: Optional[str] = None
    status: GoalStatus = GoalStatus.OPEN

    def __post_init__(self) -> None:
        super().__post_init__()
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.objective = _required_text(self.objective, "objective")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.success_criteria = _text_list(self.success_criteria, "success_criteria")
        self.constraints = _text_list(self.constraints, "constraints")
        self.parent_goal_id = _optional_text(self.parent_goal_id, "parent_goal_id")
        self.status = _enum(self.status, GoalStatus, "status")
        if self.parent_goal_id == self.goal_id:
            raise ValidationError("parent_goal_id cannot equal goal_id")


class EvidenceNeed(BaseModel):
    """A question whose answer would reduce uncertainty for a goal/decision."""

    need_id: str
    goal_id: str
    question: str
    why_needed: str
    blocking: bool = False
    evidence_refs: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.need_id = _required_text(self.need_id, "need_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.question = _required_text(self.question, "question")
        self.why_needed = _required_text(self.why_needed, "why_needed")
        self.blocking = _strict_bool(self.blocking, "blocking")
        self.evidence_refs = _text_list(self.evidence_refs, "evidence_refs")


class UnknownRecord(BaseModel):
    """An explicit unknown; uncertainty is data, not a prompt failure."""

    unknown_id: str
    goal_id: str
    question: str
    consequence: str
    blocking: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        self.unknown_id = _required_text(self.unknown_id, "unknown_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.question = _required_text(self.question, "question")
        self.consequence = _required_text(self.consequence, "consequence")
        self.blocking = _strict_bool(self.blocking, "blocking")


class ActionIntent(BaseModel):
    """A provider-neutral statement of a capability the brain needs.

    ``capability_need`` is semantic (e.g. MARKET_RESEARCH), never a concrete
    tool/provider/connector name. The body is responsible for resolving it.
    """

    intent_id: str
    goal_id: str
    owner_agent: BrainAgentId
    purpose: str
    capability_need: str
    expected_observation: str
    evidence_required: bool = False
    constraints: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.intent_id = _required_text(self.intent_id, "intent_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.purpose = _required_text(self.purpose, "purpose")
        raw_capability = _required_text(self.capability_need, "capability_need").upper()
        if not _CAPABILITY_RE.fullmatch(raw_capability):
            raise ValidationError(
                "capability_need must be a semantic UPPER_SNAKE_CASE identifier"
            )
        self.capability_need = raw_capability
        self.expected_observation = _required_text(
            self.expected_observation, "expected_observation"
        )
        self.evidence_required = _strict_bool(
            self.evidence_required, "evidence_required"
        )
        self.constraints = _text_list(self.constraints, "constraints")


class DecisionRecord(BaseModel):
    """A brain decision with explicit rationale, evidence lineage and uncertainty."""

    decision_id: str
    goal_id: str
    agent_id: BrainAgentId
    statement: str
    rationale: str
    disposition: DecisionDisposition = DecisionDisposition.PROCEED
    evidence_refs: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.decision_id = _required_text(self.decision_id, "decision_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.statement = _required_text(self.statement, "statement")
        self.rationale = _required_text(self.rationale, "rationale")
        self.disposition = _enum(
            self.disposition, DecisionDisposition, "disposition"
        )
        self.evidence_refs = _text_list(self.evidence_refs, "evidence_refs")
        self.confidence = _confidence(self.confidence)


class StopDecision(BaseModel):
    """Explicit stopping semantics so models cannot silently end a trajectory."""

    should_stop: bool
    reason: StopReason
    rationale: str
    unresolved_questions: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.should_stop = _strict_bool(self.should_stop, "should_stop")
        self.reason = _enum(self.reason, StopReason, "reason")
        self.rationale = _required_text(self.rationale, "rationale")
        self.unresolved_questions = _text_list(
            self.unresolved_questions, "unresolved_questions"
        )
        if self.should_stop and self.reason == StopReason.CONTINUE:
            raise ValidationError("A stopping decision cannot use reason=CONTINUE")
        if not self.should_stop and self.reason != StopReason.CONTINUE:
            raise ValidationError("A continuing decision must use reason=CONTINUE")
