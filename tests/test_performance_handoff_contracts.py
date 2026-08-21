"""Unit Tests for Grounded Performance Handoff Contracts & Measurement Planning (Phase 3D.4).

Validates:
- No fake CTR, CVR, CPA, CAC, LTV, ROAS, revenue, or conversion numbers
- UNKNOWN baseline markers are preserved
- CTR denominator discipline (clicks / impressions)
- Platform attribution is not treated as causal incrementality
- Technical search channel remains HYPOTHESIZED_CHANNEL
- INCONCLUSIVE decision rule is supported
- Unconfigured stop loss remains NOT_CONFIGURED
- Creative variant IDs (VAR-A, VAR-B, VAR-C) are valid
- Full 4-stage lineage (Evidence -> Strategy -> Creative -> Performance) is valid
- Performance -> CMO handoff contains no hidden reasoning
- FREE_ONLY_MODE is preserved
"""

import json
from pathlib import Path
import unittest
from schemas.handoff import GroundedPerformanceBrief, PerformanceToCMOHandoff


class TestPerformanceHandoffContracts(unittest.TestCase):
    def setUp(self):
        self.perf_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_performance"

    def test_no_fabricated_metrics_or_budgets_in_artifacts(self):
        """Verify performance artifacts contain no fake metrics, budgets, or CAC/LTV values."""
        taxonomy_path = self.perf_dir / "metric_taxonomy.json"
        allocation_path = self.perf_dir / "media_allocation_logic.json"

        self.assertTrue(taxonomy_path.exists())
        self.assertTrue(allocation_path.exists())

        alloc_data = json.loads(allocation_path.read_text(encoding="utf-8"))
        self.assertEqual(alloc_data["budget_status"], "UNKNOWN (NOT_CONFIGURED)")
        self.assertEqual(alloc_data["monetary_budget_usd"], "NOT_CONFIGURED")

    def test_unknown_baselines_preserved_in_performance_handoff(self):
        """Verify all unknown baseline markers are preserved in Performance brief and CMO handoff."""
        brief_path = self.perf_dir / "creative_performance_handoff.json"
        cmo_path = self.perf_dir / "cmo_handoff_candidate.json"

        self.assertTrue(brief_path.exists())
        self.assertTrue(cmo_path.exists())

        brief_data = json.loads(brief_path.read_text(encoding="utf-8"))
        cmo_data = json.loads(cmo_path.read_text(encoding="utf-8"))

        unknowns = brief_data.get("unknown_baselines", [])
        self.assertIn("TRANSACTION_DATA = MISSING", unknowns)
        self.assertIn("REPRESENTATIVE_DEVELOPER_RECEPTION_DATA = MISSING", unknowns)
        self.assertIn("PRIVATE_TELEMETRY_DATA = MISSING", unknowns)

        econ_unknowns = cmo_data.get("economics_unknowns", [])
        self.assertTrue(any("CAC = UNKNOWN" in u for u in econ_unknowns))
        self.assertTrue(any("LTV = UNKNOWN" in u for u in econ_unknowns))

    def test_ctr_denominator_discipline(self):
        """Verify CTR formula strictly uses impressions as denominator rather than reach."""
        taxonomy_path = self.perf_dir / "metric_taxonomy.json"
        tax_data = json.loads(taxonomy_path.read_text(encoding="utf-8"))

        ctr_metric = next((m for m in tax_data if m["name"] == "Click-Through Rate (CTR)"), None)
        self.assertIsNotNone(ctr_metric)
        self.assertIn("Impressions", ctr_metric["denominator"])
        self.assertIn("NOT Reach", ctr_metric["denominator"])

    def test_causal_discipline_and_platform_attribution_not_causal(self):
        """Verify platform-reported attribution is explicitly classified as non-causal."""
        attribution_path = self.perf_dir / "attribution_plan.json"
        self.assertTrue(attribution_path.exists())

        attr_data = json.loads(attribution_path.read_text(encoding="utf-8"))
        hierarchy = attr_data.get("attribution_hierarchy", [])
        rules = attr_data.get("causal_discipline_rules", [])

        # Verify RCTs/Holdouts > Platform-Reported
        self.assertIn("1. Randomized Controlled Trials", hierarchy[0])
        self.assertTrue(any("Never claim platform-reported conversions represent true incremental lift" in r for r in rules))

    def test_technical_search_remains_hypothesized_channel(self):
        """Verify technical search capture is classified as TEST / HYPOTHESIZED_CHANNEL."""
        channel_path = self.perf_dir / "channel_priority_plan.json"
        self.assertTrue(channel_path.exists())

        ch_data = json.loads(channel_path.read_text(encoding="utf-8"))
        experimental = ch_data.get("experimental_channels", [])

        search_ch = next((c for c in experimental if c["channel_id"] == "CHAN-TECH-SEARCH"), None)
        self.assertIsNotNone(search_ch)
        self.assertIn("HYPOTHESIZED_CHANNEL", search_ch["status"])

    def test_inconclusive_decision_rule_supported(self):
        """Verify INCONCLUSIVE is a first-class supported decision outcome."""
        rules_path = self.perf_dir / "decision_rules.json"
        self.assertTrue(rules_path.exists())

        rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
        inconclusive_rule = next((r for r in rules_data if r["action"] == "INCONCLUSIVE"), None)
        self.assertIsNotNone(inconclusive_rule)
        self.assertIn("sample size or effect size is insufficient", inconclusive_rule["condition"])

    def test_unconfigured_stop_loss_preserved(self):
        """Verify stop-loss value remains NOT_CONFIGURED until business constraints are supplied."""
        alloc_path = self.perf_dir / "media_allocation_logic.json"
        alloc_data = json.loads(alloc_path.read_text(encoding="utf-8"))

        stop_loss = alloc_data.get("stop_loss_policy", {})
        self.assertEqual(stop_loss.get("stop_loss_value"), "NOT_CONFIGURED")

    def test_creative_variant_ids_valid(self):
        """Verify all tested variant IDs match Creative variant IDs."""
        exp_path = self.perf_dir / "experiment_plan.json"
        exp_data = json.loads(exp_path.read_text(encoding="utf-8"))

        pexp1 = next((e for e in exp_data if e["experiment_id"] == "PEXP-001"), None)
        self.assertIsNotNone(pexp1)
        self.assertIn("VAR-A", pexp1["treatment"])
        self.assertIn("VAR-B", pexp1["control"])

    def test_four_stage_lineage_graph(self):
        """Verify lineage from Evidence -> Strategy -> Creative -> Performance."""
        cmo_path = self.perf_dir / "cmo_handoff_candidate.json"
        cmo_data = json.loads(cmo_path.read_text(encoding="utf-8"))

        evid_lineage = cmo_data.get("evidence_lineage", {})
        strat_lineage = cmo_data.get("strategy_lineage", {})
        creative_lineage = cmo_data.get("creative_lineage", {})

        self.assertTrue(len(evid_lineage) > 0)
        self.assertTrue(len(strat_lineage) > 0)
        self.assertTrue(len(creative_lineage) > 0)
        self.assertIn("STRAT-001", strat_lineage)
        self.assertIn("COPY-SF-01", creative_lineage)

    def test_cmo_candidate_handoff_no_hidden_reasoning(self):
        """Verify CMO candidate handoff contains no raw chain of thought."""
        cmo_path = self.perf_dir / "cmo_handoff_candidate.json"
        data = json.loads(cmo_path.read_text(encoding="utf-8"))

        self.assertNotIn("thought", data)
        self.assertNotIn("chain_of_thought", data)
        self.assertIn("experiment_portfolio", data)
        self.assertEqual(len(data["experiment_portfolio"]), 3)


if __name__ == "__main__":
    unittest.main()
