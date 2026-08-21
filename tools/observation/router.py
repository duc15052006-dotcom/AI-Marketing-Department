"""Observation Router (Phases 3C.0 / 3C.1 / 3C.2 / 3C.3 / 3D.0).

Convenience facade exposing typed methods for sensory observation capabilities.
Routes requests through ToolGateway and CapabilityRegistry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from tools.gateway.contracts import CapabilityRequest, CapabilityResult, ToolExecutionContext
from tools.gateway.gateway import ToolGateway
from tools.observation.models import SearchScope


class ObservationRouter:
    """Convenience router for agent observation capabilities."""

    def __init__(self, gateway: Optional[ToolGateway] = None) -> None:
        self.gateway = gateway or ToolGateway()

    def read_page(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        agent_id: str = "intelligence",
        timeout: float = 15.0,
    ) -> CapabilityResult:
        """Fetch and extract clean markdown/text and metadata from a public URL."""
        context = ToolExecutionContext(
            agent_id=agent_id,
            product_id=product_id,
            brand_id=brand_id,
            timeout_seconds=timeout,
        )
        req = CapabilityRequest(
            capability="read_page",
            parameters={"url": url},
            context=context,
        )
        return self.gateway.execute(req)

    def analyze_url(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        agent_id: str = "intelligence",
        timeout: float = 15.0,
    ) -> CapabilityResult:
        """Extract structured metadata (OpenGraph, Schema.org, canonical) from a public URL."""
        context = ToolExecutionContext(
            agent_id=agent_id,
            product_id=product_id,
            brand_id=brand_id,
            timeout_seconds=timeout,
        )
        req = CapabilityRequest(
            capability="analyze_url",
            parameters={"url": url},
            context=context,
        )
        return self.gateway.execute(req)

    def youtube_metadata(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        agent_id: str = "intelligence",
        timeout: float = 15.0,
    ) -> CapabilityResult:
        """Fetch video metadata and engagement metrics for a public YouTube video."""
        context = ToolExecutionContext(
            agent_id=agent_id,
            product_id=product_id,
            brand_id=brand_id,
            timeout_seconds=timeout,
        )
        req = CapabilityRequest(
            capability="youtube_metadata",
            parameters={"url": url},
            context=context,
        )
        return self.gateway.execute(req)

    def read_transcript(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        preferred_languages: Optional[List[str]] = None,
        agent_id: str = "intelligence",
        timeout: float = 15.0,
    ) -> CapabilityResult:
        """Fetch and parse transcript segments for a public YouTube video."""
        context = ToolExecutionContext(
            agent_id=agent_id,
            product_id=product_id,
            brand_id=brand_id,
            timeout_seconds=timeout,
        )
        req = CapabilityRequest(
            capability="read_transcript",
            parameters={"url": url, "preferred_languages": preferred_languages or ["vi", "en"]},
            context=context,
        )
        return self.gateway.execute(req)

    def read_forum_thread(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        max_comments: int = 50,
        agent_id: str = "intelligence",
        timeout: float = 15.0,
    ) -> CapabilityResult:
        """Fetch a public discussion thread and comments."""
        context = ToolExecutionContext(
            agent_id=agent_id,
            product_id=product_id,
            brand_id=brand_id,
            timeout_seconds=timeout,
        )
        req = CapabilityRequest(
            capability="read_forum_thread",
            parameters={"url": url, "max_comments": max_comments},
            context=context,
        )
        return self.gateway.execute(req)

    def search_public_discussions(
        self,
        query: str,
        product_id: str,
        brand_id: str,
        platform: str = "hacker_news",
        community: Optional[str] = None,
        sort: str = "relevance",
        time_range: Optional[str] = None,
        max_results: int = 20,
        agent_id: str = "intelligence",
        timeout: float = 15.0,
    ) -> CapabilityResult:
        """Search public discussions across supported platforms."""
        context = ToolExecutionContext(
            agent_id=agent_id,
            product_id=product_id,
            brand_id=brand_id,
            timeout_seconds=timeout,
        )
        req = CapabilityRequest(
            capability="search_public_discussions",
            parameters={
                "query": query,
                "platform": platform,
                "community": community,
                "sort": sort,
                "time_range": time_range,
                "max_results": max_results,
            },
            context=context,
        )
        return self.gateway.execute(req)

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
        preferred_backend: Optional[str] = None,
        search_scope: Optional[Union[SearchScope, str]] = None,
        agent_id: str = "intelligence",
        timeout: float = 15.0,
    ) -> CapabilityResult:
        """Execute provider-independent web search discovery."""
        context = ToolExecutionContext(
            agent_id=agent_id,
            product_id=product_id,
            brand_id=brand_id,
            timeout_seconds=timeout,
            allowed_domains=allowed_domains or [],
        )
        scope_val = search_scope.value if isinstance(search_scope, SearchScope) else search_scope
        req = CapabilityRequest(
            capability="search_web",
            parameters={
                "query": query,
                "language": language,
                "region": region,
                "time_range": time_range,
                "safe_search": safe_search,
                "max_results": max_results,
                "allowed_domains": allowed_domains or [],
                "blocked_domains": blocked_domains or [],
                "preferred_backend": preferred_backend,
                "search_scope": scope_val or SearchScope.GENERAL_WEB.value,
            },
            context=context,
        )
        return self.gateway.execute(req)
