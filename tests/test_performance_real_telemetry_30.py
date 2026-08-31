"""Production regressions for Performance telemetry truthfulness."""

import unittest

from connectors.analytics_connector import RealAnalyticsConnector
from integrations.models.base import ModelResponse, ModelResponseStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionReceiptRepository
from tools.tool_gateway import ToolGateway


class CapturingPerformanceGateway:
    def __init__(self) -> None:
        self.requests = []
        self.provider_registry = None
        self.model_policy = None

    def generate(self, request, **kwargs):
        self.requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            provider="telemetry_test",
            model_name="telemetry_test",
            status=ModelResponseStatus.SUCCESS,
            content="Performance planning output without observed winner claims.",
        )


class PerformanceRealTelemetry30Tests(unittest.TestCase):
    def _build_runtime(self, connector: RealAnalyticsConnector):
        registry = CapabilityRegistry()
        receipts = ExecutionReceiptRepository()
        tools = ToolGateway(capability_registry=registry, receipt_repository=receipts)
        tools.register_adapter(
            connector,
            aliases=[
                "analytics_adapter",
                "kpi_calc_adapter",
                "attribution_adapter",
                "stats_analysis_adapter",
                "data_retrieval_adapter",
            ],
        )
        model = CapturingPerformanceGateway()
        runtime = FiveAgentDepartmentRuntime(model_gateway=model, tool_gateway=tools)
        return runtime, model, receipts

    @staticmethod
    def _seed_upstream(context):
        context.stage_outputs["strategist"] = {
            "status": "COMPLETED",
            "positioning": "Grounded positioning",
        }
        context.stage_outputs["creative"] = {
            "status": "COMPLETED",
            "creative_synthesis": "Grounded creative synthesis",
        }

    def test_real_ingested_campaign_metrics_enter_performance_context(self):
        connector = RealAnalyticsConnector()
        connector.ingest_campaign_metrics(
            "CAMP-REAL-30",
            [
                {"channel": "meta", "impressions": 10000, "clicks": 500, "conversions": 40, "spend": 800.0, "revenue": 2400.0},
                {"channel": "search", "impressions": 20000, "clicks": 700, "conversions": 60, "spend": 1200.0, "revenue": 3600.0},
            ],
        )
        runtime, model, receipts = self._build_runtime(connector)
        context = runtime.start_run(objective="Evaluate campaign", campaign_id="CAMP-REAL-30")
        self._seed_upstream(context)

        output = runtime.execute_stage_performance(context)

        self.assertEqual(output["analytics_data_status"], "REAL_AVAILABLE")
        self.assertTrue(output["analytics_receipt_id"])
        self.assertIsNone(output["calc_receipt_id"])
        receipt = receipts.get_receipt(output["analytics_receipt_id"])
        self.assertEqual(receipt.capability_id, "analytics_retrieval")
        self.assertEqual(receipt.data["impressions"], 30000)
        self.assertEqual(receipt.data["revenue"], 6000.0)
        user_prompt = model.requests[-1].messages[-1].content
        self.assertIn("REAL_AVAILABLE", user_prompt)
        self.assertIn("30000", user_prompt)
        self.assertIn("6000.0", user_prompt)
        self.assertNotIn("target_cac", user_prompt)

    def test_no_ingested_metrics_stays_no_data_and_creates_no_fake_evidence(self):
        connector = RealAnalyticsConnector()
        runtime, model, receipts = self._build_runtime(connector)
        context = runtime.start_run(objective="Evaluate empty campaign", campaign_id="CAMP-NO-DATA-30")
        self._seed_upstream(context)

        output = runtime.execute_stage_performance(context)

        self.assertTrue(output["analytics_data_status"].startswith("NO_OBSERVED_DATA"))
        receipt = receipts.get_receipt(output["analytics_receipt_id"])
        self.assertEqual(receipt.error_class, "NO_DATA")
        self.assertIsNone(receipt.data)
        user_prompt = model.requests[-1].messages[-1].content
        self.assertIn("NO_OBSERVED_DATA", user_prompt)
        self.assertNotIn("target_cac", user_prompt)
        tool_evidence = [
            item for item in context.working_state.get("provenance_index", {}).values()
            if item.get("source_type") == "TOOL_RECEIPT"
        ]
        self.assertEqual(tool_evidence, [])

    def test_mock_analytics_success_is_not_promoted_to_grounded_evidence(self):
        # Default ToolGateway legacy analytics adapters are MOCK. Runtime must
        # retain the receipt for auditability but exclude its payload from the
        # grounded Performance evidence channel.
        registry = CapabilityRegistry()
        receipts = ExecutionReceiptRepository()
        tools = ToolGateway(capability_registry=registry, receipt_repository=receipts)
        model = CapturingPerformanceGateway()
        runtime = FiveAgentDepartmentRuntime(model_gateway=model, tool_gateway=tools)
        context = runtime.start_run(objective="Evaluate legacy mock path", campaign_id="CAMP-MOCK-30")
        self._seed_upstream(context)

        output = runtime.execute_stage_performance(context)

        self.assertEqual(output["analytics_data_status"], "NON_REAL_TELEMETRY_IGNORED:MOCK")
        user_prompt = model.requests[-1].messages[-1].content
        self.assertIn("NON_REAL_TELEMETRY_IGNORED:MOCK", user_prompt)
        tool_evidence = [
            item for item in context.working_state.get("provenance_index", {}).values()
            if item.get("source_type") == "TOOL_RECEIPT"
        ]
        self.assertEqual(tool_evidence, [])


if __name__ == "__main__":
    unittest.main()
