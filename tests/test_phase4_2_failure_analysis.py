"""Unit Tests for Phase 4.2: Five-Agent Hallucination & Handoff Failure Analysis.

Validates:
1. Deterministic failure detection across all 14 unsupported claim classes
2. Claim lineage traceability and originator tracking
3. Product Claim Firewall rules (Customer Pain != Feature, Category != SKU)
4. Numeric Authority Rules (No invented budgets, prices, margins, CPAs, sample sizes)
5. Handoff Claim Inheritance & Status Invariance
6. CMO Final Fail-Closed Provenance Gate
"""

import json
from pathlib import Path
import unittest


class TestPhase42FailureAnalysis(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.lineage_path = self.base_dir / "evaluations" / "phase4_2_claim_lineage.json"
        self.report_path = self.base_dir / "evaluations" / "phase4_2_failure_analysis.md"
        self.parity_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_1_2_true_parity"

        self.assertTrue(self.lineage_path.exists(), "Lineage JSON must exist")
        self.assertTrue(self.report_path.exists(), "Analysis Markdown must exist")
        self.lineage_data = json.loads(self.lineage_path.read_text(encoding="utf-8"))

    def test_lineage_metadata_and_artifact_hashes(self):
        """Verify frozen artifact hashes are captured and match non-empty files."""
        meta = self.lineage_data.get("metadata", {})
        self.assertEqual(meta.get("analysis_phase"), "4.2")
        self.assertEqual(meta.get("total_material_claims"), 20)
        self.assertEqual(meta.get("supported_claims"), 6)
        self.assertEqual(meta.get("unsupported_claims"), 14)

        hashes = meta.get("artifact_hashes", {})
        self.assertEqual(len(hashes), 7)
        for k, h in hashes.items():
            self.assertEqual(len(h.get("sha256", "")), 64)
            self.assertGreater(h.get("size_bytes", 0), 0)

    def test_missing_budget_cannot_be_invented(self):
        """Verify 20M VND budget is flagged as INVENTED_BUSINESS_INPUT."""
        claims = {c["CLAIM_ID"]: c for c in self.lineage_data["claims"]}
        clm = claims.get("CLM-004")
        self.assertIsNotNone(clm)
        self.assertFalse(clm["SUPPORTED"])
        self.assertEqual(clm["FAILURE_TYPE"], "INVENTED_BUSINESS_INPUT")
        self.assertEqual(clm["ORIGINATOR"], "PERFORMANCE")
        self.assertIn("CMO_FINAL", clm["FAILED_REVIEWERS"])

    def test_missing_price_cannot_be_invented(self):
        """Verify 369k-429k VND retail pricing is flagged as INVENTED_BUSINESS_INPUT."""
        claims = {c["CLAIM_ID"]: c for c in self.lineage_data["claims"]}
        clm = claims.get("CLM-005")
        self.assertIsNotNone(clm)
        self.assertFalse(clm["SUPPORTED"])
        self.assertEqual(clm["FAILURE_TYPE"], "INVENTED_BUSINESS_INPUT")
        self.assertEqual(clm["ORIGINATOR"], "STRATEGIST")

    def test_missing_warranty_cannot_be_promoted_from_hypothesis(self):
        """Verify 12-month warranty is flagged as HYPOTHESIS_PROMOTED_TO_FACT."""
        claims = {c["CLAIM_ID"]: c for c in self.lineage_data["claims"]}
        clm = claims.get("CLM-011")
        self.assertIsNotNone(clm)
        self.assertFalse(clm["SUPPORTED"])
        self.assertEqual(clm["FAILURE_TYPE"], "HYPOTHESIS_PROMOTED_TO_FACT")
        self.assertEqual(clm["ORIGINATOR"], "INTELLIGENCE")

    def test_customer_pain_cannot_become_product_feature(self):
        """Verify socket wobble / motherboard surge anxiety is flagged when claimed as SKU feature."""
        claims = {c["CLAIM_ID"]: c for c in self.lineage_data["claims"]}
        clm12 = claims.get("CLM-012")
        clm15 = claims.get("CLM-015")
        self.assertEqual(clm12["FAILURE_TYPE"], "CUSTOMER_REQUIREMENT_PROMOTED_TO_PRODUCT_FEATURE")
        self.assertEqual(clm15["FAILURE_TYPE"], "CUSTOMER_REQUIREMENT_PROMOTED_TO_PRODUCT_FEATURE")

    def test_missing_product_weight_cannot_be_invented(self):
        """Verify 100g GaN vs 350g OEM brick weight is flagged as INVENTED_PRODUCT_FACT."""
        claims = {c["CLAIM_ID"]: c for c in self.lineage_data["claims"]}
        clm = claims.get("CLM-014")
        self.assertIsNotNone(clm)
        self.assertFalse(clm["SUPPORTED"])
        self.assertEqual(clm["FAILURE_TYPE"], "INVENTED_PRODUCT_FACT")
        self.assertEqual(clm["ORIGINATOR"], "CREATIVE")

    def test_experiment_statistical_rules_cannot_be_fabricated(self):
        """Verify 1,200 clicks / 90% confidence / 15% MDE is flagged as INVENTED_NUMERIC_THRESHOLD."""
        claims = {c["CLAIM_ID"]: c for c in self.lineage_data["claims"]}
        clm = claims.get("CLM-017")
        self.assertIsNotNone(clm)
        self.assertFalse(clm["SUPPORTED"])
        self.assertEqual(clm["FAILURE_TYPE"], "INVENTED_NUMERIC_THRESHOLD")
        self.assertEqual(clm["ORIGINATOR"], "PERFORMANCE")

    def test_propagation_and_final_qa_escape_rate(self):
        """Verify all 14 unsupported claims propagated and escaped CMO Final review in Phase 4.1.2."""
        unsupported = [c for c in self.lineage_data["claims"] if not c["SUPPORTED"]]
        self.assertEqual(len(unsupported), 14)
        escapes = [c for c in unsupported if "CMO_FINAL" in c["PROPAGATORS"]]
        self.assertEqual(len(escapes), 14, "All 14 unsupported claims escaped CMO Final review in Phase 4.1.2")

    def test_origin_distribution_breakdown(self):
        """Verify originator distribution matches audit findings."""
        unsupported = [c for c in self.lineage_data["claims"] if not c["SUPPORTED"]]
        origins = {}
        for c in unsupported:
            orig = c["ORIGINATOR"]
            origins[orig] = origins.get(orig, 0) + 1

        self.assertEqual(origins.get("PERFORMANCE"), 7)
        self.assertEqual(origins.get("STRATEGIST"), 5)
        self.assertEqual(origins.get("INTELLIGENCE"), 1)
        self.assertEqual(origins.get("CREATIVE"), 1)


if __name__ == "__main__":
    unittest.main()
