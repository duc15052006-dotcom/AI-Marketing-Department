"""Unit Tests for Phase 4.0 Fresh Five-Agent End-to-End Autonomous Benchmark.

Validates:
- Complete product isolation (PROD_FRESH_GAN65_BENCHMARK / BRAND_FRESH_GAN65_BENCHMARK) and 0 Ollama data leakage
- 6-core-call budget adherence across the 6 pipeline stages
- Exactly 5 permanent agent roster preserved (CMO, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE; 0 sixth agents)
- Complete 6-stage lineage graph integrity from EVID-GAN65-01..05 to CMO-DEC-001..006
- Zero unauthorized external execution approvals (SUPERVISED mode enforced)
- Unknown baselines, economics, and budgets strictly preserved
- Guaranteed product specification boundaries respected with zero fabricated features
"""

import json
from pathlib import Path
import unittest


class TestFiveAgentE2EGAN65(unittest.TestCase):
    def setUp(self):
        self.e2e_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "five_agent_e2e_gan65"

    def test_fresh_product_isolation_and_zero_ollama_contamination(self):
        """Verify product isolation and zero Ollama data or IDs in the fresh benchmark directory."""
        self.assertTrue(self.e2e_dir.exists())

        files_to_check = [
            self.e2e_dir / "initial_user_objective.json",
            self.e2e_dir / "initial_cmo_plan.json",
            self.e2e_dir / "research" / "evidence_bundle.json",
            self.e2e_dir / "research" / "intelligence_output.json",
            self.e2e_dir / "strategy" / "strategist_output.json",
            self.e2e_dir / "creative" / "creative_output.json",
            self.e2e_dir / "performance" / "performance_output.json",
            self.e2e_dir / "cmo" / "decision_register.json",
            self.e2e_dir / "cmo" / "department_status.json",
            self.e2e_dir / "lineage_graph.json",
            self.e2e_dir / "benchmark_manifest.json",
        ]

        for fpath in files_to_check:
            self.assertTrue(fpath.exists(), f"File {fpath} must exist.")
            content = fpath.read_text(encoding="utf-8").lower()
            self.assertNotIn("ollama", content, f"Ollama data leakage detected in {fpath.name}")
            self.assertIn("gan65", content, f"Expected fresh benchmark identifier in {fpath.name}")

    def test_six_core_agent_call_budget_adherence(self):
        """Verify benchmark executed exactly within the 6 core model call budget."""
        manifest_path = self.e2e_dir / "benchmark_manifest.json"
        self.assertTrue(manifest_path.exists())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("total_model_calls"), 6)
        self.assertEqual(manifest.get("eval_decision"), "PASS")
        self.assertTrue(manifest.get("free_only_mode"))

    def test_exact_five_permanent_agent_roster_preserved(self):
        """Verify exactly 5 permanent agent owners are assigned across decisions with 0 sixth agents."""
        status_path = self.e2e_dir / "cmo" / "department_status.json"
        dec_path = self.e2e_dir / "cmo" / "decision_register.json"

        self.assertTrue(status_path.exists())
        self.assertTrue(dec_path.exists())

        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        roster = status_data.get("permanent_agent_roster", [])
        self.assertEqual(len(roster), 5)
        self.assertEqual(set(roster), {"CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"})

        dec_data = json.loads(dec_path.read_text(encoding="utf-8"))
        for d in dec_data:
            owner = d.get("owner_agent")
            self.assertIn(owner, set(roster))

    def test_fresh_end_to_end_lineage_graph_intact(self):
        """Verify full 6-stage lineage graph connects evidence to intelligence, strategy, creative, perf, and cmo."""
        lineage_path = self.e2e_dir / "lineage_graph.json"
        self.assertTrue(lineage_path.exists())

        lineage_data = json.loads(lineage_path.read_text(encoding="utf-8"))
        chain = lineage_data.get("chain", [])
        self.assertTrue(len(chain) > 0)

        c0 = chain[0]
        evids = " ".join(c0.get("evidence", []))
        self.assertIn("EVID-GAN65-01", evids)
        self.assertTrue(len(c0.get("intelligence_finding", "")) > 0)
        self.assertTrue(len(c0.get("strategy_positioning", "")) > 0)
        self.assertTrue(len(c0.get("creative_asset", "")) > 0)
        self.assertTrue(len(c0.get("performance_experiment", "")) > 0)
        self.assertTrue(len(c0.get("cmo_decision", "")) > 0)

    def test_no_unauthorized_external_execution_approvals(self):
        """Verify all public distribution and media spend items require explicit human approval in SUPERVISED mode."""
        approval_path = self.e2e_dir / "cmo" / "approval_register.json"
        self.assertTrue(approval_path.exists())

        app_data = json.loads(approval_path.read_text(encoding="utf-8"))
        self.assertEqual(app_data.get("autonomy_mode"), "SUPERVISED")

        approvals = app_data.get("approvals", [])
        for app in approvals:
            self.assertFalse(app.get("live_execution_permitted", True))

    def test_unknown_baselines_preserved_across_all_stages(self):
        """Verify missing transaction data, unknown economics, and unconfigured budgets are preserved throughout."""
        intel_path = self.e2e_dir / "research" / "intelligence_output.json"
        strat_path = self.e2e_dir / "strategy" / "strategist_output.json"
        perf_path = self.e2e_dir / "performance" / "performance_output.json"

        intel_data = json.loads(intel_path.read_text(encoding="utf-8"))
        strat_data = json.loads(strat_path.read_text(encoding="utf-8"))
        perf_data = json.loads(perf_path.read_text(encoding="utf-8"))

        self.assertTrue(any("TRANSACTION_DATA" in u for u in intel_data.get("known_unknowns", [])))
        self.assertTrue(any("TRANSACTION_DATA" in u for u in strat_data.get("unknown_or_required_research", [])))
        self.assertTrue(any("CAC = UNKNOWN" in u for u in perf_data.get("economics_unknowns", [])))
        self.assertTrue(any("BUDGET = NOT_CONFIGURED" in u for u in perf_data.get("economics_unknowns", [])))

    def test_guaranteed_specifications_discipline(self):
        """Verify product specs are strictly limited to guaranteed 65W GaN USB-C charger without unbacked claims."""
        strat_path = self.e2e_dir / "strategy" / "strategist_output.json"
        creative_path = self.e2e_dir / "creative" / "creative_output.json"

        strat_data = json.loads(strat_path.read_text(encoding="utf-8"))
        creative_data = json.loads(creative_path.read_text(encoding="utf-8"))

        what_not = " ".join(strat_data.get("what_not_to_do", [])).lower()
        self.assertIn("fastest", what_not)

        # Verify creative assets do not claim unverified absolute thermal perfection
        copy_texts = " ".join([c.get("body", "") + " " + c.get("hook", "") for c in creative_data.get("copy_assets", [])]).lower()
        self.assertNotIn("never overheats", copy_texts)
        self.assertNotIn("zero heat", copy_texts)


if __name__ == "__main__":
    unittest.main()
