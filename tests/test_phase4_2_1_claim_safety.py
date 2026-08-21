"""Unit Tests for Phase 4.2.1: Systemic Claim Safety Implementation.

Validates:
1. Claim Provenance Contract & MaterialClaim schema
2. Claim Status Invariance Validator
3. Numeric Authority Gate & StatusAwareNumeric container
4. Product Claim Firewall semantic boundaries
5. Creative Claim Safety Validator
6. Performance Planning Safety Validator
7. CMO Final Fail-Closed Gate & Authorization state
8. Offline audit detection of 14/14 known failures
"""

import json
from pathlib import Path
import unittest

from governance.claim_safety import (
    ClaimStatusInvarianceValidator,
    CreativeClaimSafetyValidator,
    FinalClaimAuditGate,
    NumericAuthorityValidator,
    PerformancePlanningSafetyValidator,
    ProductClaimFirewall,
    ValidationDecision,
    validate_claim_lineage,
)
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    NumericStatus,
    SourceType,
    StatusAwareNumeric,
    StatusAwarePolicy,
    SupportStatus,
)


class TestPhase421ClaimSafety(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.lineage_path = self.base_dir / "evaluations" / "phase4_2_claim_lineage.json"
        self.assertTrue(self.lineage_path.exists())

    def test_claim_provenance_contract_structure(self):
        """Verify MaterialClaim schema requires all provenance fields."""
        claim = MaterialClaim(
            claim_id="CLM-TEST-001",
            claim_text="GaN power delivers 65W output.",
            claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
            source_type=SourceType.INPUT_SPEC,
            source_ids=["EVID-GAN65-01"],
            origin_agent="INTELLIGENCE",
            support_status=SupportStatus.SUPPORTED,
            confidence=1.0,
            allowed_usage=AllowedUsage.PUBLIC_CLAIM,
        )
        self.assertEqual(claim.claim_class, ClaimClass.VERIFIED_PRODUCT_FACT)
        self.assertEqual(claim.support_status, SupportStatus.SUPPORTED)
        self.assertEqual(claim.allowed_usage, AllowedUsage.PUBLIC_CLAIM)

    def test_claim_status_invariance_blocks_silent_upgrades(self):
        """Verify receiving agent cannot upgrade HYPOTHESIS to FACT without source evidence."""
        up_claim = MaterialClaim(
            claim_id="CLM-HYPO-001",
            claim_text="12-month warranty will maximize volume.",
            claim_class=ClaimClass.HYPOTHESIS,
            source_type=SourceType.AGENT_HYPOTHESIS,
            origin_agent="INTELLIGENCE",
            support_status=SupportStatus.PARTIALLY_SUPPORTED,
            allowed_usage=AllowedUsage.HYPOTHESIS_ONLY,
        )

        # Attempt silent promotion to FACT in Strategist
        res = ClaimStatusInvarianceValidator.validate_transition(
            upstream_claim=up_claim,
            downstream_claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
            downstream_usage=AllowedUsage.PUBLIC_CLAIM,
        )
        self.assertEqual(res.decision, ValidationDecision.FAIL)
        self.assertEqual(res.rule_name, "STATUS_INVARIANCE_VIOLATION")
        self.assertEqual(res.recommended_action, "DOWNGRADE_TO_HYPOTHESIS")

    def test_numeric_authority_blocks_unauthorized_numbers(self):
        """Verify NumericAuthorityValidator blocks ungrounded numeric values."""
        # Unbacked 20M budget
        res_budget = NumericAuthorityValidator.validate_numeric_authority(
            field_category="BUDGET",
            numeric_entry=20000000,
            has_human_input=False,
            has_verified_evidence=False,
        )
        self.assertEqual(res_budget.decision, ValidationDecision.FAIL)
        self.assertEqual(res_budget.rule_name, "UNSUPPORTED_NUMERIC_INVENTION")

        # Unbacked CPA ceiling
        res_cpa = NumericAuthorityValidator.validate_numeric_authority(
            field_category="CPA",
            numeric_entry=120000,
            has_human_input=False,
            has_verified_evidence=False,
        )
        self.assertEqual(res_cpa.decision, ValidationDecision.FAIL)

    def test_numeric_authority_allows_human_and_derived_numbers(self):
        """Verify NumericAuthorityValidator allows human authorized or derived numbers."""
        # Human authorized price
        res_price = NumericAuthorityValidator.validate_numeric_authority(
            field_category="PRICE",
            numeric_entry=429000,
            has_human_input=True,
        )
        self.assertEqual(res_price.decision, ValidationDecision.PASS)

        # Experiment calculated sample size
        res_ss = NumericAuthorityValidator.validate_numeric_authority(
            field_category="SAMPLE_SIZE",
            numeric_entry=1200,
            is_experiment_calculation=True,
        )
        self.assertEqual(res_ss.decision, ValidationDecision.PASS)

    def test_status_aware_numeric_eliminates_slot_pressure(self):
        """Verify StatusAwareNumeric represents TO_BE_ESTABLISHED and PROPOSED_FOR_TEST without fabricating numbers."""
        num_unknown = StatusAwareNumeric.to_be_established(unit="VND", data_required="Historical conversion baseline")
        self.assertIsNone(num_unknown.value)
        self.assertEqual(num_unknown.status, NumericStatus.TO_BE_ESTABLISHED)

        res_check = NumericAuthorityValidator.validate_numeric_authority(
            field_category="CAC",
            numeric_entry=num_unknown,
        )
        self.assertEqual(res_check.decision, ValidationDecision.PASS)
        self.assertEqual(res_check.rule_name, "STATUS_AWARE_NUMERIC_OK")

    def test_product_claim_firewall_blocks_customer_fear_to_feature(self):
        """Verify ProductClaimFirewall blocks converting consumer anxiety into verified hardware features."""
        claim_text = "Charger incorporates engineered socket wobble proof design and Zero Motherboard Risk guarantee."
        res = ProductClaimFirewall.audit_claim_text(claim_text, source_type=SourceType.AGENT_INFERENCE)
        self.assertEqual(res.decision, ValidationDecision.FAIL)
        self.assertEqual(res.rule_name, "CUSTOMER_PAIN_PROMOTED_TO_FEATURE")

    def test_product_claim_firewall_blocks_category_to_sku_efficiency(self):
        """Verify ProductClaimFirewall blocks asserting category advantage as verified SKU measurement."""
        claim_text = "Product has verified superior thermal efficiency with measured 100g compact weight."
        res = ProductClaimFirewall.audit_claim_text(claim_text, source_type=SourceType.AGENT_INFERENCE)
        self.assertEqual(res.decision, ValidationDecision.FAIL)
        self.assertEqual(res.rule_name, "CATEGORY_OR_COMPETITOR_PROMOTED_TO_SKU_FACT")

    def test_creative_claim_safety_blocks_unsupported_physical_measurements(self):
        """Verify CreativeClaimSafetyValidator blocks asserting 100g vs 350g without verified fact."""
        res = CreativeClaimSafetyValidator.validate_creative_demonstration(
            demonstration_attribute="weight",
            claim_text="Scale displays 385g OEM vs 100g GaN",
            is_verified_fact=False,
            is_visual_placeholder=False,
        )
        self.assertEqual(res.decision, ValidationDecision.FAIL)
        self.assertEqual(res.rule_name, "UNSUPPORTED_CREATIVE_DEMONSTRATION")

    def test_creative_claim_safety_allows_story_structure_and_placeholders(self):
        """Verify CreativeClaimSafetyValidator allows creative metaphors and conceptual placeholders."""
        res = CreativeClaimSafetyValidator.validate_creative_demonstration(
            demonstration_attribute="weight",
            claim_text="Visual metaphor: Heavy brick sweeping off desk",
            is_verified_fact=False,
            is_visual_placeholder=True,
        )
        self.assertEqual(res.decision, ValidationDecision.PASS)

    def test_performance_planning_safety_blocks_unauthorized_operating_rules(self):
        """Verify PerformancePlanningSafetyValidator blocks ungrounded operating rules."""
        res = PerformancePlanningSafetyValidator.validate_experiment_design(
            has_variance_data=False,
            has_financial_authorization=False,
            sample_size=1200,
            cpa_ceiling=120000,
            is_explicitly_proposed_test=False,
        )
        self.assertEqual(res.decision, ValidationDecision.FAIL)
        self.assertEqual(res.rule_name, "INSUFFICIENT_DATA_FOR_OPERATING_RULE")

    def test_cmo_final_fail_closed_gate_blocks_unsupported_claims(self):
        """Verify FinalClaimAuditGate blocks executive authorization when unsupported claims exist."""
        claims = [
            MaterialClaim(
                claim_id="CLM-001",
                claim_text="GaN semiconductor delivers 65W output.",
                claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                source_type=SourceType.INPUT_SPEC,
                origin_agent="INTELLIGENCE",
                support_status=SupportStatus.SUPPORTED,
                allowed_usage=AllowedUsage.PUBLIC_CLAIM,
            ),
            MaterialClaim(
                claim_id="CLM-002",
                claim_text="Product has Zero Motherboard Risk guarantee.",
                claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                source_type=SourceType.UNSUPPORTED_INVENTION,
                origin_agent="STRATEGIST",
                support_status=SupportStatus.UNSUPPORTED,
                allowed_usage=AllowedUsage.PUBLIC_CLAIM,
            ),
        ]
        audit = FinalClaimAuditGate.audit_claim_register(claims)
        self.assertEqual(audit.authorization_status, "BLOCKED")
        self.assertEqual(audit.blocked_claims, 1)

    def test_cmo_final_gate_approves_fully_grounded_claims(self):
        """Verify FinalClaimAuditGate approves when all claims are supported or preserved unknowns."""
        claims = [
            MaterialClaim(
                claim_id="CLM-001",
                claim_text="GaN semiconductor delivers 65W output.",
                claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                source_type=SourceType.INPUT_SPEC,
                origin_agent="INTELLIGENCE",
                support_status=SupportStatus.SUPPORTED,
                allowed_usage=AllowedUsage.PUBLIC_CLAIM,
            ),
            MaterialClaim(
                claim_id="CLM-002",
                claim_text="Retail price is TO_BE_ESTABLISHED by Human Stakeholder.",
                claim_class=ClaimClass.UNKNOWN,
                source_type=SourceType.UNSUPPORTED_INVENTION,
                origin_agent="STRATEGIST",
                support_status=SupportStatus.UNKNOWN,
                allowed_usage=AllowedUsage.INTERNAL_PLANNING,
            ),
        ]
        audit = FinalClaimAuditGate.audit_claim_register(claims)
        self.assertEqual(audit.authorization_status, "APPROVED_WITH_CONDITIONS")
        self.assertEqual(audit.blocked_claims, 0)

    def test_offline_audit_detects_all_14_known_failures(self):
        """Verify offline audit detects 14/14 known unsupported claims from Phase 4.1.2."""
        from evaluations.run_phase4_2_1_offline_audit import run_offline_audit
        run_offline_audit()
        report_path = self.base_dir / "evaluations" / "phase4_2_1_claim_safety_report.md"
        self.assertTrue(report_path.exists())
        content = report_path.read_text(encoding="utf-8")
        self.assertIn("`KNOWN_FAILURES_DETECTED`:** **`14/14`**", content)


if __name__ == "__main__":
    unittest.main()
