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


class AdversarialSearchResultsAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def adapter_name(self) -> str:
        return "intelligence_search_results_adversarial_v2"

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
        return AdapterResult(
            success=True,
            execution_mode=ExecutionMode.REAL,
            data={
                "query": parameters.get("query", ""),
                "result_count": 6,
                "results": [
                    {
                        "rank": 1,
                        "title": "Metric Vietnam ecommerce report",
                        "url": "https://metric.example.test/report",
                        "snippet": "Discovery metadata only; the substantive number is on-page.",
                    },
                    {
                        "rank": 2,
                        "title": "Sapo market report",
                        "url": "https://sapo.example.test/market",
                        "snippet": "Discovery metadata only; the substantive sample is on-page.",
                    },
                    {
                        "rank": 3,
                        "title": "Tinhte consumer discussion",
                        "url": "https://tinhte.example.test/thread",
                        "snippet": "Discovery metadata only; substantive observations are on-page.",
                    },
                    {
                        "rank": 4,
                        "title": "Duplicate Metric result",
                        "url": "https://metric.example.test/report",
                        "snippet": "Duplicate URL must not cause a second page read.",
                    },
                    {
                        "rank": 5,
                        "title": "Unsafe non-http result",
                        "url": "javascript:alert('not-a-page')",
                        "snippet": "Must never be dispatched to read_page.",
                    },
                    {
                        "rank": 6,
                        "title": "Overflow result",
                        "url": "https://overflow.example.test/fourth",
                        "snippet": "Must remain outside the bounded follow-up budget.",
                    },
                ],
            },
        )


class RecordingPageAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.urls: List[str] = []

    @property
    def adapter_name(self) -> str:
        return "intelligence_page_reader_adversarial_v2"

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
        if "metric" in url:
            marker = "METRIC_PAGE_EVIDENCE_V2 revenue_growth=37pct"
        elif "sapo" in url:
            marker = "SAPO_PAGE_EVIDENCE_V2 consumer_sample=1240"
        else:
            marker = "TINHTE_PAGE_EVIDENCE_V2 observed_objections=shipping_and_warranty"
        return AdapterResult(
            success=True,
            execution_mode=ExecutionMode.REAL,
            data={
                "url": url,
                "content_type": "text/html",
                "extracted_text": marker,
            },
        )


class IntelligenceFollowSearchResultsAdversarialV2Tests(unittest.TestCase):
    def test_intelligence_reads_bounded_unique_http_pages_before_synthesis(self) -> None:
        model_gateway = FakeIntelligenceModelGateway()
        runtime = FiveAgentDepartmentRuntime(model_gateway=model_gateway)
        search = AdversarialSearchResultsAdapter()
        pages = RecordingPageAdapter()
        runtime.tool_gateway.register_adapter(search, aliases=["search_adapter"])
        runtime.tool_gateway.register_adapter(pages, aliases=["http_adapter"])

        context, output, _artifact = runtime.run_research_inquiry(
            objective="Research Vietnam ecommerce market using Metric, Sapo, and Tinhte evidence",
            business_id="BIZ-INTEL-FOLLOW-V2",
        )

        self.assertEqual("COMPLETED", output.get("status"))
        self.assertEqual(1, search.calls, "Intelligence must perform one discovery search, not recursive searches.")
        self.assertEqual(
            [
                "https://metric.example.test/report",
                "https://sapo.example.test/market",
                "https://tinhte.example.test/thread",
            ],
            pages.urls,
            "Intelligence must follow at most three unique HTTP(S) pages discovered by web_search before synthesis.",
        )
        self.assertGreaterEqual(
            len(context.execution_receipt_refs),
            4,
            "Search plus three governed page reads must remain in execution lineage.",
        )
        self.assertEqual(1, len(model_gateway.recorded_requests))
        rendered_prompt = "\n".join(
            str(message.content)
            for message in model_gateway.recorded_requests[0].messages
        )
        self.assertIn("METRIC_PAGE_EVIDENCE_V2", rendered_prompt)
        self.assertIn("SAPO_PAGE_EVIDENCE_V2", rendered_prompt)
        self.assertIn("TINHTE_PAGE_EVIDENCE_V2", rendered_prompt)
        self.assertNotIn("overflow.example.test/fourth", pages.urls)


if __name__ == "__main__":
    unittest.main()
