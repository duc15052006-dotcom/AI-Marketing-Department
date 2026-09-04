"""Provider-neutral cognitive domain for the five-agent marketing brain.

This package intentionally owns only semantic cognition contracts. It must not
import runtime, tools, provider integrations, persistence, or connector code.
"""

from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    EvidenceNeed,
    GoalSpec,
    GoalStatus,
    StopDecision,
    StopReason,
    UnknownRecord,
)
from brain.planning import (
    PlanRevision,
    PlanSnapshot,
    PlanStatus,
    PlanStep,
    PlanStepState,
    RevisionTrigger,
    apply_plan_revision,
    ready_step_ids,
)

__all__ = [
    "ActionIntent",
    "BrainAgentId",
    "DecisionDisposition",
    "DecisionRecord",
    "EvidenceNeed",
    "GoalSpec",
    "GoalStatus",
    "PlanRevision",
    "PlanSnapshot",
    "PlanStatus",
    "PlanStep",
    "PlanStepState",
    "RevisionTrigger",
    "StopDecision",
    "StopReason",
    "UnknownRecord",
    "apply_plan_revision",
    "ready_step_ids",
]
