"""Tests verifying the CMO Agent Definition and Professional DNA integrity."""

import unittest
from pathlib import Path
from tests.test_agent_manifests import parse_yaml_frontmatter


class TestCMODefinition(unittest.TestCase):
    def setUp(self):
        self.cmo_md_path = (
            Path(__file__).resolve().parent.parent
            / ".agents"
            / "agents"
            / "cmo"
            / "agent.md"
        )
        self.assertTrue(self.cmo_md_path.exists(), "cmo/agent.md does not exist")
        self.content = self.cmo_md_path.read_text(encoding="utf-8")
        self.frontmatter = parse_yaml_frontmatter(self.content)

    def test_cmo_frontmatter_valid(self):
        """Verify CMO frontmatter has name 'cmo' and non-empty description."""
        self.assertEqual(self.frontmatter.get("name"), "cmo")
        self.assertIn("Chief Marketing Officer", self.frontmatter.get("description", ""))

    def test_cmo_identity_and_role_boundaries(self):
        """Verify CMO is defined as orchestrator and NOT primary executor of specialist tasks."""
        self.assertIn("Executive Master Orchestrator", self.content)
        self.assertIn("the primary market researcher", self.content)
        self.assertIn("the primary copywriter", self.content)
        self.assertIn("the primary video creator", self.content)
        self.assertIn("the analytics processor", self.content)
        self.assertIn("the publishing worker", self.content)

    def test_epistemic_discipline_sections(self):
        """Verify CMO enforces the 4 epistemic tiers and rejects hypotheses as facts."""
        self.assertIn("Epistemic Discipline", self.content)
        self.assertIn("FACT", self.content)
        self.assertIn("OBSERVATION", self.content)
        self.assertIn("INFERENCE", self.content)
        self.assertIn("HYPOTHESIS", self.content)
        self.assertIn("Never Present Hypotheses or Inferences as Facts", self.content)

    def test_business_first_decision_model(self):
        """Verify mandatory establishment of business objectives, KPIs, and constraints."""
        self.assertIn("OBJECTIVE", self.content)
        self.assertIn("PRIMARY KPI", self.content)
        self.assertIn("SECONDARY KPIs", self.content)
        self.assertIn("CONSTRAINTS", self.content)
        self.assertIn("DOWNSIDE RISK & REVERSIBILITY", self.content)

    def test_specialist_delegation_mapping(self):
        """Verify all 4 specialist targets are clearly mapped."""
        self.assertIn("INTELLIGENCE", self.content)
        self.assertIn("STRATEGIST", self.content)
        self.assertIn("CREATIVE", self.content)
        self.assertIn("PERFORMANCE", self.content)

    def test_delegation_quality_standard(self):
        """Verify TaskEnvelope field mandates and prohibition of vague delegations."""
        self.assertIn("TASK_ID", self.content)
        self.assertIn("PRODUCT_ID", self.content)
        self.assertIn("EVIDENCE_REQUIRED", self.content)
        self.assertIn("SUCCESS_CRITERIA", self.content)
        self.assertIn("Never issue vague delegations", self.content)

    def test_cross_agent_review_and_contradictions(self):
        """Verify cross-specialist reviews and contradiction resolution protocols."""
        self.assertIn("Cross-Agent Review", self.content)
        self.assertIn("Contradiction Resolution Protocol", self.content)
        self.assertIn("Reject false compromises", self.content)

    def test_performance_interpretation_and_bottlenecks(self):
        """Verify avoidance of vanity metrics and diagnosis of conversion bottlenecks."""
        self.assertIn("High Views / Impressions + Low Conversion", self.content)
        self.assertIn("High Click-Through Rate (CTR) + Low Landing Page Conversion (CVR)", self.content)
        self.assertIn("Low Views + High Conversion Per Viewer", self.content)

    def test_rejecting_universal_p_value_dogmatism(self):
        """Patch 2B.1.1: Verify CMO avoids rigid universal p < 0.05 winner requirements."""
        self.assertIn("Multi-Dimensional Experiment Decision Rules", self.content)
        self.assertIn("Effect Size", self.content)
        self.assertIn("Confidence & Uncertainty Bounds", self.content)
        self.assertIn("Sample Size & Statistical Power", self.content)
        self.assertIn("Practical Significance & Business Impact", self.content)
        self.assertIn("Guardrail Metrics", self.content)
        self.assertIn("treat a single rigid threshold", self.content)

    def test_avoiding_premature_experiment_stopping(self):
        """Patch 2B.1.1: Verify CMO stopping rules distinguish guardrail halts from premature termination."""
        self.assertIn("Balanced Experiment Stopping Policy", self.content)
        self.assertIn("Avoid Premature Stopping", self.content)
        self.assertIn("Immediate Pause/Stop Triggers", self.content)
        self.assertIn("Complete Test Horizon", self.content)

    def test_distinguishing_security_tiers_and_runtime_gates(self):
        """Patch 2B.1.1: Verify clear distinction between Policy, Designed, Implemented, and Runtime controls."""
        self.assertIn("POLICY", self.content)
        self.assertIn("DESIGNED CONTROL", self.content)
        self.assertIn("IMPLEMENTED CONTROL", self.content)
        self.assertIn("RUNTIME-ENFORCED CONTROL", self.content)
        self.assertIn("Required Future Runtime Gate", self.content)
        self.assertIn("Zero Credential Exposure", self.content)

    def test_cmo_preflight_self_check_questions(self):
        """Verify the presence of the 12 CMO pre-flight self-check audit questions."""
        self.assertIn("CMO Pre-Flight Self-Check (12 Executive Questions)", self.content)
        for i in range(1, 13):
            self.assertIn(f"{i}.", self.content)


if __name__ == "__main__":
    unittest.main()
