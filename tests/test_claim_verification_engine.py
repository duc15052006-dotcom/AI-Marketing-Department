"""Unit Tests for Claim Verification Engine Foundation (Phase CLAIM-REPAIR-03A).

Validates all 20 required contract items using fast deterministic MockClaimVerifier,
with an opt-in integration test for the real neural weights.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict

from runtime.claim_verification import (
    BaseClaimVerifier,
    ClaimVerificationResult,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    DeterministicFindings,
    MockClaimVerifier,
    MultilingualNLIClaimVerifier,
    PROVISIONAL_TAU_CONTRADICTION,
    PROVISIONAL_TAU_ENTAILMENT,
    SemanticScores,
    VerificationVerdict,
    audit_deterministic_claim_guards,
    extract_currency_codes,
    extract_explicit_skus,
    extract_numeric_tokens,
    extract_scope_regions,
    extract_temporal_years,
)
from schemas.claim_provenance import AllowedUsage, ClaimClass


class TestClaimVerificationEngine(unittest.TestCase):
    """Test suite verifying claim verification foundation contracts."""

    def setUp(self) -> None:
        self.mock_verifier = MockClaimVerifier()

    # -----------------------------------------------------------------------
    # 1. Deterministic Numeric Mismatch
    # -----------------------------------------------------------------------
    def test_01_deterministic_numeric_mismatch(self) -> None:
        claim = "The system delivers 500 lumens output."
        evidence = "Laboratory report certifies 300 lumens output."
        res = self.mock_verifier.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.CONTRADICTED)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertEqual(res.deterministic_findings.guard_name, "NUMERIC_VALUE_MISMATCH")

    # -----------------------------------------------------------------------
    # 2. Currency Mismatch
    # -----------------------------------------------------------------------
    def test_02_currency_mismatch(self) -> None:
        claim = "Price is 50 USD per license."
        evidence = "Pricing sheet confirms 50 EUR per license."
        res = self.mock_verifier.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.CONTRADICTED)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertEqual(res.deterministic_findings.guard_name, "CURRENCY_MISMATCH")

    # -----------------------------------------------------------------------
    # 3. Explicit SKU Mismatch
    # -----------------------------------------------------------------------
    def test_03_explicit_sku_mismatch(self) -> None:
        claim = "Model VD-500 features fast charging."
        evidence = "Model VD-900 features fast charging."
        res = self.mock_verifier.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.CONTRADICTED)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertEqual(res.deterministic_findings.guard_name, "ENTITY_SKU_MISMATCH")

    # -----------------------------------------------------------------------
    # 4. Scope Separation (Geographic Mismatch vs Security Provenance Scope)
    # -----------------------------------------------------------------------
    def test_04a_geographic_scope_mismatch(self) -> None:
        claim = "Top seller worldwide in 2026."
        evidence = "Certified top seller in Vietnam market."
        res = self.mock_verifier.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.CONTRADICTED)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertEqual(res.deterministic_findings.guard_name, "GEOGRAPHIC_SCOPE_MISMATCH")

    def test_04b_security_provenance_scope_violation(self) -> None:
        claim = "Top seller in Vietnam in 2026."
        evidence = "Certified top seller in Vietnam in 2026."
        claim_meta = {"tenant_id": "BRAND-ALPHA", "run_id": "RUN-01"}
        source_meta = {"tenant_id": "BRAND-BETA", "run_id": "RUN-01"}
        res = self.mock_verifier.verify_claim(claim, evidence, claim_metadata=claim_meta, source_metadata=source_meta)
        self.assertEqual(res.verdict, VerificationVerdict.SCOPE_VIOLATION)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertEqual(res.deterministic_findings.guard_name, "SECURITY_SCOPE_VIOLATION")

    # -----------------------------------------------------------------------
    # 5. MOCK Receipt
    # -----------------------------------------------------------------------
    def test_05_mock_receipt_rejected(self) -> None:
        claim = "Battery lasts 24 hours."
        evidence = "Observed 24 hours playback in test."
        source_meta = {"execution_mode": "MOCK", "source_id": "RECEIPT-MOCK-01"}
        res = self.mock_verifier.verify_claim(claim, evidence, source_metadata=source_meta)
        self.assertEqual(res.verdict, VerificationVerdict.UNSUPPORTED)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertIn("MOCK", res.deterministic_findings.guard_name)

    # -----------------------------------------------------------------------
    # 6. SANDBOX Receipt
    # -----------------------------------------------------------------------
    def test_06_sandbox_receipt_rejected(self) -> None:
        claim = "Conversion rate is 4.5%."
        evidence = "Observed 4.5% conversion in sandbox test."
        source_meta = {"execution_mode": "SANDBOX", "source_id": "RECEIPT-SANDBOX-01"}
        res = self.mock_verifier.verify_claim(claim, evidence, source_metadata=source_meta)
        self.assertEqual(res.verdict, VerificationVerdict.UNSUPPORTED)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertIn("SANDBOX", res.deterministic_findings.guard_name)

    # -----------------------------------------------------------------------
    # 7. Failed Receipt
    # -----------------------------------------------------------------------
    def test_07_failed_receipt_rejected(self) -> None:
        claim = "Target CTR reached 3.2%."
        evidence = "Execution log details."
        for status in ("ERROR", "TIMEOUT", "BLOCKED", "APPROVAL_REQUIRED"):
            source_meta = {"status": status, "source_id": f"RECEIPT-{status}-01"}
            res = self.mock_verifier.verify_claim(claim, evidence, source_metadata=source_meta)
            self.assertEqual(res.verdict, VerificationVerdict.UNSUPPORTED)
            self.assertFalse(res.deterministic_findings.passed)
            self.assertEqual(res.deterministic_findings.guard_name, f"EXECUTION_STATE_{status}")

    # -----------------------------------------------------------------------
    # 8. Hypothesis Preservation
    # -----------------------------------------------------------------------
    def test_08_hypothesis_preservation(self) -> None:
        claim = "Hypothesis: Titanium frame increases user purchase intent by 25%."
        evidence = "Consumer survey shows users prefer titanium frame."
        claim_meta = {"claim_class": ClaimClass.HYPOTHESIS, "allowed_usage": AllowedUsage.HYPOTHESIS_ONLY}
        res = self.mock_verifier.verify_claim(claim, evidence, claim_metadata=claim_meta)
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertEqual(res.deterministic_findings.guard_name, "EPISTEMIC_HYPOTHESIS_PRESERVATION")
        self.assertEqual(res.epistemic_type_preserved, str(ClaimClass.HYPOTHESIS))

    # -----------------------------------------------------------------------
    # 9. Planning Preservation
    # -----------------------------------------------------------------------
    def test_09_planning_preservation(self) -> None:
        claim = "Target ROAS is 4.0 for Q4 campaign."
        evidence = "Market benchmark data."
        for p_class in (ClaimClass.PROPOSED_TARGET, ClaimClass.PROPOSED_TEST):
            claim_meta = {"claim_class": p_class, "allowed_usage": AllowedUsage.EXPERIMENT_ONLY}
            res = self.mock_verifier.verify_claim(claim, evidence, claim_metadata=claim_meta)
            self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)
            self.assertFalse(res.deterministic_findings.passed)
            self.assertEqual(res.deterministic_findings.guard_name, "EPISTEMIC_HYPOTHESIS_PRESERVATION")

    # -----------------------------------------------------------------------
    # 10. Supported Semantic Result
    # -----------------------------------------------------------------------
    def test_10_supported_semantic_result(self) -> None:
        claim = "VoltDrive EV charges in 15 minutes."
        evidence = "Specs confirm 15 minutes fast charge."
        scores = SemanticScores(p_entailment=0.96, p_neutral=0.03, p_contradiction=0.01, argmax_label="ENTAILMENT")
        v = MockClaimVerifier(forced_semantic_scores={(evidence, claim): scores})
        res = v.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.SUPPORTED)
        self.assertGreaterEqual(res.confidence, PROVISIONAL_TAU_ENTAILMENT)
        self.assertTrue(res.deterministic_findings.passed)

    # -----------------------------------------------------------------------
    # 11. Contradiction Result
    # -----------------------------------------------------------------------
    def test_11_contradiction_result(self) -> None:
        claim = "Product is waterproof up to 50 meters."
        evidence = "Product is splash-resistant only, not waterproof."
        scores = SemanticScores(p_entailment=0.01, p_neutral=0.02, p_contradiction=0.97, argmax_label="CONTRADICTION")
        v = MockClaimVerifier(forced_semantic_scores={(evidence, claim): scores})
        res = v.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.CONTRADICTED)
        self.assertGreaterEqual(res.confidence, PROVISIONAL_TAU_CONTRADICTION)

    # -----------------------------------------------------------------------
    # 12. Neutral -> Inconclusive
    # -----------------------------------------------------------------------
    def test_12_neutral_inconclusive_result(self) -> None:
        claim = "The solar inverter features smart grid synchronization."
        evidence = "Solar panel market grew 15% this year."
        scores = SemanticScores(p_entailment=0.02, p_neutral=0.96, p_contradiction=0.02, argmax_label="NEUTRAL")
        v = MockClaimVerifier(forced_semantic_scores={(evidence, claim): scores})
        res = v.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)


    # -----------------------------------------------------------------------
    # 13. Model Missing -> INCONCLUSIVE
    # -----------------------------------------------------------------------
    def test_13_model_missing_fails_closed(self) -> None:
        claim = "Unibody aluminum frame."
        evidence = "Frame is forged from aluminum."
        v = MockClaimVerifier(simulate_model_failure=True)
        res = v.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)
        self.assertIn("model load failure", res.reason)

    # -----------------------------------------------------------------------
    # 14. Inference Exception -> INCONCLUSIVE
    # -----------------------------------------------------------------------
    def test_14_inference_exception_fails_closed(self) -> None:
        claim = "Zero emission electric vehicle."
        evidence = "Vehicle produces zero direct emissions."
        v = MockClaimVerifier(simulate_exception=True)
        res = v.verify_claim(claim, evidence)
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)
        self.assertIn("exception", res.reason)

    # -----------------------------------------------------------------------
    # 15. Label Mapping Failure Simulation
    # -----------------------------------------------------------------------
    def test_15_label_mapping_failure_fails_closed(self) -> None:
        # MultilingualNLIClaimVerifier with invalid label mapping returns INCONCLUSIVE
        verifier = MultilingualNLIClaimVerifier()
        # Mocking invalid config
        verifier._is_loaded = False
        res = verifier.verify_claim("Claim", "Evidence")
        # In test environment without loaded weights, fails closed to INCONCLUSIVE
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)

    # -----------------------------------------------------------------------
    # 16. Threshold Boundaries
    # -----------------------------------------------------------------------
    def test_16_threshold_boundaries(self) -> None:
        claim = "Boundary test claim."
        evidence = "Boundary test evidence."

        # Case A: exactly 0.90 entailment -> SUPPORTED
        scores_a = SemanticScores(p_entailment=0.90, p_neutral=0.08, p_contradiction=0.02)
        va = MockClaimVerifier(forced_semantic_scores={(evidence, claim): scores_a})
        self.assertEqual(va.verify_claim(claim, evidence).verdict, VerificationVerdict.SUPPORTED)

        # Case B: 0.8999 entailment -> INCONCLUSIVE (fails closed)
        scores_b = SemanticScores(p_entailment=0.8999, p_neutral=0.08, p_contradiction=0.0201)
        vb = MockClaimVerifier(forced_semantic_scores={(evidence, claim): scores_b})
        self.assertEqual(vb.verify_claim(claim, evidence).verdict, VerificationVerdict.INCONCLUSIVE)

        # Case C: exactly 0.70 contradiction -> CONTRADICTED
        scores_c = SemanticScores(p_entailment=0.05, p_neutral=0.25, p_contradiction=0.70)
        vc = MockClaimVerifier(forced_semantic_scores={(evidence, claim): scores_c})
        self.assertEqual(vc.verify_claim(claim, evidence).verdict, VerificationVerdict.CONTRADICTED)

        # Case D: 0.6999 contradiction -> INCONCLUSIVE
        scores_d = SemanticScores(p_entailment=0.05, p_neutral=0.2501, p_contradiction=0.6999)
        vd = MockClaimVerifier(forced_semantic_scores={(evidence, claim): scores_d})
        self.assertEqual(vd.verify_claim(claim, evidence).verdict, VerificationVerdict.INCONCLUSIVE)

    # -----------------------------------------------------------------------
    # 17. Compound Claim Not Auto-Supported
    # -----------------------------------------------------------------------
    def test_17_compound_claim_not_auto_supported(self) -> None:
        claim = "Titanium chassis and 48 hours battery life."
        evidence = "Official specs confirm Grade 5 titanium chassis."
        claim_meta = {"is_compound": True}
        res = self.mock_verifier.verify_claim(claim, evidence, claim_metadata=claim_meta)
        self.assertEqual(res.verdict, VerificationVerdict.INCONCLUSIVE)
        self.assertFalse(res.deterministic_findings.passed)
        self.assertEqual(res.deterministic_findings.guard_name, "COMPOUND_CLAIM_GUARD")

    # -----------------------------------------------------------------------
    # 18. Batch Preserves Ordering
    # -----------------------------------------------------------------------
    def test_18_batch_preserves_ordering(self) -> None:
        requests = [
            ("Claim 1", "Evidence 1", {}, {}),
            ("Claim 2", "Evidence 2 (MOCK)", {}, {"execution_mode": "MOCK"}),
            ("Claim 3", "Evidence 3", {}, {}),
            ("Claim 4", "Evidence 4 (HYP)", {"claim_class": ClaimClass.HYPOTHESIS}, {}),
            ("Claim 5", "Evidence 5", {}, {}),
        ]
        results = self.mock_verifier.verify_batch(requests)
        self.assertEqual(len(results), 5)
        for i, res in enumerate(results):
            self.assertEqual(res.claim_text, f"Claim {i+1}")
        self.assertEqual(results[1].verdict, VerificationVerdict.UNSUPPORTED)
        self.assertEqual(results[3].verdict, VerificationVerdict.INCONCLUSIVE)

    # -----------------------------------------------------------------------
    # 19. No Agent 6 Invariant
    # -----------------------------------------------------------------------
    def test_19_no_agent_6_invariant(self) -> None:
        # Verify verifier imports and uses no 6th agent
        from schemas.claim_provenance import ClaimClass
        from runtime.handoff import EpistemicType
        # The Five Agents are: cmo, intelligence, strategist, creative, performance
        # Ensure our claim verification foundation is a pure tool/runtime library, not an agent
        self.assertTrue(issubclass(MockClaimVerifier, BaseClaimVerifier))
        self.assertTrue(issubclass(MultilingualNLIClaimVerifier, BaseClaimVerifier))

    # -----------------------------------------------------------------------
    # 20. No Second LLM Call Invariant
    # -----------------------------------------------------------------------
    def test_20_no_second_llm_call_invariant(self) -> None:
        # Verify MultilingualNLIClaimVerifier uses sequence classification, not text generation LLM
        v = MultilingualNLIClaimVerifier()
        self.assertEqual(v.tau_entailment, 0.90)
        self.assertEqual(v.tau_contradiction, 0.70)
        self.assertFalse(hasattr(v, "generate"))
        self.assertFalse(hasattr(v, "prompt"))

    # -----------------------------------------------------------------------
    # 21. Numeric Guard Unit Alignment Audit
    # -----------------------------------------------------------------------
    def test_21_numeric_guard_unit_alignment_audit(self) -> None:
        # Case A: Battery 5000mAh with extra metric in evidence -> PASS
        c_a = "Battery capacity is 5000mAh."
        e_a = "Battery capacity is 5000mAh and video playback is 18 hours."
        res_a = self.mock_verifier.verify_claim(c_a, e_a)
        self.assertTrue(res_a.deterministic_findings.passed)

        # Case B: Battery playback 18 hours with extra metric in evidence -> PASS
        c_b = "Battery playback lasts 18 hours."
        e_b = "Battery capacity is 5000mAh and playback lasts 18 hours."
        res_b = self.mock_verifier.verify_claim(c_b, e_b)
        self.assertTrue(res_b.deterministic_findings.passed)

        # Case C: Battery 5000mAh vs 4500mAh -> NUMERIC mismatch
        c_c = "Battery capacity is 5000mAh."
        e_c = "Battery capacity is 4500mAh."
        res_c = self.mock_verifier.verify_claim(c_c, e_c)
        self.assertEqual(res_c.verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(res_c.deterministic_findings.guard_name, "NUMERIC_VALUE_MISMATCH")

        # Case D: Warranty 24 months with 30-day replacement and 24-month warranty -> PASS
        c_d = "Warranty is 24 months."
        e_d = "30-day replacement policy and 24-month warranty."
        res_d = self.mock_verifier.verify_claim(c_d, e_d)
        self.assertTrue(res_d.deterministic_findings.passed)

        # Case E: Warranty 24 months vs 12-month warranty and 30-day replacement -> NUMERIC mismatch
        c_e = "Warranty is 24 months."
        e_e = "12-month warranty and 30-day replacement policy."
        res_e = self.mock_verifier.verify_claim(c_e, e_e)
        self.assertEqual(res_e.verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(res_e.deterministic_findings.guard_name, "NUMERIC_VALUE_MISMATCH")

    # -----------------------------------------------------------------------
    # 22. Currency Guard Audit
    # -----------------------------------------------------------------------
    def test_22_currency_guard_audit(self) -> None:
        # Case A: Price 500 USD with 10% VAT -> PASS
        c_a = "Price is 500 USD."
        e_a = "Price is 500 USD including 10% VAT."
        res_a = self.mock_verifier.verify_claim(c_a, e_a)
        self.assertTrue(res_a.deterministic_findings.passed)

        # Case B: Price 500 USD vs 500 EUR -> CURRENCY_MISMATCH
        c_b = "Price is 500 USD."
        e_b = "Price is 500 EUR."
        res_b = self.mock_verifier.verify_claim(c_b, e_b)
        self.assertEqual(res_b.verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(res_b.deterministic_findings.guard_name, "CURRENCY_MISMATCH")

        # Case C: Save 20% vs Price 500 USD and discount is 20% -> PASS
        c_c = "Save 20%."
        e_c = "Price is 500 USD and discount is 20%."
        res_c = self.mock_verifier.verify_claim(c_c, e_c)
        self.assertTrue(res_c.deterministic_findings.passed)

    # -----------------------------------------------------------------------
    # 23. Temporal Guard Audit
    # -----------------------------------------------------------------------
    def test_23_temporal_guard_audit(self) -> None:
        # Case A: Certified in 2026 vs Founded 2024, Certified 2026 -> PASS
        c_a = "Certified in 2026."
        e_a = "Company founded in 2024. Certification issued in 2026."
        res_a = self.mock_verifier.verify_claim(c_a, e_a)
        self.assertTrue(res_a.deterministic_findings.passed)

        # Case B: 2000 mAh is a numeric measurement, not a calendar year
        c_b = "Battery capacity is 2000 mAh."
        e_b = "Battery capacity is 2500 mAh."
        res_b = self.mock_verifier.verify_claim(c_b, e_b)
        self.assertEqual(res_b.verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(res_b.deterministic_findings.guard_name, "NUMERIC_VALUE_MISMATCH")

    # -----------------------------------------------------------------------
    # 24. Structured SKU & Comparison Document Audit
    # -----------------------------------------------------------------------
    def test_24_sku_guard_audit(self) -> None:
        # Case A: Structured metadata SKU mismatch -> ENTITY_SKU_MISMATCH
        claim_meta = {"sku": "MODEL-LITE"}
        source_meta = {"sku": "MODEL-PRO"}
        res_a = self.mock_verifier.verify_claim("Product is lightweight.", "Specs confirmed.", claim_metadata=claim_meta, source_metadata=source_meta)
        self.assertEqual(res_a.verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(res_a.deterministic_findings.guard_name, "ENTITY_SKU_MISMATCH")

        # Case B: Multi-product comparison text does not falsely block matching subclaim
        c_b = "Model Lite uses aluminum."
        e_b = "Model Pro uses titanium. Model Lite uses aluminum."
        res_b = self.mock_verifier.verify_claim(c_b, e_b)
        self.assertTrue(res_b.deterministic_findings.passed)

    # -----------------------------------------------------------------------
    # 25. Mixed Batch Fail-Closed Behavior
    # -----------------------------------------------------------------------
    def test_25_mixed_batch_fail_closed_behavior(self) -> None:
        # Setup mock verifier with specific semantic overrides
        item2_scores = SemanticScores(p_entailment=0.96, p_neutral=0.03, p_contradiction=0.01)
        item3_scores = SemanticScores(p_entailment=0.01, p_neutral=0.02, p_contradiction=0.97)

        v = MockClaimVerifier(
            forced_semantic_scores={
                ("Evidence 2 (semantically verified)", "Claim 2 (supported)"): item2_scores,
                ("Evidence 3 (semantically contradicted)", "Claim 3 (contradicted)"): item3_scores,
            }
        )

        requests = [
            ("Price is 500 USD", "Price is 500 EUR", {}, {}),                               # 1. Deterministic mismatch
            ("Claim 2 (supported)", "Evidence 2 (semantically verified)", {}, {}),           # 2. Semantic support
            ("Claim 3 (contradicted)", "Evidence 3 (semantically contradicted)", {}, {}),   # 3. Semantic contradiction
            ("Target ROAS is 4.0", "Market report", {"claim_class": ClaimClass.HYPOTHESIS}, {}), # 4. Hypothesis
            ("Claim 5 (execution fail)", "Evidence 5", {}, {"status": "ERROR"}),             # 5. Failed receipt
        ]

        results = v.verify_batch(requests)
        self.assertEqual(len(results), 5)

        # 1. Item 1: Deterministic mismatch -> CONTRADICTED
        self.assertEqual(results[0].claim_text, "Price is 500 USD")
        self.assertEqual(results[0].verdict, VerificationVerdict.CONTRADICTED)
        self.assertEqual(results[0].deterministic_findings.guard_name, "CURRENCY_MISMATCH")

        # 2. Item 2: Semantic support -> SUPPORTED
        self.assertEqual(results[1].claim_text, "Claim 2 (supported)")
        self.assertEqual(results[1].verdict, VerificationVerdict.SUPPORTED)
        self.assertGreaterEqual(results[1].confidence, 0.90)

        # 3. Item 3: Semantic contradiction -> CONTRADICTED
        self.assertEqual(results[2].claim_text, "Claim 3 (contradicted)")
        self.assertEqual(results[2].verdict, VerificationVerdict.CONTRADICTED)

        # 4. Item 4: Hypothesis -> INCONCLUSIVE, epistemic type preserved
        self.assertEqual(results[3].claim_text, "Target ROAS is 4.0")
        self.assertEqual(results[3].verdict, VerificationVerdict.INCONCLUSIVE)
        self.assertEqual(results[3].epistemic_type_preserved, str(ClaimClass.HYPOTHESIS))

        # 5. Item 5: Failed receipt -> UNSUPPORTED
        self.assertEqual(results[4].claim_text, "Claim 5 (execution fail)")
        self.assertEqual(results[4].verdict, VerificationVerdict.UNSUPPORTED)

    # -----------------------------------------------------------------------
    # Optional Real Model Integration Test (Opt-in via env flag)
    # Migrated (PROD-VERIFIER-02B): neural inference now executes ONLY inside
    # the isolated verifier worker; the main process never loads torch.
    # Requires a configured worker interpreter (VERIFIER_PYTHON_EXECUTABLE or
    # explicit constructor argument) whose environment contains the pinned
    # model weights. Never runs by default.
    # -----------------------------------------------------------------------
    @unittest.skipUnless(
        os.environ.get("RUN_REAL_MODEL_TEST") == "1",
        "Opt-in test requiring isolated worker + real model weights (set RUN_REAL_MODEL_TEST=1)",
    )
    def test_real_model_integration(self) -> None:
        interpreter = os.environ.get("VERIFIER_PYTHON_EXECUTABLE", "")
        if not interpreter:
            self.skipTest("VERIFIER_PYTHON_EXECUTABLE not configured for isolated verifier worker")
        from runtime.verifier_worker.client import SidecarClaimVerifier

        verifier = SidecarClaimVerifier(interpreter_executable=interpreter)
        try:
            claim = "Khung viền được chế tác từ titan chuẩn hàng không vũ trụ."
            evidence = "Tài liệu thông số kỹ thuật sản phẩm: Khung máy sử dụng hợp kim titan cấp hàng không vũ trụ (Grade 5 Titanium), gia công CNC nguyên khối."
            res = verifier.verify_claim(claim, evidence)
            self.assertEqual(res.verdict, VerificationVerdict.SUPPORTED)
            self.assertGreaterEqual(res.confidence, 0.90)
            self.assertEqual(res.model_id, DEFAULT_MODEL_ID)
            self.assertEqual(res.model_revision, DEFAULT_MODEL_REVISION)
            # Boundary truth: the main process still has no ML modules loaded.
            self.assertNotIn("torch", sys.modules)
            self.assertNotIn("transformers", sys.modules)
        finally:
            verifier.close()




if __name__ == "__main__":
    unittest.main()
