"""Observation Package.

Provides normalized models, static HTTP backends, YouTube observation backends,
public discussion backends, search discovery managers, capability registry, and high-level observation routing.
"""

from __future__ import annotations

from tools.observation.discussion_backend import PublicDiscussionBackend
from tools.observation.http_backend import HttpStaticBackend
from tools.observation.models import (
    CaptionGenerationType,
    ContentTrustLevel,
    ContentTruthStatus,
    ContentVariant,
    DiscussionComment,
    DiscussionSearchSummary,
    DiscussionThread,
    EpistemicType,
    ExtractionConfidence,
    ExtractionQualityMetrics,
    IdentityType,
    ObservationRecord,
    RedditAuthState,
    RedditCapabilityState,
    RedditPolicyState,
    SearchResultItem,
    SearchResultSet,
    SourceCredibility,
    SourceReference,
    TranscriptionQuality,
)
from tools.observation.registry import CapabilityRegistration, CapabilityRegistry
from tools.observation.router import ObservationRouter
from tools.observation.search_backend import (
    BaseSearchBackend,
    DuckDuckGoHtmlSearchBackend,
    SearchManager,
    SearXNGSearchBackend,
    WikipediaSearchBackend,
)
from tools.observation.youtube_backend import YouTubeYtDlpBackend

__all__ = [
    "CaptionGenerationType",
    "ContentTrustLevel",
    "ContentTruthStatus",
    "ContentVariant",
    "DiscussionComment",
    "DiscussionSearchSummary",
    "DiscussionThread",
    "EpistemicType",
    "ExtractionConfidence",
    "ExtractionQualityMetrics",
    "IdentityType",
    "ObservationRecord",
    "RedditAuthState",
    "RedditCapabilityState",
    "RedditPolicyState",
    "SearchResultItem",
    "SearchResultSet",
    "SourceReference",
    "SourceCredibility",
    "TranscriptionQuality",
    "HttpStaticBackend",
    "YouTubeYtDlpBackend",
    "PublicDiscussionBackend",
    "BaseSearchBackend",
    "SearXNGSearchBackend",
    "DuckDuckGoHtmlSearchBackend",
    "WikipediaSearchBackend",
    "SearchManager",
    "CapabilityRegistration",
    "CapabilityRegistry",
    "ObservationRouter",
]
