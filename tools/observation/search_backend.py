"""Provider-Independent Web Discovery & Search Backend (Phase 3C.3 / 3D.0 Hardened).

Provides structured web discovery capabilities (search_web) behind a stable,
provider-agnostic interface. Supports SearXNG meta-search, Wikipedia OpenSearch API,
and DuckDuckGo HTML discovery with domain filtering, strict result bounds, URL deduplication,
search scopes, maturity tracking, and untrusted snippet classification.
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import bs4
import httpx
from tools.gateway.contracts import CostClass, ToolError
from tools.gateway.security import SecurityValidator, SecurityValidationError
from tools.observation.models import (
    BackendMaturityState,
    ContentTrustLevel,
    ContentTruthStatus,
    EpistemicType,
    ExtractionConfidence,
    ObservationRecord,
    SearchResultItem,
    SearchResultSet,
    SearchScope,
    SearXNGAdapterState,
    SourceCredibility,
)


class BaseSearchBackend(ABC):
    """Abstract interface for all sensory search engine adapters."""

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 10,
        language: str = "en",
        region: Optional[str] = None,
        time_range: Optional[str] = None,
        safe_search: bool = True,
        allowed_domains: Optional[List[str]] = None,
        blocked_domains: Optional[List[str]] = None,
        search_scope: SearchScope = SearchScope.GENERAL_WEB,
        timeout: float = 15.0,
    ) -> Tuple[Optional[SearchResultSet], Optional[ToolError]]:
        """Execute search discovery and return normalized SearchResultSet."""
        pass


class SearXNGSearchBackend(BaseSearchBackend):
    """SearXNG meta-search engine backend (Supports self-hosted and managed instances)."""

    BACKEND_ID = "search_searxng"
    COST_CLASS = CostClass.COST_0_LIGHT

    def __init__(self, base_url: Optional[str] = None, default_timeout: float = 15.0) -> None:
        if base_url is None:
            from config.authority import get_runtime_config
            base_url = get_runtime_config().searxng_base_url or "http://127.0.0.1:8080"
        self.base_url = base_url.rstrip("/")
        self.default_timeout = default_timeout
        self.adapter_state = SearXNGAdapterState.IMPLEMENTED
        self.provenance = "SELF_HOSTED_META_SEARCH" if "127.0.0.1" in self.base_url or "localhost" in self.base_url else "THIRD_PARTY_META_SEARCH"

    def get_runtime_state(self) -> SearXNGAdapterState:
        """Evaluate SearXNG runtime connection state."""
        if not self.base_url:
            return SearXNGAdapterState.NOT_CONFIGURED
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{self.base_url}/healthz")
                if resp.status_code == 200:
                    return SearXNGAdapterState.READY
                return SearXNGAdapterState.DEGRADED
        except Exception:
            return SearXNGAdapterState.UNAVAILABLE

    def search(
        self,
        query: str,
        max_results: int = 10,
        language: str = "en",
        region: Optional[str] = None,
        time_range: Optional[str] = None,
        safe_search: bool = True,
        allowed_domains: Optional[List[str]] = None,
        blocked_domains: Optional[List[str]] = None,
        search_scope: SearchScope = SearchScope.GENERAL_WEB,
        timeout: float = 15.0,
    ) -> Tuple[Optional[SearchResultSet], Optional[ToolError]]:
        """Execute JSON search on SearXNG instance."""
        search_endpoint = f"{self.base_url}/search"
        params: Dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": "1" if safe_search else "0",
        }
        if time_range:
            params["time_range"] = time_range

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(search_endpoint, params=params)
                if resp.status_code == 429:
                    return None, ToolError(
                        error_code="RATE_LIMITED",
                        message="SearXNG instance returned HTTP 429 Rate Limited.",
                        backend_used=self.BACKEND_ID,
                        retryable=True,
                    )
                if resp.status_code != 200:
                    return None, ToolError(
                        error_code=f"HTTP_{resp.status_code}",
                        message=f"SearXNG returned HTTP {resp.status_code}",
                        backend_used=self.BACKEND_ID,
                    )
                data = resp.json()
        except Exception as e:
            return None, ToolError(
                error_code="SEARXNG_UNAVAILABLE",
                message=f"Could not connect to SearXNG at {self.base_url}: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )

        raw_results = data.get("results", [])
        items: List[SearchResultItem] = []
        seen_urls: Set[str] = set()

        for idx, r in enumerate(raw_results, start=1):
            if len(items) >= max_results:
                break
            raw_url = r.get("url")
            if not raw_url or raw_url in seen_urls:
                continue

            parsed_url = urllib.parse.urlparse(raw_url)
            domain = (parsed_url.hostname or "").lower()

            if allowed_domains and not any(domain == ad.lower() or domain.endswith("." + ad.lower()) for ad in allowed_domains):
                continue
            if blocked_domains and any(domain == bd.lower() or domain.endswith("." + bd.lower()) for bd in blocked_domains):
                continue

            seen_urls.add(raw_url)
            items.append(
                SearchResultItem(
                    rank=idx,
                    title=r.get("title") or "Untitled",
                    url=raw_url,
                    display_url=parsed_url.netloc + parsed_url.path,
                    snippet=r.get("content") or "",
                    published_at=None,
                    source_domain=domain,
                    result_type="web_page",
                )
            )

        result_set = SearchResultSet(
            query=query,
            executed_query=query,
            backend=self.BACKEND_ID,
            backend_provenance=self.provenance,
            search_scope=search_scope,
            result_count=len(items),
            results=items,
            collection_limit=max_results,
            has_more=len(raw_results) > max_results,
        )

        return result_set, None


class WikipediaSearchBackend(BaseSearchBackend):
    """Official Wikipedia OpenSearch API Backend for encyclopedic reference."""

    BACKEND_ID = "search_wikipedia_opensearch"
    COST_CLASS = CostClass.COST_0_LIGHT

    def __init__(self, default_timeout: float = 15.0) -> None:
        self.default_timeout = default_timeout
        self.provenance = "FIRST_PARTY_OFFICIAL_API"
        self.maturity_state = BackendMaturityState.READY
        self.supported_scope = SearchScope.ENCYCLOPEDIC_REFERENCE

    def search(
        self,
        query: str,
        max_results: int = 10,
        language: str = "en",
        region: Optional[str] = None,
        time_range: Optional[str] = None,
        safe_search: bool = True,
        allowed_domains: Optional[List[str]] = None,
        blocked_domains: Optional[List[str]] = None,
        search_scope: SearchScope = SearchScope.ENCYCLOPEDIC_REFERENCE,
        timeout: float = 15.0,
    ) -> Tuple[Optional[SearchResultSet], Optional[ToolError]]:
        """Query Wikipedia OpenSearch API."""
        endpoint = f"https://{language}.wikipedia.org/w/api.php"
        params = {
            "action": "opensearch",
            "search": query,
            "limit": max_results,
            "namespace": 0,
            "format": "json",
        }
        headers = {"User-Agent": "AntigravityMarketingObservationBot/1.0"}

        try:
            with httpx.Client(timeout=timeout, headers=headers) as client:
                resp = client.get(endpoint, params=params)
                if resp.status_code != 200:
                    return None, ToolError(
                        error_code=f"HTTP_{resp.status_code}",
                        message=f"Wikipedia API returned HTTP {resp.status_code}",
                        backend_used=self.BACKEND_ID,
                    )
                data = resp.json()
        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to query Wikipedia OpenSearch API: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )

        if not isinstance(data, list) or len(data) < 4:
            return None, ToolError(
                error_code="INVALID_RESPONSE",
                message="Wikipedia returned malformed OpenSearch array.",
                backend_used=self.BACKEND_ID,
            )

        titles = data[1]
        snippets = data[2]
        urls = data[3]

        items: List[SearchResultItem] = []
        for idx in range(len(titles)):
            if len(items) >= max_results:
                break
            raw_url = urls[idx] if idx < len(urls) else ""
            if not raw_url:
                continue

            parsed_url = urllib.parse.urlparse(raw_url)
            domain = (parsed_url.hostname or "").lower()

            items.append(
                SearchResultItem(
                    rank=idx + 1,
                    title=titles[idx] if idx < len(titles) else "Untitled",
                    url=raw_url,
                    display_url=parsed_url.netloc + parsed_url.path,
                    snippet=snippets[idx] if idx < len(snippets) else "",
                    source_domain=domain,
                    result_type="encyclopedic_article",
                )
            )

        result_set = SearchResultSet(
            query=query,
            executed_query=query,
            backend=self.BACKEND_ID,
            backend_provenance=self.provenance,
            search_scope=SearchScope.ENCYCLOPEDIC_REFERENCE,
            result_count=len(items),
            results=items,
            collection_limit=max_results,
            has_more=False,
        )

        return result_set, None


class DuckDuckGoHtmlSearchBackend(BaseSearchBackend):
    """DuckDuckGo HTML Search Interface (Unofficial Experimental Discovery)."""

    BACKEND_ID = "search_duckduckgo_html"
    COST_CLASS = CostClass.COST_0_LIGHT

    def __init__(self, default_timeout: float = 15.0) -> None:
        self.default_timeout = default_timeout
        self.provenance = "UNOFFICIAL_HTML_PARSE"
        self.maturity_state = BackendMaturityState.EXPERIMENTAL
        self.last_request_time: float = 0.0
        self.min_request_interval_sec: float = 1.0

    def _rate_limit_pause(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval_sec:
            time.sleep(self.min_request_interval_sec - elapsed)
        self.last_request_time = time.time()

    def search(
        self,
        query: str,
        max_results: int = 10,
        language: str = "en",
        region: Optional[str] = None,
        time_range: Optional[str] = None,
        safe_search: bool = True,
        allowed_domains: Optional[List[str]] = None,
        blocked_domains: Optional[List[str]] = None,
        search_scope: SearchScope = SearchScope.GENERAL_WEB,
        timeout: float = 15.0,
    ) -> Tuple[Optional[SearchResultSet], Optional[ToolError]]:
        """Fetch search results via DuckDuckGo HTML endpoint with polite rate control."""
        self._rate_limit_pause()
        endpoint = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        data = {"q": query, "b": ""}

        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                resp = client.post(endpoint, data=data)
                if resp.status_code == 429:
                    return None, ToolError(
                        error_code="RATE_LIMITED",
                        message="DuckDuckGo HTML search rate limited.",
                        backend_used=self.BACKEND_ID,
                        retryable=True,
                    )
                if resp.status_code != 200:
                    return None, ToolError(
                        error_code=f"HTTP_{resp.status_code}",
                        message=f"DuckDuckGo returned HTTP {resp.status_code}",
                        backend_used=self.BACKEND_ID,
                    )
                html_text = resp.text
        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to fetch DuckDuckGo search: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )

        soup = bs4.BeautifulSoup(html_text, "html.parser")
        result_divs = soup.find_all("div", class_=re.compile(r"result\s+results_links"))

        items: List[SearchResultItem] = []
        seen_urls: Set[str] = set()

        for idx, div in enumerate(result_divs, start=1):
            if len(items) >= max_results:
                break

            title_tag = div.find("a", class_="result__a")
            snippet_tag = div.find("a", class_="result__snippet")

            if not title_tag:
                continue

            raw_href = title_tag.get("href", "")
            target_url = raw_href
            if "/l/?uddg=" in raw_href:
                parsed_wrapper = urllib.parse.urlparse(raw_href)
                params_wrapper = urllib.parse.parse_qs(parsed_wrapper.query)
                if "uddg" in params_wrapper and params_wrapper["uddg"]:
                    target_url = params_wrapper["uddg"][0]

            if not target_url.startswith("http") or target_url in seen_urls:
                continue

            parsed_url = urllib.parse.urlparse(target_url)
            domain = (parsed_url.hostname or "").lower()

            if allowed_domains and not any(domain == ad.lower() or domain.endswith("." + ad.lower()) for ad in allowed_domains):
                continue
            if blocked_domains and any(domain == bd.lower() or domain.endswith("." + bd.lower()) for bd in blocked_domains):
                continue

            seen_urls.add(target_url)
            title_text = title_tag.get_text(strip=True)
            snippet_text = snippet_tag.get_text(strip=True) if snippet_tag else ""

            items.append(
                SearchResultItem(
                    rank=len(items) + 1,
                    title=title_text,
                    url=target_url,
                    display_url=parsed_url.netloc + parsed_url.path,
                    snippet=snippet_text,
                    source_domain=domain,
                    result_type="web_page",
                )
            )

        result_set = SearchResultSet(
            query=query,
            executed_query=query,
            backend=self.BACKEND_ID,
            backend_provenance=self.provenance,
            search_scope=SearchScope.GENERAL_WEB,
            result_count=len(items),
            results=items,
            collection_limit=max_results,
            has_more=len(result_divs) > max_results,
        )

        return result_set, None


class SearchManager:
    """Central search discovery router orchestrating primary backends and fallback chains."""

    BACKEND_ID = "search_web_engine"
    COST_CLASS = CostClass.COST_0_LIGHT

    DEFAULT_MAX_RESULTS = 10
    ABSOLUTE_MAX_RESULTS = 50

    def __init__(
        self,
        searxng_backend: Optional[SearXNGSearchBackend] = None,
        duckduckgo_backend: Optional[DuckDuckGoHtmlSearchBackend] = None,
        wikipedia_backend: Optional[WikipediaSearchBackend] = None,
        default_timeout: float = 15.0,
    ) -> None:
        self.searxng = searxng_backend or SearXNGSearchBackend(default_timeout=default_timeout)
        self.ddg = duckduckgo_backend or DuckDuckGoHtmlSearchBackend(default_timeout=default_timeout)
        self.wikipedia = wikipedia_backend or WikipediaSearchBackend(default_timeout=default_timeout)
        self.default_timeout = default_timeout

    def search_web(
        self,
        query: str,
        product_id: str,
        brand_id: str,
        language: str = "en",
        region: Optional[str] = None,
        time_range: Optional[str] = None,
        safe_search: bool = True,
        max_results: int = 10,
        allowed_domains: Optional[List[str]] = None,
        blocked_domains: Optional[List[str]] = None,
        search_scope: SearchScope = SearchScope.GENERAL_WEB,
        preferred_backend: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[Optional[ObservationRecord], Optional[ToolError]]:
        """Execute provider-independent web search discovery and return typed ObservationRecord."""
        t0 = time.perf_counter()
        req_timeout = timeout or self.default_timeout

        if not query or not query.strip():
            return None, ToolError(
                error_code="EMPTY_QUERY",
                message="Search query must be a non-empty string.",
                backend_used=self.BACKEND_ID,
            )

        cleaned_query = query.strip()
        bounded_max_results = min(max(1, max_results), self.ABSOLUTE_MAX_RESULTS)

        # 1. Resolve Scope-Aware Execution Chain
        backends: List[Tuple[str, BaseSearchBackend, SearchScope]] = []

        if search_scope == SearchScope.ENCYCLOPEDIC_REFERENCE or preferred_backend == "wikipedia":
            backends = [
                ("wikipedia", self.wikipedia, SearchScope.ENCYCLOPEDIC_REFERENCE),
                ("duckduckgo", self.ddg, SearchScope.GENERAL_WEB),
                ("searxng", self.searxng, SearchScope.GENERAL_WEB),
            ]
        elif preferred_backend == "searxng":
            backends = [
                ("searxng", self.searxng, SearchScope.GENERAL_WEB),
                ("duckduckgo", self.ddg, SearchScope.GENERAL_WEB),
            ]
        else:
            # Default GENERAL_WEB search prioritizes general web engines
            backends = [
                ("duckduckgo", self.ddg, SearchScope.GENERAL_WEB),
                ("searxng", self.searxng, SearchScope.GENERAL_WEB),
            ]

        last_error: Optional[ToolError] = None
        result_set: Optional[SearchResultSet] = None
        used_backend_name: str = "none"

        for b_name, backend, effective_scope in backends:
            res_set, err = backend.search(
                query=cleaned_query,
                max_results=bounded_max_results,
                language=language,
                region=region,
                time_range=time_range,
                safe_search=safe_search,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
                search_scope=effective_scope,
                timeout=req_timeout,
            )
            if res_set and not err and res_set.result_count > 0:
                result_set = res_set
                used_backend_name = b_name
                break
            if err:
                last_error = err

        if not result_set:
            if last_error and not last_error.retryable:
                return None, last_error
            result_set = SearchResultSet(
                query=cleaned_query,
                executed_query=cleaned_query,
                backend="none",
                backend_provenance="NO_RESULTS",
                search_scope=search_scope,
                result_count=0,
                results=[],
                collection_limit=bounded_max_results,
            )

        t_end = time.perf_counter()
        total_latency_ms = (t_end - t0) * 1000.0

        ext_conf = ExtractionConfidence.HIGH if result_set.result_count > 0 else ExtractionConfidence.MEDIUM

        normalized_payload = {
            "search_results": result_set.model_dump(),
            "sampling_context": {
                "original_query": query,
                "executed_query": cleaned_query,
                "search_scope": search_scope.value if isinstance(search_scope, SearchScope) else search_scope,
                "language": language,
                "region": region,
                "time_range": time_range,
                "safe_search": safe_search,
                "collection_limit": bounded_max_results,
                "result_count": result_set.result_count,
                "backend_used": result_set.backend,
                "backend_provenance": result_set.backend_provenance,
                "allowed_domains": allowed_domains or [],
                "blocked_domains": blocked_domains or [],
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
            "telemetry": {
                "total_latency_ms": round(total_latency_ms, 2),
            },
        }

        obs = ObservationRecord(
            capability="search_web",
            source_platform="search_engine",
            source_type="search_discovery",
            source_url_or_id=f"search://{result_set.backend}?q={urllib.parse.quote(cleaned_query)}",
            backend_used=result_set.backend,
            collection_method="SEARCH_ENGINE_DISCOVERY",
            normalized_data=normalized_payload,
            evidence_class=EpistemicType.OBSERVATION,
            extraction_confidence=ext_conf,
            source_credibility=SourceCredibility.UNKNOWN,
            content_truth_status=ContentTruthStatus.UNVERIFIED,
            limitations=[
                f"Web discovery via {result_set.backend} (Provenance: {result_set.backend_provenance}, Scope: {search_scope})",
                "Search rankings do not indicate source credibility, truth, or real-world consumer demand",
                "Search snippets may be truncated, stale, or contextually incomplete; substantive evidence requires separate read_page()",
                "Discovered URLs are not automatically fetched by search_web",
            ],
            product_id=product_id,
            brand_id=brand_id,
            content_trust=ContentTrustLevel.UNTRUSTED_EXTERNAL,
        )

        return obs, None
