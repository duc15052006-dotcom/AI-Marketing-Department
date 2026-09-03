from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from integrations.models.base import ModelRequest, ModelResponse, ModelResponseStatus, ModelUsage
from integrations.models.gateway import UniversalModelGateway
from runtime.engine import FiveAgentDepartmentRuntime
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


class FakeIntelligenceModelGateway(UniversalModelGateway):
    def __init__(self) -> None:
        super().__init__(free_only_mode=True)
        self.recorded_requests: List[ModelRequest] = []

    def generate(
        self,
        request: ModelRequest,
        profile: str = "default",
        provider_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model_policy: Optional[Any] = None,
        provider_snapshot: Optional[Any] = None,
        strict_model_pin: bool = False,
        allow_paid: bool = False,
    ) -> ModelResponse:
        self.recorded_requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            provider="fake_provider",
            model_name="fake_model",
            status=ModelResponseStatus.SUCCESS,
            content="Grounded intelligence synthesis.",
            usage=ModelUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            latency_ms=1.0,
        )


class SearchResultsAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def adapter_name(self) -> str:
        return "search_results_test_adapter"

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        self.calls += 1
        self.assert_capability = capability_id
        return AdapterResult(
            success=True,
            execution_mode=ExecutionMode.REAL,
            data={
                "query": parameters.get("query", ""),
                "result_count": 2,
                "results": [
                    {
                        "rank": 1,
                        "title": "Metric Vietnam ecommerce report",
                        "url": "https://metric.example.test/report",
                        "snippet": "Search snippet only; substantive metric is on the page.",
                    },
                    {
                        "rank": 2,
                        "title": "Sapo market report",
                        "url": "https://sapo.example.test/market",
                        "snippet": "Search snippet only; substantive consumer data is on the page.",
                    },
                ],
            },
        )


class RecordingPageAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.urls: List[str] = []

    @property
    def adapter_name(self) -> str:
        return "recording_page_test_adapter"

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        url = str(parameters.get("url", ""))
        self.urls.append(url)
        marker = (
            "METRIC_PAGE_EVIDENCE_2026 revenue_growth=37pct"
            if "metric" in url
            else "SAPO_PAGE_EVIDENCE_2026 consumer_sample=1240"
        )
        return AdapterResult(
            success=True,
            execution_mode=ExecutionMode.REAL,
            data={
                "url": url,
                "content_type": "text/html",
                "extracted_text": marker,
            },
        )


class IntelligenceFollowSearchResultsV1Tests(unittest.TestCase):
    def test_research_reads_discovered_pages_and_places_content_in_model_context(self) -> None:
        model_gateway = FakeIntelligenceModelGateway()
        runtime = FiveAgentDepartmentRuntime(model_gateway=model_gateway)
        search = SearchResultsAdapter()
        pages = RecordingPageAdapter()
        runtime.tool_gateway.register_adapter(search, aliases=["search_adapter"])
        runtime.tool_gateway.register_adapter(pages, aliases=["http_adapter"])

        context, output, _artifact = runtime.run_research_inquiry(
            objective="Research Vietnam ecommerce market using Metric and Sapo evidence",
            business_id="BIZ-WEB-RED-001",
        )

        self.assertEqual(output.get("status"), "COMPLETED")
        self.assertEqual(search.calls, 1)
        self.assertEqual(
            pages.urls,
            [
                "https://metric.example.test/report",
                "https://sapo.example.test/market",
            ],
            "Intelligence must read substantive pages discovered by web_search before synthesis.",
        )
        self.assertGreaterEqual(len(context.execution_receipt_refs), 3)
        self.assertEqual(len(model_gateway.recorded_requests), 1)
        rendered_prompt = "\n".join(
            str(message.content)
            for message in model_gateway.recorded_requests[0].messages
        )
        self.assertIn("METRIC_PAGE_EVIDENCE_2026", rendered_prompt)
        self.assertIn("SAPO_PAGE_EVIDENCE_2026", rendered_prompt)


if __name__ == "__main__":
    unittest.main()
