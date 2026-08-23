"""Permission & Safety Layer (Phase 5.1 & PROD-SEC-01).

Enforces Role-Based Access Control (RBAC), capability permission validation,
and Cryptographic Human Approval Authority for high-risk, publishing, and financial actions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timezone
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


def compute_request_fingerprint(
    capability_id: str,
    parameters: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    business_id: Optional[str] = None,
) -> str:
    """Compute deterministic canonical SHA-256 fingerprint of a consequential tool request."""
    norm_params = json.dumps(parameters or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    raw = f"{capability_id.strip().lower()}:{run_id or ''}:{business_id or ''}:{norm_params}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    action_type: str = ""
    capability_id: str = ""
    run_id: str = ""
    business_id: Optional[str] = None
    request_fingerprint: str = ""
    approved_by: str = "Human Operator"
    approved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    scope: str = ""
    risk_level: RiskLevel = RiskLevel.CRITICAL
    claimed: bool = False
    claimed_at: Optional[str] = None
    consumed: bool = False
    consumed_at: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.capability_id and self.action_type:
            self.capability_id = self.action_type
        if not self.action_type and self.capability_id:
            self.action_type = self.capability_id
        if not self.created_at and self.approved_at:
            self.created_at = self.approved_at


class PolicyEngine:
    """Evaluates agent permissions and gates high-risk operational requests."""

    def __init__(self, custom_permissions: Optional[Dict[str, Set[PermissionLevel]]] = None) -> None:
        self._agent_permissions = custom_permissions or AGENT_DEFAULT_PERMISSIONS
        self._approved_tokens: Dict[str, HumanApprovalRecord] = {}
        self._lock = threading.Lock()

    def register_approval(self, approval: HumanApprovalRecord) -> None:
        """Register a human approval record."""
        if not approval.capability_id and approval.action_type:
            approval.capability_id = approval.action_type
        if not approval.action_type and approval.capability_id:
            approval.action_type = approval.capability_id
        with self._lock:
            self._approved_tokens[approval.approval_token] = approval

    def create_server_approval(
        self,
        capability_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        run_id: str = "",
        business_id: Optional[str] = None,
        approved_by: str = "Human Operator",
        ttl_seconds: int = 300,
        risk_level: RiskLevel = RiskLevel.CRITICAL,
        scope: str = "",
    ) -> HumanApprovalRecord:
        """Issue a cryptographically secure, server-generated human approval record (>=256 bits entropy)."""
        token = f"appr_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc).isoformat()
        fp = compute_request_fingerprint(
            capability_id=capability_id,
            parameters=parameters or {},
            run_id=run_id,
            business_id=business_id,
        )
        record = HumanApprovalRecord(
            approval_token=token,
            action_type=capability_id,
            capability_id=capability_id,
            run_id=run_id,
            business_id=business_id,
            request_fingerprint=fp,
            approved_by=approved_by,
            approved_at=now.isoformat(),
            created_at=now.isoformat(),
            expires_at=expires_at,
            scope=scope or (business_id or "GLOBAL"),
            risk_level=risk_level,
            claimed=False,
            consumed=False,
        )
        with self._lock:
            self._approved_tokens[token] = record
        return record

    def revoke_approval(self, approval_token: str) -> None:
        """Revoke a human approval token."""
        with self._lock:
            self._approved_tokens.pop(approval_token, None)

    def claim_approval(self, approval_token: Optional[str]) -> bool:
        """Atomically claim an approval token BEFORE consequential connector dispatch (one-shot)."""
        if not approval_token:
            return False
        with self._lock:
            if approval_token not in self._approved_tokens:
                return False
            rec = self._approved_tokens[approval_token]
            if rec.consumed or rec.claimed:
                return False
            rec.claimed = True
            rec.claimed_at = datetime.now(timezone.utc).isoformat()
            return True

    def consume_approval(self, approval_token: Optional[str]) -> bool:
        """Finalize consumption of an approval token after consequential dispatch."""
        if not approval_token:
            return False
        with self._lock:
            if approval_token not in self._approved_tokens:
                return False
            rec = self._approved_tokens[approval_token]
            rec.claimed = True
            rec.consumed = True
            rec.consumed_at = datetime.now(timezone.utc).isoformat()
            return True

    def get_approval(self, approval_token: str) -> Optional[HumanApprovalRecord]:
        with self._lock:
            return self._approved_tokens.get(approval_token)

    def evaluate(
        self,
        agent_id: str,
        capability: CapabilityDescriptor,
        approval_token: Optional[str] = None,
        run_id: Optional[str] = None,
        business_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
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
                    error_code="HUMAN_APPROVAL_REQUIRED",
                    reason=f"HUMAN_APPROVAL_REQUIRED: Capability '{capability.capability_id}' has risk level {capability.risk_level.value} and requires human approval token.",
                )

            # Verify token exists in server-side registry
            if approval_token not in self._approved_tokens:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="INVALID_APPROVAL_TOKEN",
                    reason=f"INVALID_APPROVAL_TOKEN: Provided approval token '{approval_token}' is not registered or has been revoked.",
                )

            record = self._approved_tokens[approval_token]

            # Check claimed / consumed state (one-time replay prevention)
            if record.consumed or record.claimed:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_ALREADY_CONSUMED" if record.consumed else "APPROVAL_ALREADY_CLAIMED",
                    reason=f"APPROVAL_ALREADY_CONSUMED: Approval token '{approval_token}' has already been claimed or consumed and cannot be replayed.",
                )

            # Check expiration
            if record.expires_at:
                try:
                    exp_dt = datetime.fromisoformat(record.expires_at)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > exp_dt:
                        return PolicyDecision(
                            allowed=False,
                            requires_human_approval=True,
                            error_code="APPROVAL_EXPIRED",
                            reason=f"APPROVAL_EXPIRED: Approval token '{approval_token}' expired at {record.expires_at}.",
                        )
                except Exception as ex:
                    return PolicyDecision(
                        allowed=False,
                        requires_human_approval=True,
                        error_code="APPROVAL_RECORD_CORRUPT",
                        reason=f"APPROVAL_RECORD_CORRUPT: Invalid expires_at format in approval record: {ex}",
                    )

            # Check capability / action match
            rec_cap = record.capability_id or record.action_type
            if rec_cap and rec_cap.strip().lower() != capability.capability_id.strip().lower():
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_CAPABILITY_MISMATCH",
                    reason=f"APPROVAL_CAPABILITY_MISMATCH: Approval was granted for '{rec_cap}' but request is for '{capability.capability_id}'.",
                )

            # Check run_id match (if bound in record)
            if record.run_id and run_id and record.run_id != run_id:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_RUN_MISMATCH",
                    reason=f"APPROVAL_RUN_MISMATCH: Approval is bound to run '{record.run_id}', not '{run_id}'.",
                )

            # Check business_id match (if bound in record)
            if record.business_id and business_id and record.business_id != business_id:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_BUSINESS_MISMATCH",
                    reason=f"APPROVAL_BUSINESS_MISMATCH: Approval is bound to business '{record.business_id}', not '{business_id}'.",
                )

            # Check request fingerprint match (if present on record)
            if record.request_fingerprint and parameters is not None:
                expected_fp = compute_request_fingerprint(
                    capability_id=capability.capability_id,
                    parameters=parameters,
                    run_id=run_id or record.run_id,
                    business_id=business_id or record.business_id,
                )
                if record.request_fingerprint != expected_fp:
                    return PolicyDecision(
                        allowed=False,
                        requires_human_approval=True,
                        error_code="APPROVAL_FINGERPRINT_MISMATCH",
                        reason=f"APPROVAL_FINGERPRINT_MISMATCH: Request parameters/scope fingerprint do not match approval record.",
                    )

        return PolicyDecision(
            allowed=True,
            requires_human_approval=requires_approval,
            reason="AUTHORIZED",
        )
