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

__all__ = [
    "ActionIntent",
    "BrainAgentId",
    "DecisionDisposition",
    "DecisionRecord",
    "EvidenceNeed",
    "GoalSpec",
    "GoalStatus",
    "StopDecision",
    "StopReason",
    "UnknownRecord",
]
