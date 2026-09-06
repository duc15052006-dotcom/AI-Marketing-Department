"""Provider-neutral Brain action authorization seams.

This module owns semantic authorization contracts only. It deliberately imports
no runtime, tools, provider, connector, persistence, or adapter code.

V1 keeps the validated structural runtime veto used by ToolGateway. The semantic
ActionIntent path separately binds Brain intent to canonical decision authority;
runtime wiring of that stronger provenance remains a later isolated slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
)

if TYPE_CHECKING:
    from brain.decisions import DecisionEvaluationRequest


class ActionDisposition(str, Enum):
    """Brain authorization result for one action request."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field_name} must be a boolean")
    return value


@dataclass(frozen=True)
class RuntimeActionIntent:
    """Trusted registry metadata presented to the runtime Brain veto seam."""

    intent_id: str
    run_id: str
    agent_id: str
    capability_id: str
    capability_category: str
    risk_level: str
    human_approval_required: bool
    consequential: bool

    def __post_init__(self) -> None:
        intent_id = _required_text(self.intent_id, "intent_id")
        run_id = _required_text(self.run_id, "run_id")
        agent_id = _required_text(self.agent_id, "agent_id").upper()
        capability_id = _required_text(self.capability_id, "capability_id")
        capability_category = _required_text(
            self.capability_category, "capability_category"
        ).upper()
        risk_level = _required_text(self.risk_level, "risk_level").upper()

        try:
            canonical_agent = BrainAgentId(agent_id)
        except ValueError as exc:
            raise ValueError(
                "agent_id must identify one of the five permanent agents"
            ) from exc

        if capability_category not in {
            "OBSERVE", "CREATE", "PUBLISH", "ANALYZE", "FILE_DATA"
        }:
            raise ValueError(
                "capability_category is not a recognized trusted category"
            )
        if risk_level not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ValueError("risk_level is not a recognized trusted risk level")

        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "agent_id", canonical_agent.value.lower())
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "capability_category", capability_category)
        object.__setattr__(self, "risk_level", risk_level)
        object.__setattr__(
            self,
            "human_approval_required",
            _strict_bool(
                self.human_approval_required, "human_approval_required"
            ),
        )
        object.__setattr__(
            self,
            "consequential",
            _strict_bool(self.consequential, "consequential"),
        )


@dataclass(frozen=True)
class ActionAuthorization:
    """Auditable Brain authorization result at an action boundary."""

    intent_id: str
    disposition: ActionDisposition
    reason: str

    def __post_init__(self) -> None:
        intent_id = _required_text(self.intent_id, "intent_id")
        reason = _required_text(self.reason, "reason")
        disposition = self.disposition
        if not isinstance(disposition, ActionDisposition):
            try:
                disposition = ActionDisposition(str(disposition).strip().upper())
            except ValueError as exc:
                raise ValueError("disposition must be ALLOW or BLOCK") from exc
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "reason", reason)


def authorize_action(intent: RuntimeActionIntent) -> ActionAuthorization:
    """Validated V1 structural runtime veto policy.

    This function intentionally preserves the already-qualified ToolGateway V1
    behavior. Semantic Decision provenance is enforced by
    :func:`authorize_action_intent` and will be wired into runtime separately.
    """

    if not isinstance(intent, RuntimeActionIntent):
        raise ValueError("intent must be RuntimeActionIntent")
    return ActionAuthorization(
        intent_id=intent.intent_id,
        disposition=ActionDisposition.ALLOW,
        reason="BRAIN_ACTION_GATE_V1_STRUCTURAL_ALLOW",
    )


def authorize_action_intent(
    intent: ActionIntent,
    decision_request: "DecisionEvaluationRequest",
) -> ActionAuthorization:
    """Authorize a semantic ActionIntent from canonical Decision provenance.

    The raw ``DecisionEvaluationRequest`` is the authority input. This function
    recomputes the canonical DecisionEvaluation with ``evaluate_decision``;
    caller-created evaluation summaries are never accepted as authority.
    """

    from brain.decisions import DecisionEvaluationRequest, evaluate_decision

    if not isinstance(intent, ActionIntent):
        raise ValueError("intent must be ActionIntent")
    if not isinstance(decision_request, DecisionEvaluationRequest):
        raise ValueError("decision_request must be DecisionEvaluationRequest")

    def block(reason: str) -> ActionAuthorization:
        return ActionAuthorization(
            intent_id=intent.intent_id,
            disposition=ActionDisposition.BLOCK,
            reason=reason,
        )

    decision = decision_request.decision

    if intent.decision_id is None:
        return block(
            "DECISION_PROVENANCE_REQUIRED: ActionIntent has no bound decision_id."
        )

    if intent.decision_id != decision.decision_id:
        return block(
            "DECISION_ID_MISMATCH: ActionIntent decision_id does not match the canonical decision request."
        )

    if (
        intent.goal_id != decision.goal_id
        or intent.owner_agent != decision.agent_id
    ):
        return block(
            "DECISION_CONTEXT_MISMATCH: ActionIntent goal/owner does not match the bound canonical decision."
        )

    evaluation = evaluate_decision(decision_request)
    if (
        evaluation.decision_id != decision.decision_id
        or evaluation.goal_id != decision.goal_id
    ):
        return block(
            "DECISION_CONTEXT_MISMATCH: canonical decision evaluation identity changed during recomputation."
        )

    if evaluation.disposition != DecisionDisposition.PROCEED:
        return block(
            "DECISION_NOT_AUTHORIZED: canonical decision evaluation did not authorize PROCEED."
        )

    return ActionAuthorization(
        intent_id=intent.intent_id,
        disposition=ActionDisposition.ALLOW,
        reason="CANONICAL_DECISION_PROCEED: ActionIntent is bound to an exact canonical PROCEED decision.",
    )
