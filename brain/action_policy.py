"""Provider-neutral Brain action authorization seam.

This module owns only the semantic pre-dispatch authorization contract used
by the Body-side ToolGateway. It deliberately imports no runtime, tools,
provider, connector, persistence, or adapter code.

V1 establishes a fail-closed Brain veto point on every registered tool
dispatch. It does not yet claim that Decision provenance is bound to an
action; that stronger lineage contract is a separate hardening slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from brain.contracts import BrainAgentId


class ActionDisposition(str, Enum):
    """Brain authorization result for one runtime action request."""

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
    """Trusted registry metadata presented to the Brain authorization seam."""

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
    """Auditable Brain decision at the runtime action boundary."""

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
    """Default V1 policy after structural trusted-metadata validation.

    V1 preserves current valid execution behavior while making this Brain
    authorization seam mandatory. Decision/Plan provenance will tighten
    this default in the next isolated hardening slice.
    """

    if not isinstance(intent, RuntimeActionIntent):
        raise ValueError("intent must be RuntimeActionIntent")
    return ActionAuthorization(
        intent_id=intent.intent_id,
        disposition=ActionDisposition.ALLOW,
        reason="BRAIN_ACTION_GATE_V1_STRUCTURAL_ALLOW",
    )
