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
from typing import Any, Dict, List, Optional, Set, Tuple
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


class PendingApprovalStatus(str, Enum):
    """Lifecycle status of a proposed consequential action awaiting human review."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class PendingApprovalRecord(BaseModel):
    """Immutable server-originated proposal for a consequential action awaiting explicit human decision."""
    pending_approval_id: str
    capability_id: str
    action_type: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    request_fingerprint: str = ""
    run_id: str = ""
    business_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    status: PendingApprovalStatus = PendingApprovalStatus.PENDING
    decision_reason: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    approval_token: Optional[str] = None
    scope: str = ""
    risk_level: RiskLevel = RiskLevel.CRITICAL

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.action_type and self.capability_id:
            self.action_type = self.capability_id
        if not self.capability_id and self.action_type:
            self.capability_id = self.action_type


class PolicyEngine:
    """Evaluates agent permissions and gates high-risk operational requests."""

    def __init__(self, custom_permissions: Optional[Dict[str, Set[PermissionLevel]]] = None) -> None:
        self._agent_permissions = custom_permissions or AGENT_DEFAULT_PERMISSIONS
        self._approved_tokens: Dict[str, HumanApprovalRecord] = {}
        self._pending_approvals: Dict[str, PendingApprovalRecord] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _is_expired(expires_at: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Return expiry state without ever exposing the approval token."""
        if not expires_at:
            return False, None
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > exp_dt, None
        except Exception as ex:
            return False, str(ex)

    def create_pending_approval(
        self,
        capability_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        run_id: str = "",
        business_id: Optional[str] = None,
        ttl_seconds: int = 300,
        scope: str = "",
        risk_level: RiskLevel = RiskLevel.CRITICAL,
    ) -> PendingApprovalRecord:
        """Create an immutable server-side pending approval record for a proposed consequential action."""
        params = parameters or {}
        fp = compute_request_fingerprint(
            capability_id=capability_id,
            parameters=params,
            run_id=run_id,
            business_id=business_id,
        )
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc).isoformat()

        with self._lock:
            # Check for existing active PENDING record with identical fingerprint and run
            for existing in self._pending_approvals.values():
                if (
                    existing.status == PendingApprovalStatus.PENDING
                    and existing.capability_id == capability_id
                    and existing.run_id == run_id
                    and existing.request_fingerprint == fp
                ):
                    # Check if expired
                    if existing.expires_at:
                        try:
                            exp_dt = datetime.fromisoformat(existing.expires_at)
                            if exp_dt.tzinfo is None:
                                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                            if now <= exp_dt:
                                return existing
                            existing.status = PendingApprovalStatus.EXPIRED
                        except Exception:
                            pass

            pending_id = f"pending_appr_{secrets.token_urlsafe(16)}"
            record = PendingApprovalRecord(
                pending_approval_id=pending_id,
                capability_id=capability_id,
                action_type=capability_id,
                parameters=params,
                request_fingerprint=fp,
                run_id=run_id,
                business_id=business_id,
                created_at=now.isoformat(),
                expires_at=expires_at,
                status=PendingApprovalStatus.PENDING,
                scope=scope or (business_id or "GLOBAL"),
                risk_level=risk_level,
            )
            self._pending_approvals[pending_id] = record
            return record

    def get_pending_approval(self, pending_approval_id: str) -> Optional[PendingApprovalRecord]:
        """Retrieve a pending approval record by ID."""
        with self._lock:
            return self._pending_approvals.get(pending_approval_id)

    def list_pending_approvals(
        self,
        run_id: Optional[str] = None,
        status: Optional[PendingApprovalStatus] = None,
    ) -> List[PendingApprovalRecord]:
        """List all pending approval records matching optional run_id or status filters."""
        now = datetime.now(timezone.utc)
        with self._lock:
            results = []
            for p in self._pending_approvals.values():
                # Auto-expire if past expiry date
                if p.status == PendingApprovalStatus.PENDING and p.expires_at:
                    try:
                        exp_dt = datetime.fromisoformat(p.expires_at)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        if now > exp_dt:
                            p.status = PendingApprovalStatus.EXPIRED
                    except Exception:
                        pass

                if run_id and p.run_id != run_id:
                    continue
                if status and p.status != status:
                    continue
                results.append(p)
            return results

    def approve_pending_action(
        self,
        pending_approval_id: str,
        approved_by: str = "Human Operator",
        decision_metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[HumanApprovalRecord], str]:
        """Explicitly approve a server-originated pending action, issuing a one-shot execution authority."""
        now = datetime.now(timezone.utc)
        with self._lock:
            rec = self._pending_approvals.get(pending_approval_id)
            if not rec:
                return False, None, "PENDING_ACTION_NOT_FOUND"

            # Check expiration
            if rec.expires_at:
                try:
                    exp_dt = datetime.fromisoformat(rec.expires_at)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if now > exp_dt:
                        rec.status = PendingApprovalStatus.EXPIRED
                        return False, None, "PENDING_ACTION_EXPIRED"
                except Exception as ex:
                    return False, None, f"CORRUPT_EXPIRY: {ex}"

            # Check current status
            if rec.status != PendingApprovalStatus.PENDING:
                return False, None, f"INVALID_STATUS_{rec.status.value}"

            # Transition state
            rec.status = PendingApprovalStatus.APPROVED
            rec.approved_by = approved_by
            rec.approved_at = now.isoformat()

            # Issue cryptographic one-shot execution authority
            token = f"appr_{secrets.token_urlsafe(32)}"
            ttl_sec = 300
            if rec.expires_at:
                try:
                    exp_dt = datetime.fromisoformat(rec.expires_at)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    ttl_sec = max(10, int((exp_dt - now).total_seconds()))
                except Exception:
                    pass

            approval_record = HumanApprovalRecord(
                approval_token=token,
                action_type=rec.capability_id,
                capability_id=rec.capability_id,
                run_id=rec.run_id,
                business_id=rec.business_id,
                request_fingerprint=rec.request_fingerprint,
                approved_by=approved_by,
                approved_at=now.isoformat(),
                created_at=now.isoformat(),
                expires_at=datetime.fromtimestamp(now.timestamp() + ttl_sec, tz=timezone.utc).isoformat(),
                scope=rec.scope,
                risk_level=rec.risk_level,
                claimed=False,
                consumed=False,
            )
            self._approved_tokens[token] = approval_record
            rec.approval_token = token
            return True, approval_record, "APPROVED"

    def reject_pending_action(
        self,
        pending_approval_id: str,
        reason: str = "Rejected by human operator",
    ) -> Tuple[bool, str]:
        """Explicitly reject a server-originated pending action."""
        with self._lock:
            rec = self._pending_approvals.get(pending_approval_id)
            if not rec:
                return False, "PENDING_ACTION_NOT_FOUND"

            if rec.status != PendingApprovalStatus.PENDING:
                return False, f"INVALID_STATUS_{rec.status.value}"

            rec.status = PendingApprovalStatus.REJECTED
            rec.decision_reason = reason
            return True, "REJECTED"

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
        """Atomically claim an unexpired approval token before consequential dispatch."""
        if not approval_token:
            return False
        with self._lock:
            rec = self._approved_tokens.get(approval_token)
            if rec is None or rec.consumed or rec.claimed:
                return False
            expired, corrupt = self._is_expired(rec.expires_at)
            if corrupt or expired:
                return False
            rec.claimed = True
            rec.claimed_at = datetime.now(timezone.utc).isoformat()
            return True

    def consume_approval(self, approval_token: Optional[str]) -> bool:
        """Finalize consumption of a claimed approval token after consequential dispatch."""
        if not approval_token:
            return False
        with self._lock:
            rec = self._approved_tokens.get(approval_token)
            if rec is None or rec.consumed or not rec.claimed:
                return False
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

            # Verify token exists in server-side registry. Never echo bearer authority.
            if approval_token not in self._approved_tokens:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="INVALID_APPROVAL_TOKEN",
                    reason="INVALID_APPROVAL_TOKEN: Provided approval authority is not registered or has been revoked.",
                )

            record = self._approved_tokens[approval_token]

            # Check claimed / consumed state (one-time replay prevention)
            if record.consumed or record.claimed:
                error_code = "APPROVAL_ALREADY_CONSUMED" if record.consumed else "APPROVAL_ALREADY_CLAIMED"
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code=error_code,
                    reason=f"{error_code}: Approval authority has already been used and cannot be replayed.",
                )

            # Check expiration
            expired, corrupt = self._is_expired(record.expires_at)
            if corrupt:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_RECORD_CORRUPT",
                    reason=f"APPROVAL_RECORD_CORRUPT: Invalid expires_at format in approval record: {corrupt}",
                )
            if expired:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_EXPIRED",
                    reason=f"APPROVAL_EXPIRED: Approval authority expired at {record.expires_at}.",
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

            # Bound scope is mandatory when present on the approval record.
            if record.run_id and not run_id:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_RUN_CONTEXT_REQUIRED",
                    reason="APPROVAL_RUN_CONTEXT_REQUIRED: Approval is bound to a run but the request supplied no run context.",
                )
            if record.run_id and record.run_id != run_id:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_RUN_MISMATCH",
                    reason=f"APPROVAL_RUN_MISMATCH: Approval is bound to run '{record.run_id}', not '{run_id}'.",
                )

            if record.business_id and not business_id:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_BUSINESS_CONTEXT_REQUIRED",
                    reason="APPROVAL_BUSINESS_CONTEXT_REQUIRED: Approval is bound to a business but the request supplied no business context.",
                )
            if record.business_id and record.business_id != business_id:
                return PolicyDecision(
                    allowed=False,
                    requires_human_approval=True,
                    error_code="APPROVAL_BUSINESS_MISMATCH",
                    reason=f"APPROVAL_BUSINESS_MISMATCH: Approval is bound to business '{record.business_id}', not '{business_id}'.",
                )

            # Fingerprints are exact request bindings; never backfill missing request context here.
            if record.request_fingerprint:
                if parameters is None:
                    return PolicyDecision(
                        allowed=False,
                        requires_human_approval=True,
                        error_code="APPROVAL_PARAMETERS_REQUIRED",
                        reason="APPROVAL_PARAMETERS_REQUIRED: Approval is bound to request parameters but none were supplied.",
                    )
                expected_fp = compute_request_fingerprint(
                    capability_id=capability.capability_id,
                    parameters=parameters,
                    run_id=run_id,
                    business_id=business_id,
                )
                if record.request_fingerprint != expected_fp:
                    return PolicyDecision(
                        allowed=False,
                        requires_human_approval=True,
                        error_code="APPROVAL_FINGERPRINT_MISMATCH",
                        reason="APPROVAL_FINGERPRINT_MISMATCH: Request parameters/scope fingerprint does not match approval record.",
                    )

        return PolicyDecision(
            allowed=True,
            requires_human_approval=requires_approval,
            reason="AUTHORIZED",
        )