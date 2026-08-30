"""Regression coverage preventing fabricated analytics from entering agent context."""

import unittest

from connectors.analytics_connector import RealAnalyticsConnector
from tools.receipts import ExecutionMode


class AnalyticsNoFabricatedResults27Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector = RealAnalyticsConnector()

    def _assert_no_fabricated_result(self, capability_id: str) -> None:
        result = self.connector.execute(capability_id, {})
        self.assertTrue(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)
        self.assertIsInstance(result.data, dict)
        self.assertFalse(result.data["analysis_available"])
        self.assertEqual(result.data["status"], "NO_OBSERVED_DATA")

        forbidden_keys = {
            "channel_weights",
            "stat_sig",
            "p_value",
            "winner",
            "uplift",
            "ctr",
            "cvr",
            "roas",
            "cac",
            "revenue",
            "conversions",
        }
        self.assertTrue(forbidden_keys.isdisjoint(result.data.keys()))

        serialized = repr(result.data).lower()
        self.assertNotIn("0.008", serialized)
        self.assertNotIn("paid_search", serialized)
        self.assertNotIn("paid_social", serialized)

    def test_attribution_without_observed_data_returns_no_data_marker_only(self):
        self._assert_no_fabricated_result("attribution_data_access")

    def test_experiment_analysis_without_observed_data_returns_no_data_marker_only(self):
        self._assert_no_fabricated_result("experiment_result_analysis")


if __name__ == "__main__":
    unittest.main()
