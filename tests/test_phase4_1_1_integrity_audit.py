"""Unit Tests for Phase 4.1.1: Benchmark Integrity & Telemetry Audit.

Verifies:
1. exact model identity not collapsed
2. five-agent exact token totals required (or INCOMPLETE marked)
3. estimated token multipliers prohibited
4. model mismatch invalidates direct comparison
5. hardening disclosure required in summary
6. 'architectural superiority' wording prohibited without human evidence
7. blind packet identity leakage equals 0
"""

import json
from pathlib import Path
import re
import unittest


class TestPhase411IntegrityAudit(unittest.TestCase):
    def setUp(self):
        self.comp_dir = Path(__file__).resolve().parent.parent / "evaluations" / "benchmarks" / "phase4_1_comparison"
        self.e2e_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "five_agent_e2e_gan65"

    def test_exact_model_identity_not_collapsed(self):
        """Verify baseline and five-agent record explicit resolved model strings."""
        manifest_path = self.comp_dir / "comparison_manifest.json"
        self.assertTrue(manifest_path.exists())

        comp = json.loads(manifest_path.read_text(encoding="utf-8"))
        parity = comp.get("model_parity", {})

        self.assertIn("baseline_model_resolved", parity)
        self.assertIn("five_agent_model_resolved", parity)
        self.assertNotEqual(parity["baseline_model_resolved"], "")
        self.assertNotEqual(parity["five_agent_model_resolved"], "")
        self.assertNotIn(" / ", parity["baseline_model_resolved"])

    def test_model_mismatch_invalidates_direct_comparison(self):
        """Verify model mismatch marks verdict as INCONCLUSIVE_MODEL_MISMATCH."""
        manifest_path = self.comp_dir / "comparison_manifest.json"
        comp = json.loads(manifest_path.read_text(encoding="utf-8"))

        parity = comp.get("model_parity", {})
        if parity.get("status") == "FAIL":
            self.assertEqual(comp.get("preliminary_verdict"), "INCONCLUSIVE_MODEL_MISMATCH")

    def test_five_agent_exact_token_totals_or_incomplete_status(self):
        """Verify token accounting handles incomplete stage telemetry cleanly."""
        eff_path = self.comp_dir / "efficiency_comparison.json"
        eff = json.loads(eff_path.read_text(encoding="utf-8"))

        self.assertIn("token_comparison_status", eff)
        if eff.get("five_agent_total_tokens") == 0:
            self.assertEqual(eff["token_comparison_status"], "INCOMPLETE")

    def test_estimated_token_multipliers_prohibited(self):
        """Verify token multiplier is not an ungrounded estimate range when data is incomplete."""
        eff_path = self.comp_dir / "efficiency_comparison.json"
        eff = json.loads(eff_path.read_text(encoding="utf-8"))

        if eff.get("token_comparison_status") == "INCOMPLETE":
            self.assertIn("Incomplete", str(eff.get("token_multiplier")))

    def test_hardening_disclosure_required(self):
        """Verify summary explicitly discloses prior hardening difference."""
        summary_path = self.comp_dir / "comparison_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertIn("hardening_disclosure", summary)
        self.assertIn("Phase 4.0.1", summary["hardening_disclosure"])
        self.assertEqual(summary.get("comparison_framing"), "PRODUCTION_ARCHITECTURE_VS_SINGLE_CALL_BASELINE")

    def test_architectural_superiority_wording_prohibited(self):
        """Verify ungrounded 'architectural superiority' phrase is prohibited."""
        summary_path = self.comp_dir / "comparison_summary.json"
        eff_path = self.comp_dir / "efficiency_comparison.json"

        s_text = summary_path.read_text(encoding="utf-8").lower()
        e_text = eff_path.read_text(encoding="utf-8").lower()

        self.assertNotIn("architectural superiority", s_text)
        self.assertNotIn("architectural superiority", e_text)

    def test_blind_packet_identity_leak_count_zero(self):
        """Verify blind review packet contains zero identity leaks."""
        packet_path = self.comp_dir / "blind_review_packet.md"
        content = packet_path.read_text(encoding="utf-8")

        forbidden = ["cmo", "intelligence agent", "strategist agent", "creative agent", "performance agent"]
        for term in forbidden:
            matches = re.findall(rf"\b{term}\b", content, re.IGNORECASE)
            self.assertEqual(len(matches), 0, f"Found leaked term: {term} in blind review packet")


if __name__ == "__main__":
    unittest.main()
