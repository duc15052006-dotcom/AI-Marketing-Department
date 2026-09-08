"""Provider-neutral cognitive domain for the five-ASI marketing brain.

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
from brain.learning import (
    LearningClaimKind,
    LearningDecision,
    LearningDisposition,
    LearningEpisode,
    LearningMethod,
    analyze_learning_episode,
)
from brain.metacognition import (
    GapResolutionDirective,
    KnowledgeGap,
    KnowledgeGapKind,
    KnowledgeState,
    LearningStrategy,
    MetacognitionDecision,
    MetacognitionRequest,
    assess_metacognition,
    derive_knowledge_gaps,
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
    "GapResolutionDirective",
    "GoalSpec",
    "GoalStatus",
    "KnowledgeGap",
    "KnowledgeGapKind",
    "KnowledgeState",
    "LearningClaimKind",
    "LearningDecision",
    "LearningDisposition",
    "LearningEpisode",
    "LearningMethod",
    "LearningStrategy",
    "MetacognitionDecision",
    "MetacognitionRequest",
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
    "analyze_learning_episode",
    "apply_plan_revision",
    "assess_metacognition",
    "derive_knowledge_gaps",
    "ready_step_ids",
    "select_reasoning_depth",
]
