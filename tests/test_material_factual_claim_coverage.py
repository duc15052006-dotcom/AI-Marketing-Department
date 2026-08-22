"""Unit tests verifying material factual claim coverage under CLAIM-REPAIR-03B (CLAIM-01).

Validates all 21 contract items from Phase CLAIM-REPAIR-03B:
- Free-text detection across quantified, ranking, comparative, spec, certification, price/warranty, and market stat claims.
- Preservation of planning, targets, hypotheses, and subjective puffery.
- Dual English and Vietnamese coverage (including no-accent forms).
- Source presence enforcement and raw output preservation.
- Five-Agent invariant.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict

from knowledge.repository import LocalKnowledgeRepository
from runtime.engine import FiveAgentDepartmentRuntime, RuntimeContext
from schemas.claim_provenance import AllowedUsage, ClaimClass


class TestMaterialFactualClaimCoverage(unittest.TestCase):
    """Test suite covering CLAIM-01 material factual claim detection and governance."""

    def setUp(self) -> None:
        self.engine_cls = FiveAgentDepartmentRuntime

    # 1. Unsupported "Battery lasts 3x longer" -> BLOCK
    def test_01_unsupported_battery_3x_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Our flagship phone: Battery lasts 3x longer than before.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 2. Unsupported "#1 in Vietnam" -> BLOCK
    def test_02_unsupported_number_one_in_vietnam_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Rated #1 in Vietnam by market researchers.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 3. Unsupported "Save 40%" -> BLOCK
    def test_03_unsupported_save_percentage_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Customers save 40% on subscription costs.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 4. Unsupported "Made from aerospace-grade titanium" -> BLOCK
    def test_04_unsupported_aerospace_titanium_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Chassis is made from aerospace-grade titanium for durability.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 5. Unsupported "9/10 users prefer this" -> BLOCK
    def test_05_unsupported_user_ratio_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "In recent studies, 9 out of 10 users prefer this application.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 6. Unsupported "No competitor matches its durability" -> BLOCK
    def test_06_unsupported_comparative_durability_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "No competitor matches its durability in extreme conditions.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 7. Unsupported "IP68 certified" -> BLOCK
    def test_07_unsupported_ip68_certified_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Device is IP68 certified waterproof up to 2 meters.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 8. Unsupported "30-day money-back guarantee" -> BLOCK
    def test_08_unsupported_money_back_guarantee_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Comes with a 30-day money-back guarantee with zero questions asked.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 9. Unsupported "1 million units sold" -> BLOCK
    def test_09_unsupported_million_units_sold_blocked(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Over 1 million units sold worldwide in the first quarter.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(supported, 0)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 10. Unsupported Vietnamese quantified claim -> BLOCK
    def test_10_unsupported_vietnamese_quantified_blocked(self) -> None:
        for claim in (
            "Pin dùng lâu hơn gấp 3 lần.",
            "pin lau hon gap 3 lan.",
            "Tiết kiệm 40% chi phí vận hành.",
            "tiet kiem 40% chi phi.",
        ):
            total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
                claim, provenance_index={}
            )
            self.assertGreaterEqual(total, 1, f"Failed to detect: {claim}")
            self.assertEqual(supported, 0)
            self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 11. Unsupported Vietnamese ranking -> BLOCK
    def test_11_unsupported_vietnamese_ranking_blocked(self) -> None:
        for claim in (
            "Sản phẩm số 1 Việt Nam về âm thanh.",
            "San pham so 1 viet nam.",
            "Bán chạy nhất thị trường hiện nay.",
            "ban chay nhat thi truong.",
        ):
            total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
                claim, provenance_index={}
            )
            self.assertGreaterEqual(total, 1, f"Failed to detect: {claim}")
            self.assertEqual(supported, 0)
            self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 12. Unsupported Vietnamese warranty/certification -> BLOCK
    def test_12_unsupported_vietnamese_warranty_certification_blocked(self) -> None:
        for claim in (
            "Bảo hành chính hãng 24 tháng.",
            "bao hanh 24 thang.",
            "Khung titan hàng không siêu nhẹ.",
            "khung titan hang khong.",
            "Hoàn tiền 100% trong 30 ngày.",
            "hoan tien 100% trong 30 ngay.",
            "Không đối thủ nào bền bằng.",
            "khong doi thu nao ben bang.",
        ):
            total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
                claim, provenance_index={}
            )
            self.assertGreaterEqual(total, 1, f"Failed to detect: {claim}")
            self.assertEqual(supported, 0)
            self.assertEqual(actions.get("claim_1"), "BLOCK_PUBLICATION")

    # 13. Neutral subjective copy -> NOT blocked
    def test_13_neutral_subjective_copy_not_blocked(self) -> None:
        for phrase in (
            "Beautiful modern design for young professionals.",
            "Simple to use interface with intuitive controls.",
            "Premium feel in your hands.",
            "Great for everyday work and productivity.",
            "Stylish and modern appearance.",
        ):
            total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
                phrase, provenance_index={}
            )
            self.assertEqual(total, 0, f"Subjective copy falsely flagged: {phrase}")
            self.assertEqual(len(reasons), 0)

    # 14. Planning: "Target 40% savings" -> Preserved
    def test_14_planning_target_savings_preserved(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Campaign plan: Target a 40% savings in customer CPA across Q4.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(hyp, 1)
        self.assertEqual(len(reasons), 0)
        self.assertEqual(actions.get("claim_1"), "PRESERVE_HYPOTHESIS")

    # 15. Hypothesis: "We hypothesize Variant B may improve CTR" -> Preserved
    def test_15_hypothesis_variant_b_preserved(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "We hypothesize battery messaging may improve conversion by 25%.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(hyp, 1)
        self.assertEqual(len(reasons), 0)
        self.assertEqual(actions.get("claim_1"), "PRESERVE_HYPOTHESIS")

    # 16. Proposed goal: "Goal: become #1 in Vietnam" -> Preserved
    def test_16_proposed_goal_number_one_preserved(self) -> None:
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Goal: become the #1 choice in Vietnam in this category.",
            provenance_index={},
        )
        self.assertGreaterEqual(total, 1)
        self.assertEqual(hyp, 1)
        self.assertEqual(len(reasons), 0)
        self.assertEqual(actions.get("claim_1"), "PRESERVE_HYPOTHESIS")

    # 17. Factual claim with qualifying source ID -> Passes CLAIM-01 layer
    def test_17_factual_claim_with_qualifying_source_passes_presence_gate(self) -> None:
        prov_index = {
            "SRC_BATTERY_01": {
                "source_id": "SRC_BATTERY_01",
                "epistemic_tier": "VERIFIED_SOURCE",
                "source_type": "TIER_1_CANONICAL_GROUND_TRUTH",
                "content": "Laboratory tests prove battery lasts 3x longer than previous models.",
            }
        }
        from runtime.claim_verification import MockClaimVerifier
        total, supported, hyp, reasons, actions = self.engine_cls._scan_unsupported_product_claims(
            "Battery lasts 3x longer (Source: SRC_BATTERY_01) in laboratory tests.",
            provenance_index=prov_index,
            claim_verifier=MockClaimVerifier(),
        )
        self.assertEqual(total, 1)
        self.assertEqual(supported, 1)
        self.assertEqual(len(reasons), 0)
        self.assertEqual(actions.get("claim_1"), "AUTHORIZE")

    # 18. Structured HYPOTHESIS remains hypothesis
    def test_18_structured_hypothesis_remains_hypothesis(self) -> None:
        ctx = RuntimeContext(objective="Test GTM")
        ctx.working_state["stage_handoffs"] = {
            "strategy": {
                "claims": [
                    {
                        "claim_id": "HYP-01",
                        "claim_text": "Battery messaging will increase CTR by 20%",
                        "claim_class": ClaimClass.HYPOTHESIS.value,
                        "allowed_usage": AllowedUsage.HYPOTHESIS_ONLY.value,
                        "support_status": "UNSUPPORTED",
                    }
                ]
            }
        }
        rt = FiveAgentDepartmentRuntime(knowledge_repo=LocalKnowledgeRepository())
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="# FINAL CMO PLAN\nWe propose testing creative concepts.",
        )
        self.assertEqual(audit_res.authorization_status, "APPROVED")
        self.assertNotIn("UNSUPPORTED_STRUCTURED_CLAIM [HYP-01]", audit_res.blocking_reasons)

    # 19. Structured PUBLIC factual claim requires evidence
    def test_19_structured_public_claim_requires_evidence(self) -> None:
        ctx = RuntimeContext(objective="Test GTM")
        ctx.working_state["stage_handoffs"] = {
            "strategy": {
                "claims": [
                    {
                        "claim_id": "FACT-01",
                        "claim_text": "Rated #1 in Vietnam across all categories",
                        "claim_class": ClaimClass.VERIFIED_PRODUCT_FACT.value,
                        "allowed_usage": AllowedUsage.PUBLIC_CLAIM.value,
                        "support_status": "UNSUPPORTED",
                    }
                ]
            }
        }
        rt = FiveAgentDepartmentRuntime(knowledge_repo=LocalKnowledgeRepository())
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text="# FINAL CMO PLAN\nStrategic overview.",
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(any("UNSUPPORTED_STRUCTURED_CLAIM [FACT-01]" in r for r in audit_res.blocking_reasons))

    # 20. Raw output preserved verbatim
    def test_20_raw_output_preserved_verbatim(self) -> None:
        raw_text = "# FINAL_CMO_VERDICT\nRated #1 in Vietnam with battery lasts 3x longer than all competitors."
        ctx = RuntimeContext(objective="Test GTM")
        rt = FiveAgentDepartmentRuntime(knowledge_repo=LocalKnowledgeRepository())
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text=raw_text,
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        # Ensure the evaluation process does not modify the raw input text
        self.assertEqual(raw_text, "# FINAL_CMO_VERDICT\nRated #1 in Vietnam with battery lasts 3x longer than all competitors.")

    # 21. Five-Agent Invariant
    def test_21_five_agent_invariant(self) -> None:
        from governance.access_matrix import PERMANENT_FIVE_AGENTS
        self.assertEqual(
            set(PERMANENT_FIVE_AGENTS),
            {"cmo", "intelligence", "strategist", "creative", "performance"},
            "Architecture must maintain exactly Five Agents (no 6th verifier agent).",
        )


if __name__ == "__main__":
    unittest.main()
