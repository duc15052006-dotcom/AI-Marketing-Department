"""Observation Domain Models & Normalized Contracts.

Defines the normalized ObservationRecord schema, separated semantic confidence tiers,
discussion thread/comment models, search result contracts, privacy classifications, and strict epistemic boundaries.
Retrieved external text is marked with CONTENT_TRUST = UNTRUSTED_EXTERNAL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field
from schemas.protocol import EpistemicType


class ContentTrustLevel(str, Enum):
    """Trust classification for data ingested from outside the secure workspace."""
    UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"
    VERIFIED_WORKSPACE = "VERIFIED_WORKSPACE"
    SYSTEM_DEFINED = "SYSTEM_DEFINED"


class ExtractionConfidence(str, Enum):
    """Reflects mechanical extraction quality (completeness of text, headings, metadata)."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class SourceCredibility(str, Enum):
    """Reflects evaluated authority and independence of the publishing entity."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ContentTruthStatus(str, Enum):
    """Reflects whether factual assertions within observed text have been independently verified."""
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTED = "CONFLICTED"


class CaptionGenerationType(str, Enum):
    """Origin method of subtitle/caption track."""
    MANUAL = "MANUAL"
    AUTOMATIC = "AUTOMATIC"


class TranscriptionQuality(str, Enum):
    """Assessed linguistic accuracy of transcript (default UNKNOWN unless independently verified)."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class IdentityType(str, Enum):
    """Classification of observed user identity."""
    PSEUDONYMOUS_PLATFORM_IDENTIFIER = "PSEUDONYMOUS_PLATFORM_IDENTIFIER"
    ANONYMIZED_HASH = "ANONYMIZED_HASH"
    REAL_WORLD_EXPLICIT_NAME = "REAL_WORLD_EXPLICIT_NAME"
    UNKNOWN = "UNKNOWN"


class ContentVariant(str, Enum):
    """Indicates whether observed external text has undergone sanitization/redaction."""
    ORIGINAL = "ORIGINAL"
    SANITIZED = "SANITIZED"


class RedditAuthState(str, Enum):
    CONFIGURED = "CONFIGURED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class RedditPolicyState(str, Enum):
    APPROVED = "APPROVED"
    COMMERCIAL_APPROVAL_REQUIRED = "COMMERCIAL_APPROVAL_REQUIRED"
    UNVERIFIED = "UNVERIFIED"
    RESTRICTED = "RESTRICTED"


class RedditCapabilityState(str, Enum):
    READY = "READY"
    BLOCKED_AUTH = "BLOCKED_AUTH"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    BLOCKED_POLICY_AND_AUTH = "BLOCKED_POLICY_AND_AUTH"


class SearchScope(str, Enum):
    """Targeted scope for search discovery."""
    GENERAL_WEB = "GENERAL_WEB"
    ENCYCLOPEDIC_REFERENCE = "ENCYCLOPEDIC_REFERENCE"
    OFFICIAL_DOMAIN = "OFFICIAL_DOMAIN"
    PUBLIC_DISCUSSION = "PUBLIC_DISCUSSION"


class BackendMaturityState(str, Enum):
    """Operational maturity level of a tool backend adapter."""
    EXPERIMENTAL = "EXPERIMENTAL"
    READY = "READY"
    DEGRADED = "DEGRADED"


class SearXNGAdapterState(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ExtractionQualityMetrics(BaseModel):
    """Structural extraction completeness metrics."""
    text_length: int = 0
    title_present: bool = False
    main_text_present: bool = False
    metadata_present: bool = False
    canonical_present: bool = False


class DiscussionComment(BaseModel):
    """Normalized comment within a public discussion thread."""
    comment_id: str
    parent_comment_id: Optional[str] = None
    thread_id: str
    author_display_name: Optional[str] = None
    author_platform_identifier: Optional[str] = None
    identity_type: IdentityType = IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER
    created_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    body: str = ""
    depth: int = 0
    reported_score: Optional[int] = None
    is_op: bool = False
    permalink: Optional[str] = None
    status: str = "ACTIVE"  # ACTIVE | DELETED | REMOVED | UNAVAILABLE
    content_variant: ContentVariant = ContentVariant.ORIGINAL
    redaction_applied: bool = False
    redaction_types: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.author_platform_identifier and self.author_display_name:
            self.author_platform_identifier = self.author_display_name


class DiscussionThread(BaseModel):
    """Normalized public discussion thread header and metadata."""
    thread_id: str
    platform: str  # reddit | hacker_news | discourse | web_forum
    upstream_provenance: str = "FIRST_PARTY_OFFICIAL_API"  # FIRST_PARTY_OFFICIAL_API | THIRD_PARTY_SEARCH_INDEX | DIRECT_DOM
    thread_url: str
    title: str
    author_display_name: Optional[str] = None
    author_platform_identifier: Optional[str] = None
    identity_type: IdentityType = IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER
    created_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    body: Optional[str] = None
    community: Optional[str] = None  # e.g. subreddit, category, forum name
    reported_score: Optional[int] = None
    reported_comment_count: Optional[int] = None
    language: Optional[str] = None
    tags_or_flair: List[str] = Field(default_factory=list)
    outbound_links: List[str] = Field(default_factory=list)
    comments: List[DiscussionComment] = Field(default_factory=list)
    content_variant: ContentVariant = ContentVariant.ORIGINAL
    redaction_applied: bool = False
    redaction_types: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.author_platform_identifier and self.author_display_name:
            self.author_platform_identifier = self.author_display_name


class DiscussionSearchSummary(BaseModel):
    """Sampling context and result set for a public discussion search query."""
    query: str
    platform: str
    upstream_provenance: str = "THIRD_PARTY_SEARCH_INDEX"
    community_scope: Optional[str] = None
    time_window: Optional[str] = None
    sort_method: str = "relevance"
    result_count: int = 0
    comment_count_collected: int = 0
    collection_limit: int = 20
    pagination_state: Optional[str] = None
    has_more: bool = False
    threads: List[DiscussionThread] = Field(default_factory=list)


class SearchResultItem(BaseModel):
    """Normalized search hit discovered by search engine."""
    rank: int
    title: str
    url: str
    display_url: Optional[str] = None
    snippet: str = ""
    published_at: Optional[datetime] = None
    source_domain: str = ""
    result_type: str = "web_page"


class SearchResultSet(BaseModel):
    """Normalized output set of search discovery results."""
    query: str
    executed_query: str
    backend: str
    backend_provenance: str  # SELF_HOSTED_META_SEARCH | THIRD_PARTY_SEARCH_API | FIRST_PARTY_OFFICIAL_API | UNOFFICIAL_HTML_PARSE
    search_scope: SearchScope = SearchScope.GENERAL_WEB
    result_count: int = 0
    results: List[SearchResultItem] = Field(default_factory=list)
    pagination_state: Optional[str] = None
    collection_limit: int = 10
    has_more: bool = False
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceReference(BaseModel):
    """Compact reference pointer to an observed external resource."""
    source_url: str
    platform: str = "web"
    title: Optional[str] = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ObservationRecord(BaseModel):
    """Normalized empirical observation deliverable passed to marketing agents.

    Epistemic boundary rules:
    1. extraction_confidence measures parser fidelity, NOT claim veracity.
    2. source_credibility defaults to UNKNOWN for public web retrievals.
    3. content_truth_status defaults to UNVERIFIED (never automatically converted into FACT).
    """
    observation_id: str = Field(default_factory=lambda: f"OBS-{uuid.uuid4().hex[:12]}")
    capability: str = Field(..., description="e.g. 'read_page', 'youtube_metadata', 'read_forum_thread', 'search_web'")
    source_platform: str = Field(default="web", description="web | youtube | reddit | hacker_news | web_forum | search_engine")
    source_type: str = Field(default="article", description="article | landing_page | video | transcript | discussion_thread | discussion_search_result | search_discovery")
    source_url_or_id: str = Field(..., description="Target URL, video ID, thread ID, or search query")
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observed_at: Optional[datetime] = Field(None, description="Original publication/upload timestamp if detectable")
    backend_used: str = Field(..., description="e.g. 'http_static', 'youtube_ytdlp', 'discussion_public', 'search_searxng'")
    collection_method: str = Field(default="DIRECT_HTTP", description="DIRECT_HTTP | YTDLP_PUBLIC_EXTRACTION | PUBLIC_JSON_API | FORUM_DOM_PARSE | SEARCH_ENGINE_DISCOVERY")
    raw_reference: Optional[str] = Field(None, description="Filesystem path or bounded snapshot pointer")
    normalized_data: Dict[str, Any] = Field(default_factory=dict, description="Structured payload: text, title, metadata, discussion, search")
    evidence_class: EpistemicType = Field(default=EpistemicType.OBSERVATION)
    freshness_days: Optional[float] = Field(None, description="Days elapsed since original observation")

    # Separated Semantic Confidence & Epistemic Verification
    extraction_confidence: ExtractionConfidence = Field(
        default=ExtractionConfidence.UNKNOWN,
        description="Fidelity and completeness of content extraction by parser",
    )
    source_credibility: SourceCredibility = Field(
        default=SourceCredibility.UNKNOWN,
        description="Assessed authority/trustworthiness of external domain (default UNKNOWN)",
    )
    content_truth_status: ContentTruthStatus = Field(
        default=ContentTruthStatus.UNVERIFIED,
        description="Epistemic status of source claims (default UNVERIFIED)",
    )

    # Backward Compatibility Field (Deprecated)
    confidence: Optional[str] = Field(
        default=None,
        description="DEPRECATED: Legacy field maintained for backward compatibility. Mirrors extraction_confidence.",
    )

    limitations: List[str] = Field(default_factory=list, description="Known sampling gaps or parser limits")
    product_id: str = Field(..., description="Product isolation partition key")
    brand_id: str = Field(..., description="Brand partition key")
    content_trust: ContentTrustLevel = Field(default=ContentTrustLevel.UNTRUSTED_EXTERNAL)

    # Trusted execution scope (sourced from RuntimeContext/AuthoritativeScope, NOT model parameters)
    run_id: str = Field(default="", description="Trusted execution run ID from RuntimeContext")
    business_id: str = Field(default="", description="Trusted business scope from RuntimeContext")
    project_id: str = Field(default="", description="Trusted project scope from RuntimeContext")

    def __post_init__(self) -> None:
        super().__post_init__()
        # Sync legacy confidence field if not explicitly supplied
        if self.confidence is None:
            self.confidence = self.extraction_confidence.value
