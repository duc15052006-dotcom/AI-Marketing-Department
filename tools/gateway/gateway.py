"""Tool Gateway Core Implementation.

Executes capability requests against registered backends, enforces security gates,
manages backend timeouts and retries, and normalizes output results.
Contains zero marketing reasoning, zero prompt templates, and exposes zero secrets.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from tools.gateway.contracts import (
    BackendHealth,
    CapabilityRequest,
    CapabilityResult,
    CapabilityState,
    CostClass,
    ToolError,
)

if TYPE_CHECKING:
    from tools.observation.discussion_backend import PublicDiscussionBackend
    from tools.observation.http_backend import HttpStaticBackend
    from tools.observation.registry import CapabilityRegistry
    from tools.observation.search_backend import SearchManager
    from tools.observation.youtube_backend import YouTubeYtDlpBackend


class ToolGateway:
    """Central gateway for executing sensory and operational tool capabilities."""

    def __init__(
        self,
        registry: Optional[Any] = None,
        http_backend: Optional[Any] = None,
        youtube_backend: Optional[Any] = None,
        discussion_backend: Optional[Any] = None,
        search_backend: Optional[Any] = None,
    ) -> None:
        if registry is None:
            from tools.observation.registry import CapabilityRegistry
            self.registry = CapabilityRegistry()
        else:
            self.registry = registry

        if http_backend is None:
            from tools.observation.http_backend import HttpStaticBackend
            self.http_backend = HttpStaticBackend()
        else:
            self.http_backend = http_backend

        if youtube_backend is None:
            from tools.observation.youtube_backend import YouTubeYtDlpBackend
            self.youtube_backend = YouTubeYtDlpBackend()
        else:
            self.youtube_backend = youtube_backend

        if discussion_backend is None:
            from tools.observation.discussion_backend import PublicDiscussionBackend
            self.discussion_backend = PublicDiscussionBackend()
        else:
            self.discussion_backend = discussion_backend

        if search_backend is None:
            from tools.observation.search_backend import SearchManager
            self.search_backend = SearchManager()
        else:
            self.search_backend = search_backend

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        """Execute a capability request with security validation and error normalization."""
        start_time = time.perf_counter()

        # 1. Capability Discovery & Permission Check
        cap_reg = self.registry.get_capability(request.capability)
        if not cap_reg:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                error=ToolError(
                    error_code="CAPABILITY_NOT_FOUND",
                    message=f"Capability '{request.capability}' is not recognized by the Tool Gateway.",
                ),
                latency_ms=latency_ms,
            )

        if cap_reg.status == CapabilityState.NO_PERMISSION:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="BLOCKED",
                error=ToolError(
                    error_code="NO_PERMISSION",
                    message=f"Execution of capability '{request.capability}' is blocked by workspace permission policy.",
                ),
                latency_ms=latency_ms,
            )

        if cap_reg.status == CapabilityState.DISABLED:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                error=ToolError(
                    error_code="CAPABILITY_DISABLED",
                    message=f"Capability '{request.capability}' is administratively disabled.",
                ),
                latency_ms=latency_ms,
            )

        # 2. Get Execution Chain
        execution_chain = self.registry.get_execution_chain(request.capability)
        if not execution_chain:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                error=ToolError(
                    error_code="NO_HEALTHY_BACKEND",
                    message=f"No healthy backends currently available for capability '{request.capability}'.",
                ),
                latency_ms=latency_ms,
            )

        # 3. Dispatch to Backend
        last_error: Optional[ToolError] = None
        last_backend_id: str = execution_chain[0]
        for backend_id in execution_chain:
            last_backend_id = backend_id
            if backend_id == "http_static":
                result = self._execute_http_static(request, start_time)
            elif backend_id == "youtube_ytdlp":
                result = self._execute_youtube_ytdlp(request, start_time)
            elif backend_id == "discussion_public":
                result = self._execute_discussion_public(request, start_time)
            elif backend_id == "search_web_engine":
                result = self._execute_search_web(request, start_time)
            else:
                result = CapabilityResult(
                    request_id=request.request_id,
                    capability=request.capability,
                    status="ERROR",
                    backend_used=backend_id,
                    error=ToolError(error_code="UNKNOWN_BACKEND", message=f"Backend '{backend_id}' not implemented."),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            if result.status == "SUCCESS":
                self._record_backend_success(backend_id, result.latency_ms)
                return result
            else:
                self._record_backend_failure(backend_id, result.error)
                last_error = result.error

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return CapabilityResult(
            request_id=request.request_id,
            capability=request.capability,
            status="ERROR",
            backend_used=last_backend_id,
            error=last_error or ToolError(error_code="EXECUTION_FAILED", message="All backends failed."),
            latency_ms=latency_ms,
        )

    def _execute_http_static(
        self, request: CapabilityRequest, start_time: float
    ) -> CapabilityResult:
        """Execute read_page or analyze_url on the HttpStaticBackend."""
        url = request.parameters.get("url")
        if not url:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                backend_used="http_static",
                error=ToolError(
                    error_code="MISSING_PARAMETER",
                    message="Missing required parameter 'url' for web observation.",
                    backend_used="http_static",
                ),
                latency_ms=latency_ms,
            )

        timeout = request.context.timeout_seconds
        allowed_domains = request.context.allowed_domains

        if request.capability == "read_page":
            obs, err = self.http_backend.read_page(
                url=url,
                product_id=request.context.product_id,
                brand_id=request.context.brand_id,
                timeout=timeout,
                allowed_domains=allowed_domains,
            )
        elif request.capability == "analyze_url":
            obs, err = self.http_backend.analyze_url(
                url=url,
                product_id=request.context.product_id,
                brand_id=request.context.brand_id,
                timeout=timeout,
                allowed_domains=allowed_domains,
            )
        else:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                backend_used="http_static",
                error=ToolError(
                    error_code="UNSUPPORTED_HTTP_CAPABILITY",
                    message=f"Capability '{request.capability}' not supported on http_static backend.",
                ),
                latency_ms=latency_ms,
            )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if err:
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                error=err,
                backend_used="http_static",
                cost_class=CostClass.COST_0_LIGHT,
                latency_ms=latency_ms,
            )

        return CapabilityResult(
            request_id=request.request_id,
            capability=request.capability,
            status="SUCCESS",
            data=obs.normalized_data if obs else None,
            observation_record=obs.model_dump() if obs else None,
            backend_used="http_static",
            cost_class=CostClass.COST_0_LIGHT,
            latency_ms=latency_ms,
        )

    def _execute_youtube_ytdlp(
        self, request: CapabilityRequest, start_time: float
    ) -> CapabilityResult:
        """Execute youtube_metadata or read_transcript on YouTubeYtDlpBackend."""
        url = request.parameters.get("url")
        if not url:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                backend_used="youtube_ytdlp",
                error=ToolError(
                    error_code="MISSING_PARAMETER",
                    message="Missing required parameter 'url' for YouTube observation.",
                    backend_used="youtube_ytdlp",
                ),
                latency_ms=latency_ms,
            )

        timeout = request.context.timeout_seconds

        if request.capability == "youtube_metadata":
            obs, err = self.youtube_backend.youtube_metadata(
                url=url,
                product_id=request.context.product_id,
                brand_id=request.context.brand_id,
                timeout=timeout,
            )
        elif request.capability == "read_transcript":
            preferred_languages = request.parameters.get("preferred_languages")
            obs, err = self.youtube_backend.read_transcript(
                url=url,
                product_id=request.context.product_id,
                brand_id=request.context.brand_id,
                preferred_languages=preferred_languages,
                timeout=timeout,
            )
        else:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                backend_used="youtube_ytdlp",
                error=ToolError(
                    error_code="UNSUPPORTED_YOUTUBE_CAPABILITY",
                    message=f"Capability '{request.capability}' not supported on youtube_ytdlp backend.",
                ),
                latency_ms=latency_ms,
            )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if err:
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                error=err,
                backend_used="youtube_ytdlp",
                cost_class=CostClass.COST_1_LOCAL_PARSE,
                latency_ms=latency_ms,
            )

        return CapabilityResult(
            request_id=request.request_id,
            capability=request.capability,
            status="SUCCESS",
            data=obs.normalized_data if obs else None,
            observation_record=obs.model_dump() if obs else None,
            backend_used="youtube_ytdlp",
            cost_class=CostClass.COST_1_LOCAL_PARSE,
            latency_ms=latency_ms,
        )

    def _execute_discussion_public(
        self, request: CapabilityRequest, start_time: float
    ) -> CapabilityResult:
        """Execute read_forum_thread or search_public_discussions on PublicDiscussionBackend."""
        timeout = request.context.timeout_seconds

        if request.capability == "read_forum_thread":
            url = request.parameters.get("url")
            if not url:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                return CapabilityResult(
                    request_id=request.request_id,
                    capability=request.capability,
                    status="ERROR",
                    backend_used="discussion_public",
                    error=ToolError(
                        error_code="MISSING_PARAMETER",
                        message="Missing required parameter 'url' for discussion thread observation.",
                        backend_used="discussion_public",
                    ),
                    latency_ms=latency_ms,
                )
            max_comments = request.parameters.get("max_comments", 50)
            obs, err = self.discussion_backend.read_forum_thread(
                url=url,
                product_id=request.context.product_id,
                brand_id=request.context.brand_id,
                max_comments=max_comments,
                timeout=timeout,
            )
        elif request.capability == "search_public_discussions":
            query = request.parameters.get("query")
            if not query:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                return CapabilityResult(
                    request_id=request.request_id,
                    capability=request.capability,
                    status="ERROR",
                    backend_used="discussion_public",
                    error=ToolError(
                        error_code="MISSING_PARAMETER",
                        message="Missing required parameter 'query' for public discussion search.",
                        backend_used="discussion_public",
                    ),
                    latency_ms=latency_ms,
                )
            platform = request.parameters.get("platform", "hacker_news")
            community = request.parameters.get("community")
            sort = request.parameters.get("sort", "relevance")
            time_range = request.parameters.get("time_range")
            max_results = request.parameters.get("max_results", 20)

            obs, err = self.discussion_backend.search_public_discussions(
                query=query,
                product_id=request.context.product_id,
                brand_id=request.context.brand_id,
                platform=platform,
                community=community,
                sort=sort,
                time_range=time_range,
                max_results=max_results,
                timeout=timeout,
            )
        else:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                backend_used="discussion_public",
                error=ToolError(
                    error_code="UNSUPPORTED_DISCUSSION_CAPABILITY",
                    message=f"Capability '{request.capability}' not supported on discussion_public backend.",
                ),
                latency_ms=latency_ms,
            )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if err:
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                error=err,
                backend_used="discussion_public",
                cost_class=CostClass.COST_0_LIGHT,
                latency_ms=latency_ms,
            )

        return CapabilityResult(
            request_id=request.request_id,
            capability=request.capability,
            status="SUCCESS",
            data=obs.normalized_data if obs else None,
            observation_record=obs.model_dump() if obs else None,
            backend_used="discussion_public",
            cost_class=CostClass.COST_0_LIGHT,
            latency_ms=latency_ms,
        )

    def _execute_search_web(
        self, request: CapabilityRequest, start_time: float
    ) -> CapabilityResult:
        """Execute search_web on SearchManager."""
        query = request.parameters.get("query")
        if not query:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                backend_used="search_web_engine",
                error=ToolError(
                    error_code="MISSING_PARAMETER",
                    message="Missing required parameter 'query' for web search.",
                    backend_used="search_web_engine",
                ),
                latency_ms=latency_ms,
            )

        timeout = request.context.timeout_seconds
        language = request.parameters.get("language", "en")
        region = request.parameters.get("region")
        time_range = request.parameters.get("time_range")
        safe_search = request.parameters.get("safe_search", True)
        max_results = request.parameters.get("max_results", 10)
        allowed_domains = request.parameters.get("allowed_domains") or request.context.allowed_domains
        blocked_domains = request.parameters.get("blocked_domains")
        preferred_backend = request.parameters.get("preferred_backend")

        obs, err = self.search_backend.search_web(
            query=query,
            product_id=request.context.product_id,
            brand_id=request.context.brand_id,
            language=language,
            region=region,
            time_range=time_range,
            safe_search=safe_search,
            max_results=max_results,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            preferred_backend=preferred_backend,
            timeout=timeout,
            run_id=request.context.run_id,
            business_id=request.context.business_id,
            project_id=request.context.project_id,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if err:
            return CapabilityResult(
                request_id=request.request_id,
                capability=request.capability,
                status="ERROR",
                error=err,
                backend_used="search_web_engine",
                cost_class=CostClass.COST_0_LIGHT,
                latency_ms=latency_ms,
            )

        return CapabilityResult(
            request_id=request.request_id,
            capability=request.capability,
            status="SUCCESS",
            data=obs.normalized_data if obs else None,
            observation_record=obs.model_dump() if obs else None,
            backend_used=obs.backend_used if obs else "search_web_engine",
            cost_class=CostClass.COST_0_LIGHT,
            latency_ms=latency_ms,
        )

    def _record_backend_success(self, backend_id: str, latency_ms: float) -> None:
        bhealth = self.registry.get_backend_health(backend_id)
        if bhealth:
            bhealth.consecutive_failures = 0
            bhealth.last_success_at = datetime.now(timezone.utc)
            bhealth.state = CapabilityState.READY
            bhealth.avg_latency_ms = (bhealth.avg_latency_ms * 0.8) + (latency_ms * 0.2)

    def _record_backend_failure(self, backend_id: str, error: Optional[ToolError]) -> None:
        bhealth = self.registry.get_backend_health(backend_id)
        if bhealth:
            bhealth.consecutive_failures += 1
            bhealth.last_error_at = datetime.now(timezone.utc)
            bhealth.last_error_message = error.message if error else "Unknown error"
            if bhealth.consecutive_failures >= 3:
                bhealth.state = CapabilityState.DEGRADED
