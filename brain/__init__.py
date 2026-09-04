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
from brain.reasoning import (
    ReasoningAssessment,
    ReasoningDecision,
    ReasoningDepth,
    Reversibility,
    SignalLevel,
    select_reasoning_depth,
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
    "ReasoningAssessment",
    "ReasoningDecision",
    "ReasoningDepth",
    "Reversibility",
    "RevisionTrigger",
    "SignalLevel",
    "StopDecision",
    "StopReason",
    "UnknownRecord",
    "apply_plan_revision",
    "ready_step_ids",
    "select_reasoning_depth",
]
