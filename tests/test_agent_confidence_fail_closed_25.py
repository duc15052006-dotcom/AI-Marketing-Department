"""Regression coverage for qualitative agent confidence authority."""

import unittest

from integrations.models.invocation import AgentRunResult, normalize_confidence_tier


class AgentConfidenceFailClosed25Tests(unittest.TestCase):
    def test_known_qualitative_tiers_are_preserved(self):
        for raw, expected in [
            ("LOW", "LOW"),
            ("medium", "MEDIUM"),
            (" High ", "HIGH"),
            ("UNKNOWN", "UNKNOWN"),
        ]:
            tier, statistical = normalize_confidence_tier(raw)
            self.assertEqual(tier, expected)
            self.assertIsNone(statistical)

    def test_arbitrary_confidence_string_fails_closed(self):
        tier, statistical = normalize_confidence_tier("VERY HIGH")
        self.assertEqual(tier, "UNKNOWN")
        self.assertIsNone(statistical)

    def test_numeric_string_is_not_treated_as_confidence(self):
        tier, statistical = normalize_confidence_tier("0.95")
        self.assertEqual(tier, "UNKNOWN")
        self.assertIsNone(statistical)

    def test_model_numeric_score_is_not_promoted_to_statistical_confidence(self):
        tier, statistical = normalize_confidence_tier(0.95)
        self.assertEqual(tier, "UNKNOWN")
        self.assertIsNone(statistical)

    def test_boolean_is_not_promoted_to_confidence(self):
        tier, statistical = normalize_confidence_tier(True)
        self.assertEqual(tier, "UNKNOWN")
        self.assertIsNone(statistical)

    def test_missing_result_confidence_defaults_to_unknown(self):
        result = AgentRunResult(agent_id="cmo", task_id="T1", product_id="P1")
        self.assertEqual(result.confidence, "UNKNOWN")
        self.assertIsNone(result.statistical_confidence)


if __name__ == "__main__":
    unittest.main()
