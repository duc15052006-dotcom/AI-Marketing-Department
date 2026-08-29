from tools.gateway.contracts import ToolError
from tools.observation.models import SearchResultSet, SearchScope
from tools.observation.search_backend import BaseSearchBackend, SearchManager


class StubSearchBackend(BaseSearchBackend):
    def __init__(self, *, result_count=0, error=None, backend="stub"):
        self.result_count = result_count
        self.error = error
        self.backend = backend

    def search(self, query, max_results=10, language="en", region=None, time_range=None,
               safe_search=True, allowed_domains=None, blocked_domains=None,
               search_scope=SearchScope.GENERAL_WEB, timeout=15.0):
        if self.error is not None:
            return None, self.error
        return SearchResultSet(
            query=query,
            executed_query=query,
            backend=self.backend,
            backend_provenance="TEST_REAL_RESPONSE",
            search_scope=search_scope,
            result_count=self.result_count,
            results=[],
            collection_limit=max_results,
            has_more=False,
        ), None


def test_all_retryable_backend_failures_are_not_relabelled_no_results():
    err1 = ToolError(error_code="NETWORK_ERROR", message="network unavailable", backend_used="ddg", retryable=True)
    err2 = ToolError(error_code="SEARXNG_UNAVAILABLE", message="backend unavailable", backend_used="searx", retryable=True)
    mgr = SearchManager(
        duckduckgo_backend=StubSearchBackend(error=err1),
        searxng_backend=StubSearchBackend(error=err2),
    )
    obs, err = mgr.search_web("decor growth", product_id="", brand_id="")
    assert obs is None
    assert err is not None
    assert err.error_code in {"NETWORK_ERROR", "SEARXNG_UNAVAILABLE"}
    assert err.retryable is True


def test_real_empty_backend_response_may_truthfully_return_no_results():
    mgr = SearchManager(
        duckduckgo_backend=StubSearchBackend(result_count=0, backend="ddg"),
        searxng_backend=StubSearchBackend(result_count=0, backend="searx"),
    )
    obs, err = mgr.search_web("unlikely query", product_id="", brand_id="")
    assert err is None
    assert obs is not None
    search_results = obs.normalized_data["search_results"]
    assert search_results["result_count"] == 0
    assert search_results["backend_provenance"] == "NO_RESULTS"


def test_empty_result_plus_degraded_backend_is_marked_partial_degradation():
    err = ToolError(error_code="SEARXNG_UNAVAILABLE", message="backend unavailable", backend_used="searx", retryable=True)
    mgr = SearchManager(
        duckduckgo_backend=StubSearchBackend(result_count=0, backend="ddg"),
        searxng_backend=StubSearchBackend(error=err),
    )
    obs, returned_err = mgr.search_web("decor", product_id="", brand_id="")
    assert returned_err is None
    assert obs is not None
    assert obs.normalized_data["search_results"]["backend_provenance"] == "NO_RESULTS_PARTIAL_DEGRADATION"
    assert obs.normalized_data["sampling_context"]["backend_errors"]
