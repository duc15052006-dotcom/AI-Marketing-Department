"""Long-horizon semantic checkpoint/resume validation for the five-ASI Brain.

A checkpoint is a cognitive snapshot that another trusted layer may store and
reload.  This module does not write files, databases, queues, schedules, or
worker state.  It reconstructs canonical Brain models at the use boundary,
proves the supplied continuity that can be proven semantically, and chooses
whether cognition may resume or must research, replan, reassess, or stop.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.autonomous_loop import (
    AutonomousCognitiveLoopDecision,
    AutonomousCognitiveLoopRequest,
    derive_autonomous_cognitive_loop,
)
from brain.cognitive_loop import CognitivePhase
from brain.contracts import BrainAgentId, GoalSpec, GoalStatus
from brain.planning import PlanSnapshot, PlanStatus
from brain.world_state import WorldStateSnapshot
from schemas.base import BaseModel, Field, ValidationError


class ResumeDisposition(str, Enum):
    """Semantic disposition for continuing one suspended cognitive lineage."""

    RESUME = "RESUME"
    RESEARCH_REQUIRED = "RESEARCH_REQUIRED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    REASSESS_REQUIRED = "REASSESS_REQUIRED"
    TERMINAL = "TERMINAL"


class ResumeDirectiveKind(str, Enum):
    """Provider-neutral next move after checkpoint continuity validation."""

    RESUME_COGNITION = "RESUME_COGNITION"
    RESEARCH = "RESEARCH"
    REPLAN = "REPLAN"
    REASSESS = "REASSESS"
    STOP = "STOP"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return _required_text(value, field_name)


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{field_name} must be a positive integer")
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


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must be a {expected_type.__name__} or serialized mapping"
    )


def _canonical_autonomous_request(raw: object) -> AutonomousCognitiveLoopRequest:
    return AutonomousCognitiveLoopRequest(
        **_payload(raw, AutonomousCognitiveLoopRequest, "autonomous_request")
    )


def _canonical_world_state(raw: object) -> WorldStateSnapshot:
    return WorldStateSnapshot(**_payload(raw, WorldStateSnapshot, "world_state"))


def _unique_text_list(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list")
    result: List[str] = []
    seen = set()
    for raw in value:
        item = _required_text(raw, field_name)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


class ResumeDirective(BaseModel):
    kind: ResumeDirectiveKind
    target_ids: List[str] = Field(default_factory=list)
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.kind = _enum(self.kind, ResumeDirectiveKind, "kind")
        self.target_ids = _unique_text_list(self.target_ids, "target_ids")
        self.rationale = _required_text(self.rationale, "rationale")


class CognitiveCheckpoint(BaseModel):
    """One semantic suspension point; storage remains outside the Brain."""

    checkpoint_id: str
    sequence: int
    agent_id: BrainAgentId
    autonomous_request: AutonomousCognitiveLoopRequest
    reason: str
    previous_checkpoint_id: Optional[str] = None
    world_state: Optional[WorldStateSnapshot] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.checkpoint_id = _required_text(self.checkpoint_id, "checkpoint_id")
        self.sequence = _positive_int(self.sequence, "sequence")
        self.previous_checkpoint_id = _optional_text(
            self.previous_checkpoint_id, "previous_checkpoint_id"
        )
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.autonomous_request = _canonical_autonomous_request(
            self.autonomous_request
        )
        self.reason = _required_text(self.reason, "reason")

        if self.sequence == 1 and self.previous_checkpoint_id is not None:
            raise ValidationError(
                "initial checkpoint sequence cannot declare previous_checkpoint_id"
            )
        if self.sequence > 1 and self.previous_checkpoint_id is None:
            raise ValidationError(
                "non-initial checkpoint sequence requires previous_checkpoint_id"
            )
        if self.previous_checkpoint_id == self.checkpoint_id:
            raise ValidationError("checkpoint cannot reference itself as previous")

        goal = self.autonomous_request.cognitive_cycle.goal
        if goal.owner_agent != self.agent_id:
            raise ValidationError(
                "checkpoint agent_id must exactly match the suspended goal owner"
            )

        if self.world_state is not None:
            self.world_state = _canonical_world_state(self.world_state)
            if self.world_state.goal_id != goal.goal_id:
                raise ValidationError(
                    "checkpoint world_state goal_id must match suspended goal_id"
                )
            if self.world_state.agent_id != self.agent_id:
                raise ValidationError(
                    "checkpoint world_state agent_id must match checkpoint agent_id"
                )


class CheckpointResumeRequest(BaseModel):
    """Current semantic state plus the runtime-observed checkpoint identity."""

    resume_id: str
    checkpoint: CognitiveCheckpoint
    observed_latest_checkpoint_id: str
    observed_latest_sequence: int
    current_request: AutonomousCognitiveLoopRequest
    current_world_state: Optional[WorldStateSnapshot] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.resume_id = _required_text(self.resume_id, "resume_id")
        self.checkpoint = CognitiveCheckpoint(
            **_payload(self.checkpoint, CognitiveCheckpoint, "checkpoint")
        )
        self.observed_latest_checkpoint_id = _required_text(
            self.observed_latest_checkpoint_id,
            "observed_latest_checkpoint_id",
        )
        self.observed_latest_sequence = _positive_int(
            self.observed_latest_sequence,
            "observed_latest_sequence",
        )
        self.current_request = _canonical_autonomous_request(self.current_request)
        if self.current_world_state is not None:
            self.current_world_state = _canonical_world_state(
                self.current_world_state
            )

        suspended_goal = self.checkpoint.autonomous_request.cognitive_cycle.goal
        current_goal = self.current_request.cognitive_cycle.goal
        _validate_immutable_goal_identity(suspended_goal, current_goal)
        if current_goal.owner_agent != self.checkpoint.agent_id:
            raise ValidationError(
                "current goal owner must exactly match checkpoint agent_id"
            )

        if self.current_world_state is not None:
            if self.current_world_state.goal_id != current_goal.goal_id:
                raise ValidationError(
                    "current_world_state goal_id must match resumed goal_id"
                )
            if self.current_world_state.agent_id != self.checkpoint.agent_id:
                raise ValidationError(
                    "current_world_state agent_id must match checkpoint agent_id"
                )


class CheckpointResumeDecision(BaseModel):
    """Detached semantic result; it grants no external execution authority."""

    resume_id: str
    checkpoint_id: str
    disposition: ResumeDisposition
    directive: ResumeDirective
    autonomous_decision: AutonomousCognitiveLoopDecision

    def __post_init__(self) -> None:
        super().__post_init__()
        self.resume_id = _required_text(self.resume_id, "resume_id")
        self.checkpoint_id = _required_text(self.checkpoint_id, "checkpoint_id")
        self.disposition = _enum(
            self.disposition, ResumeDisposition, "disposition"
        )
        self.directive = ResumeDirective(
            **_payload(self.directive, ResumeDirective, "directive")
        )
        self.autonomous_decision = AutonomousCognitiveLoopDecision(
            **_payload(
                self.autonomous_decision,
                AutonomousCognitiveLoopDecision,
                "autonomous_decision",
            )
        )


def _validate_immutable_goal_identity(
    suspended_goal: GoalSpec,
    current_goal: GoalSpec,
) -> None:
    immutable_fields = (
        "goal_id",
        "objective",
        "owner_agent",
        "success_criteria",
        "constraints",
        "parent_goal_id",
    )
    for field_name in immutable_fields:
        if getattr(suspended_goal, field_name) != getattr(current_goal, field_name):
            raise ValidationError(
                f"resumed goal {field_name} must match checkpoint goal identity"
            )


def _canonical_request(raw: object) -> CheckpointResumeRequest:
    if not isinstance(raw, CheckpointResumeRequest):
        raise ValidationError("request must be a CheckpointResumeRequest")
    return CheckpointResumeRequest(**copy.deepcopy(raw.model_dump()))


def _directive(
    kind: ResumeDirectiveKind,
    target_ids: List[str],
    rationale: str,
) -> ResumeDirective:
    return ResumeDirective(
        kind=kind,
        target_ids=list(target_ids),
        rationale=rationale,
    )


def _result(
    *,
    request: CheckpointResumeRequest,
    disposition: ResumeDisposition,
    directive: ResumeDirective,
    autonomous_decision: AutonomousCognitiveLoopDecision,
) -> CheckpointResumeDecision:
    return CheckpointResumeDecision(
        resume_id=request.resume_id,
        checkpoint_id=request.checkpoint.checkpoint_id,
        disposition=disposition,
        directive=directive.model_copy(deep=True),
        autonomous_decision=autonomous_decision.model_copy(deep=True),
    )


def _validate_fresh_checkpoint(request: CheckpointResumeRequest) -> None:
    checkpoint = request.checkpoint
    if (
        request.observed_latest_checkpoint_id != checkpoint.checkpoint_id
        or request.observed_latest_sequence != checkpoint.sequence
    ):
        raise ValidationError(
            "selected checkpoint is stale relative to observed latest checkpoint identity"
        )


def _plan_continuity(
    checkpoint_plan: Optional[PlanSnapshot],
    current_plan: Optional[PlanSnapshot],
) -> tuple[Optional[ResumeDisposition], List[str]]:
    if checkpoint_plan is None and current_plan is None:
        return None, []
    if checkpoint_plan is not None and current_plan is None:
        raise ValidationError(
            "current semantic state cannot silently lose the checkpoint plan"
        )
    if checkpoint_plan is None and current_plan is not None:
        return ResumeDisposition.REASSESS_REQUIRED, [current_plan.plan_id]

    assert checkpoint_plan is not None and current_plan is not None

    if current_plan.plan_id != checkpoint_plan.plan_id:
        return ResumeDisposition.REPLAN_REQUIRED, [current_plan.plan_id]
    if current_plan.revision < checkpoint_plan.revision:
        raise ValidationError("plan revision rollback across resume is forbidden")
    if current_plan.revision > checkpoint_plan.revision:
        if (
            current_plan.revision != checkpoint_plan.revision + 1
            or current_plan.parent_revision != checkpoint_plan.revision
        ):
            raise ValidationError(
                "newer plan revision must prove contiguous checkpoint lineage"
            )
        return ResumeDisposition.REASSESS_REQUIRED, [current_plan.plan_id]

    if current_plan.status in {PlanStatus.NEEDS_REVISION, PlanStatus.ABANDONED}:
        return ResumeDisposition.REPLAN_REQUIRED, [current_plan.plan_id]

    if current_plan.model_dump() != checkpoint_plan.model_dump():
        return ResumeDisposition.REASSESS_REQUIRED, [current_plan.plan_id]

    return None, []


def _world_continuity(
    checkpoint_world: Optional[WorldStateSnapshot],
    current_world: Optional[WorldStateSnapshot],
) -> tuple[Optional[ResumeDisposition], List[str]]:
    if checkpoint_world is None and current_world is None:
        return None, []
    if checkpoint_world is not None and current_world is None:
        raise ValidationError(
            "current semantic state cannot silently lose checkpoint world state"
        )
    if checkpoint_world is None and current_world is not None:
        return ResumeDisposition.REASSESS_REQUIRED, [current_world.snapshot_id]

    assert checkpoint_world is not None and current_world is not None

    if current_world.snapshot_id == checkpoint_world.snapshot_id:
        if current_world.model_dump() != checkpoint_world.model_dump():
            raise ValidationError(
                "same world-state snapshot_id cannot be semantically rewritten"
            )
        return None, []

    if current_world.previous_snapshot_id != checkpoint_world.snapshot_id:
        raise ValidationError(
            "new world state must directly bind the checkpoint world-state snapshot"
        )
    return ResumeDisposition.REASSESS_REQUIRED, [current_world.snapshot_id]


def resume_cognition(raw_request: CheckpointResumeRequest) -> CheckpointResumeDecision:
    """Validate continuity and derive one safe semantic resume disposition."""

    request = _canonical_request(raw_request)
    _validate_fresh_checkpoint(request)

    current_goal = request.current_request.cognitive_cycle.goal
    autonomous_decision = derive_autonomous_cognitive_loop(request.current_request)

    if current_goal.status in {GoalStatus.SATISFIED, GoalStatus.ABANDONED}:
        return _result(
            request=request,
            disposition=ResumeDisposition.TERMINAL,
            directive=_directive(
                ResumeDirectiveKind.STOP,
                [current_goal.goal_id],
                "the canonical goal is terminal and must not resume",
            ),
            autonomous_decision=autonomous_decision,
        )

    if current_goal.status == GoalStatus.BLOCKED or autonomous_decision.phase == CognitivePhase.BLOCKED:
        return _result(
            request=request,
            disposition=ResumeDisposition.REASSESS_REQUIRED,
            directive=_directive(
                ResumeDirectiveKind.REASSESS,
                [current_goal.goal_id],
                "the canonical goal is blocked; blind continuation is forbidden",
            ),
            autonomous_decision=autonomous_decision,
        )

    checkpoint_plan = request.checkpoint.autonomous_request.cognitive_cycle.plan
    current_plan = request.current_request.cognitive_cycle.plan
    plan_disposition, plan_targets = _plan_continuity(
        checkpoint_plan, current_plan
    )
    world_disposition, world_targets = _world_continuity(
        request.checkpoint.world_state,
        request.current_world_state,
    )

    if autonomous_decision.phase == CognitivePhase.RESEARCH:
        return _result(
            request=request,
            disposition=ResumeDisposition.RESEARCH_REQUIRED,
            directive=_directive(
                ResumeDirectiveKind.RESEARCH,
                list(autonomous_decision.directive.target_ids),
                "current canonical cognition requires knowledge reduction before resume",
            ),
            autonomous_decision=autonomous_decision,
        )

    if plan_disposition == ResumeDisposition.REPLAN_REQUIRED or autonomous_decision.phase == CognitivePhase.REPLANNING:
        targets = plan_targets or [current_goal.goal_id]
        return _result(
            request=request,
            disposition=ResumeDisposition.REPLAN_REQUIRED,
            directive=_directive(
                ResumeDirectiveKind.REPLAN,
                targets,
                "plan continuity requires canonical replanning before resume",
            ),
            autonomous_decision=autonomous_decision,
        )

    if world_disposition == ResumeDisposition.REASSESS_REQUIRED:
        return _result(
            request=request,
            disposition=ResumeDisposition.REASSESS_REQUIRED,
            directive=_directive(
                ResumeDirectiveKind.REASSESS,
                world_targets,
                "world-state continuity changed and must be reassessed before resume",
            ),
            autonomous_decision=autonomous_decision,
        )

    if plan_disposition == ResumeDisposition.REASSESS_REQUIRED:
        return _result(
            request=request,
            disposition=ResumeDisposition.REASSESS_REQUIRED,
            directive=_directive(
                ResumeDirectiveKind.REASSESS,
                plan_targets,
                "plan lineage advanced and must be reassessed before resume",
            ),
            autonomous_decision=autonomous_decision,
        )

    return _result(
        request=request,
        disposition=ResumeDisposition.RESUME,
        directive=_directive(
            ResumeDirectiveKind.RESUME_COGNITION,
            [request.checkpoint.checkpoint_id],
            "checkpoint identity and current semantic continuity are consistent",
        ),
        autonomous_decision=autonomous_decision,
    )
