"""Provider-neutral meta-learning policy for the five-ASI Brain.

Meta-learning asks a different question from ordinary learning: not "what did we
learn?" but "which learning strategy actually reduced uncertainty in this class
of problems?"

The policy evaluates before/after metacognitive states itself, compares only
semantic knowledge progress, and updates strategy preference conservatively.
It never changes model weights, providers, tools, runtime scheduling, or durable
memory directly.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Dict, List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.metacognition import (
    KnowledgeState,
    LearningStrategy,
    MetacognitionDecision,
    MetacognitionRequest,
    assess_metacognition,
)
from schemas.base import BaseModel, Field, ValidationError


class TrialEffect(str, Enum):
    IMPROVED = "IMPROVED"
    NEUTRAL = "NEUTRAL"
    REGRESSED = "REGRESSED"


class MetaLearningDisposition(str, Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    PREFER_STRATEGY = "PREFER_STRATEGY"
    RETAIN_POLICY = "RETAIN_POLICY"
    REVISE_POLICY = "REVISE_POLICY"


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


class StrategyTrial(BaseModel):
    """One auditable attempt to reduce uncertainty using one learning strategy."""

    trial_id: str
    problem_family_id: str
    strategy: LearningStrategy
    before_request: MetacognitionRequest
    after_request: MetacognitionRequest

    def __post_init__(self) -> None:
        super().__post_init__()
        self.trial_id = _required_text(self.trial_id, "trial_id")
        self.problem_family_id = _required_text(
            self.problem_family_id, "problem_family_id"
        )
        self.strategy = _enum(self.strategy, LearningStrategy, "strategy")
        if self.strategy == LearningStrategy.NONE:
            raise ValidationError("strategy trials cannot use NONE")

        if not isinstance(self.before_request, MetacognitionRequest):
            raise ValidationError(
                "before_request must be a MetacognitionRequest"
            )
        if not isinstance(self.after_request, MetacognitionRequest):
            raise ValidationError(
                "after_request must be a MetacognitionRequest"
            )
        self.before_request = copy.deepcopy(self.before_request)
        self.after_request = copy.deepcopy(self.after_request)

        if self.before_request.goal_id != self.after_request.goal_id:
            raise ValidationError(
                "before/after metacognition requests must bind to the same goal_id"
            )
        if self.before_request.agent_id != self.after_request.agent_id:
            raise ValidationError(
                "before/after metacognition requests must bind to the same ASI"
            )


class StrategyPerformance(BaseModel):
    strategy: LearningStrategy
    total_trials: int
    improved_trials: int
    neutral_trials: int
    regressed_trials: int

    def __post_init__(self) -> None:
        super().__post_init__()
        self.strategy = _enum(self.strategy, LearningStrategy, "strategy")
        if self.strategy == LearningStrategy.NONE:
            raise ValidationError("strategy performance cannot use NONE")
        counts = (
            self.total_trials,
            self.improved_trials,
            self.neutral_trials,
            self.regressed_trials,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValidationError("strategy performance counts must be integers >= 0")
        if (
            self.improved_trials
            + self.neutral_trials
            + self.regressed_trials
            != self.total_trials
        ):
            raise ValidationError(
                "strategy performance effect counts must sum to total_trials"
            )


class MetaLearningRequest(BaseModel):
    assessment_id: str
    problem_family_id: str
    policy_owner_agent: BrainAgentId
    trials: List[StrategyTrial] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.problem_family_id = _required_text(
            self.problem_family_id, "problem_family_id"
        )
        self.policy_owner_agent = _enum(
            self.policy_owner_agent, BrainAgentId, "policy_owner_agent"
        )
        if not isinstance(self.trials, list):
            raise ValidationError("trials must be a list of StrategyTrial")

        normalized: List[StrategyTrial] = []
        trial_ids = set()
        for raw in self.trials:
            if not isinstance(raw, StrategyTrial):
                raise ValidationError("trials must contain only StrategyTrial items")
            trial = copy.deepcopy(raw)
            if trial.problem_family_id != self.problem_family_id:
                raise ValidationError(
                    "strategy trial problem_family_id must match request"
                )
            if trial.trial_id in trial_ids:
                raise ValidationError(f"duplicate strategy trial id: {trial.trial_id}")
            trial_ids.add(trial.trial_id)
            normalized.append(trial)
        self.trials = normalized


class MetaLearningDecision(BaseModel):
    assessment_id: str
    problem_family_id: str
    policy_owner_agent: BrainAgentId
    disposition: MetaLearningDisposition
    preferred_strategy: Optional[LearningStrategy] = None
    performance: List[StrategyPerformance] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.assessment_id = _required_text(self.assessment_id, "assessment_id")
        self.problem_family_id = _required_text(
            self.problem_family_id, "problem_family_id"
        )
        self.policy_owner_agent = _enum(
            self.policy_owner_agent, BrainAgentId, "policy_owner_agent"
        )
        self.disposition = _enum(
            self.disposition, MetaLearningDisposition, "disposition"
        )
        if self.preferred_strategy is not None:
            self.preferred_strategy = _enum(
                self.preferred_strategy, LearningStrategy, "preferred_strategy"
            )
            if self.preferred_strategy == LearningStrategy.NONE:
                raise ValidationError("preferred_strategy cannot be NONE")
        if not isinstance(self.performance, list):
            raise ValidationError("performance must be a list of StrategyPerformance")
        self.performance = [
            copy.deepcopy(item)
            if isinstance(item, StrategyPerformance)
            else StrategyPerformance(**item)
            for item in self.performance
        ]
        if not isinstance(self.reasons, list) or not self.reasons:
            raise ValidationError("reasons must contain at least one meta-learning reason")
        normalized_reasons: List[str] = []
        seen = set()
        for raw in self.reasons:
            reason = _required_text(raw, "reasons")
            if reason not in seen:
                seen.add(reason)
                normalized_reasons.append(reason)
        self.reasons = normalized_reasons

        if self.disposition == MetaLearningDisposition.PREFER_STRATEGY:
            if self.preferred_strategy is None:
                raise ValidationError(
                    "PREFER_STRATEGY requires preferred_strategy"
                )
        elif self.preferred_strategy is not None:
            raise ValidationError(
                "preferred_strategy is only valid for PREFER_STRATEGY"
            )


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must be a {expected_type.__name__} or serialized mapping"
    )


def _canonical_metacognition(raw: object, field_name: str) -> MetacognitionRequest:
    return MetacognitionRequest(**_payload(raw, MetacognitionRequest, field_name))


def _canonical_strategy_trial(raw: object) -> StrategyTrial:
    data = _payload(raw, StrategyTrial, "trials")
    before = _canonical_metacognition(data.pop("before_request", None), "before_request")
    after = _canonical_metacognition(data.pop("after_request", None), "after_request")
    return StrategyTrial(**data, before_request=before, after_request=after)


def _canonical_request(raw: object) -> MetaLearningRequest:
    if not isinstance(raw, MetaLearningRequest):
        raise ValidationError("request must be a MetaLearningRequest")
    data = copy.deepcopy(raw.model_dump())
    raw_trials = data.pop("trials", [])
    if not isinstance(raw_trials, list):
        raise ValidationError("trials must be a list of StrategyTrial")
    trials = [_canonical_strategy_trial(item) for item in raw_trials]
    return MetaLearningRequest(**data, trials=trials)


_STATE_SEVERITY = {
    KnowledgeState.SUFFICIENT: 0,
    KnowledgeState.INCOMPLETE: 1,
    KnowledgeState.CONTESTED: 2,
    KnowledgeState.BLOCKED: 3,
}
_MIN_TRIALS_FOR_POLICY_UPDATE = 3


def _unresolved_count(decision: MetacognitionDecision) -> int:
    return (
        len(decision.open_gap_ids)
        + len(decision.contested_claim_ids)
        + len(decision.insufficient_claim_ids)
    )


def _trial_effect(trial: StrategyTrial) -> TrialEffect:
    before = assess_metacognition(trial.before_request)
    after = assess_metacognition(trial.after_request)
    before_key = (_STATE_SEVERITY[before.knowledge_state], _unresolved_count(before))
    after_key = (_STATE_SEVERITY[after.knowledge_state], _unresolved_count(after))
    if after_key < before_key:
        return TrialEffect.IMPROVED
    if after_key > before_key:
        return TrialEffect.REGRESSED
    return TrialEffect.NEUTRAL


def evaluate_meta_learning(request: MetaLearningRequest) -> MetaLearningDecision:
    """Evaluate which learning strategy reduces uncertainty most reliably."""

    request = _canonical_request(request)

    counts: Dict[LearningStrategy, Dict[TrialEffect, int]] = {}
    for trial in request.trials:
        effect = _trial_effect(trial)
        bucket = counts.setdefault(
            trial.strategy,
            {
                TrialEffect.IMPROVED: 0,
                TrialEffect.NEUTRAL: 0,
                TrialEffect.REGRESSED: 0,
            },
        )
        bucket[effect] += 1

    performance: List[StrategyPerformance] = []
    for strategy in sorted(counts, key=lambda item: item.value):
        bucket = counts[strategy]
        total = sum(bucket.values())
        performance.append(
            StrategyPerformance(
                strategy=strategy,
                total_trials=total,
                improved_trials=bucket[TrialEffect.IMPROVED],
                neutral_trials=bucket[TrialEffect.NEUTRAL],
                regressed_trials=bucket[TrialEffect.REGRESSED],
            )
        )

    eligible = [
        item
        for item in performance
        if item.total_trials >= _MIN_TRIALS_FOR_POLICY_UPDATE
    ]
    if not eligible:
        return MetaLearningDecision(
            assessment_id=request.assessment_id,
            problem_family_id=request.problem_family_id,
            policy_owner_agent=request.policy_owner_agent,
            disposition=MetaLearningDisposition.INSUFFICIENT_EVIDENCE,
            performance=performance,
            reasons=[
                "no learning strategy has enough comparable trials for a policy update"
            ],
        )

    safe_candidates = [
        item
        for item in eligible
        if item.regressed_trials == 0
        and item.improved_trials * 3 >= item.total_trials * 2
    ]
    if safe_candidates:
        best_rate = max(
            item.improved_trials / item.total_trials for item in safe_candidates
        )
        best = [
            item
            for item in safe_candidates
            if item.improved_trials / item.total_trials == best_rate
        ]
        if len(best) == 1:
            return MetaLearningDecision(
                assessment_id=request.assessment_id,
                problem_family_id=request.problem_family_id,
                policy_owner_agent=request.policy_owner_agent,
                disposition=MetaLearningDisposition.PREFER_STRATEGY,
                preferred_strategy=best[0].strategy,
                performance=performance,
                reasons=[
                    "one strategy has uniquely strong repeated uncertainty reduction without regression"
                ],
            )

    if all(
        item.regressed_trials > 0
        and item.regressed_trials >= item.improved_trials
        for item in eligible
    ):
        return MetaLearningDecision(
            assessment_id=request.assessment_id,
            problem_family_id=request.problem_family_id,
            policy_owner_agent=request.policy_owner_agent,
            disposition=MetaLearningDisposition.REVISE_POLICY,
            performance=performance,
            reasons=[
                "qualified strategies regress at least as often as they improve knowledge state"
            ],
        )

    return MetaLearningDecision(
        assessment_id=request.assessment_id,
        problem_family_id=request.problem_family_id,
        policy_owner_agent=request.policy_owner_agent,
        disposition=MetaLearningDisposition.RETAIN_POLICY,
        performance=performance,
        reasons=[
            "evidence is sufficient to evaluate strategy behavior but not to justify a unique preference"
        ],
    )
