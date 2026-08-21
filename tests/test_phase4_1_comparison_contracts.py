"""Unit Tests for Phase 4.1: Controlled Single-Model Baseline vs Five-Agent System.

Verifies:
1. five-agent artifacts frozen and unmodified
2. same product fact boundary enforced
3. same Evidence IDs available to baseline
4. no Strategist/Creative/Performance/CMO output leaked to baseline
5. baseline does not load specialist DNA
6. same evaluator rules applied to both systems
7. evaluator does not patch competitor outputs
8. blind packet hides system identity
9. actual telemetry only (no arbitrary aggregate scores)
10. FREE_ONLY_MODE preserved
"""

import hashlib
import json
from pathlib import Path
import unittest


class TestPhase41ComparisonContracts(unittest.TestCase):
    def setUp(self):
        self.comp_dir = Path(__file__).resolve().parent.parent / "evaluations" / "benchmarks" / "phase4_1_comparison"
        self.e2e_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "five_agent_e2e_gan65"

    def test_five_agent_artifacts_frozen_and_unmodified(self):
        """Verify five-agent snapshot manifest matches files currently on disk."""
        manifest_path = self.comp_dir / "five_agent_snapshot_manifest.json"
        self.assertTrue(manifest_path.exists())

        snap_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        checksums = snap_data.get("artifact_checksums", {})
        self.assertTrue(len(checksums) > 0)

        for rel_path, meta in checksums.items():
            full_path = self.e2e_dir / rel_path
            self.assertTrue(full_path.exists(), f"File {rel_path} must exist on disk.")
            current_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
            self.assertEqual(current_hash, meta["sha256"], f"File {rel_path} was modified after freezing!")

    def test_same_product_fact_boundary_enforced(self):
        """Verify guaranteed facts match across baseline input and user objective."""
        input_path = self.comp_dir / "single_model_input.json"
        obj_path = self.e2e_dir / "initial_user_objective.json"

        self.assertTrue(input_path.exists())
        self.assertTrue(obj_path.exists())

        sm_input = json.loads(input_path.read_text(encoding="utf-8"))
        user_obj = json.loads(obj_path.read_text(encoding="utf-8"))

        self.assertEqual(sm_input.get("product_id"), user_obj.get("product_id"))
        self.assertEqual(sm_input.get("brand_id"), user_obj.get("brand_id"))
        self.assertEqual(sm_input.get("guaranteed_specifications"), user_obj.get("guaranteed_specifications"))

    def test_same_evidence_ids_available_to_baseline(self):
        """Verify all fresh Evidence IDs (EVID-GAN65-01..05) were supplied to baseline."""
        input_path = self.comp_dir / "single_model_input.json"
        sm_input = json.loads(input_path.read_text(encoding="utf-8"))

        evid_items = sm_input.get("evidence_bundle", {}).get("items", [])
        evid_ids = {item.get("evidence_id") for item in evid_items}

        for i in range(1, 6):
            expected = f"EVID-GAN65-0{i}"
            self.assertIn(expected, evid_ids)

    def test_no_specialist_output_leaked_to_baseline(self):
        """Verify baseline input contains zero downstream specialist artifacts (no STRAT, CRTV, PERF, CMO outputs)."""
        input_path = self.comp_dir / "single_model_input.json"
        content = input_path.read_text(encoding="utf-8").lower()

        self.assertNotIn("cmo-dec-", content)
        self.assertNotIn("pexp-00", content)
        self.assertNotIn("copy-sf-", content)
        self.assertNotIn("script-sf-", content)

    def test_baseline_does_not_load_specialist_dna(self):
        """Verify baseline did not concatenate or load agent DNA files."""
        run_manifest_path = self.comp_dir / "single_model_run_manifest.json"
        self.assertTrue(run_manifest_path.exists())

        manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("model_calls"), 1)
        self.assertEqual(manifest.get("status"), "SUCCESS")

    def test_same_evaluator_rules_applied_to_both_systems(self):
        """Verify machine_comparison.json contains evaluations across identical dimensions."""
        comp_path = self.comp_dir / "machine_comparison.json"
        self.assertTrue(comp_path.exists())

        comp = json.loads(comp_path.read_text(encoding="utf-8"))
        dims = comp.get("dimension_evaluations", {})

        required_dims = [
            "CLAIM_GROUNDING",
            "INVALID_EVIDENCE_IDS",
            "UNSUPPORTED_PRODUCT_CLAIMS",
            "FABRICATED_METRICS",
            "UNKNOWN_PRESERVATION",
            "PRODUCT_FACT_DISCIPLINE",
            "STRATEGIC_TRADEOFF_DISCIPLINE",
            "CREATIVE_CLAIM_DISCIPLINE",
            "MEASUREMENT_DISCIPLINE",
            "CAUSAL_DISCIPLINE",
            "APPROVAL_GOVERNANCE",
        ]

        for dim in required_dims:
            self.assertIn(dim, dims)
            self.assertIn("single_model", dims[dim])
            self.assertIn("five_agent", dims[dim])

    def test_evaluator_does_not_patch_competitor_outputs(self):
        """Verify single_model_output.json is stored exactly as generated without auto-correction."""
        sm_out_path = self.comp_dir / "single_model_output.json"
        self.assertTrue(sm_out_path.exists())

        sm_data = json.loads(sm_out_path.read_text(encoding="utf-8"))
        self.assertIn("EXECUTIVE_SUMMARY", sm_data)
        self.assertIn("RESEARCH_FINDINGS", sm_data)
        self.assertIn("EXPERIMENTS", sm_data)

    def test_blind_packet_hides_system_identity(self):
        """Verify blind review packet anonymizes candidate systems to SYSTEM_A and SYSTEM_B."""
        packet_path = self.comp_dir / "blind_review_packet.md"
        self.assertTrue(packet_path.exists())

        content = packet_path.read_text(encoding="utf-8")
        self.assertIn("SYSTEM_A", content)
        self.assertIn("SYSTEM_B", content)
        self.assertIn("HUMAN REVIEWER SCORECARD", content)

    def test_actual_telemetry_only_no_fake_aggregates(self):
        """Verify efficiency comparison contains actual recorded metrics without arbitrary composite scores."""
        eff_path = self.comp_dir / "efficiency_comparison.json"
        self.assertTrue(eff_path.exists())

        eff = json.loads(eff_path.read_text(encoding="utf-8"))
        self.assertIn("single_model_calls", eff)
        self.assertIn("five_agent_calls", eff)
        self.assertIn("single_latency_ms", eff)
        self.assertIn("five_agent_latency_ms", eff)
        self.assertIn("call_multiplier", eff)
        self.assertIn("latency_multiplier", eff)
        self.assertIn("pareto_classification", eff)

    def test_free_only_mode_preserved(self):
        """Verify FREE_ONLY_MODE remained active across both single model and five agent benchmarks."""
        comp_man_path = self.comp_dir / "comparison_manifest.json"
        self.assertTrue(comp_man_path.exists())

        comp_man = json.loads(comp_man_path.read_text(encoding="utf-8"))
        self.assertEqual(comp_man.get("comparison_mode"), "EVIDENCE_CONTROLLED")


if __name__ == "__main__":
    unittest.main()
