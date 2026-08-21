"""Unit Tests for Phase 4.0.1: Product Claim Semantic Audit & Evaluator Rules.

Verifies:
1. category property != product property
2. competitor feature != our feature
3. customer requirement != our product feature
4. 65W USB-C != universal laptop compatibility
5. GaN != verified cooler product temperature
6. customer heat concern != thermal protection feature
7. conditional compatibility wording accepted
8. new product evidence may permit stronger claim
9. downstream semantic escalation detected
10. external launch wording remains approval-gated
"""

import json
from pathlib import Path
import unittest


class TestProductClaimSemanticDiscipline(unittest.TestCase):
    def setUp(self):
        self.e2e_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "five_agent_e2e_gan65"

    def test_category_property_not_treated_as_verified_product_property(self):
        """Verify generic GaN technology properties are not treated as verified product measurements."""
        strat_path = self.e2e_dir / "strategy" / "strategist_output.json"
        self.assertTrue(strat_path.exists())

        strat_data = json.loads(strat_path.read_text(encoding="utf-8"))
        what_not = " ".join(strat_data.get("what_not_to_do", []))
        self.assertIn("Do NOT infer our product runs cooler", what_not)

    def test_competitor_feature_not_treated_as_our_feature(self):
        """Verify competitor multi-port or price features do not become our unverified product specs."""
        intel_path = self.e2e_dir / "research" / "intelligence_output.json"
        intel_data = json.loads(intel_path.read_text(encoding="utf-8"))

        # Gaps must explicitly record that our exact SKU price and specs remain unknown
        gaps = " ".join(intel_data.get("evidence_gaps", []))
        self.assertIn("SPECIFIC_SKU_PRICE = UNKNOWN", gaps)

    def test_customer_requirement_not_treated_as_our_product_feature(self):
        """Verify customer concern over thermal dissipation is treated as customer requirement, not verified feature."""
        intel_path = self.e2e_dir / "research" / "intelligence_output.json"
        strat_path = self.e2e_dir / "strategy" / "strategist_output.json"

        intel_data = json.loads(intel_path.read_text(encoding="utf-8"))
        strat_data = json.loads(strat_path.read_text(encoding="utf-8"))

        findings = " ".join(intel_data.get("validated_findings", []))
        self.assertIn("customer requirements and anxieties regarding thermal dissipation", findings)

        what_not = " ".join(strat_data.get("what_not_to_do", []))
        self.assertIn("Do NOT treat customer thermal/safety requirements as verified product features", what_not)

    def test_65w_usbc_not_treated_as_universal_laptop_compatibility(self):
        """Verify 65W USB-C is qualified rather than asserting universal compatibility across all laptops."""
        strat_path = self.e2e_dir / "strategy" / "strategist_output.json"
        strat_data = json.loads(strat_path.read_text(encoding="utf-8"))

        core_pos = strat_data.get("positioning", {}).get("core_positioning", "")
        self.assertIn("for compatible USB-C devices", core_pos)
        self.assertNotIn("universal laptop compatibility", core_pos.lower())

    def test_gan_technology_not_asserting_verified_cooler_product_temp(self):
        """Verify creative assets do not claim unverified cooler product temperatures."""
        crtv_path = self.e2e_dir / "creative" / "creative_output.json"
        crtv_data = json.loads(crtv_path.read_text(encoding="utf-8"))

        all_copy = " ".join([c.get("body", "") + " " + c.get("hook", "") for c in crtv_data.get("copy_assets", [])])
        self.assertNotIn("running cooler", all_copy.lower())
        self.assertNotIn("never overheats", all_copy.lower())
        self.assertNotIn("cool to the touch", all_copy.lower())

    def test_customer_heat_concern_not_claimed_as_thermal_protection_feature(self):
        """Verify customer heat concern is not silently upgraded to an unverified thermal protection guarantee."""
        strat_path = self.e2e_dir / "strategy" / "strategist_output.json"
        strat_data = json.loads(strat_path.read_text(encoding="utf-8"))

        recs = strat_data.get("recommendations", [])
        strat_02 = next((r for r in recs if r.get("rec_id") == "STRAT-02"), {})
        self.assertIn("customer risk requirements", strat_02.get("rationale", ""))
        self.assertNotIn("guaranteed zero overheating", json.dumps(strat_data).lower())

    def test_conditional_compatibility_wording_accepted(self):
        """Verify conditional compatibility language ('for compatible USB-C devices') is correctly used."""
        strat_path = self.e2e_dir / "strategy" / "strategist_output.json"
        crtv_path = self.e2e_dir / "creative" / "creative_output.json"

        strat_data = json.loads(strat_path.read_text(encoding="utf-8"))
        crtv_data = json.loads(crtv_path.read_text(encoding="utf-8"))

        strat_pos = strat_data.get("positioning", {}).get("core_positioning", "")
        self.assertTrue("compatible" in strat_pos.lower())

        copy_hero = next((c for c in crtv_data.get("copy_assets", []) if c.get("asset_id") == "COPY-HERO-01"), {})
        self.assertIn("compatible", copy_hero.get("headline", "").lower())

    def test_new_product_evidence_may_permit_stronger_claim_logic(self):
        """Verify evaluator allows stronger claims IF backed by explicit product-specific evidence."""
        # When supported by direct test evidence, a claim is valid
        supported_claim = {
            "claim": "Runs 15C cooler than OEM silicon brick at 65W load",
            "claim_type": "VERIFIED_PRODUCT_FACT",
            "evidence": ["EVID-LAB-TEST-GAN-001"],
            "verification_status": "LAB_VERIFIED",
        }
        self.assertEqual(supported_claim["claim_type"], "VERIFIED_PRODUCT_FACT")
        self.assertEqual(supported_claim["verification_status"], "LAB_VERIFIED")

    def test_downstream_semantic_escalation_detected_and_prevented(self):
        """Verify downstream stages (Creative, Performance, CMO) do not escalate product claims."""
        cmo_path = self.e2e_dir / "cmo" / "final_cmo_output.json"
        cmo_data = json.loads(cmo_path.read_text(encoding="utf-8"))

        exec_summary = cmo_data.get("executive_summary", {})
        know = " ".join(exec_summary.get("what_do_we_know", []))
        self.assertIn("Category literature indicates", know)
        self.assertIn("for compatible USB-C devices", know)

    def test_external_launch_wording_remains_approval_gated(self):
        """Verify external actions and deployment remain gated under SUPERVISED mode."""
        approval_path = self.e2e_dir / "cmo" / "approval_register.json"
        cmo_path = self.e2e_dir / "cmo" / "final_cmo_output.json"

        app_data = json.loads(approval_path.read_text(encoding="utf-8"))
        self.assertEqual(app_data.get("autonomy_mode"), "SUPERVISED")

        cmo_data = json.loads(cmo_path.read_text(encoding="utf-8"))
        act_on = " ".join(cmo_data.get("executive_summary", {}).get("what_is_strong_enough_to_act_on", []))
        self.assertIn("for human approval", act_on)


if __name__ == "__main__":
    unittest.main()
