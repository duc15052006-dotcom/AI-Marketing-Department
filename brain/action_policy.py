"""Provider-neutral Brain action authorization seams.

This module owns semantic authorization contracts only. It deliberately imports
no runtime, tools, provider, connector, persistence, or adapter code.

V1 keeps the validated structural runtime veto used by ToolGateway. The semantic
ActionIntent path separately binds Brain intent to canonical decision authority;
runtime wiring of that stronger provenance remains a later isolated slice.

Capability binding is deliberately modeled as a non-execution assessment. A
successful semantic binding only proves that trusted capability metadata can
satisfy an ActionIntent; it does not by itself authorize execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Tuple

from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
)

if TYPE_CHECKING:
    from brain.decisions import DecisionEvaluationRequest


_SEMANTIC_NEED_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")


class ActionDisposition(str, Enum):
    """Brain authorization result for one action request."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class CapabilityBindingDisposition(str, Enum):
    """Non-execution result for semantic ActionIntent/capability matching."""

    BOUND = "BOUND"
    REJECTED = "REJECTED"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _semantic_need(value: object) -> str:
    normalized = _required_text(value, "semantic_need").upper()
    if not _SEMANTIC_NEED_RE.fullmatch(normalized):
        raise ValueError(
            "semantic_need must be provider-neutral UPPER_SNAKE_CASE"
        )
    return normalized


@dataclass(frozen=True)
class BrainActionAuthority:
    """Typed semantic authority envelope for trusted Body-side handoff.

    This value binds the exact canonical ActionIntent to the exact raw
    DecisionEvaluationRequest. It is transport authority only: possessing
    this envelope never authorizes execution. ToolGateway must still
    recompute canonical decision policy and trusted capability binding.
    """

    action_intent: ActionIntent
    decision_request: "DecisionEvaluationRequest"

    def __post_init__(self) -> None:
        from brain.decisions import DecisionEvaluationRequest

        if not isinstance(self.action_intent, ActionIntent):
            raise ValueError("action_intent must be an ActionIntent")
        if not isinstance(self.decision_request, DecisionEvaluationRequest):
            raise ValueError(
                "decision_request must be a DecisionEvaluationRequest"
            )

        decision = self.decision_request.decision
        if self.action_intent.decision_id is None:
            raise ValueError(
                "BrainActionAuthority requires ActionIntent decision provenance"
            )
        if self.action_intent.decision_id != decision.decision_id:
            raise ValueError(
                "BrainActionAuthority decision_id must match canonical decision"
            )
        if self.action_intent.goal_id != decision.goal_id:
            raise ValueError(
                "BrainActionAuthority goal_id must match canonical decision"
            )
        if self.action_intent.owner_agent != decision.agent_id:
            raise ValueError(
                "BrainActionAuthority owner must match canonical decision agent"
            )


@dataclass(frozen=True)
class TrustedCapabilityBinding:
    """Brain-neutral projection of trusted capability-registry authority.

    Runtime/body layers may construct this value only from a trusted capability
    snapshot. Brain never imports CapabilityDescriptor or any tools/runtime code.
    """

    capability_id: str
    semantic_needs: Tuple[str, ...]
    supported_agents: Tuple[str, ...]

    def __post_init__(self) -> None:
        capability_id = _required_text(self.capability_id, "capability_id")
        if not isinstance(self.semantic_needs, (list, tuple)):
            raise ValueError("semantic_needs must be a list or tuple")
        if not isinstance(self.supported_agents, (list, tuple)):
            raise ValueError("supported_agents must be a list or tuple")

        semantic_needs = []
        for value in self.semantic_needs:
            need = _semantic_need(value)
            if need not in semantic_needs:
                semantic_needs.append(need)

        supported_agents = []
        for value in self.supported_agents:
            agent = _required_text(value, "supported_agent").upper()
            if agent != "ALL":
                try:
                    agent = BrainAgentId(agent).value
                except ValueError as exc:
                    raise ValueError(
                        "supported_agents must contain permanent Brain agents or ALL"
                    ) from exc
            if agent not in supported_agents:
                supported_agents.append(agent)

        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "semantic_needs", tuple(semantic_needs))
        object.__setattr__(self, "supported_agents", tuple(supported_agents))


@dataclass(frozen=True)
class CapabilityBindingAssessment:
    """Auditable semantic binding result; never execution authority."""

    intent_id: str
    capability_id: str
    semantic_need: str
    disposition: CapabilityBindingDisposition
    reason: str

    def __post_init__(self) -> None:
        intent_id = _required_text(self.intent_id, "intent_id")
        capability_id = _required_text(self.capability_id, "capability_id")
        semantic_need = _semantic_need(self.semantic_need)
        reason = _required_text(self.reason, "reason")
        disposition = self.disposition
        if not isinstance(disposition, CapabilityBindingDisposition):
            try:
                disposition = CapabilityBindingDisposition(
                    str(disposition).strip().upper()
                )
            except ValueError as exc:
                raise ValueError(
                    "disposition must be BOUND or REJECTED"
                ) from exc
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "semantic_need", semantic_need)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "reason", reason)


def evaluate_action_intent_capability_binding(
    intent: ActionIntent,
    binding: TrustedCapabilityBinding,
) -> CapabilityBindingAssessment:
    """Evaluate semantic ActionIntent/capability compatibility fail-closed.

    This function is intentionally not an execution authorizer. A BOUND result
    must still be combined with canonical Decision provenance and runtime policy
    before any dispatch may occur.
    """

    if not isinstance(intent, ActionIntent):
        raise ValueError("intent must be ActionIntent")
    if not isinstance(binding, TrustedCapabilityBinding):
        raise ValueError("binding must be TrustedCapabilityBinding")

    def assessment(
        disposition: CapabilityBindingDisposition,
        reason: str,
    ) -> CapabilityBindingAssessment:
        return CapabilityBindingAssessment(
            intent_id=intent.intent_id,
            capability_id=binding.capability_id,
            semantic_need=intent.capability_need,
            disposition=disposition,
            reason=reason,
        )

    if intent.capability_need not in binding.semantic_needs:
        return assessment(
            CapabilityBindingDisposition.REJECTED,
            "CAPABILITY_NEED_MISMATCH: trusted capability metadata does not "
            "declare the ActionIntent semantic need.",
        )

    owner = intent.owner_agent.value
    if "ALL" not in binding.supported_agents and owner not in binding.supported_agents:
        return assessment(
            CapabilityBindingDisposition.REJECTED,
            "CAPABILITY_AGENT_MISMATCH: trusted capability metadata does not "
            "permit the ActionIntent owner agent.",
        )

    return assessment(
        CapabilityBindingDisposition.BOUND,
        "TRUSTED_CAPABILITY_BOUND: semantic need and permanent-agent owner "
        "match trusted capability metadata.",
    )


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
    :func:`authorize_action_intent`; production promotion of that stronger
    provenance remains a separately certified migration so operator-approved
    legacy V1 actions are not silently redefined by an unrelated hardening patch.
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
