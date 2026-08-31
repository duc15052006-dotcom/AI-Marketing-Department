"""Governed Five-Agent Runtime Execution Engine & Action Gate.

Enforces mandatory runtime claim safety, persistent ClaimRegister state,
pre-handoff validation, and deterministic CMO Final fail-closed authorization.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from schemas.base import BaseModel, Field
from governance.claim_register import ClaimRegister
from governance.claim_safety import (
    ClaimStatusInvarianceValidator,
    ClaimValidationResult,
    CreativeClaimSafetyValidator,
    FinalClaimAuditGate,
    FinalClaimAuditGateResult,
    NumericAuthorityValidator,
    PerformancePlanningSafetyValidator,
    ProductClaimFirewall,
    ValidationDecision,
)
from integrations.models.base import BaseModelAdapter
from integrations.models.invocation import AgentRunResult, invoke_agent
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    NumericStatus,
    SourceType,
    StatusAwareNumeric,
    SupportStatus,
)
from schemas.protocol import ActionRequest, AgentRole, ApprovalState, PermissionMode, TaskEnvelope, TaskStatus

logger = logging.getLogger("governed_runtime")


class PreHandoffAuditReport(BaseModel):
    """Audit report generated before passing output from Agent N to Agent N+1."""
    from_agent: str
    to_agent: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_valid: bool
    validation_failures: List[ClaimValidationResult] = Field(default_factory=list)
    claims_modified_or_downgraded: List[str] = Field(default_factory=list)
    allowed_claims_for_receiver: List[str] = Field(default_factory=list)


class GovernedExecutionPipeline:
    """Manages the full 6-stage Five-Agent execution with strict claim-safety gates."""

    def __init__(self, register_id: str = "GOVERNED-REGISTER-001"):
        self.claim_register = ClaimRegister(register_id=register_id)
        self.handoff_audit_history: List[PreHandoffAuditReport] = []
        self.final_audit_result: Optional[FinalClaimAuditGateResult] = None
        self.final_authorization: str = "PENDING"  # PENDING | APPROVED | APPROVED_WITH_CONDITIONS | BLOCKED

    def pre_handoff_validation(
        self,
        from_agent: str,
        to_agent: str,
        stage_output: Dict[str, Any],
        has_human_input: bool = False,
    ) -> PreHandoffAuditReport:
        """Run all Phase 4.2.1 safety validators before passing output to next agent."""
        failures: List[ClaimValidationResult] = []
        downgraded: List[str] = []

        all_claims = self.claim_register.get_all_claims()

        for claim in all_claims:
            # 1. Product Claim Firewall
            res_fw = ProductClaimFirewall.audit_claim_text(claim.claim_text, claim.source_type)
            if res_fw.decision == ValidationDecision.FAIL:
                failures.append(res_fw)
                if claim.support_status != SupportStatus.UNSUPPORTED:
                    self.claim_register.modify_claim(
                        claim_id=claim.claim_id,
                        new_status=SupportStatus.UNSUPPORTED,
                        new_usage=AllowedUsage.INTERNAL_PLANNING,
                        reason=res_fw.reason,
                        agent_id=from_agent,
                    )
                    downgraded.append(claim.claim_id)

            # 2. Claim Status Invariance Validation
            if claim.claim_class == ClaimClass.VERIFIED_PRODUCT_FACT and claim.source_type in (SourceType.AGENT_HYPOTHESIS, SourceType.UNSUPPORTED_INVENTION):
                res_inv = ClaimStatusInvarianceValidator.validate_transition(
                    upstream_claim=MaterialClaim(
                        claim_id=claim.claim_id,
                        claim_text=claim.claim_text,
                        claim_class=ClaimClass.HYPOTHESIS,
                        source_type=SourceType.AGENT_HYPOTHESIS,
                        origin_agent=claim.origin_agent,
                        support_status=SupportStatus.PARTIALLY_SUPPORTED,
                        allowed_usage=AllowedUsage.HYPOTHESIS_ONLY,
                    ),
                    downstream_claim_class=claim.claim_class,
                    downstream_usage=claim.allowed_usage,
                )
                if res_inv.decision == ValidationDecision.FAIL:
                    failures.append(res_inv)
                    self.claim_register.modify_claim(
                        claim_id=claim.claim_id,
                        new_status=SupportStatus.PARTIALLY_SUPPORTED,
                        new_usage=AllowedUsage.HYPOTHESIS_ONLY,
                        reason=res_inv.reason,
                        agent_id=from_agent,
                    )
                    downgraded.append(claim.claim_id)

            # 3. Numeric Authority Validator
            cat = "PRICE" if "price" in claim.claim_text.lower() else ("BUDGET" if "budget" in claim.claim_text.lower() else claim.claim_class.value)
            if claim.claim_class in (ClaimClass.PROPOSED_TARGET, ClaimClass.BUSINESS_FACT) or cat in ("PRICE", "BUDGET"):
                res_num = NumericAuthorityValidator.validate_numeric_authority(
                    field_category=cat,
                    numeric_entry=1.0 if claim.support_status == SupportStatus.SUPPORTED else None,
                    has_human_input=has_human_input,
                )
                if res_num.decision == ValidationDecision.FAIL:
                    failures.append(res_num)
                    self.claim_register.modify_claim(
                        claim_id=claim.claim_id,
                        new_status=SupportStatus.UNKNOWN,
                        new_usage=AllowedUsage.INTERNAL_PLANNING,
                        reason=res_num.reason,
                        agent_id=from_agent,
                    )
                    downgraded.append(claim.claim_id)

            # 4. Creative Target Filtering
            if to_agent.lower() == "creative":
                # Creative can only consume PUBLIC_CLAIM or VERIFIED_PRODUCT_FACT as public claims
                if claim.allowed_usage == AllowedUsage.HYPOTHESIS_ONLY and claim.claim_class == ClaimClass.VERIFIED_PRODUCT_FACT:
                    failures.append(ClaimValidationResult(
                        claim_id=claim.claim_id,
                        decision=ValidationDecision.FAIL,
                        rule_name="CREATIVE_USAGE_RESTRICTION",
                        reason=f"Claim {claim.claim_id} is a hypothesis and cannot be passed to Creative as a verified product fact.",
                        recommended_action="FILTER_FROM_CREATIVE_CONTEXT",
                    ))

            # 4. Performance Planning Validator
            if from_agent.lower() == "performance":
                if "rule" in claim.claim_text.lower() or "cpa" in claim.claim_text.lower():
                    res_perf = PerformancePlanningSafetyValidator.validate_experiment_design(
                        has_variance_data=False,
                        has_financial_authorization=has_human_input,
                        cpa_ceiling=100.0,
                        is_explicitly_proposed_test=False,
                    )
                    if res_perf.decision == ValidationDecision.FAIL:
                        failures.append(res_perf)
                        self.claim_register.modify_claim(
                            claim_id=claim.claim_id,
                            new_status=SupportStatus.UNKNOWN,
                            new_usage=AllowedUsage.EXPERIMENT_ONLY,
                            reason=res_perf.reason,
                            agent_id=from_agent,
                        )
                        downgraded.append(claim.claim_id)

        # Snapshot version for from_agent
        self.claim_register.create_snapshot(stage_name=from_agent)

        allowed_for_next = [
            c.claim_id for c in self.claim_register.get_all_claims()
            if c.allowed_usage != AllowedUsage.BLOCKED
        ]

        report = PreHandoffAuditReport(
            from_agent=from_agent,
            to_agent=to_agent,
            is_valid=(len(failures) == 0),
            validation_failures=failures,
            claims_modified_or_downgraded=downgraded,
            allowed_claims_for_receiver=allowed_for_next,
        )
        self.handoff_audit_history.append(report)
        return report

    def evaluate_cmo_final_gate(self) -> FinalClaimAuditGateResult:
        """Deterministic fail-closed audit gate executed after CMO Final model response."""
        audit_res = FinalClaimAuditGate.audit_claim_register(self.claim_register.get_all_claims())
        self.final_audit_result = audit_res
        self.final_authorization = audit_res.authorization_status
        return audit_res

    def validate_action_request(
        self,
        action_request: Union[ActionRequest, Dict[str, Any]],
        permission_mode: PermissionMode = PermissionMode.SUPERVISED,
    ) -> Dict[str, Any]:
        """Verify action request against both deterministic claim safety and permission state."""
        # 1. Deterministic Claim Gate Check
        if self.final_authorization == "BLOCKED":
            return {
                "decision": "BLOCKED",
                "action_id": getattr(action_request, "action_id", "ACT-001"),
                "reason": "Execution blocked: FinalClaimAuditGate contains unresolved blocking unsupported claims.",
                "blocking_reasons": self.final_audit_result.blocking_reasons if self.final_audit_result else [],
                "approval_state": ApprovalState.REJECTED,
            }

        # Non-terminal claim authorization states never grant autonomous
        # execution authority. Only explicit APPROVED reaches the permission
        # mode gate; PENDING/conditional states remain human-gated.
        if self.final_authorization != "APPROVED":
            return {
                "decision": "READY_FOR_HUMAN_APPROVAL",
                "action_id": getattr(action_request, "action_id", "ACT-001"),
                "reason": (
                    "Final claim authorization is not fully approved; "
                    f"current state={self.final_authorization}. Human resolution/sign-off is required."
                ),
                "approval_state": ApprovalState.PENDING_APPROVAL,
            }

        # 2. Permission Mode Evaluation
        if permission_mode == PermissionMode.MANUAL or permission_mode == PermissionMode.SUPERVISED:
            return {
                "decision": "READY_FOR_HUMAN_APPROVAL",
                "action_id": getattr(action_request, "action_id", "ACT-001"),
                "reason": "Claim safety verified; awaiting mandatory human executive sign-off under SUPERVISED mode.",
                "approval_state": ApprovalState.PENDING_APPROVAL,
            }

        return {
            "decision": "AUTHORIZED",
            "action_id": getattr(action_request, "action_id", "ACT-001"),
            "reason": "Claim safety and permission checks passed.",
            "approval_state": ApprovalState.APPROVED,
        }

    def save_checkpoint(self, checkpoint_dir: Path) -> None:
        """Persist ClaimRegister and validation audit history to checkpoint files."""
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / "claim_register_checkpoint.json").write_text(
            json.dumps(self.claim_register.to_dict(), indent=2), encoding="utf-8"
        )
        history_data = [r.model_dump(mode="json") for r in self.handoff_audit_history]
        (checkpoint_dir / "handoff_audit_history.json").write_text(
            json.dumps(history_data, indent=2), encoding="utf-8"
        )
        if self.final_audit_result:
            (checkpoint_dir / "final_cmo_audit.json").write_text(
                json.dumps(self.final_audit_result.model_dump(mode="json"), indent=2), encoding="utf-8"
            )

    @classmethod
    def load_checkpoint(cls, checkpoint_dir: Path) -> GovernedExecutionPipeline:
        """Restore GovernedExecutionPipeline from checkpoint files."""
        pipeline = cls()
        reg_file = checkpoint_dir / "claim_register_checkpoint.json"
        if reg_file.exists():
            data = json.loads(reg_file.read_text(encoding="utf-8"))
            pipeline.claim_register = ClaimRegister.from_dict(data)

        audit_file = checkpoint_dir / "final_cmo_audit.json"
        if audit_file.exists():
            audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
            pipeline.final_audit_result = FinalClaimAuditGateResult(**audit_data)
            pipeline.final_authorization = pipeline.final_audit_result.authorization_status

        return pipeline
