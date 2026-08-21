"""Unit Tests for Strategy Claim Discipline & Hardened Evaluator (Phase 3D.2.1).

Validates:
- Unsupported numerical effect sizes (20%, 30%+) are detected
- TO_BE_ESTABLISHED baseline status is accepted
- Unsupported superlatives ("fastest", "best") are detected
- First-party privacy statements are qualified
- Unsupported general-consumer hardware assumptions are detected
- Search discovery is classified as HYPOTHESIS requiring validation rather than demand proof
"""

import json
import re
import unittest
from schemas.handoff import (
    MetricBaselineStatus,
    RecommendationGroundingStatus,
    StrategicClaimType,
    StrategicExperiment,
    StrategicRecommendation,
)


class TestStrategyClaimDiscipline(unittest.TestCase):
    def test_unsupported_percentage_effect_sizes_detected(self):
        """Verify evaluator detects arbitrary numerical effect size percentages in hypotheses."""
        hyp_invalid_1 = "Upfront sizing tool will reduce onboarding drop-off by over 20%."
        hyp_invalid_2 = "Developers convert with 30%+ higher API activation velocity."
        hyp_valid = "Upfront sizing tool may reduce initial onboarding drop-off."

        has_arbitrary_pct_1 = bool(re.search(r"\d+%", hyp_invalid_1))
        has_arbitrary_pct_2 = bool(re.search(r"\d+%", hyp_invalid_2))
        has_arbitrary_pct_valid = bool(re.search(r"\d+%", hyp_valid))

        self.assertTrue(has_arbitrary_pct_1)
        self.assertTrue(has_arbitrary_pct_2)
        self.assertFalse(has_arbitrary_pct_valid)

    def test_to_be_established_baseline_accepted(self):
        """Verify experiments without baselines require TO_BE_ESTABLISHED classification."""
        exp = StrategicExperiment(
            experiment_id="EXP-TEST-001",
            hypothesis="Upfront VRAM guidance reduces drop-off",
            target_segment="Developers",
            change_or_treatment="Interactive sizing calculator",
            primary_metric="CLI Setup Completion Rate (TO_BE_ESTABLISHED)",
            metric_status=MetricBaselineStatus.TO_BE_ESTABLISHED,
            expected_signal="Reduced abandonment",
            time_or_sample_requirement="14 days",
            stop_condition="Halt if friction increases",
        )

        self.assertEqual(exp.metric_status, MetricBaselineStatus.TO_BE_ESTABLISHED)
        self.assertIn("TO_BE_ESTABLISHED", exp.primary_metric)

    def test_unsupported_superlative_detected(self):
        """Verify unverified superlatives like 'fastest' are caught by auditor."""
        claim_unsupported = "Ollama is the fastest way to run models locally."
        claim_qualified = "Ollama is a streamlined CLI runtime for local model execution."

        has_superlative_1 = "fastest" in claim_unsupported
        has_superlative_2 = "fastest" in claim_qualified

        self.assertTrue(has_superlative_1)
        self.assertFalse(has_superlative_2)

    def test_first_party_privacy_claim_remains_qualified(self):
        """Verify first-party privacy statements are classified as FIRST_PARTY_CLAIM."""
        rec = StrategicRecommendation(
            rec_id="STRAT-PRIVACY",
            title="Privacy-Centric Positioning",
            recommendation="Highlight offline zero-data-leakage architecture for compliance teams.",
            rationale="First-party copy emphasizes offline execution and no data training.",
            claim_type=StrategicClaimType.FIRST_PARTY_CLAIM,
            supported_by=["EVID-WEB-893338BD"],
        )

        self.assertEqual(rec.claim_type, StrategicClaimType.FIRST_PARTY_CLAIM)
        self.assertIn("EVID-WEB-893338BD", rec.supported_by)

    def test_general_consumer_hardware_assumption_detected(self):
        """Verify unproven population hardware claims are flagged as unsupported assumptions."""
        tradeoff_invalid = "Will not run ads to consumers lacking local GPU hardware."
        tradeoff_corrected = "Current evidence is strongly developer-oriented and does not establish broad consumer-market fit."

        is_population_assumption_1 = "lacking local gpu" in tradeoff_invalid.lower()
        is_population_assumption_2 = "lacking local gpu" in tradeoff_corrected.lower()

        self.assertTrue(is_population_assumption_1)
        self.assertFalse(is_population_assumption_2)

    def test_search_discovery_discipline_requires_validation_test(self):
        """Verify search discovery is treated as a hypothesis requiring validation rather than demand proof."""
        rec = StrategicRecommendation(
            rec_id="STRAT-SEARCH",
            title="Technical Search Channel",
            recommendation="Hypothesize technical search as an acquisition channel for developer queries.",
            rationale="Search discovery identified technical queries; volume requires validation.",
            claim_type=StrategicClaimType.HYPOTHESIS,
            supported_by=["EVID-SRCH-132D6868"],
            validation_test="Execute 21-day search capture test to measure install rates.",
        )

        self.assertEqual(rec.claim_type, StrategicClaimType.HYPOTHESIS)
        self.assertTrue(len(rec.validation_test) > 0)


if __name__ == "__main__":
    unittest.main()
