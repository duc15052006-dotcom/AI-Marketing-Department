"""Capability Registry Implementation.

Maintains registrations for all observational and operational capabilities,
tracks real-time backend health, and resolves cost-prioritized execution chains.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field
from tools.gateway.contracts import (
    BackendHealth,
    CapabilityState,
    CostClass,
)


class CapabilityRegistration(BaseModel):
    """Specification of an individual capability and its supported backends."""
    capability_id: str = Field(..., description="Unique capability name, e.g. 'read_page'")
    description: str
    allowed_backends: List[str] = Field(default_factory=list)
    preferred_backend: str
    cost_class: CostClass = CostClass.COST_0_LIGHT
    read_only: bool = True
    requires_network: bool = True
    requires_secret: bool = False
    permissions: List[str] = Field(default_factory=list)
    status: CapabilityState = CapabilityState.READY
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CapabilityRegistry:
    """Central registry and dispatch engine for observation capabilities."""

    def __init__(self) -> None:
        self._capabilities: Dict[str, CapabilityRegistration] = {}
        self._backends: Dict[str, BackendHealth] = {}
        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        """Seed default observation capabilities and backends."""
        # 1. Register Default Backends
        self.register_backend(
            BackendHealth(
                backend_id="http_static",
                state=CapabilityState.READY,
                cost_class=CostClass.COST_0_LIGHT,
                last_success_at=datetime.now(timezone.utc),
            )
        )
        self.register_backend(
            BackendHealth(
                backend_id="youtube_ytdlp",
                state=CapabilityState.READY,
                cost_class=CostClass.COST_1_LOCAL_PARSE,
                last_success_at=datetime.now(timezone.utc),
            )
        )
        self.register_backend(
            BackendHealth(
                backend_id="discussion_public",
                state=CapabilityState.READY,
                cost_class=CostClass.COST_0_LIGHT,
                last_success_at=datetime.now(timezone.utc),
            )
        )
        self.register_backend(
            BackendHealth(
                backend_id="search_web_engine",
                state=CapabilityState.READY,
                cost_class=CostClass.COST_0_LIGHT,
                last_success_at=datetime.now(timezone.utc),
            )
        )

        # 2. Register Web Capabilities
        self.register_capability(
            CapabilityRegistration(
                capability_id="read_page",
                description="Fetches public webpage and extracts full readable text content and headings via HTTP.",
                allowed_backends=["http_static"],
                preferred_backend="http_static",
                cost_class=CostClass.COST_0_LIGHT,
                read_only=True,
                requires_network=True,
                requires_secret=False,
                status=CapabilityState.READY,
            )
        )
        self.register_capability(
            CapabilityRegistration(
                capability_id="analyze_url",
                description="Fetches public webpage and extracts OpenGraph, JSON-LD, meta tags, and page metadata.",
                allowed_backends=["http_static"],
                preferred_backend="http_static",
                cost_class=CostClass.COST_0_LIGHT,
                read_only=True,
                requires_network=True,
                requires_secret=False,
                status=CapabilityState.READY,
            )
        )

        # 3. Register YouTube Capabilities
        self.register_capability(
            CapabilityRegistration(
                capability_id="youtube_metadata",
                description="Extracts public video metadata, view counts, upload dates, and channel information via yt-dlp.",
                allowed_backends=["youtube_ytdlp"],
                preferred_backend="youtube_ytdlp",
                cost_class=CostClass.COST_1_LOCAL_PARSE,
                read_only=True,
                requires_network=True,
                requires_secret=False,
                status=CapabilityState.READY,
            )
        )
        self.register_capability(
            CapabilityRegistration(
                capability_id="read_transcript",
                description="Fetches and parses manual subtitles or automatic captions into timed segments for a public YouTube video.",
                allowed_backends=["youtube_ytdlp"],
                preferred_backend="youtube_ytdlp",
                cost_class=CostClass.COST_1_LOCAL_PARSE,
                read_only=True,
                requires_network=True,
                requires_secret=False,
                status=CapabilityState.READY,
            )
        )

        # 4. Register Public Discussion Capabilities (Phase 3C.2)
        self.register_capability(
            CapabilityRegistration(
                capability_id="read_forum_thread",
                description="Fetches a public discussion thread (Reddit, Hacker News, web forums) and parses title, body, and comments.",
                allowed_backends=["discussion_public"],
                preferred_backend="discussion_public",
                cost_class=CostClass.COST_0_LIGHT,
                read_only=True,
                requires_network=True,
                requires_secret=False,
                status=CapabilityState.READY,
            )
        )
        self.register_capability(
            CapabilityRegistration(
                capability_id="search_public_discussions",
                description="Searches public discussion platforms with explicit sampling metadata, bounds, and polite rate controls.",
                allowed_backends=["discussion_public"],
                preferred_backend="discussion_public",
                cost_class=CostClass.COST_0_LIGHT,
                read_only=True,
                requires_network=True,
                requires_secret=False,
                status=CapabilityState.READY,
            )
        )

        # 5. Register Web Search Capability (Phase 3C.3)
        self.register_capability(
            CapabilityRegistration(
                capability_id="search_web",
                description="Discovers public web search results across provider-independent search backends with bounds and domain filtering.",
                allowed_backends=["search_web_engine"],
                preferred_backend="search_web_engine",
                cost_class=CostClass.COST_0_LIGHT,
                read_only=True,
                requires_network=True,
                requires_secret=False,
                status=CapabilityState.READY,
            )
        )

    def register_capability(self, reg: CapabilityRegistration) -> None:
        self._capabilities[reg.capability_id] = reg

    def register_backend(self, health: BackendHealth) -> None:
        self._backends[health.backend_id] = health

    def get_capability(self, capability_id: str) -> Optional[CapabilityRegistration]:
        return self._capabilities.get(capability_id)

    def get_backend_health(self, backend_id: str) -> Optional[BackendHealth]:
        return self._backends.get(backend_id)

    def list_capabilities(self) -> List[CapabilityRegistration]:
        return list(self._capabilities.values())

    def get_execution_chain(self, capability_id: str) -> List[str]:
        """Return prioritized list of healthy backend IDs for a capability."""
        if capability_id not in self._capabilities:
            raise KeyError(f"Capability '{capability_id}' is not registered.")

        reg = self._capabilities[capability_id]
        if reg.status not in (CapabilityState.READY, CapabilityState.DEGRADED):
            return []

        candidates = [reg.preferred_backend] + [
            b for b in reg.allowed_backends if b != reg.preferred_backend
        ]

        healthy = []
        for bid in candidates:
            bhealth = self._backends.get(bid)
            if bhealth and bhealth.state in (CapabilityState.READY, CapabilityState.DEGRADED):
                healthy.append(bid)

        return healthy
