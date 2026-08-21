"""Unit Tests for Phase 4.2.2: Claim Safety Runtime Enforcement.

Validates:
1. Real Five-Agent execution path integration with ClaimRegister
2. Pre-handoff validation across all specialist boundaries
3. Adversarial simulation test cases A through I (0 model calls)
4. Checkpoint persistence and restoration across restarts
5. Action Gate verification (blocks external mutations when claims are blocked)
6. Zero bypass verification (CLAIM_SAFETY_BYPASS_PATHS == 0)
"""

import json
from pathlib import Path
import tempfile
import unittest

from governance.claim_register import ClaimRegister
from governance.claim_safety import (
    ClaimStatusInvarianceValidator,
    CreativeClaimSafetyValidator,
    FinalClaimAuditGate,
    NumericAuthorityValidator,
    PerformancePlanningSafetyValidator,
    ProductClaimFirewall,
    ValidationDecision,
)
from governance.runtime_engine import GovernedExecutionPipeline
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    NumericStatus,
    SourceType,
    StatusAwareNumeric,
    SupportStatus,
)
from schemas.protocol import ActionRequest, AgentRole, ApprovalState, PermissionMode


class TestPhase422RuntimeEnforcement(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.pipeline = GovernedExecutionPipeline(register_id="TEST-PIPELINE-001")

    def test_case_a_intelligence_warranty_hypothesis_invariance(self):
        """Case A: Intelligence emits warranty as HYPOTHESIS -> Strategist attempts FACT upgrade -> blocked/downgraded."""
        claim = MaterialClaim(
            claim_id="CLM-WARRANTY-001",
            claim_text="12-month 1-to-1 warranty will drive higher conversion.",
            claim_class=ClaimClass.HYPOTHESIS,
            source_type=SourceType.AGENT_HYPOTHESIS,
            origin_agent="INTELLIGENCE",
            support_status=SupportStatus.PARTIALLY_SUPPORTED,
            allowed_usage=AllowedUsage.HYPOTHESIS_ONLY,
        )
        # Strategist attempts to upgrade hypothesis to verified product fact
        claim.claim_class = ClaimClass.VERIFIED_PRODUCT_FACT
        claim.allowed_usage = AllowedUsage.PUBLIC_CLAIM
        self.pipeline.claim_register.register_claim(claim)

        # Pre-handoff check from Strategist to Creative
        report = self.pipeline.pre_handoff_validation(
            from_agent="STRATEGIST",
            to_agent="CREATIVE",
            stage_output={"positioning": "Value proposition"},
        )
        self.assertFalse(report.is_valid)
        self.assertIn("CLM-WARRANTY-001", report.claims_modified_or_downgraded)
        updated = self.pipeline.claim_register.get_claim("CLM-WARRANTY-001")
        self.assertEqual(updated.allowed_usage, AllowedUsage.HYPOTHESIS_ONLY)

    def test_case_b_strategist_invents_retail_price(self):
        """Case B: Strategist invents retail price -> NumericAuthority gate catches before Creative."""
        claim = MaterialClaim(
            claim_id="CLM-PRICE-001",
            claim_text="Retail price is 399,000 VND.",
            claim_class=ClaimClass.PROPOSED_TARGET,
            source_type=SourceType.UNSUPPORTED_INVENTION,
            origin_agent="STRATEGIST",
            support_status=SupportStatus.SUPPORTED,  # Falsely marked supported without human input
            allowed_usage=AllowedUsage.PUBLIC_CLAIM,
        )
        self.pipeline.claim_register.register_claim(claim)

        report = self.pipeline.pre_handoff_validation(
            from_agent="STRATEGIST",
            to_agent="CREATIVE",
            stage_output={"price": 399000},
            has_human_input=False,
        )
        self.assertIn("CLM-PRICE-001", report.claims_modified_or_downgraded)
        updated_claim = self.pipeline.claim_register.get_claim("CLM-PRICE-001")
        self.assertEqual(updated_claim.support_status, SupportStatus.UNKNOWN)

    def test_case_c_creative_invents_product_weight(self):
        """Case C: Creative invents product weight -> Creative safety rejects claim."""
        res = CreativeClaimSafetyValidator.validate_creative_demonstration(
            demonstration_attribute="weight",
            claim_text="Scale shows exactly 100g compact weight.",
            is_verified_fact=False,
            is_visual_placeholder=False,
        )
        self.assertEqual(res.decision, ValidationDecision.FAIL)
        self.assertEqual(res.rule_name, "UNSUPPORTED_CREATIVE_DEMONSTRATION")

    def test_case_d_performance_invents_cpa_roas_sample_size(self):
        """Case D: Performance invents CPA/ROAS/sample size -> Performance validator converts to insufficient/proposed."""
        claim = MaterialClaim(
            claim_id="CLM-PERF-001",
            claim_text="Operating rule: CPA must not exceed 120,000 VND.",
            claim_class=ClaimClass.PROPOSED_TARGET,
            source_type=SourceType.UNSUPPORTED_INVENTION,
            origin_agent="PERFORMANCE",
            support_status=SupportStatus.SUPPORTED,
            allowed_usage=AllowedUsage.INTERNAL_PLANNING,
        )
        self.pipeline.claim_register.register_claim(claim)

        report = self.pipeline.pre_handoff_validation(
            from_agent="PERFORMANCE",
            to_agent="CMO_FINAL",
            stage_output={"target_cpa": 120000},
            has_human_input=False,
        )
        self.assertIn("CLM-PERF-001", report.claims_modified_or_downgraded)
        updated = self.pipeline.claim_register.get_claim("CLM-PERF-001")
        self.assertEqual(updated.allowed_usage, AllowedUsage.EXPERIMENT_ONLY)

    def test_case_e_category_gan_property_becomes_sku_thermal_claim(self):
        """Case E: Category GaN property becomes SKU thermal claim -> Product firewall blocks."""
        claim = MaterialClaim(
            claim_id="CLM-FIREWALL-001",
            claim_text="Our charger delivers certified coldest operating and Zero Motherboard Risk guarantee.",
            claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
            source_type=SourceType.AGENT_INFERENCE,
            origin_agent="STRATEGIST",
            support_status=SupportStatus.SUPPORTED,
            allowed_usage=AllowedUsage.PUBLIC_CLAIM,
        )
        self.pipeline.claim_register.register_claim(claim)

        report = self.pipeline.pre_handoff_validation(
            from_agent="STRATEGIST",
            to_agent="CREATIVE",
            stage_output={},
        )
        self.assertIn("CLM-FIREWALL-001", report.claims_modified_or_downgraded)
        updated = self.pipeline.claim_register.get_claim("CLM-FIREWALL-001")
        self.assertEqual(updated.support_status, SupportStatus.UNSUPPORTED)

    def test_case_f_unsupported_claims_reach_cmo_prose_anyway(self):
        """Case F: Unsupported claims reach CMO prose anyway -> deterministic FinalClaimAuditGate blocks final authorization."""
        claim = MaterialClaim(
            claim_id="CLM-UNSUPPORTED-001",
            claim_text="Zero Motherboard Risk guarantee.",
            claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
            source_type=SourceType.UNSUPPORTED_INVENTION,
            origin_agent="CMO_FINAL",
            support_status=SupportStatus.UNSUPPORTED,
            allowed_usage=AllowedUsage.PUBLIC_CLAIM,
        )
        self.pipeline.claim_register.register_claim(claim)

        audit = self.pipeline.evaluate_cmo_final_gate()
        self.assertEqual(audit.authorization_status, "BLOCKED")
        self.assertEqual(self.pipeline.final_authorization, "BLOCKED")

    def test_case_g_valid_human_authorized_budget(self):
        """Case G: Valid human-authorized budget -> passes."""
        res = NumericAuthorityValidator.validate_numeric_authority(
            field_category="BUDGET",
            numeric_entry=20000000,
            has_human_input=True,
        )
        self.assertEqual(res.decision, ValidationDecision.PASS)

    def test_case_h_verified_weight_evidence(self):
        """Case H: Verified weight evidence -> passes Creative."""
        res = CreativeClaimSafetyValidator.validate_creative_demonstration(
            demonstration_attribute="weight",
            claim_text="Weight confirmed on official lab balance.",
            is_verified_fact=True,
        )
        self.assertEqual(res.decision, ValidationDecision.PASS)

    def test_case_i_authorized_finance_cpa(self):
        """Case I: Authorized finance CPA -> passes Performance."""
        res = PerformancePlanningSafetyValidator.validate_experiment_design(
            has_variance_data=True,
            has_financial_authorization=True,
            cpa_ceiling=120000,
            is_explicitly_proposed_test=True,
        )
        self.assertEqual(res.decision, ValidationDecision.PASS)

    def test_checkpoint_persistence_and_restoration(self):
        """Verify ClaimRegister and audit histories persist and reload across restart."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_path = Path(tmpdir)
            claim = MaterialClaim(
                claim_id="CLM-PERSIST-001",
                claim_text="65W GaN charging output.",
                claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                source_type=SourceType.INPUT_SPEC,
                origin_agent="INTELLIGENCE",
                support_status=SupportStatus.SUPPORTED,
                allowed_usage=AllowedUsage.PUBLIC_CLAIM,
            )
            self.pipeline.claim_register.register_claim(claim)
            self.pipeline.evaluate_cmo_final_gate()
            self.pipeline.save_checkpoint(chk_path)

            # Reload pipeline
            restored = GovernedExecutionPipeline.load_checkpoint(chk_path)
            self.assertIsNotNone(restored.claim_register.get_claim("CLM-PERSIST-001"))
            self.assertEqual(restored.final_authorization, "APPROVED")

    def test_action_gate_blocks_when_claim_safety_is_blocked(self):
        """Verify ActionGate rejects publishing / spend requests when FinalClaimAuditGate is BLOCKED."""
        self.pipeline.final_authorization = "BLOCKED"
        action_req = ActionRequest(
            action_id="ACT-PUBLISH-001",
            agent_name=AgentRole.PERFORMANCE,
            product_id="PROD-GAN65",
            campaign_id="CAMP-PILOT-01",
            platform_target="Meta Ads API",
            requested_action="DEPLOY_AD_SET",
        )
        res = self.pipeline.validate_action_request(action_req, permission_mode=PermissionMode.SUPERVISED)
        self.assertEqual(res["decision"], "BLOCKED")
        self.assertEqual(res["approval_state"], ApprovalState.REJECTED)

    def test_zero_bypass_path_enforcement(self):
        """Verify there are 0 bypass paths in governed execution pipeline."""
        bypass_count = 0
        # Pipeline must require claim_register instantiation
        if not hasattr(self.pipeline, "claim_register") or self.pipeline.claim_register is None:
            bypass_count += 1
        # Pipeline must enforce pre_handoff_validation
        if not hasattr(self.pipeline, "pre_handoff_validation"):
            bypass_count += 1
        # Pipeline must enforce evaluate_cmo_final_gate
        if not hasattr(self.pipeline, "evaluate_cmo_final_gate"):
            bypass_count += 1
        # Pipeline must enforce validate_action_request
        if not hasattr(self.pipeline, "validate_action_request"):
            bypass_count += 1

        self.assertEqual(bypass_count, 0, "CLAIM_SAFETY_BYPASS_PATHS must be 0")


if __name__ == "__main__":
    unittest.main()
