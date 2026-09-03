"""Adversarial truthfulness regression for production web-search zero-result handling.

A search backend that returns a structurally successful observation with
`backend_used='none'` and `result_count=0` has not produced substantive web
evidence. The production ObservationSearchAdapter must not translate that into
a REAL successful ToolGateway receipt.
"""

import unittest

from tools.adapters import ObservationSearchAdapter
from tools.capabilities import CapabilityRegistry
from tools.gateway.contracts import CapabilityResult
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class _DeterministicObservationGateway:
    def __init__(self, result: CapabilityResult) -> None:
        self.result = result
        self.calls = 0

    def execute(self, request):
        self.calls += 1
        return self.result


class WebSearchZeroResultsTruthfulnessV1Tests(unittest.TestCase):
    def _execute_with_inner_result(self, inner_result: CapabilityResult):
        adapter = ObservationSearchAdapter()
        deterministic_gateway = _DeterministicObservationGateway(inner_result)
        adapter._gateway = deterministic_gateway

        gateway = ToolGateway(capability_registry=CapabilityRegistry())
        gateway.register_adapter(adapter, aliases=["search_adapter"])

        receipt = gateway.execute(
            ToolRequest(
                run_id="RUN-WEB-ZERO-RESULTS-V1",
                agent_id="intelligence",
                capability_id="web_search",
                parameters={"query": "market demand vietnam 2026"},
                business_id="BIZ-WEB-TRUTH",
                project_id="PROJ-WEB-TRUTH",
            )
        )
        return receipt, deterministic_gateway

    def test_zero_result_observation_is_not_reported_as_real_success(self) -> None:
        zero_result_payload = {
            "search_results": {
                "query": "market demand vietnam 2026",
                "executed_query": "market demand vietnam 2026",
                "backend": "none",
                "backend_provenance": "NO_RESULTS",
                "search_scope": "GENERAL_WEB",
                "result_count": 0,
                "results": [],
                "collection_limit": 10,
                "has_more": False,
            },
            "sampling_context": {
                "result_count": 0,
                "backend_used": "none",
                "backend_provenance": "NO_RESULTS",
            },
        }
        inner = CapabilityResult(
            request_id="INNER-ZERO-1",
            capability="search_web",
            status="SUCCESS",
            data=zero_result_payload,
            observation_record={
                "capability": "search_web",
                "backend_used": "none",
                "normalized_data": zero_result_payload,
            },
            backend_used="none",
        )

        receipt, deterministic_gateway = self._execute_with_inner_result(inner)

        self.assertEqual(deterministic_gateway.calls, 1)
        self.assertEqual(
            receipt.status,
            ExecutionStatus.ERROR,
            "A zero-result observation must be explicit NO_DATA, not a successful evidence receipt.",
        )
        self.assertEqual(receipt.error_class, "NO_DATA")
        self.assertNotEqual(
            receipt.execution_mode,
            ExecutionMode.REAL,
            "backend_used='none' must never be promoted to REAL execution provenance.",
        )

    def test_nonempty_real_search_result_remains_successful_real_observation(self) -> None:
        one_result_payload = {
            "search_results": {
                "query": "market demand vietnam 2026",
                "executed_query": "market demand vietnam 2026",
                "backend": "duckduckgo",
                "backend_provenance": "DUCKDUCKGO_HTML",
                "search_scope": "GENERAL_WEB",
                "result_count": 1,
                "results": [
                    {
                        "rank": 1,
                        "title": "Observed market source",
                        "url": "https://example.org/market-source",
                        "snippet": "Observed result snippet",
                        "source_domain": "example.org",
                        "result_type": "web_page",
                    }
                ],
                "collection_limit": 10,
                "has_more": False,
            },
            "sampling_context": {
                "result_count": 1,
                "backend_used": "duckduckgo",
                "backend_provenance": "DUCKDUCKGO_HTML",
            },
        }
        inner = CapabilityResult(
            request_id="INNER-REAL-1",
            capability="search_web",
            status="SUCCESS",
            data=one_result_payload,
            observation_record={
                "capability": "search_web",
                "backend_used": "duckduckgo",
                "normalized_data": one_result_payload,
            },
            backend_used="duckduckgo",
        )

        receipt, deterministic_gateway = self._execute_with_inner_result(inner)

        self.assertEqual(deterministic_gateway.calls, 1)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertIsNone(receipt.error_class)
        self.assertIsNotNone(receipt.observation_record)


if __name__ == "__main__":
    unittest.main()
