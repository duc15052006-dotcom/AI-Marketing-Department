"""Permission & Safety Layer (Phase 5.1).

Enforces Role-Based Access Control (RBAC), capability permission validation,
and Human Approval Gates for high-risk, publishing, and financial actions.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from schemas.base import BaseModel, Field
from tools.capabilities import CapabilityCategory, CapabilityDescriptor, PermissionLevel, RiskLevel

logger = logging.getLogger("tool_security")


AGENT_DEFAULT_PERMISSIONS: Dict[str, Set[PermissionLevel]] = {
    "intelligence": {
        PermissionLevel.READ_ONLY,
    },
    "strategist": {
        PermissionLevel.READ_ONLY,
        PermissionLevel.ANALYTICS,
    },
    "creative": {
        PermissionLevel.READ_ONLY,
        PermissionLevel.CREATE_LOCAL,
    },
    "performance": {
        PermissionLevel.READ_ONLY,
        PermissionLevel.ANALYTICS,
    },
    "cmo": {
        PermissionLevel.READ_ONLY,
        PermissionLevel.CREATE_LOCAL,
        PermissionLevel.EXTERNAL_WRITE,
        PermissionLevel.PUBLISH,
        PermissionLevel.FINANCIAL_OR_HIGH_RISK,
        PermissionLevel.ANALYTICS,
    },
}


class PolicyDecision(BaseModel):
    """Result of policy and permission evaluation."""
    allowed: bool
    requires_human_approval: bool = False
    error_code: Optional[str] = None
    reason: str = "ALLOWED"
    missing_permissions: List[str] = Field(default_factory=list)


class HumanApprovalRecord(BaseModel):
    """Record of a verified human approval for high-risk actions."""
    approval_token: str
    action_type: str
    approved_by: str
    approved_at: str
    scope: str
    risk_level: RiskLevel


class PolicyEngine:
    """Evaluates agent permissions and gates high-risk operational requests."""

    def __init__(self, custom_permissions: Optional[Dict[str, Set[PermissionLevel]]] = None) -> None:
        self._agent_permissions = custom_permissions or AGENT_DEFAULT_PERMISSIONS
        self._approved_tokens: Dict[str, HumanApprovalRecord] = {}

    def register_approval(self, approval: HumanApprovalRecord) -> None:
        """Register a valid human approval record."""
        self._approved_tokens[approval.approval_token] = approval

    def revoke_approval(self, approval_token: str) -> None:
        """Revoke a human approval token."""
        self._approved_tokens.pop(approval_token, None)

    def evaluate(
        self,
        agent_id: str,
        capability: CapabilityDescriptor,
        approval_token: Optional[str] = None,
    ) -> PolicyDecision:
        """Evaluate if an agent is authorized to execute a capability."""
        aid = agent_id.lower()

        # 1. Agent Role Recognition Gate
        if aid not in self._agent_permissions:
            return PolicyDecision(
                allowed=False,
                error_code="UNRECOGNIZED_AGENT",
                reason=f"UNRECOGNIZED_AGENT: Agent '{agent_id}' is not an authorized member of the Five-Agent Department.",
            )

        # 2. RBAC Permission Level Check
        agent_perms = self._agent_permissions[aid]
        missing = [p.value for p in capability.required_permissions if p not in agent_perms]
        if missing:
            return PolicyDecision(
                allowed=False,
                error_code="PERMISSION_DENIED",
                missing_permissions=missing,
                reason=f"PERMISSION_DENIED: Agent '{agent_id}' lacks required permissions: {', '.join(missing)}.",
            )

        # 3. Supported Agents Check on Descriptor
        if capability.supported_agents:
            allowed_agents = [sa.lower() for sa in capability.supported_agents]
            if "all" not in allowed_agents and aid not in allowed_agents:
                return PolicyDecision(
                    allowed=False,
                    error_code="ROLE_NOT_SUPPORTED",
                    reason=f"ROLE_NOT_SUPPORTED: Capability '{capability.capability_id}' is not supported for agent '{agent_id}'.",
                )

        # 4. Human Approval Gate
        requires_approval = (
            capability.human_approval_required
            or capability.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            or capability.category == CapabilityCategory.PUBLISH
            or PermissionLevel.FINANCIAL_OR_HIGH_RISK in capability.required_permissions
            or PermissionLevel.PUBLISH in capability.required_permissions
        )

        if requires_approval:
            if not approval_token:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    reason=f"HUMAN_APPROVAL_REQUIRED: Capability '{capability.capability_id}' has risk level {capability.risk_level.value} and requires human approval token.",
                )

            # Verify token
            if approval_token not in self._approved_tokens:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    reason=f"INVALID_APPROVAL_TOKEN: Provided approval token '{approval_token}' is not registered or has expired.",
                )

        return PolicyDecision(
            allowed=True,
            requires_human_approval=requires_approval,
            reason="AUTHORIZED",
        )
