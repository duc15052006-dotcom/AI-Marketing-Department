"""Conservative semantic self-improvement proposals for the five-ASI Brain.

This layer may propose one narrowly scoped change to a learning-strategy
preference when canonical meta-learning evidence supports it.  It cannot apply
that change, mutate code or prompts, select providers/tools, alter permissions,
or grant execution authority.  Applying any proposal remains an external
review/governance responsibility.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.meta_learning import (
    MetaLearningDecision,
    MetaLearningDisposition,
    MetaLearningRequest,
    StrategyTrial,
    evaluate_meta_learning,
)
from brain.metacognition import LearningStrategy, MetacognitionRequest
from schemas.base import BaseModel, Field, ValidationError


class SafeSelfImprovementDisposition(str, Enum):
    """Allowed semantic outcomes of one self-improvement assessment."""

    NO_CHANGE = "NO_CHANGE"
    PROPOSE_STRATEGY_CHANGE = "PROPOSE_STRATEGY_CHANGE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{field_name} must be a positive integer")
    return value


def _strict_true(value: object, field_name: str) -> bool:
    if value is not True:
        raise ValidationError(f"{field_name} must be true")
    return True


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


def _optional_strategy(value: object, field_name: str) -> Optional[LearningStrategy]:
    if value is None:
        return None
    strategy = _enum(value, LearningStrategy, field_name)
    if strategy == LearningStrategy.NONE:
        raise ValidationError(f"{field_name} cannot be NONE")
    return strategy


def _unique_reasons(value: object, field_name: str = "reasons") -> List[str]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field_name} must contain at least one reason")
    reasons: List[str] = []
    seen = set()
    for raw in value:
        reason = _required_text(raw, field_name)
        if reason not in seen:
            seen.add(reason)
            reasons.append(reason)
    return reasons


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must be a {expected_type.__name__} or serialized mapping"
    )


def _canonical_metacognition(raw: object, field_name: str) -> MetacognitionRequest:
    return MetacognitionRequest(
        **_payload(raw, MetacognitionRequest, field_name)
    )


def _canonical_strategy_trial(raw: object) -> StrategyTrial:
    data = _payload(raw, StrategyTrial, "trials")
    before = _canonical_metacognition(data.pop("before_request", None), "before_request")
    after = _canonical_metacognition(data.pop("after_request", None), "after_request")
    return StrategyTrial(**data, before_request=before, after_request=after)


def _canonical_meta_learning(raw: object) -> MetaLearningRequest:
    data = _payload(raw, MetaLearningRequest, "meta_learning")
    raw_trials = data.pop("trials", [])
    if not isinstance(raw_trials, list):
        raise ValidationError("meta_learning trials must be a list")
    trials = [_canonical_strategy_trial(item) for item in raw_trials]
    return MetaLearningRequest(**data, trials=trials)


class LearningPolicySnapshot(BaseModel):
    """Current semantic learning-policy state supplied by an external owner."""

    policy_id: str
    revision: int
    problem_family_id: str
    owner_agent: BrainAgentId
    preferred_strategy: Optional[LearningStrategy] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.policy_id = _required_text(self.policy_id, "policy_id")
        self.revision = _positive_int(self.revision, "revision")
        self.problem_family_id = _required_text(
            self.problem_family_id, "problem_family_id"
        )
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.preferred_strategy = _optional_strategy(
            self.preferred_strategy, "preferred_strategy"
        )
        self._semantic_snapshot = copy.deepcopy(self.model_dump())


class LearningStrategyChangeProposal(BaseModel):
    """A review-required proposal; it is not an applied policy mutation."""

    proposal_id: str
    policy_id: str
    problem_family_id: str
    owner_agent: BrainAgentId
    from_revision: int
    proposed_revision: int
    current_strategy: Optional[LearningStrategy] = None
    proposed_strategy: LearningStrategy
    source_assessment_id: str
    requires_external_review: bool = True
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.proposal_id = _required_text(self.proposal_id, "proposal_id")
        self.policy_id = _required_text(self.policy_id, "policy_id")
        self.problem_family_id = _required_text(
            self.problem_family_id, "problem_family_id"
        )
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.from_revision = _positive_int(self.from_revision, "from_revision")
        self.proposed_revision = _positive_int(
            self.proposed_revision, "proposed_revision"
        )
        if self.proposed_revision != self.from_revision + 1:
            raise ValidationError(
                "strategy-change proposal revision must advance exactly by one"
            )
        self.current_strategy = _optional_strategy(
            self.current_strategy, "current_strategy"
        )
        self.proposed_strategy = _enum(
            self.proposed_strategy, LearningStrategy, "proposed_strategy"
        )
        if self.proposed_strategy == LearningStrategy.NONE:
            raise ValidationError("proposed_strategy cannot be NONE")
        if self.current_strategy == self.proposed_strategy:
            raise ValidationError(
                "strategy-change proposal must actually change preferred strategy"
            )
        self.source_assessment_id = _required_text(
            self.source_assessment_id, "source_assessment_id"
        )
        self.requires_external_review = _strict_true(
            self.requires_external_review, "requires_external_review"
        )
        self.reasons = _unique_reasons(self.reasons)


class SafeSelfImprovementRequest(BaseModel):
    """One exact policy snapshot evaluated against canonical meta-learning input."""

    improvement_id: str
    current_policy: LearningPolicySnapshot
    meta_learning: MetaLearningRequest

    def __post_init__(self) -> None:
        super().__post_init__()
        self.improvement_id = _required_text(self.improvement_id, "improvement_id")
        self.current_policy = LearningPolicySnapshot(
            **_payload(self.current_policy, LearningPolicySnapshot, "current_policy")
        )
        self.meta_learning = _canonical_meta_learning(self.meta_learning)
        if self.current_policy.problem_family_id != self.meta_learning.problem_family_id:
            raise ValidationError(
                "current policy problem_family_id must exactly match meta-learning scope"
            )
        if self.current_policy.owner_agent != self.meta_learning.policy_owner_agent:
            raise ValidationError(
                "current policy owner_agent must exactly match meta-learning policy owner"
            )
        self._semantic_snapshot = copy.deepcopy(self.model_dump())


class SafeSelfImprovementDecision(BaseModel):
    """Detached semantic recommendation with canonical meta-learning provenance."""

    improvement_id: str
    policy_id: str
    problem_family_id: str
    owner_agent: BrainAgentId
    source_assessment_id: str
    disposition: SafeSelfImprovementDisposition
    meta_learning_decision: MetaLearningDecision
    proposal: Optional[LearningStrategyChangeProposal] = None
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.improvement_id = _required_text(self.improvement_id, "improvement_id")
        self.policy_id = _required_text(self.policy_id, "policy_id")
        self.problem_family_id = _required_text(
            self.problem_family_id, "problem_family_id"
        )
        self.owner_agent = _enum(self.owner_agent, BrainAgentId, "owner_agent")
        self.source_assessment_id = _required_text(
            self.source_assessment_id, "source_assessment_id"
        )
        self.disposition = _enum(
            self.disposition,
            SafeSelfImprovementDisposition,
            "disposition",
        )
        self.meta_learning_decision = MetaLearningDecision(
            **_payload(
                self.meta_learning_decision,
                MetaLearningDecision,
                "meta_learning_decision",
            )
        )
        if self.meta_learning_decision.assessment_id != self.source_assessment_id:
            raise ValidationError(
                "source_assessment_id must match canonical meta-learning decision"
            )
        if self.meta_learning_decision.problem_family_id != self.problem_family_id:
            raise ValidationError(
                "decision problem_family_id must match canonical meta-learning decision"
            )
        if self.meta_learning_decision.policy_owner_agent != self.owner_agent:
            raise ValidationError(
                "decision owner_agent must match canonical meta-learning decision"
            )
        if self.proposal is not None:
            self.proposal = LearningStrategyChangeProposal(
                **_payload(
                    self.proposal,
                    LearningStrategyChangeProposal,
                    "proposal",
                )
            )
        if self.disposition == SafeSelfImprovementDisposition.PROPOSE_STRATEGY_CHANGE:
            if self.proposal is None:
                raise ValidationError(
                    "PROPOSE_STRATEGY_CHANGE requires a strategy-change proposal"
                )
        elif self.proposal is not None:
            raise ValidationError(
                "only PROPOSE_STRATEGY_CHANGE may carry a proposal"
            )
        self.reasons = _unique_reasons(self.reasons)


def _validate_snapshot(raw: object, expected_type: type, field_name: str) -> None:
    original = getattr(raw, "_semantic_snapshot", None)
    if original is None or copy.deepcopy(raw.model_dump()) != original:
        raise ValidationError(f"{field_name} semantic state changed after validation")


def _canonical_request(raw: object) -> SafeSelfImprovementRequest:
    if not isinstance(raw, SafeSelfImprovementRequest):
        raise ValidationError("request must be a SafeSelfImprovementRequest")
    _validate_snapshot(raw, SafeSelfImprovementRequest, "safe self-improvement request")
    _validate_snapshot(raw.current_policy, LearningPolicySnapshot, "learning policy snapshot")
    return SafeSelfImprovementRequest(**copy.deepcopy(raw.model_dump()))


def _decision(
    *,
    request: SafeSelfImprovementRequest,
    meta_decision: MetaLearningDecision,
    disposition: SafeSelfImprovementDisposition,
    reasons: List[str],
    proposal: Optional[LearningStrategyChangeProposal] = None,
) -> SafeSelfImprovementDecision:
    return SafeSelfImprovementDecision(
        improvement_id=request.improvement_id,
        policy_id=request.current_policy.policy_id,
        problem_family_id=request.current_policy.problem_family_id,
        owner_agent=request.current_policy.owner_agent,
        source_assessment_id=meta_decision.assessment_id,
        disposition=disposition,
        meta_learning_decision=meta_decision.model_copy(deep=True),
        proposal=proposal.model_copy(deep=True) if proposal is not None else None,
        reasons=list(reasons),
    )


def propose_safe_self_improvement(
    raw_request: SafeSelfImprovementRequest,
) -> SafeSelfImprovementDecision:
    """Derive a review-required strategy proposal without applying any change."""

    request = _canonical_request(raw_request)
    meta_decision = evaluate_meta_learning(request.meta_learning)

    if meta_decision.disposition == MetaLearningDisposition.REVISE_POLICY:
        return _decision(
            request=request,
            meta_decision=meta_decision,
            disposition=SafeSelfImprovementDisposition.HUMAN_REVIEW_REQUIRED,
            reasons=[
                "canonical meta-learning indicates the policy needs revision, but Brain cannot invent or apply a replacement policy"
            ],
        )

    if meta_decision.disposition in {
        MetaLearningDisposition.INSUFFICIENT_EVIDENCE,
        MetaLearningDisposition.RETAIN_POLICY,
    }:
        return _decision(
            request=request,
            meta_decision=meta_decision,
            disposition=SafeSelfImprovementDisposition.NO_CHANGE,
            reasons=[
                "canonical meta-learning does not justify a unique learning-strategy change"
            ],
        )

    if meta_decision.disposition != MetaLearningDisposition.PREFER_STRATEGY:
        raise ValidationError("unsupported canonical meta-learning disposition")

    preferred = meta_decision.preferred_strategy
    if preferred is None or preferred == LearningStrategy.NONE:
        raise ValidationError(
            "canonical PREFER_STRATEGY decision requires a concrete learning strategy"
        )

    if request.current_policy.preferred_strategy == preferred:
        return _decision(
            request=request,
            meta_decision=meta_decision,
            disposition=SafeSelfImprovementDisposition.NO_CHANGE,
            reasons=[
                "canonical preferred learning strategy already matches the current policy"
            ],
        )

    proposal = LearningStrategyChangeProposal(
        proposal_id=f"{request.improvement_id}:strategy-change",
        policy_id=request.current_policy.policy_id,
        problem_family_id=request.current_policy.problem_family_id,
        owner_agent=request.current_policy.owner_agent,
        from_revision=request.current_policy.revision,
        proposed_revision=request.current_policy.revision + 1,
        current_strategy=request.current_policy.preferred_strategy,
        proposed_strategy=preferred,
        source_assessment_id=meta_decision.assessment_id,
        requires_external_review=True,
        reasons=[
            "canonical meta-learning found one uniquely supported strategy preference",
            "external review is required before any policy state may change",
        ],
    )
    return _decision(
        request=request,
        meta_decision=meta_decision,
        disposition=SafeSelfImprovementDisposition.PROPOSE_STRATEGY_CHANGE,
        proposal=proposal,
        reasons=[
            "a narrowly scoped learning-strategy preference change is proposed for external review"
        ],
    )
