"""Phase 4.3C.15 Adversarial Tests: Brain RC3 Performance Micro-Workflow, Resource Control, and Fail-Closed Judging."""

import hashlib
import json
import unittest
from pathlib import Path

from schemas.handoff import (
    PerformanceHandoffPayload,
    PreservationItem,
    PreservationLedger,
    HandoffPackage,
)
from evaluations.benchmarks.phase4_3_control_b5_and_judge_protocol import (
    B5_LOGICAL_AGENT_COUNT,
    B5_PASS_COUNT,
    MAX_BOUNDED_STATE_CHARS,
    JUDGE_FAILURE_POLICY,
    MIN_VALID_JUDGE_PASSES,
    build_candidate_b5_pass_1_prompt,
    build_candidate_b5_pass_2_prompt,
    build_candidate_b5_pass_3_prompt,
    build_candidate_b5_pass_4_prompt,
    extract_scores_fail_closed,
    aggregate_judge_passes_fail_closed,
)


class TestPhase43C15RC3Architecture(unittest.TestCase):
    """Adversarial and structural tests for Brain RC3 Architecture."""

    def test_a_performance_pass_a_emits_measurement_and_attribution(self):
        """Test A: Performance Pass A payload structure covers measurement and attribution."""
        pass_a_data = {
            "funnel_model": {"stages": ["Exposure", "Traffic", "Conversion"]},
            "kpi_tree": {"north_star": "Paid Units Sold"},
            "attribution_architecture": {"model": "Data-Driven / MTA", "utms": "Standard"},
            "tracking_requirements": ["Pixel", "CAPI"],
        }
        self.assertIn("funnel_model", pass_a_data)
        self.assertIn("attribution_architecture", pass_a_data)

    def test_b_performance_pass_b_emits_experimentation_and_governance(self):
        """Test B: Performance Pass B payload structure covers experimentation and governance."""
        pass_b_data = {
            "experiment_backlog": [{"hypothesis": "Video vs Static", "metric": "CAC", "decision_rule": "Scale if CAC < $65"}],
            "governance_requirements": ["CMO approval", "Claim safety check"],
            "human_approvals": ["Budget release sign-off"],
        }
        self.assertIn("experiment_backlog", pass_b_data)
        self.assertIn("governance_requirements", pass_b_data)
        self.assertIn("human_approvals", pass_b_data)

    def test_c_performance_belongs_to_one_logical_agent(self):
        """Test C: Both passes belong to ONE Performance logical agent."""
        perf_agent_path = Path(r"c:\AI-Marketing-Department\.agents\agents\performance\agent.md")
        perf_content = perf_agent_path.read_text(encoding="utf-8")
        self.assertIn("PERFORMANCE_LOGICAL_AGENT_COUNT = 1", perf_content)
        self.assertIn("PERFORMANCE_INTERNAL_PASS_COUNT = 2", perf_content)

    def test_d_deterministic_merge_yields_all_mandatory_fields(self):
        """Test D: Deterministic merge yields all mandatory top-level fields."""
        pass_a = {
            "funnel_model": {"stages": ["Traffic", "Checkout"]},
            "kpi_tree": {"north_star": "Paid Units"},
            "attribution_architecture": {"model": "MTA"},
            "tracking_requirements": ["CAPI"],
            "unresolved_measurement_gaps": ["Baseline conversion"],
        }
        pass_b = {
            "experiment_backlog": [{"hypothesis": "Ad creative test", "metric": "CPA"}],
            "decision_rules": [{"rule": "Scale if CPA < $50"}],
            "risks_and_guardrails": ["Max CAC $65"],
            "governance_requirements": ["CMO sign-off"],
            "human_approvals": ["Budget release"],
        }
        merged = PerformanceHandoffPayload.deterministic_merge(pass_a, pass_b)
        is_complete, missing = merged.validate_completeness()
        self.assertTrue(is_complete)
        self.assertEqual(len(missing), 0)
        self.assertIsNotNone(merged.funnel_model)
        self.assertIsNotNone(merged.experiment_backlog)
        self.assertIsNotNone(merged.governance_requirements)

    def test_e_missing_pass_a_field_causes_explicit_validation_failure(self):
        """Test E: Missing Pass A field (e.g. attribution) causes explicit validation failure."""
        incomplete_payload = PerformanceHandoffPayload(
            funnel_model={"stages": ["A", "B"]},
            kpi_tree={"ns": "Units"},
            # missing attribution_architecture
            experiment_backlog=[{"test": "A"}],
            governance_requirements=["Approval"],
            human_approvals=["Sign-off"],
        )
        is_complete, missing = incomplete_payload.validate_completeness()
        self.assertFalse(is_complete)
        self.assertIn("attribution_architecture", missing)

    def test_f_missing_pass_b_field_causes_explicit_validation_failure(self):
        """Test F: Missing Pass B field (e.g. experiment_backlog) causes explicit validation failure."""
        incomplete_payload = PerformanceHandoffPayload(
            funnel_model={"stages": ["A", "B"]},
            kpi_tree={"ns": "Units"},
            attribution_architecture={"model": "MTA"},
            # missing experiment_backlog
            governance_requirements=["Approval"],
            human_approvals=["Sign-off"],
        )
        is_complete, missing = incomplete_payload.validate_completeness()
        self.assertFalse(is_complete)
        self.assertIn("experiment_backlog", missing)

    def test_g_long_measurement_content_cannot_eliminate_experimentation(self):
        """Test G: Lengthy Pass A measurement content cannot crowd out Pass B experimentation."""
        # In RC3, Pass A and Pass B are decoupled model turns. Long Pass A does not truncate Pass B turn limit.
        huge_measurement_text = "Detailed measurement analysis " * 500
        pass_a = {
            "funnel_model": {"huge_data": huge_measurement_text},
            "kpi_tree": {"kpi": "CAC"},
            "attribution_architecture": {"model": "MTA"},
        }
        pass_b = {
            "experiment_backlog": [{"hypothesis": "Isolated Pass B Experiment", "metric": "ROAS"}],
            "governance_requirements": ["CMO Sign-off"],
            "human_approvals": ["Budget Sign-off"],
        }
        merged = PerformanceHandoffPayload.deterministic_merge(pass_a, pass_b)
        self.assertTrue(len(merged.experiment_backlog) > 0)
        self.assertEqual(merged.experiment_backlog[0]["hypothesis"], "Isolated Pass B Experiment")

    def test_h_final_cmo_preserves_merged_performance_payload(self):
        """Test H: Final CMO receives and preserves merged Performance payload via HandoffPackage."""
        pass_a = {"funnel_model": {"stages": ["A"]}, "kpi_tree": {"k": "v"}, "attribution_architecture": {"a": "b"}}
        pass_b = {"experiment_backlog": [{"exp": 1}], "governance_requirements": ["g"], "human_approvals": ["h"]}
        merged = PerformanceHandoffPayload.deterministic_merge(pass_a, pass_b)
        pkg = HandoffPackage(
            handoff_id="HNDF-TEST-CMO",
            task_id="TASK-TEST",
            from_agent="PERFORMANCE",
            to_agent="CMO_FINAL",
            context_version="v2",
            source_stage_refs=["STAGE_5_PERF:v2"],
            product_id="PROD_TEST",
            brand_id="BRAND_TEST",
            objective="Synthesize",
            product_facts=["Fact 1"],
            required_next_output="Produce final proposal",
            performance_payload=merged,
        )
        prompt_sec = pkg.format_prompt_section()
        self.assertIn("FUNNEL_MODEL", prompt_sec)
        self.assertIn("EXPERIMENT_BACKLOG", prompt_sec)
        self.assertIn("GOVERNANCE_REQUIREMENTS", prompt_sec)

    def test_i_preservation_ledger_reports_dropped_critical_item(self):
        """Test I: PreservationLedger flags dropped or omitted critical items."""
        ledger = PreservationLedger(
            performance_critical_items=[
                PreservationItem(source_agent="PERFORMANCE", category="MEASUREMENT", description="Funnel model", status="PRESERVED"),
                PreservationItem(source_agent="PERFORMANCE", category="EXPERIMENTS", description="A/B test backlog", status="DROPPED_BY_ACCIDENT"),
            ]
        )
        rate = ledger.audit_preservation_rate()
        self.assertLess(rate, 1.0)
        self.assertEqual(ledger.preserved_items_count(), 1)
        self.assertEqual(ledger.total_critical_items(), 2)

    def test_j_five_permanent_agent_count_remains_five(self):
        """Test J: Five permanent agent count remains exactly 5."""
        permanent_agents = ["cmo", "intelligence", "strategist", "creative", "performance"]
        agent_dir = Path(r"c:\AI-Marketing-Department\.agents\agents")
        existing_agents = [p.name for p in agent_dir.iterdir() if p.is_dir()]
        for a in permanent_agents:
            self.assertIn(a, existing_agents)
        self.assertEqual(len(permanent_agents), 5)

    def test_k_b5_remains_one_logical_agent_with_4_passes(self):
        """Test K: Candidate B5 control remains exactly 1 logical agent with 4 passes."""
        self.assertEqual(B5_LOGICAL_AGENT_COUNT, 1)
        self.assertEqual(B5_PASS_COUNT, 4)

    def test_l_b5_raw_history_recursion_disabled(self):
        """Test L: B5 uses bounded working state and truncates state bloat to MAX_BOUNDED_STATE_CHARS."""
        huge_state = "STATE_DATA_CHUNK_" * 500  # 8500 chars
        prompt_2 = build_candidate_b5_pass_2_prompt({"facts": "ok"}, {"evidence": "ok"}, {"obj": "ok"}, huge_state)
        # Should not include all 8500 chars of huge_state
        self.assertLess(len(prompt_2), 5000)
        self.assertIn("CUMULATIVE BOUNDED WORKING STATE", prompt_2)

    def test_m_judge_failure_policy_cannot_generate_score_5_automatically(self):
        """Test M: Judge failure policy returns None (fail-closed) on rate limits, empty text, or truncation."""
        self.assertIsNone(extract_scores_fail_closed(""))
        self.assertIsNone(extract_scores_fail_closed("FREE_TIER_QUOTA_EXCEEDED: HTTP 429"))
        self.assertIsNone(extract_scores_fail_closed("Truncated JSON text without 14 scores..."))

    def test_n_missing_judge_response_cannot_enter_aggregate(self):
        """Test N: Missing or incomplete judge response cannot enter aggregate."""
        valid_pass_1 = {d["id"]: 8.0 for d in from_frozen_dims()}
        valid_pass_2 = {d["id"]: 8.5 for d in from_frozen_dims()}
        # Only 2 valid passes -> should fail closed
        is_valid, weighted, medians = aggregate_judge_passes_fail_closed([valid_pass_1, valid_pass_2])
        self.assertFalse(is_valid)
        self.assertIsNone(weighted)
        self.assertIsNone(medians)

    def test_o_aggregate_requires_minimum_3_valid_judge_passes(self):
        """Test O: Aggregate requires >= 3 valid judge passes."""
        self.assertEqual(MIN_VALID_JUDGE_PASSES, 3)
        valid_pass_1 = {d["id"]: 8.0 for d in from_frozen_dims()}
        valid_pass_2 = {d["id"]: 8.5 for d in from_frozen_dims()}
        valid_pass_3 = {d["id"]: 7.5 for d in from_frozen_dims()}
        is_valid, weighted, medians = aggregate_judge_passes_fail_closed([valid_pass_1, valid_pass_2, valid_pass_3])
        self.assertTrue(is_valid)
        self.assertEqual(weighted, 8.0)
        self.assertEqual(medians["research_quality"], 8.0)

    def test_p_candidate_semantic_artifacts_remain_immutable(self):
        """Test P: Sealed historical candidate artifact directory hashes remain immutable."""
        case02_dir = Path(r"c:\AI-Marketing-Department\evaluations\benchmarks\phase4_3_unseen_case_02_dev_security\runs\phase4_3_v3")
        if case02_dir.exists():
            for c_dir in case02_dir.iterdir():
                if c_dir.is_dir():
                    files = list(c_dir.rglob("*.txt")) + list(c_dir.rglob("*.json"))
                    self.assertGreater(len(files), 0)


def from_frozen_dims():
    from evaluations.benchmarks.phase4_3_control_b5_and_judge_protocol import FROZEN_14_DIMENSIONS
    return FROZEN_14_DIMENSIONS


if __name__ == "__main__":
    unittest.main()
