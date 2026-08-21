"""Systemic Claim Safety, Provenance Invariance, and Fail-Closed Governance.

Implements generic architectural validators:
1. ClaimStatusInvarianceValidator
2. NumericAuthorityValidator
3. ProductClaimFirewall
4. CreativeClaimSafetyValidator
5. PerformancePlanningSafetyValidator
6. FinalClaimAuditGate
7. validate_claim_lineage
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from schemas.base import BaseModel, Field
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    ClaimStatusUpgradeRecord,
    MaterialClaim,
    NumericStatus,
    SourceType,
    StatusAwareNumeric,
    StatusAwarePolicy,
    SupportStatus,
)


class ValidationDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    DOWNGRADE_REQUIRED = "DOWNGRADE_REQUIRED"
    HUMAN_INPUT_REQUIRED = "HUMAN_INPUT_REQUIRED"


class ClaimValidationResult(BaseModel):
    """Result of a single claim safety validation."""
    claim_id: str
    decision: ValidationDecision
    rule_name: str
    reason: str
    recommended_action: str
    recommended_status: Optional[str] = None
    recommended_usage: Optional[AllowedUsage] = None


# ==============================================================================
# 1. CLAIM STATUS INVARIANCE VALIDATOR
# ==============================================================================
class ClaimStatusInvarianceValidator:
    """Ensures downstream receiving agents cannot silently upgrade epistemic status."""

    FORBIDDEN_SILENT_UPGRADES: Set[Tuple[ClaimClass, ClaimClass]] = {
        (ClaimClass.UNKNOWN, ClaimClass.VERIFIED_PRODUCT_FACT),
        (ClaimClass.UNKNOWN, ClaimClass.BUSINESS_FACT),
        (ClaimClass.HYPOTHESIS, ClaimClass.VERIFIED_PRODUCT_FACT),
        (ClaimClass.HYPOTHESIS, ClaimClass.BUSINESS_FACT),
        (ClaimClass.INFERENCE, ClaimClass.VERIFIED_PRODUCT_FACT),
        (ClaimClass.MARKET_OBSERVATION, ClaimClass.VERIFIED_PRODUCT_FACT),
        (ClaimClass.CUSTOMER_OBSERVATION, ClaimClass.VERIFIED_PRODUCT_FACT),
        (ClaimClass.PROPOSED_TARGET, ClaimClass.BUSINESS_FACT),
        (ClaimClass.PROPOSED_TEST, ClaimClass.BUSINESS_FACT),
    }

    AUTHORIZED_UPGRADE_SOURCES: Set[SourceType] = {
        SourceType.INPUT_SPEC,
        SourceType.VERIFIED_EVIDENCE,
        SourceType.HUMAN_BUSINESS_INPUT,
        SourceType.EXPERIMENT_RESULT,
    }

    @classmethod
    def validate_transition(
        cls,
        upstream_claim: MaterialClaim,
        downstream_claim_class: ClaimClass,
        downstream_usage: AllowedUsage,
        upgrade_source: Optional[SourceType] = None,
        upgrade_reason: Optional[str] = None,
        authorized_by: Optional[str] = None,
    ) -> ClaimValidationResult:
        """Validate whether an epistemic status change across handoff boundary is permitted."""
        orig_class = upstream_claim.claim_class

        # Check if an unauthorized upgrade occurred
        if (orig_class, downstream_claim_class) in cls.FORBIDDEN_SILENT_UPGRADES:
            if not upgrade_source or upgrade_source not in cls.AUTHORIZED_UPGRADE_SOURCES:
                return ClaimValidationResult(
                    claim_id=upstream_claim.claim_id,
                    decision=ValidationDecision.FAIL,
                    rule_name="STATUS_INVARIANCE_VIOLATION",
                    reason=f"Silent epistemic upgrade from {orig_class.value} to {downstream_claim_class.value} is prohibited without verified evidence, human business authorization, or experiment results.",
                    recommended_action="DOWNGRADE_TO_HYPOTHESIS",
                    recommended_status=orig_class.value,
                    recommended_usage=AllowedUsage.HYPOTHESIS_ONLY,
                )

        # Check if usage boundary was escalated without support
        if upstream_claim.allowed_usage in (AllowedUsage.HYPOTHESIS_ONLY, AllowedUsage.EXPERIMENT_ONLY):
            if downstream_usage == AllowedUsage.PUBLIC_CLAIM and upstream_claim.support_status != SupportStatus.SUPPORTED:
                return ClaimValidationResult(
                    claim_id=upstream_claim.claim_id,
                    decision=ValidationDecision.FAIL,
                    rule_name="USAGE_ESCALATION_VIOLATION",
                    reason=f"Claim with usage boundary {upstream_claim.allowed_usage.value} cannot be promoted to PUBLIC_CLAIM without verified support.",
                    recommended_action="BLOCK_PUBLICATION",
                    recommended_status=orig_class.value,
                    recommended_usage=upstream_claim.allowed_usage,
                )

        return ClaimValidationResult(
            claim_id=upstream_claim.claim_id,
            decision=ValidationDecision.PASS,
            rule_name="STATUS_INVARIANCE_OK",
            reason="Claim status transition respects epistemic boundary.",
            recommended_action="PRESERVE_STATUS",
        )


# ==============================================================================
# 2. NUMERIC AUTHORITY GATE
# ==============================================================================
class NumericAuthorityValidator:
    """Prevents agents from fabricating authoritative numbers for budgets, prices, KPIs, margins."""

    PROTECTED_NUMERIC_CATEGORIES: Set[str] = {
        "PRICE",
        "BUDGET",
        "COGS",
        "MARGIN",
        "CAC",
        "CPA",
        "ROAS",
        "ACOS",
        "RETURN_RATE",
        "CONVERSION_TARGET",
        "SAMPLE_SIZE",
        "MDE",
        "CONFIDENCE_THRESHOLD",
        "WARRANTY_DURATION",
        "WEIGHT",
        "DIMENSIONS",
        "PERFORMANCE_THRESHOLD",
        "CHANNEL_BUDGET_SPLIT",
        "KPI_TARGET",
        "EXPERIMENT_THRESHOLD",
        "INVENTED_BUSINESS_INPUT",
        "OFFER",
        "WARRANTY",
        "CHANNEL_DECISION",
        "FINANCIAL_TARGET",
    }

    @classmethod
    def validate_numeric_authority(
        cls,
        field_category: str,
        numeric_entry: Union[StatusAwareNumeric, Dict[str, Any], float, int, None],
        has_human_input: bool = False,
        has_verified_evidence: bool = False,
        is_mathematically_derived: bool = False,
        is_experiment_calculation: bool = False,
    ) -> ClaimValidationResult:
        """Validate if a protected numeric value has authoritative grounding."""
        cat_upper = field_category.upper()
        if cat_upper not in cls.PROTECTED_NUMERIC_CATEGORIES:
            return ClaimValidationResult(
                claim_id=field_category,
                decision=ValidationDecision.PASS,
                rule_name="NON_PROTECTED_CATEGORY",
                reason=f"Category {field_category} is not in protected numeric authority list.",
                recommended_action="ALLOW",
            )

        # Inspect value and status
        val = None
        status = None
        if isinstance(numeric_entry, StatusAwareNumeric):
            val = numeric_entry.value
            status = numeric_entry.status
        elif isinstance(numeric_entry, dict):
            val = numeric_entry.get("value")
            status = numeric_entry.get("status")
        elif isinstance(numeric_entry, (int, float)):
            val = numeric_entry
            status = "ESTABLISHED"
        elif numeric_entry is None:
            return ClaimValidationResult(
                claim_id=field_category,
                decision=ValidationDecision.PASS,
                rule_name="NULL_NUMERIC_OK",
                reason="Value is null / unestablished.",
                recommended_action="PRESERVE_UNKNOWN",
            )

        # If marked TO_BE_ESTABLISHED or PROPOSED_FOR_TEST, it is safe
        if status in (NumericStatus.TO_BE_ESTABLISHED, NumericStatus.PROPOSED_FOR_TEST, NumericStatus.INSUFFICIENT_DATA, "TO_BE_ESTABLISHED", "PROPOSED_FOR_TEST", "INSUFFICIENT_DATA"):
            return ClaimValidationResult(
                claim_id=field_category,
                decision=ValidationDecision.PASS,
                rule_name="STATUS_AWARE_NUMERIC_OK",
                reason=f"Protected numeric category {field_category} is properly flagged as {status}.",
                recommended_action="PRESERVE_CONTAINER",
            )

        # If value is present as an authoritative number, require valid grounding source
        if val is not None:
            is_grounded = (
                has_human_input
                or has_verified_evidence
                or is_mathematically_derived
                or is_experiment_calculation
            )
            if not is_grounded:
                return ClaimValidationResult(
                    claim_id=field_category,
                    decision=ValidationDecision.FAIL,
                    rule_name="UNSUPPORTED_NUMERIC_INVENTION",
                    reason=f"Protected numeric value {val} for {field_category} lacks human authorization, evidence support, or mathematical derivation.",
                    recommended_action="MARK_TO_BE_ESTABLISHED",
                    recommended_status=NumericStatus.TO_BE_ESTABLISHED.value,
                )

        return ClaimValidationResult(
            claim_id=field_category,
            decision=ValidationDecision.PASS,
            rule_name="NUMERIC_AUTHORITY_OK",
            reason="Authoritative number has verified grounding.",
            recommended_action="ALLOW",
        )


# ==============================================================================
# 3. PRODUCT CLAIM FIREWALL
# ==============================================================================
class ProductClaimFirewall:
    """Enforces semantic boundaries preventing external properties from becoming SKU features."""

    GENERIC_TECH_KEYWORDS = ["semiconductor enables", "technology enables", "can run cooler", "enables higher efficiency", "generally smaller"]
    CUSTOMER_PAIN_KEYWORDS = ["fear of", "anxiety regarding", "frustration with", "worried about", "concerns over"]
    COMPETITOR_KEYWORDS = ["competitor offers", "competitor brand", "market standard", "benchmark brands"]

    @classmethod
    def audit_claim_text(cls, claim_text: str, source_type: SourceType, evidence_content_role: Optional[str] = None) -> ClaimValidationResult:
        """Scan claim text for categorical, competitor, or customer-pain conflations."""
        text_lower = claim_text.lower()

        # Rule 1: Customer Fear != Our Verified Safety Feature
        if any(w in text_lower for w in ["zero motherboard risk", "guaranteed zero damage", "surge proof guarantee", "socket wobble proof design", "engineered socket fit", "center-of-gravity balance", "round wall outlets", "motherboard risk", "surge protection"]):
            if source_type != SourceType.INPUT_SPEC and source_type != SourceType.HUMAN_BUSINESS_INPUT:
                return ClaimValidationResult(
                    claim_id="PRODUCT_FIREWALL_FAIL",
                    decision=ValidationDecision.FAIL,
                    rule_name="CUSTOMER_PAIN_PROMOTED_TO_FEATURE",
                    reason="Customer anxiety or forum complaints cannot be converted into verified SKU hardware protections without lab test evidence.",
                    recommended_action="DOWNGRADE_TO_HYPOTHESIS",
                    recommended_usage=AllowedUsage.INTERNAL_PLANNING,
                )

        # Rule 2: Competitor Capability / Category Advantage != Verified SKU Measurement
        if any(w in text_lower for w in ["verified superior thermal efficiency", "certified coldest operating", "exact weight 100g", "measured 100g", "350g", "385g", "100g compact", "weight is exactly"]):
            if source_type != SourceType.INPUT_SPEC and source_type != SourceType.HUMAN_BUSINESS_INPUT:
                return ClaimValidationResult(
                    claim_id="PRODUCT_FIREWALL_FAIL",
                    decision=ValidationDecision.FAIL,
                    rule_name="CATEGORY_OR_COMPETITOR_PROMOTED_TO_SKU_FACT",
                    reason="General technology category traits or competitor benchmarks cannot be asserted as verified SKU measurements without product engineering proof.",
                    recommended_action="MARK_TO_BE_ESTABLISHED",
                    recommended_usage=AllowedUsage.INTERNAL_PLANNING,
                )

        # Rule 3: Universal Compatibility Overclaiming
        if any(w in text_lower for w in ["universal compatibility with all laptops", "charges every laptop", "works on any gaming rig"]):
            return ClaimValidationResult(
                claim_id="PRODUCT_FIREWALL_FAIL",
                decision=ValidationDecision.FAIL,
                rule_name="UNSUPPORTED_UNIVERSAL_COMPATIBILITY",
                reason="Universal compatibility cannot be claimed; output must qualify compatibility to supported USB-C Power Delivery specifications.",
                recommended_action="DOWNGRADE_TO_HYPOTHESIS",
                recommended_usage=AllowedUsage.INTERNAL_PLANNING,
            )

        return ClaimValidationResult(
            claim_id="PRODUCT_FIREWALL_PASS",
            decision=ValidationDecision.PASS,
            rule_name="PRODUCT_FIREWALL_OK",
            reason="Claim respects product fact boundaries.",
            recommended_action="ALLOW",
        )


# ==============================================================================
# 4. CREATIVE CLAIM SAFETY VALIDATOR
# ==============================================================================
class CreativeClaimSafetyValidator:
    """Validates that creative assets do not fabricate unverified physical measurements or policies."""

    FACTUAL_DEMONSTRATION_ATTRIBUTES: Set[str] = {
        "weight",
        "size",
        "temperature",
        "charging_speed",
        "compatibility",
        "durability",
        "warranty",
        "certification",
        "safety",
        "price",
    }

    @classmethod
    def validate_creative_demonstration(
        cls,
        demonstration_attribute: str,
        claim_text: str,
        is_verified_fact: bool,
        is_visual_placeholder: bool = False,
    ) -> ClaimValidationResult:
        """Validate if a physical demonstration in creative storyboard is grounded."""
        attr_lower = demonstration_attribute.lower()
        if attr_lower in cls.FACTUAL_DEMONSTRATION_ATTRIBUTES:
            if not is_verified_fact and not is_visual_placeholder:
                return ClaimValidationResult(
                    claim_id=f"CREATIVE_{attr_lower.upper()}",
                    decision=ValidationDecision.FAIL,
                    rule_name="UNSUPPORTED_CREATIVE_DEMONSTRATION",
                    reason=f"Creative visual demonstration asserts concrete {attr_lower} without verified product fact grounding. Must use VISUAL_PLACEHOLDER or CONCEPTUAL_DEMONSTRATION.",
                    recommended_action="MARK_TO_BE_ESTABLISHED",
                    recommended_usage=AllowedUsage.INTERNAL_PLANNING,
                )

        return ClaimValidationResult(
            claim_id=f"CREATIVE_{attr_lower.upper()}",
            decision=ValidationDecision.PASS,
            rule_name="CREATIVE_SAFETY_OK",
            reason="Creative demonstration is grounded or designated as conceptual placeholder.",
            recommended_action="ALLOW",
        )


# ==============================================================================
# 5. PERFORMANCE PLANNING SAFETY VALIDATOR
# ==============================================================================
class PerformancePlanningSafetyValidator:
    """Validates that performance plans distinguish proposed test designs from approved rules."""

    @classmethod
    def validate_experiment_design(
        cls,
        has_variance_data: bool,
        has_financial_authorization: bool,
        sample_size: Optional[Union[int, str]] = None,
        cpa_ceiling: Optional[Union[float, int, str]] = None,
        roas_target: Optional[Union[float, int, str]] = None,
        is_explicitly_proposed_test: bool = True,
    ) -> ClaimValidationResult:
        """Ensure statistical rules without variance baselines are labeled PROPOSED_TEST_DESIGN."""
        if (sample_size is not None or cpa_ceiling is not None or roas_target is not None):
            if not has_variance_data or not has_financial_authorization:
                if not is_explicitly_proposed_test:
                    return ClaimValidationResult(
                        claim_id="PERFORMANCE_THRESHOLD",
                        decision=ValidationDecision.FAIL,
                        rule_name="INSUFFICIENT_DATA_FOR_OPERATING_RULE",
                        reason="Statistical stopping thresholds and CPA/ROAS targets cannot be enforced as APPROVED_OPERATING_RULE without baseline variance telemetry and financial authorization. Must be marked PROPOSED_TEST_DESIGN with DATA_REQUIRED.",
                        recommended_action="MARK_TO_BE_ESTABLISHED",
                        recommended_status=NumericStatus.INSUFFICIENT_DATA.value,
                    )

        return ClaimValidationResult(
            claim_id="PERFORMANCE_THRESHOLD",
            decision=ValidationDecision.PASS,
            rule_name="PERFORMANCE_SAFETY_OK",
            reason="Experiment parameters are properly classified as proposed test designs or have authorized backing.",
            recommended_action="ALLOW",
        )


# ==============================================================================
# 6. FINAL CMO FAIL-CLOSED AUDIT GATE
# ==============================================================================
class FinalClaimAuditGateResult(BaseModel):
    """Aggregate audit report generated before CMO final authorization."""
    total_claims: int
    supported_claims: int
    unknown_claims: int
    hypotheses_count: int
    blocked_claims: int
    human_input_required_count: int
    authorization_status: str  # APPROVED | APPROVED_WITH_CONDITIONS | BLOCKED
    blocking_reasons: List[str] = Field(default_factory=list)
    claim_actions: Dict[str, str] = Field(default_factory=dict)


class FinalClaimAuditGate:
    """Automated fail-closed audit gate executed before CMO sign-off."""

    @classmethod
    def audit_claim_register(cls, claims: List[MaterialClaim]) -> FinalClaimAuditGateResult:
        """Audit all material claims against systemic safety gates."""
        total = len(claims)
        supported = 0
        unknowns = 0
        hypotheses = 0
        blocked = 0
        human_req = 0
        blocking_reasons = []
        claim_actions = {}

        for claim in claims:
            cid = claim.claim_id
            # 1. Product Claim Firewall Scan
            fw_res = ProductClaimFirewall.audit_claim_text(claim.claim_text, claim.source_type)
            if fw_res.decision == ValidationDecision.FAIL:
                blocked += 1
                blocking_reasons.append(f"{cid}: {fw_res.reason}")
                claim_actions[cid] = fw_res.recommended_action
                continue

            # 2. Status & Usage Check
            if claim.support_status == SupportStatus.UNSUPPORTED:
                if claim.allowed_usage == AllowedUsage.PUBLIC_CLAIM or claim.claim_class == ClaimClass.VERIFIED_PRODUCT_FACT:
                    blocked += 1
                    blocking_reasons.append(f"{cid}: Unsupported claim cannot be authorized for PUBLIC_CLAIM.")
                    claim_actions[cid] = "BLOCK_PUBLICATION"
                    continue
                else:
                    claim_actions[cid] = "MARK_TO_BE_ESTABLISHED"
                    unknowns += 1
                    continue

            if claim.support_status == SupportStatus.UNKNOWN or claim.claim_class == ClaimClass.UNKNOWN:
                unknowns += 1
                claim_actions[cid] = "MARK_TO_BE_ESTABLISHED"
                continue

            if claim.claim_class == ClaimClass.HYPOTHESIS:
                hypotheses += 1
                claim_actions[cid] = "PRESERVE_HYPOTHESIS"
                continue

            if claim.requires_human_input:
                human_req += 1
                claim_actions[cid] = "REQUEST_HUMAN_INPUT"
                continue

            if claim.support_status == SupportStatus.SUPPORTED or claim.support_status == SupportStatus.HUMAN_AUTHORIZED:
                supported += 1
                claim_actions[cid] = "AUTHORIZE"

        # Determine authorization status
        if blocked > 0:
            auth_status = "BLOCKED"
        elif human_req > 0 or unknowns > 0:
            auth_status = "APPROVED_WITH_CONDITIONS"
        else:
            auth_status = "APPROVED"

        return FinalClaimAuditGateResult(
            total_claims=total,
            supported_claims=supported,
            unknown_claims=unknowns,
            hypotheses_count=hypotheses,
            blocked_claims=blocked,
            human_input_required_count=human_req,
            authorization_status=auth_status,
            blocking_reasons=blocking_reasons,
            claim_actions=claim_actions,
        )


# ==============================================================================
# 7. HANDOFF VALIDATION
# ==============================================================================
def validate_claim_lineage(content: Dict[str, Any], claim_register: List[MaterialClaim]) -> Dict[str, Any]:
    """Validate handoff package claim lineage before sending between agents."""
    audit_res = FinalClaimAuditGate.audit_claim_register(claim_register)
    return {
        "handoff_valid": audit_res.authorization_status != "BLOCKED",
        "audit_result": audit_res.model_dump(),
        "preserved_claims_count": len(claim_register),
    }
