"""Unit Tests for Performance Planning Assumption Discipline & Patch Rules (Phase 3D.4.1).

Validates:
- UNSUPPORTED_POPULATION_ASSUMPTION is detected on unproven population hardware claims
- Illustrative allocations are not represented as empirical optima
- Fixed calendar durations without MDE/traffic derivation are flagged
- Holdout sizes are classified as TO_BE_DETERMINED / ILLUSTRATIVE_ONLY
- Unverified GDPR/CCPA compliance claims are detected
- Corrected CMO handoff preserves unknown economics and baselines
- All corrected Performance artifacts pass discipline checks
"""

import json
from pathlib import Path
import unittest
from evaluations.patch_performance_planning_assumptions import audit_performance_text_for_discipline


class TestPerformancePlanningAssumptions(unittest.TestCase):
    def test_unsupported_consumer_population_assumption_detected(self):
        """Verify auditor catches ungrounded consumer hardware population assumptions."""
        text_invalid = "Deferred because general consumer audiences lack developer GPU hardware."
        text_valid = "Current evidence is strongly developer-oriented and does not establish broad non-technical consumer-market fit."

        issues_invalid = audit_performance_text_for_discipline(text_invalid)
        issues_valid = audit_performance_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNSUPPORTED_POPULATION_ASSUMPTION" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNSUPPORTED_POPULATION_ASSUMPTION" for iss in issues_valid))

    def test_illustrative_allocation_not_treated_as_empirical_optimum(self):
        """Verify allocation logic is classified as ILLUSTRATIVE_TEST_ALLOCATION with UNKNOWN optimality."""
        perf_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_performance"
        alloc_path = perf_dir / "media_allocation_logic.json"
        self.assertTrue(alloc_path.exists())

        alloc_data = json.loads(alloc_path.read_text(encoding="utf-8"))
        self.assertEqual(alloc_data.get("allocation_classification"), "ILLUSTRATIVE_TEST_ALLOCATION")
        self.assertEqual(alloc_data.get("empirical_optimality"), "UNKNOWN")
        self.assertTrue(alloc_data.get("requires_business_budget_configuration"))

    def test_fixed_duration_planning_assumption_detected(self):
        """Verify auditor catches fixed calendar day assertions lacking statistical derivation."""
        text_invalid = "Experiment duration requirement: 14 calendar days"
        text_valid = "duration_requirement: TO_BE_DETERMINED (Requires traffic volume, MDE, and variance calculation)"

        issues_invalid = audit_performance_text_for_discipline(text_invalid)
        issues_valid = audit_performance_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNSUPPORTED_FIXED_TEST_DURATION" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNSUPPORTED_FIXED_TEST_DURATION" for iss in issues_valid))

    def test_holdout_percentage_not_treated_as_required(self):
        """Verify holdout size is classified as TO_BE_DETERMINED and illustrative only."""
        perf_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_performance"
        inc_path = perf_dir / "incrementality_plan.json"
        self.assertTrue(inc_path.exists())

        inc_data = json.loads(inc_path.read_text(encoding="utf-8"))
        framework = inc_data.get("incrementality_testing_framework", {})
        self.assertEqual(framework.get("holdout_classification"), "ILLUSTRATIVE_ONLY")
        self.assertIn("TO_BE_DETERMINED", framework.get("holdout_size", ""))

    def test_unverified_compliance_claim_detected(self):
        """Verify auditor catches unverified GDPR/CCPA legal compliance claims."""
        text_invalid = "Privacy notes: GDPR/CCPA compliant aggregate telemetry."
        text_valid = "Privacy-conscious instrumentation design with pseudonymous IDs. (LEGAL_COMPLIANCE_STATUS = NOT_EVALUATED)."

        issues_invalid = audit_performance_text_for_discipline(text_invalid)
        issues_valid = audit_performance_text_for_discipline(text_valid)

        self.assertTrue(any(iss[0] == "UNVERIFIED_COMPLIANCE_CLAIM" for iss in issues_invalid))
        self.assertFalse(any(iss[0] == "UNVERIFIED_COMPLIANCE_CLAIM" for iss in issues_valid))

    def test_corrected_cmo_handoff_preserves_unknown_economics_and_baselines(self):
        """Verify candidate CMO handoff preserves unknown economics and unconfigured stop losses."""
        perf_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_performance"
        cmo_path = perf_dir / "cmo_handoff_candidate.json"
        self.assertTrue(cmo_path.exists())

        cmo_data = json.loads(cmo_path.read_text(encoding="utf-8"))
        econ_unknowns = cmo_data.get("economics_unknowns", [])
        self.assertTrue(any("CAC = UNKNOWN" in u for u in econ_unknowns))
        self.assertTrue(any("LTV = UNKNOWN" in u for u in econ_unknowns))
        self.assertTrue(any("ROAS = UNKNOWN" in u for u in econ_unknowns))

        stop_loss = cmo_data.get("stop_loss_policy", "")
        self.assertIn("STOP_LOSS_VALUE = NOT_CONFIGURED", stop_loss)

    def test_corrected_artifacts_pass_all_discipline_rules(self):
        """Verify all corrected Performance artifacts pass discipline checks with 0 remaining issues."""
        perf_dir = Path(__file__).resolve().parent.parent / "evaluations" / "live" / "grounded_performance"
        files_to_check = [
            "channel_priority_plan.json",
            "media_allocation_logic.json",
            "experiment_plan.json",
            "incrementality_plan.json",
            "tracking_plan.json",
            "cmo_handoff_candidate.json",
        ]

        for fname in files_to_check:
            fpath = perf_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
                issues = audit_performance_text_for_discipline(content)
                self.assertEqual(len(issues), 0, f"Discipline issues found in {fname}: {issues}")


if __name__ == "__main__":
    unittest.main()
