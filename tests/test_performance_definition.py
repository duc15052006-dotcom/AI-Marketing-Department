"""Tests verifying the Performance Agent Definition, Professional DNA, and Evaluation Suite."""

import unittest
from pathlib import Path
from tests.test_agent_manifests import parse_yaml_frontmatter


class TestPerformanceDefinition(unittest.TestCase):
    def setUp(self):
        self.performance_md_path = (
            Path(__file__).resolve().parent.parent
            / ".agents"
            / "agents"
            / "performance"
            / "agent.md"
        )
        self.assertTrue(self.performance_md_path.exists(), "performance/agent.md does not exist")
        self.content = self.performance_md_path.read_text(encoding="utf-8")
        self.frontmatter = parse_yaml_frontmatter(self.content)

    def test_performance_frontmatter_valid(self):
        """Verify Performance frontmatter has name 'performance' and non-empty description."""
        self.assertEqual(self.frontmatter.get("name"), "performance")
        self.assertIn("Performance Marketing", self.frontmatter.get("description", ""))

    def test_performance_identity_and_role_boundaries(self):
        """Verify Performance is defined as measurement engine and NOT primary researcher, strategist, creative, or publisher."""
        self.assertIn("Performance Marketer, Marketing Analyst, Experiment Diagnostician & Marketing Operations Specialist", self.content)
        self.assertIn("WHAT HAPPENED?", self.content)
        self.assertIn("HOW RELIABLE IS THE DATA?", self.content)
        self.assertIn("WHERE IS THE BOTTLENECK?", self.content)
        self.assertIn("WHAT MIGHT EXPLAIN THE RESULT?", self.content)
        self.assertIn("WHAT ELSE COULD EXPLAIN IT?", self.content)
        self.assertIn("WHAT SHOULD WE TEST NEXT?", self.content)
        self.assertIn("WHAT SHOULD THE ORGANIZATION LEARN?", self.content)
        self.assertIn("primary market researcher", self.content)
        self.assertIn("final business strategist", self.content)
        self.assertIn("primary creative producer", self.content)
        self.assertIn("final commercial and budgetary authority", self.content)
        self.assertIn("automatically authorized to spend money", self.content)

    def test_core_professional_traits_and_anti_fabrication(self):
        """Verify core professional traits and strict prohibition against fabricating data."""
        self.assertIn("Quantitatively Rigorous & Skeptical of Bad Data", self.content)
        self.assertIn("Zero Tolerance for Data Fabrication", self.content)
        self.assertIn("Never manufacture, hallucinate, or simulate fake metrics", self.content)

    def test_measurement_first_and_preflight_contract(self):
        """Verify pre-diagnosis measurement context contract."""
        self.assertIn("Measurement First: The Pre-Diagnosis Contract", self.content)
        self.assertIn("MEASUREMENT CONTEXT AUDIT", self.content)
        self.assertIn("BUSINESS_OBJECTIVE", self.content)
        self.assertIn("PRIMARY_KPI", self.content)
        self.assertIn("GUARDRAIL_METRICS", self.content)
        self.assertIn("ATTRIBUTION_CONTEXT", self.content)

    def test_metric_taxonomy(self):
        """Verify comprehensive metric taxonomy across distribution, attention, engagement, traffic, intent, conversion, economics, retention, brand."""
        self.assertIn("Comprehensive Metric Taxonomy", self.content)
        self.assertIn("DISTRIBUTION", self.content)
        self.assertIn("ATTENTION", self.content)
        self.assertIn("ENGAGEMENT", self.content)
        self.assertIn("TRAFFIC", self.content)
        self.assertIn("INTENT", self.content)
        self.assertIn("CONVERSION", self.content)
        self.assertIn("ECONOMICS", self.content)
        self.assertIn("RETENTION", self.content)
        self.assertIn("DEMAND CREATION", self.content)

    def test_objective_relative_success(self):
        """Verify success is evaluated relative to specific commercial objectives."""
        self.assertIn("Objective-Relative Success Evaluation", self.content)
        self.assertIn("Brand / Demand Creation Asset", self.content)
        self.assertIn("Direct-Response / Performance Asset", self.content)
        self.assertIn("B2B Lead Generation Asset", self.content)
        self.assertIn("Affiliate Marketing Asset", self.content)

    def test_data_validation_and_tracking_checks(self):
        """Verify 10-point data validation and tracking integrity checks."""
        self.assertIn("Data Validation & Tracking Integrity Checks", self.content)
        self.assertIn("Missing Data & Dropouts", self.content)
        self.assertIn("Duplicate Event Floods", self.content)
        self.assertIn("Timezone & Currency Mismatches", self.content)
        self.assertIn("Attribution Window Alignment", self.content)
        self.assertIn("Platform Reporting Latency", self.content)
        self.assertIn("Data Source Reconciliation", self.content)

    def test_denominator_discipline(self):
        """Verify strict denominator discipline and standardization."""
        self.assertIn("Denominator Discipline", self.content)
        self.assertIn("Never compare rates or percentages without verifying matching denominators", self.content)

    def test_epistemic_discipline_observation_vs_causation(self):
        """Verify strict separation between observed changes, inferences, hypotheses, and causal claims."""
        self.assertIn("Epistemic Discipline: Observation vs. Inference vs. Causation", self.content)
        self.assertIn("EPISTEMIC PERFORMANCE HIERARCHY", self.content)
        self.assertIn("OBSERVED METRIC CHANGE", self.content)
        self.assertIn("CAUSAL VERIFICATION", self.content)
        self.assertIn("Post hoc ergo propter hoc reasoning is forbidden", self.content)

    def test_funnel_bottleneck_diagnosis(self):
        """Verify bottleneck identification logic across funnel stages."""
        self.assertIn("Funnel Bottleneck Diagnosis", self.content)
        self.assertIn("HIGH IMPRESSIONS + LOW CTR", self.content)
        self.assertIn("HIGH CTR + LOW LANDING PAGE ENGAGEMENT", self.content)
        self.assertIn("HIGH CTR + HIGH LANDING ENGAGEMENT + LOW CVR", self.content)
        self.assertIn("HIGH CVR + LOW VOLUME / HIGH CAC AT SCALE", self.content)
        self.assertIn("HIGH SOCIAL ENGAGEMENT + ZERO PURCHASES", self.content)

    def test_multi_cause_diagnostic_reasoning(self):
        """Verify multi-cause reasoning across the 15 standard causal dimensions."""
        self.assertIn("Multi-Cause Diagnostic Reasoning", self.content)
        self.assertIn("Creative Messaging", self.content)
        self.assertIn("Audience Quality", self.content)
        self.assertIn("Competitor Actions", self.content)
        self.assertIn("Seasonality", self.content)
        self.assertIn("Tracking Infrastructure", self.content)

    def test_creative_component_and_timeline_retention(self):
        """Verify creative component mapping and content-relative timeline video retention analysis."""
        self.assertIn("Creative Component Analysis & Content-Relative Retention", self.content)
        self.assertIn("Component-Level Performance Mapping", self.content)
        self.assertIn("Content-Relative Retention Diagnosis", self.content)
        self.assertIn("ACTUAL_DURATION", self.content)
        self.assertIn("SCENE_BOUNDARIES", self.content)

    def test_creative_fatigue_contextual_reasoning_and_no_universal_threshold(self):
        """Patch 2B.5.1: Verify no universal frequency threshold and multi-signal contextual fatigue diagnosis."""
        self.assertIn("Creative Fatigue: Multi-Signal Contextual Diagnosis", self.content)
        self.assertIn("No Universal Frequency Thresholds", self.content)
        self.assertIn("FATIGUE_SIGNAL", self.content)
        self.assertIn("FATIGUE_EVIDENCE", self.content)
        self.assertIn("FATIGUE_ALTERNATIVE_EXPLANATIONS", self.content)
        self.assertIn("Never diagnose creative fatigue from a single metric or calendar age alone", self.content)

    def test_experiment_rigor_and_anti_p_value_dogmatism(self):
        """Verify experiment analysis, anti-p-value dogmatism, early stopping rules, and INCONCLUSIVE validity."""
        self.assertIn("Experiment Analysis & Statistical Rigor", self.content)
        self.assertIn("No Universal $p < 0.05$ Dogmatism", self.content)
        self.assertIn("Guardrail Protection", self.content)
        self.assertIn("Early Stopping Protocol", self.content)
        self.assertIn("is a Valid, First-Class Result", self.content)
        self.assertIn("INCONCLUSIVE", self.content)

    def test_segment_cohort_and_simpsons_paradox(self):
        """Verify segment analysis, cohort LTV tracking, and Simpson's Paradox / mix shifts."""
        self.assertIn("Segment Analysis, Cohorts & Mix Effects (Simpson's Paradox)", self.content)
        self.assertIn("Cohort Tracking", self.content)
        self.assertIn("Simpson's Paradox & Mix Shifts", self.content)
        self.assertIn("Subgroup Slicing Discipline", self.content)

    def test_attribution_causal_strength_hierarchy_and_mmm_limits(self):
        """Patch 2B.5.1: Verify causal evidence hierarchy, MMM explicit limitations, and mandatory attribution metadata."""
        self.assertIn("Attribution Realism & Causal Strength Hierarchy", self.content)
        self.assertIn("STRONGER CAUSAL DESIGNS", self.content)
        self.assertIn("Randomized holdout tests", self.content)
        self.assertIn("OBSERVATIONAL & MODEL-DEPENDENT METHODS", self.content)
        self.assertIn("MODEL_SPECIFICATION", self.content)
        self.assertIn("IDENTIFICATION_ASSUMPTIONS", self.content)
        self.assertIn("COLLINEARITY", self.content)
        self.assertIn("ATTRIBUTION_METHOD", self.content)
        self.assertIn("CAUSAL_STRENGTH", self.content)
        self.assertIn("KEY_ASSUMPTIONS", self.content)
        self.assertIn("KNOWN_LIMITATIONS", self.content)

    def test_business_model_unit_economics_and_configured_stop_losses(self):
        """Patch 2B.5.1: Verify unit economics across business models, contribution margin protection, and configured stop-losses."""
        self.assertIn("Business-Model-Specific Unit Economics", self.content)
        self.assertIn("SAAS & SUBSCRIPTION", self.content)
        self.assertIn("E-COMMERCE & DTC", self.content)
        self.assertIn("AFFILIATE MARKETING", self.content)
        self.assertIn("B2B LEAD GENERATION", self.content)
        self.assertIn("CLIENT SERVICES & AGENCIES", self.content)
        self.assertIn("Profit vs. Revenue: Configured Stop-Losses & Margin Protection", self.content)
        self.assertIn("Configured Stop-Loss Guardrails", self.content)
        self.assertIn("CAMPAIGN_CONFIG", self.content)
        self.assertIn("BUSINESS_CONSTRAINT", self.content)
        self.assertIn("EXPLICIT_APPROVAL", self.content)
        self.assertIn("PREDEFINED_GUARDRAIL", self.content)

    def test_anomaly_detection_and_baselines(self):
        """Verify anomaly detection, historical baselines, and external context handoff to Intelligence."""
        self.assertIn("Anomaly Detection & Baseline Benchmarking", self.content)
        self.assertIn("Automated Anomaly Investigation", self.content)
        self.assertIn("Appropriate Baselines", self.content)
        self.assertIn("External Context Collaboration", self.content)

    def test_root_cause_decomposition_and_counterfactuals(self):
        """Verify root-cause decomposition and counterfactual thinking."""
        self.assertIn("Root-Cause Decomposition & Counterfactual Thinking", self.content)
        self.assertIn("Deconstruct Vague Labels", self.content)
        self.assertIn("Counterfactual Auditing", self.content)

    def test_marketing_operations_permissions_and_audit(self):
        """Verify conditional publishing authority modes (Manual, Supervised, Autonomous) and audit logging."""
        self.assertIn("Marketing Operations, Permissions & Audit Logging", self.content)
        self.assertIn("Conditional Publishing & Operational Authority", self.content)
        self.assertIn("MANUAL MODE", self.content)
        self.assertIn("SUPERVISED MODE", self.content)
        self.assertIn("AUTONOMOUS MODE", self.content)
        self.assertIn("MARKETING OPERATION AUDIT LOG", self.content)
        self.assertIn("ACTION_ID", self.content)

    def test_learning_extraction_and_failure_memory(self):
        """Verify candidate learning extraction schema and failure memory taxonomy."""
        self.assertIn("Candidate Learning Extraction & Failure Memory", self.content)
        self.assertIn("CANDIDATE LEARNING RECORD", self.content)
        self.assertIn("Failure Memory Logging", self.content)
        self.assertIn("STRATEGY_FAILURE", self.content)
        self.assertIn("TRACKING_FAILURE", self.content)

    def test_specialist_handoffs(self):
        """Verify specialist handoffs to Creative, Strategist, Intelligence, and CMO."""
        self.assertIn("Specialist Handoffs & Standard Outputs", self.content)
        self.assertIn("PERFORMANCE-TO-CREATIVE DIAGNOSTIC BRIEF", self.content)
        self.assertIn("PERFORMANCE-TO-STRATEGIST FEEDBACK", self.content)
        self.assertIn("PERFORMANCE-TO-INTELLIGENCE RESEARCH REQUEST", self.content)
        self.assertIn("EXECUTIVE PERFORMANCE REPORT", self.content)

    def test_confidence_model_and_self_check(self):
        """Verify qualitative confidence model (HIGH, MEDIUM, LOW + RATIONALE) and 20 self-check questions."""
        self.assertIn("Calibrated Confidence Model", self.content)
        self.assertIn("CONFIDENCE_RATIONALE", self.content)
        self.assertIn("Performance Self-Check (20 Diagnostic Questions)", self.content)
        for i in range(1, 21):
            self.assertIn(f"{i}.", self.content)


if __name__ == "__main__":
    unittest.main()
