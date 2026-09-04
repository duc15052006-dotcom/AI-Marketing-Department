"""Provider-neutral adaptive reasoning policy for the Brain layer.

The Brain requests a semantic reasoning depth. It never selects provider-native
parameters such as token budgets, vendor-specific effort labels, or model IDs.
A later Body integration layer may map these semantic depths to capabilities
actually supported by the selected model.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Type, TypeVar

from brain.contracts import BrainAgentId
from schemas.base import BaseModel, Field, ValidationError


class ReasoningDepth(str, Enum):
    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP = "DEEP"
    VERY_DEEP = "VERY_DEEP"
    MAXIMUM = "MAXIMUM"


class SignalLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Reversibility(str, Enum):
    REVERSIBLE = "REVERSIBLE"
    COSTLY_TO_REVERSE = "COSTLY_TO_REVERSE"
    IRREVERSIBLE = "IRREVERSIBLE"


E = TypeVar("E", bound=Enum)
_DEPTH_RANK = {
    ReasoningDepth.FAST: 0,
    ReasoningDepth.BALANCED: 1,
    ReasoningDepth.DEEP: 2,
    ReasoningDepth.VERY_DEEP: 3,
    ReasoningDepth.MAXIMUM: 4,
}


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field_name} must be a boolean")
    return value


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


def _max_depth(current: ReasoningDepth, floor: ReasoningDepth) -> ReasoningDepth:
    return floor if _DEPTH_RANK[floor] > _DEPTH_RANK[current] else current


class ReasoningAssessment(BaseModel):
    """Cognitive signals used to choose how deeply an agent should reason."""

    assessment_id: str
    goal_id: str
    agent_id: BrainAgentId
    complexity: SignalLevel = SignalLevel.MEDIUM
    uncertainty: SignalLevel = SignalLevel.MEDIUM
    consequence: SignalLevel = SignalLevel.MEDIUM
    evidence_conflict: SignalLevel = SignalLevel.LOW
    reversibility: Reversibility = Reversibility.REVERSIBLE
    causal_reasoning_required: bool = False
    contradiction_resolution_required: bool = False
    minimum_depth: ReasoningDepth = ReasoningDepth.FAST

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.complexity = _enum(self.complexity, SignalLevel, "complexity")
        self.uncertainty = _enum(self.uncertainty, SignalLevel, "uncertainty")
        self.consequence = _enum(self.consequence, SignalLevel, "consequence")
        self.evidence_conflict = _enum(
            self.evidence_conflict, SignalLevel, "evidence_conflict"
        )
        self.reversibility = _enum(
            self.reversibility, Reversibility, "reversibility"
        )
        self.causal_reasoning_required = _strict_bool(
            self.causal_reasoning_required, "causal_reasoning_required"
        )
        self.contradiction_resolution_required = _strict_bool(
            self.contradiction_resolution_required,
            "contradiction_resolution_required",
        )
        self.minimum_depth = _enum(
            self.minimum_depth, ReasoningDepth, "minimum_depth"
        )


class ReasoningDecision(BaseModel):
    """Auditable semantic reasoning request produced by the Brain policy."""

    assessment_id: str
    goal_id: str
    agent_id: BrainAgentId
    depth: ReasoningDepth
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.depth = _enum(self.depth, ReasoningDepth, "depth")
        if not isinstance(self.reasons, list) or not self.reasons:
            raise ValidationError("reasons must contain at least one policy reason")
        normalized: List[str] = []
        seen = set()
        for raw in self.reasons:
            reason = _required_text(raw, "reasons")
            if reason not in seen:
                seen.add(reason)
                normalized.append(reason)
        self.reasons = normalized


def select_reasoning_depth(assessment: ReasoningAssessment) -> ReasoningDecision:
    """Choose a semantic reasoning depth using conservative cognitive floors.

    The policy is intentionally monotonic: stronger risk/uncertainty signals can
    only raise reasoning depth. A caller-supplied minimum is a floor, never a
    way to bypass a stronger policy requirement.
    """

    if not isinstance(assessment, ReasoningAssessment):
        raise ValidationError("assessment must be a ReasoningAssessment")

    signals = (
        assessment.complexity,
        assessment.uncertainty,
        assessment.consequence,
        assessment.evidence_conflict,
    )
    high_or_critical = sum(
        level in (SignalLevel.HIGH, SignalLevel.CRITICAL) for level in signals
    )
    all_low = all(level == SignalLevel.LOW for level in signals)

    depth = ReasoningDepth.FAST if all_low else ReasoningDepth.BALANCED
    reasons: List[str] = [
        "all cognitive signals are LOW"
        if all_low
        else "non-trivial cognitive signals require at least BALANCED reasoning"
    ]

    if any(
        level in (SignalLevel.HIGH, SignalLevel.CRITICAL) for level in signals
    ):
        depth = _max_depth(depth, ReasoningDepth.DEEP)
        reasons.append("at least one cognitive signal is HIGH or CRITICAL")

    if any(level == SignalLevel.CRITICAL for level in signals):
        depth = _max_depth(depth, ReasoningDepth.VERY_DEEP)
        reasons.append("a CRITICAL cognitive signal requires very deep scrutiny")

    if high_or_critical >= 2:
        depth = _max_depth(depth, ReasoningDepth.VERY_DEEP)
        reasons.append("multiple HIGH/CRITICAL signals interact")

    if assessment.evidence_conflict == SignalLevel.HIGH:
        depth = _max_depth(depth, ReasoningDepth.VERY_DEEP)
        reasons.append("HIGH evidence conflict requires contradiction-aware review")

    if assessment.evidence_conflict == SignalLevel.CRITICAL:
        depth = _max_depth(depth, ReasoningDepth.MAXIMUM)
        reasons.append("CRITICAL evidence conflict requires maximum scrutiny")

    if assessment.consequence == SignalLevel.CRITICAL:
        depth = _max_depth(depth, ReasoningDepth.MAXIMUM)
        reasons.append("CRITICAL decision consequence requires maximum scrutiny")

    if assessment.reversibility == Reversibility.COSTLY_TO_REVERSE:
        depth = _max_depth(depth, ReasoningDepth.VERY_DEEP)
        reasons.append("decision is costly to reverse")
    elif assessment.reversibility == Reversibility.IRREVERSIBLE:
        depth = _max_depth(depth, ReasoningDepth.MAXIMUM)
        reasons.append("decision is irreversible")

    if assessment.causal_reasoning_required:
        depth = _max_depth(depth, ReasoningDepth.DEEP)
        reasons.append("causal reasoning requires a DEEP floor")

    if assessment.contradiction_resolution_required:
        depth = _max_depth(depth, ReasoningDepth.VERY_DEEP)
        reasons.append("explicit contradiction resolution requires a VERY_DEEP floor")

    before_minimum = depth
    depth = _max_depth(depth, assessment.minimum_depth)
    if depth != before_minimum:
        reasons.append(
            f"task policy requested minimum semantic depth {assessment.minimum_depth.value}"
        )

    return ReasoningDecision(
        assessment_id=assessment.assessment_id,
        goal_id=assessment.goal_id,
        agent_id=assessment.agent_id,
        depth=depth,
        reasons=reasons,
    )
