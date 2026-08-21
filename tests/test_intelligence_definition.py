"""Tests verifying the Intelligence Agent Definition, Hardening Patch 2B.2.1, and Professional DNA integrity."""

import unittest
from pathlib import Path
from tests.test_agent_manifests import parse_yaml_frontmatter


class TestIntelligenceDefinition(unittest.TestCase):
    def setUp(self):
        self.intel_md_path = (
            Path(__file__).resolve().parent.parent
            / ".agents"
            / "agents"
            / "intelligence"
            / "agent.md"
        )
        self.assertTrue(self.intel_md_path.exists(), "intelligence/agent.md does not exist")
        self.content = self.intel_md_path.read_text(encoding="utf-8")
        self.frontmatter = parse_yaml_frontmatter(self.content)

    def test_intelligence_frontmatter_valid(self):
        """Verify Intelligence frontmatter has name 'intelligence' and non-empty description."""
        self.assertEqual(self.frontmatter.get("name"), "intelligence")
        self.assertIn("Intelligence", self.frontmatter.get("description", ""))

    def test_intelligence_identity_and_role_boundaries(self):
        """Verify Intelligence is defined as research engine and NOT final decision-maker/creator."""
        self.assertIn("Market & Consumer Intelligence Specialist", self.content)
        self.assertIn("reduce uncertainty before commercial marketing decisions are made", self.content)
        self.assertIn("final strategic decision-maker", self.content)
        self.assertIn("primary copywriter", self.content)
        self.assertIn("creative production director", self.content)
        self.assertIn("publishing operator", self.content)
        self.assertIn("final internal performance analyst", self.content)

    def test_epistemic_discipline_and_signal_guardrails(self):
        """Verify epistemic tiers (FACT, OBSERVATION, INFERENCE, HYPOTHESIS) and critical guardrails."""
        self.assertIn("Epistemic Discipline", self.content)
        self.assertIn("FACT", self.content)
        self.assertIn("OBSERVATION", self.content)
        self.assertIn("INFERENCE", self.content)
        self.assertIn("HYPOTHESIS", self.content)
        self.assertIn("Never Convert Popularity into Purchase Demand", self.content)
        self.assertIn("Never Convert Views into Sales Intent", self.content)
        self.assertIn("Never Convert Engagement into Commercial Opportunity", self.content)
        self.assertIn("Never Convert Correlation into Causation", self.content)
        self.assertIn("Never Convert a Small Sample into Market-Wide Truth", self.content)

    def test_source_hierarchy_and_metadata_standard(self):
        """Verify 8-tier source hierarchy and mandatory source metadata fields."""
        self.assertIn("Source Hierarchy", self.content)
        self.assertIn("First-Party Internal Business Data", self.content)
        self.assertIn("Official Primary Sources", self.content)
        self.assertIn("Direct Marketplace & Product Data", self.content)
        self.assertIn("SOURCE_ID", self.content)
        self.assertIn("SOURCE_TYPE", self.content)
        self.assertIn("ORIGIN", self.content)
        self.assertIn("URL_OR_IDENTIFIER", self.content)
        self.assertIn("PUBLISH_DATE", self.content)
        self.assertIn("COLLECTED_AT", self.content)
        self.assertIn("FRESHNESS", self.content)
        self.assertIn("RELIABILITY", self.content)

    def test_freshness_protocol(self):
        """Verify time sensitivity protocol and freshness risk metadata."""
        self.assertIn("Freshness Protocol", self.content)
        self.assertIn("OBSERVED_AT", self.content)
        self.assertIn("SOURCE_DATE", self.content)
        self.assertIn("FRESHNESS_RISK", self.content)

    def test_research_decomposition_and_search_strategy(self):
        """Verify decomposition framework and multi-angle query strategies."""
        self.assertIn("RESEARCH DECOMPOSITION FRAMEWORK", self.content)
        self.assertIn("BUSINESS QUESTION", self.content)
        self.assertIn("DECISION SUPPORTED", self.content)
        self.assertIn("KNOWN FACTS", self.content)
        self.assertIn("UNKNOWN FACTS", self.content)
        self.assertIn("STOPPING CONDITIONS", self.content)
        self.assertIn("Multi-Angle Search Strategy", self.content)

    def test_ephemeral_subagent_rules(self):
        """Verify temporary subagent roles and permanent agent count invariant."""
        self.assertIn("Ephemeral Subagent Delegation", self.content)
        self.assertIn("Product Researcher", self.content)
        self.assertIn("Consumer Researcher", self.content)
        self.assertIn("Competitor Researcher", self.content)
        self.assertIn("Review Miner", self.content)
        self.assertIn("permanent agents", self.content)

    def test_source_verification_and_deduplication(self):
        """Verify 7-step forensic verification and anti-circular citation rules."""
        self.assertIn("7-Step Forensic Source Verification", self.content)
        self.assertIn("Trace to Primary Origin", self.content)
        self.assertIn("Hunt for Disconfirming Evidence", self.content)
        self.assertIn("Detect Circular Citations", self.content)
        self.assertIn("Deduplication & Entity Resolution", self.content)

    def test_say_vs_do_triangulation_and_no_absolute_behavior_priority(self):
        """Patch 2B.2.1: Verify Say vs Do triangulation and rejection of behavioral superiority dogma."""
        self.assertIn("Say vs. Do Triangulation", self.content)
        self.assertIn("Never treat behavioral telemetry as a universally superior", self.content)
        self.assertIn("WHAT PEOPLE SAY", self.content)
        self.assertIn("WHAT PEOPLE DO", self.content)
        self.assertIn("CONTEXT", self.content)
        self.assertIn("CONSTRAINTS", self.content)
        self.assertIn("INCENTIVES", self.content)
        self.assertIn("Root-Cause Discrepancy Analysis", self.content)
        self.assertIn("Discoverability & Awareness", self.content)
        self.assertIn("UX & Usability Friction", self.content)
        self.assertIn("Social Desirability Bias", self.content)

    def test_sample_percentage_discipline(self):
        """Patch 2B.2.1: Verify review mining enforces sample-qualified percentage language."""
        self.assertIn("Sample Percentage Discipline Rule", self.content)
        self.assertIn("Never generalize a sample percentage to the entire customer population", self.content)
        self.assertIn("WITHIN_THIS_SAMPLE", self.content)
        self.assertIn("SAMPLE_SIZE", self.content)
        self.assertIn("SAMPLING_METHOD", self.content)
        self.assertIn("TIME_WINDOW", self.content)
        self.assertIn("PLATFORM", self.content)
        self.assertIn("KNOWN_BIAS", self.content)

    def test_demand_signal_taxonomy_and_no_zero_demand_inference(self):
        """Patch 2B.2.1: Verify demand signals are descriptive taxonomy, not universal hierarchy."""
        self.assertIn("Demand Analysis & Signal Taxonomy", self.content)
        self.assertIn("not a rigid universal truth ranking", self.content)
        self.assertIn("TRANSACTION SIGNALS", self.content)
        self.assertIn("PURCHASE_INTENT SIGNALS", self.content)
        self.assertIn("CONSIDERATION SIGNALS", self.content)
        self.assertIn("INTEREST SIGNALS", self.content)
        self.assertIn("ATTENTION SIGNALS", self.content)
        self.assertIn("Zero Demand", self.content)

    def test_confidence_calibration_and_anti_pseudo_precision(self):
        """Patch 2B.2.1: Verify qualitative confidence calibration, confidence rationale, and anti-pseudo-precision."""
        self.assertIn("Confidence Calibration & Anti-Pseudo-Precision Rule", self.content)
        self.assertIn("HIGH CONFIDENCE", self.content)
        self.assertIn("MEDIUM CONFIDENCE", self.content)
        self.assertIn("LOW CONFIDENCE", self.content)
        self.assertIn("CONFIDENCE_RATIONALE", self.content)
        self.assertIn("SOURCE QUALITY", self.content)
        self.assertIn("SOURCE DIVERSITY", self.content)
        self.assertIn("SAMPLE QUALITY", self.content)

    def test_observation_router_and_ethics(self):
        """Verify abstract Observation Router architecture, tool priority, and ethical rules."""
        self.assertIn("Social Observation Architecture", self.content)
        self.assertIn("search_social", self.content)
        self.assertIn("observe_trends", self.content)
        self.assertIn("fetch_comments", self.content)
        self.assertIn("analyze_url", self.content)
        self.assertIn("Observation Layer Priority Hierarchy", self.content)
        self.assertIn("Privacy, Ethics & Research Governance", self.content)

    def test_research_stopping_rule_and_handoffs(self):
        """Verify stopping criteria and structured specialist handoffs."""
        self.assertIn("Research Stopping Rule", self.content)
        self.assertIn("To CMO", self.content)
        self.assertIn("To STRATEGIST", self.content)
        self.assertIn("To CREATIVE", self.content)
        self.assertIn("To PERFORMANCE", self.content)
        self.assertIn("Failure Protocol", self.content)

    def test_intelligence_preflight_self_check_questions(self):
        """Verify the 12 diagnostic self-check audit questions for Intelligence."""
        self.assertIn("Intelligence Pre-Flight Self-Check (12 Diagnostic Questions)", self.content)
        for i in range(1, 13):
            self.assertIn(f"{i}.", self.content)


if __name__ == "__main__":
    unittest.main()
