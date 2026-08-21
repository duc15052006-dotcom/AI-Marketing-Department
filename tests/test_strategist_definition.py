"""Tests verifying the Strategist Agent Definition, Hardening Patch 2B.3.1, and Professional DNA integrity."""

import unittest
from pathlib import Path
from tests.test_agent_manifests import parse_yaml_frontmatter


class TestStrategistDefinition(unittest.TestCase):
    def setUp(self):
        self.strat_md_path = (
            Path(__file__).resolve().parent.parent
            / ".agents"
            / "agents"
            / "strategist"
            / "agent.md"
        )
        self.assertTrue(self.strat_md_path.exists(), "strategist/agent.md does not exist")
        self.content = self.strat_md_path.read_text(encoding="utf-8")
        self.frontmatter = parse_yaml_frontmatter(self.content)

    def test_strategist_frontmatter_valid(self):
        """Verify Strategist frontmatter has name 'strategist' and non-empty description."""
        self.assertEqual(self.frontmatter.get("name"), "strategist")
        self.assertIn("Strategy", self.frontmatter.get("description", ""))

    def test_strategist_identity_and_role_boundaries(self):
        """Verify Strategist is defined as strategic choice architect and NOT primary executor of other domains."""
        self.assertIn("Marketing Strategy & Growth Architect", self.content)
        self.assertIn("converts verified market evidence and business goals into clear", self.content)
        self.assertIn("WHERE SHOULD WE PLAY", self.content)
        self.assertIn("WHO SHOULD WE SERVE", self.content)
        self.assertIn("WHAT SHOULD WE NOT DO", self.content)
        self.assertIn("primary researcher", self.content)
        self.assertIn("final commercial decision-maker", self.content)
        self.assertIn("primary copywriter", self.content)
        self.assertIn("multimedia production director", self.content)
        self.assertIn("performance measurement engine", self.content)
        self.assertIn("publishing operator", self.content)

    def test_strategy_is_choice_and_tradeoffs(self):
        """Verify strategy requires trade-offs and explicit non-pursuits (no target-everyone)."""
        self.assertIn("Strategy is Choice: Trade-offs & Non-Pursuits", self.content)
        self.assertIn("WHAT WE WILL DO", self.content)
        self.assertIn("WHAT WE WILL NOT DO", self.content)
        self.assertIn("reject it as a generic wishlist", self.content)

    def test_evidence_dependency_and_input_contract(self):
        """Verify evidence classification (EVIDENCE-SUPPORTED, ASSUMPTION-DEPENDENT, EXPERIMENTAL) and input contract."""
        self.assertIn("Evidence Dependency & Epistemic Classification", self.content)
        self.assertIn("EVIDENCE-SUPPORTED", self.content)
        self.assertIn("ASSUMPTION-DEPENDENT", self.content)
        self.assertIn("EXPERIMENTAL", self.content)
        self.assertIn("STRATEGIC INPUT AUDIT", self.content)
        self.assertIn("BUSINESS_OBJECTIVE", self.content)
        self.assertIn("BUSINESS_MODEL", self.content)

    def test_business_model_strategy_adaptation(self):
        """Patch 2B.3.1: Verify strategy adapts explicitly across SaaS, E-commerce, Affiliate, Lead Gen, and Services."""
        self.assertIn("Business Model Strategy Adaptation", self.content)
        self.assertIn("SAAS & SUBSCRIPTION", self.content)
        self.assertIn("E-COMMERCE & PHYSICAL GOODS", self.content)
        self.assertIn("AFFILIATE & PARTNERSHIP MARKETING", self.content)
        self.assertIn("LEAD GENERATION (B2B / HIGH-TICKET)", self.content)
        self.assertIn("CLIENT SERVICES & AGENCIES", self.content)

    def test_contextual_economics_and_no_universal_thresholds(self):
        """Patch 2B.3.1: Verify removal of universal 70% margin / 12-month payback rules in favor of contextual benchmarks."""
        self.assertIn("Contextual Economics & Anti-Dogmatism", self.content)
        self.assertIn("No Universal Margin Rules", self.content)
        self.assertIn("No Universal Payback Rules", self.content)
        self.assertIn("REFERENCE_BENCHMARK", self.content)
        self.assertIn("WHY_IT_APPLIES", self.content)
        self.assertIn("LIMITATIONS", self.content)

    def test_bounded_strategic_loss_investment_policy(self):
        """Patch 2B.3.1: Verify distinction between accidental loss and bounded strategic investment."""
        self.assertIn("Strategic Loss & Bounded Investment Policy", self.content)
        self.assertIn("Accidental Bad Economics", self.content)
        self.assertIn("Intentional Strategic Investment", self.content)
        self.assertIn("EXPECTED_LOSS", self.content)
        self.assertIn("MAXIMUM_ACCEPTABLE_LOSS", self.content)
        self.assertIn("TIME_HORIZON", self.content)
        self.assertIn("STRATEGIC_REASON", self.content)
        self.assertIn("EXPECTED_FUTURE_VALUE", self.content)
        self.assertIn("STOP_CONDITION", self.content)

    def test_demand_creation_vs_demand_capture_balance(self):
        """Patch 2B.3.1: Verify brand vs demand balance and measurable brand accountability."""
        self.assertIn("Brand + Demand Balance: Demand Creation vs. Demand Capture", self.content)
        self.assertIn("DEMAND CREATION (Brand & Mental Availability)", self.content)
        self.assertIn("DEMAND CAPTURE (Direct Conversion & Activation)", self.content)
        self.assertIn("Brand Activity Measurement Protocol", self.content)
        self.assertIn("Branded search query volume", self.content)
        self.assertIn("Direct organic domain traffic", self.content)

    def test_segmentation_and_targeting_depth(self):
        """Verify multi-dimensional segmentation beyond demographics and value-based targeting."""
        self.assertIn("Multi-Dimensional Segmentation", self.content)
        self.assertIn("Job-to-Be-Done (JTBD)", self.content)
        self.assertIn("Context & Trigger Event", self.content)
        self.assertIn("Problem Severity", self.content)
        self.assertIn("Target Selection Rule", self.content)
        self.assertIn("largest segment is rarely the best segment", self.content)

    def test_positioning_integrity_and_category_framing(self):
        """Verify positioning schema, 6-point quality test, and category reframing rules."""
        self.assertIn("Positioning Architecture & Defensibility", self.content)
        self.assertIn("6-Point Positioning Quality Test", self.content)
        self.assertIn("RELEVANCE", self.content)
        self.assertIn("CLARITY", self.content)
        self.assertIn("CREDIBILITY", self.content)
        self.assertIn("DISTINCTIVENESS", self.content)
        self.assertIn("DEFENSIBILITY", self.content)
        self.assertIn("Category & Market Framing", self.content)
        self.assertIn("Never invent positioning claims", self.content)

    def test_value_prop_and_offer_architecture(self):
        """Verify multi-tier value dimensions and offer packaging without fake urgency."""
        self.assertIn("Value Proposition & Offer Architecture", self.content)
        self.assertIn("Functional Value", self.content)
        self.assertIn("Economic Value", self.content)
        self.assertIn("Emotional Value", self.content)
        self.assertIn("Risk Reversal & Guarantees", self.content)
        self.assertIn("Truthful Urgency / Scarcity", self.content)

    def test_pricing_reasoning_and_unit_economics(self):
        """Verify evidence-based pricing and unit economics."""
        self.assertIn("Evidence-Based Pricing Reasoning", self.content)
        self.assertIn("Willingness-to-Pay Evidence", self.content)

    def test_customer_journey_and_channel_strategy(self):
        """Verify non-linear journey mapping, bottleneck diagnosis, and channel evaluation criteria."""
        self.assertIn("Customer Journey & Non-Linear Funnel Design", self.content)
        self.assertIn("NON-LINEAR CUSTOMER JOURNEY", self.content)
        self.assertIn("Channel Strategy & Distribution Mix", self.content)
        self.assertIn("Owned Media", self.content)
        self.assertIn("Earned Media", self.content)
        self.assertIn("Paid Distribution", self.content)

    def test_content_strategy_and_pillars(self):
        """Verify content strategy functions and rejection of generic filler pillars."""
        self.assertIn("Content Strategy & Decision-Driven Pillars", self.content)
        self.assertIn("Prohibited Generic Pillars", self.content)
        self.assertIn("Permitted Strategic Pillars", self.content)
        self.assertIn("Discovery (Pattern Interruption)", self.content)
        self.assertIn("Objection Handling (Friction Removal)", self.content)

    def test_affiliate_and_growth_loops(self):
        """Verify affiliate economics and causal growth loop blueprints."""
        self.assertIn("Growth Strategy & Compounding Growth Loops", self.content)
        self.assertIn("Content-to-Insight Loop", self.content)
        self.assertIn("Customer Proof Loop", self.content)
        self.assertIn("Never diagram a growth loop without a concrete", self.content)

    def test_falsifiable_hypothesis_and_experiment_portfolio(self):
        """Verify structured hypothesis schema and multi-tier experiment portfolio."""
        self.assertIn("Falsifiable Hypothesis Design & Experiment Portfolio", self.content)
        self.assertIn("Structured Hypothesis Standard", self.content)
        self.assertIn("PRIMARY KPI", self.content)
        self.assertIn("GUARDRAIL METRICS", self.content)
        self.assertIn("DECISION RULE", self.content)

    def test_anti_dogmatism_trend_and_copycat_rules(self):
        """Verify anti-framework dogmatism, anti-trend-chasing, and anti-copycat principles."""
        self.assertIn("Anti-Dogmatism & Anti-Copycat Principles", self.content)
        self.assertIn("Anti-Framework Dogmatism", self.content)
        self.assertIn("Anti-Trend-Chasing", self.content)
        self.assertIn("Anti-Copycat Strategy", self.content)

    def test_strategic_risk_and_invalidation(self):
        """Verify strategic risk auditing, What Must Be True, and Invalidation conditions."""
        self.assertIn("Strategic Risk & Invalidation Conditions", self.content)
        self.assertIn("WHAT MUST BE TRUE", self.content)
        self.assertIn("WHAT WOULD INVALIDATE THE STRATEGY", self.content)

    def test_specialist_handoffs_and_brief_schemas(self):
        """Verify structured Creative Strategy Brief, Experiment Spec, and CMO Proposal."""
        self.assertIn("Specialist Handoffs & Standard Outputs", self.content)
        self.assertIn("CREATIVE STRATEGY BRIEF", self.content)
        self.assertIn("EXPERIMENT SPECIFICATION", self.content)
        self.assertIn("Executive Strategy Proposal", self.content)
        self.assertIn("Failure Protocol", self.content)

    def test_strategist_preflight_self_check_questions(self):
        """Verify the 15 diagnostic self-check audit questions for Strategist."""
        self.assertIn("Strategist Pre-Flight Self-Check (15 Diagnostic Questions)", self.content)
        for i in range(1, 16):
            self.assertIn(f"{i}.", self.content)


if __name__ == "__main__":
    unittest.main()
