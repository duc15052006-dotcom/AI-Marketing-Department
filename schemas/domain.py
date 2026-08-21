"""Core Marketing Domain Entities.

Provides typed models for Brands, Products, Personas,
Research, Strategies, Creative Assets, Experiments, and Learnings.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from schemas.base import BaseModel, Field


# ---------------------------------------------------------------------------
# Workspace & Foundation Entities
# ---------------------------------------------------------------------------

class Brand(BaseModel):
    """Parent Brand entity."""
    id: str = Field(..., description="Brand unique identifier, e.g. BRAND-001")
    name: str = Field(..., min_length=1)
    industry: str = Field(default="")
    mission: str = Field(default="")
    core_values: List[str] = Field(default_factory=list)
    voice_guidelines: Dict[str, Any] = Field(default_factory=dict)
    visual_guidelines: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Product(BaseModel):
    """Isolated Product entity. Enforces multi-tenant workspace separation."""
    id: str = Field(..., description="Product unique partition key, e.g. PROD-001")
    brand_id: str = Field(..., description="Parent brand ID")
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    category: str = Field(default="")
    price_model: Dict[str, Any] = Field(default_factory=dict)
    features: List[Dict[str, Any]] = Field(default_factory=list)
    unique_selling_propositions: List[str] = Field(default_factory=list)
    target_audience_ids: List[str] = Field(default_factory=list)
    workspace_path: str = Field(..., description="Relative isolated workspace path, e.g. products/PROD-001/")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Intelligence & Research Entities
# ---------------------------------------------------------------------------

class Source(BaseModel):
    """Origin source of external marketing data."""
    id: str = Field(..., description="Source ID, e.g. SRC-001")
    url: Optional[str] = None
    platform: str = Field(..., description="e.g. Meta Ad Library, Reddit, Amazon, G2")
    author_or_entity: Optional[str] = None
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Evidence(BaseModel):
    """Verifiable data point grounding an observation or claim."""
    id: str = Field(..., description="Evidence ID, e.g. EVID-001")
    source_id: str = Field(..., description="Referenced Source ID")
    raw_content: str = Field(default="")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_status: Literal["VERIFIED", "UNVERIFIED", "DISPUTED"] = Field(default="UNVERIFIED")


class CustomerInsight(BaseModel):
    """Validated insight regarding customer psychology or behavior."""
    id: str = Field(..., description="Insight ID, e.g. INSIGHT-001")
    product_id: str = Field(..., description="Product ID")
    persona_id: Optional[str] = None
    statement: str = Field(default="")
    epistemic_type: Literal["FACT", "OBSERVATION", "INFERENCE", "HYPOTHESIS"] = Field(default="OBSERVATION")
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CustomerPersona(BaseModel):
    """Target buyer persona archetype."""
    id: str = Field(..., description="Persona ID, e.g. PERS-001")
    product_id: str = Field(..., description="Product ID")
    name: str = Field(default="")
    demographics: Dict[str, Any] = Field(default_factory=dict)
    psychographics: Dict[str, Any] = Field(default_factory=dict)
    jobs_to_be_done: List[str] = Field(default_factory=list)
    pain_points: List[str] = Field(default_factory=list)
    objections: List[str] = Field(default_factory=list)
    triggers_to_purchase: List[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Synthesized research output delivered by the Intelligence Agent."""
    id: str = Field(..., description="Report ID, e.g. REP-001")
    product_id: str = Field(..., description="Product ID")
    title: str = Field(default="")
    executive_summary: str = Field(default="")
    competitor_analysis: List[Dict[str, Any]] = Field(default_factory=list)
    market_trends: List[str] = Field(default_factory=list)
    identified_insights: List[CustomerInsight] = Field(default_factory=list)
    recommended_angles: List[str] = Field(default_factory=list)
    created_by_agent: str = Field(default="INTELLIGENCE")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Strategy & Campaign Planning Entities
# ---------------------------------------------------------------------------

class MarketingHypothesis(BaseModel):
    """Falsifiable proposition to be tested via campaigns/experiments."""
    id: str = Field(..., description="Hypothesis ID, e.g. HYP-001")
    product_id: str = Field(..., description="Product ID")
    statement: str = Field(default="")
    rationale: str = Field(default="")
    target_metric: str = Field(default="CTR", description="e.g. CTR, 3s_view_rate, ROAS, CPA")
    expected_delta: float = Field(default=0.0, description="Expected percentage or absolute change")
    status: Literal["DRAFT", "ACTIVE_TEST", "VALIDATED", "DISPROVEN"] = Field(default="DRAFT")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MarketingStrategy(BaseModel):
    """Strategic marketing blueprint delivered by the Strategist Agent."""
    id: str = Field(..., description="Strategy ID, e.g. STRAT-001")
    product_id: str = Field(..., description="Product ID")
    strategic_pillars: List[str] = Field(default_factory=list)
    positioning_statement: str = Field(default="")
    value_propositions: List[str] = Field(default_factory=list)
    messaging_hierarchy: Dict[str, Any] = Field(default_factory=dict)
    target_channels: List[str] = Field(default_factory=list)
    hypothesis_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Campaign(BaseModel):
    """Marketing campaign entity."""
    id: str = Field(..., description="Campaign ID, e.g. CAMP-001")
    product_id: str = Field(..., description="Product ID")
    brand_id: str = Field(..., description="Brand ID")
    name: str = Field(default="")
    objective: Literal["AWARENESS", "TRAFFIC", "LEAD_GEN", "CONVERSION", "RETENTION"] = Field(default="CONVERSION")
    strategy_id: str = Field(default="")
    total_budget: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="USD")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Literal["PLANNING", "IN_REVIEW", "SCHEDULED", "ACTIVE", "PAUSED", "COMPLETED"] = Field(default="PLANNING")


# ---------------------------------------------------------------------------
# Creative Production Entities
# ---------------------------------------------------------------------------

class EmotionalTrigger(str, Enum):
    FEAR = "FEAR"
    CURIOSITY = "CURIOSITY"
    STATUS = "STATUS"
    RELIEF = "RELIEF"
    GREED = "GREED"
    ANGER = "ANGER"


class HookType(str, Enum):
    QUESTION = "QUESTION"
    CONTRARIAN = "CONTRARIAN"
    STORY_IN_MEDIAS_RES = "STORY_IN_MEDIAS_RES"
    DIRECT_PAIN = "DIRECT_PAIN"
    STATISTIC = "STATISTIC"


class CreativeConcept(BaseModel):
    """Overarching creative idea or angle."""
    id: str = Field(..., description="Concept ID, e.g. CONCEPT-001")
    product_id: str = Field(..., description="Product ID")
    angle_name: str = Field(default="")
    theme: str = Field(default="")
    target_persona_id: str = Field(default="")
    emotional_hook_category: EmotionalTrigger = Field(default=EmotionalTrigger.CURIOSITY)


class Hook(BaseModel):
    """The first 1.5 - 3.0 seconds of an ad."""
    id: str = Field(..., description="Hook ID, e.g. HOOK-001")
    concept_id: str = Field(default="")
    text_hook: str = Field(default="")
    visual_hook_description: str = Field(default="")
    hook_type: HookType = Field(default=HookType.QUESTION)
    duration_seconds: float = Field(default=3.0, ge=0.5, le=10.0)


class Script(BaseModel):
    """Complete narrative copywriting script."""
    id: str = Field(..., description="Script ID, e.g. SCRIPT-001")
    concept_id: str = Field(default="")
    hook_id: str = Field(default="")
    target_duration_seconds: int = Field(default=30, ge=5, le=300)
    full_text: str = Field(default="")
    call_to_action: str = Field(default="")
    cta_type: Literal["DIRECT_CLICK", "FREE_TRIAL", "DOWNLOAD", "LIMITED_DISCOUNT"] = Field(default="DIRECT_CLICK")


class Scene(BaseModel):
    """Atomic visual and audio scene within a Storyboard."""
    id: str = Field(..., description="Scene ID, e.g. SCN-001")
    sequence_index: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=3.0, gt=0.0)
    visual_description: str = Field(default="")
    voiceover_text: str = Field(default="")
    on_screen_text: str = Field(default="")
    audio_sfx_cue: Optional[str] = None
    camera_movement: str = Field(default="Static")


class Storyboard(BaseModel):
    """Scene-by-scene visual blueprint for video production."""
    id: str = Field(..., description="Storyboard ID, e.g. SB-001")
    script_id: str = Field(default="")
    scenes: List[Scene] = Field(default_factory=list)
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:5"] = Field(default="9:16")


class ContentAsset(BaseModel):
    """Base multimedia content asset."""
    id: str = Field(..., description="Asset ID, e.g. ASSET-001")
    product_id: str = Field(..., description="Product ID")
    asset_type: Literal["IMAGE", "VIDEO", "AUDIO", "VOICEOVER", "SUBTITLE", "THUMBNAIL"] = Field(default="IMAGE")
    file_path: str = Field(default="")
    resolution: Optional[str] = None
    mime_type: str = Field(default="image/png")
    generation_params: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VideoAsset(ContentAsset):
    """Rendered video asset with atomic component traceability."""
    asset_type: Literal["IMAGE", "VIDEO", "AUDIO", "VOICEOVER", "SUBTITLE", "THUMBNAIL"] = Field(default="VIDEO")
    storyboard_id: str = Field(default="")
    script_id: str = Field(default="")
    hook_id: str = Field(default="")
    duration_seconds: float = Field(default=30.0)
    timeline_manifest_path: str = Field(default="")


# ---------------------------------------------------------------------------
# Experimentation, Analytics & Learning Entities
# ---------------------------------------------------------------------------

class CreativeVariant(BaseModel):
    """Specific tagged combination of creative components deployed in an ad test."""
    id: str = Field(..., description="Variant ID, e.g. VAR-001")
    experiment_id: str = Field(default="")
    video_asset_id: str = Field(default="")
    hook_id: str = Field(default="")
    script_id: str = Field(default="")
    cta_id: Optional[str] = None
    editing_style: str = Field(default="Standard")
    platform_placement_id: Optional[str] = None


class Experiment(BaseModel):
    """Controlled marketing test."""
    id: str = Field(..., description="Experiment ID, e.g. EXP-001")
    campaign_id: str = Field(default="")
    product_id: str = Field(..., description="Product ID")
    hypothesis_id: str = Field(default="")
    experiment_type: Literal["A_B_TEST", "MULTIVARIATE", "BANDIT"] = Field(default="A_B_TEST")
    control_variant_id: str = Field(default="")
    test_variant_ids: List[str] = Field(default_factory=list)
    sample_size_target: int = Field(default=10000)
    confidence_level: float = Field(default=0.95)
    status: Literal["DRAFT", "RUNNING", "CONCLUDED", "INCONCLUSIVE"] = Field(default="DRAFT")


class PerformanceRecord(BaseModel):
    """Quantitative performance metric record for an ad variant."""
    id: str = Field(..., description="Record ID, e.g. PERF-001")
    product_id: str = Field(..., description="Product ID")
    variant_id: str = Field(default="")
    channel: str = Field(default="")
    record_date: Optional[date] = None
    impressions: int = Field(default=0)
    spend: float = Field(default=0.0)
    clicks: int = Field(default=0)
    video_views_3s: int = Field(default=0)
    video_views_100pct: int = Field(default=0)
    conversions: int = Field(default=0)
    revenue: float = Field(default=0.0)

    @property
    def ctr(self) -> float:
        return (self.clicks / self.impressions) if self.impressions > 0 else 0.0

    @property
    def cpc(self) -> float:
        return (self.spend / self.clicks) if self.clicks > 0 else 0.0

    @property
    def cpa(self) -> float:
        return (self.spend / self.conversions) if self.conversions > 0 else 0.0

    @property
    def roas(self) -> float:
        return (self.revenue / self.spend) if self.spend > 0 else 0.0


class Learning(BaseModel):
    """Distilled empirical finding extracted from experiments."""
    id: str = Field(..., description="Learning ID, e.g. LRN-001")
    product_id: str = Field(..., description="Product ID")
    brand_id: Optional[str] = None
    hypothesis_id: Optional[str] = None
    observation: str = Field(default="")
    evidence: List[str] = Field(default_factory=list)
    sample_size: int = Field(default=0)
    context: Dict[str, Any] = Field(default_factory=dict)
    result: str = Field(default="")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    scope: Literal["PRODUCT_SPECIFIC", "BRAND_WIDE", "GLOBAL_MARKETING"] = Field(default="PRODUCT_SPECIFIC")
    possible_confounders: List[str] = Field(default_factory=list)
    recommendation: str = Field(default="")
    needs_retest: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Failure(BaseModel):
    """Preserved negative result and root cause analysis."""
    id: str = Field(..., description="Failure ID, e.g. FAIL-001")
    product_id: str = Field(..., description="Product ID")
    experiment_id: Optional[str] = None
    description: str = Field(default="")
    root_cause_analysis: str = Field(default="")
    preventative_rule: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
