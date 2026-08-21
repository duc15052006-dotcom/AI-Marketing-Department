"""Capability Registry Architecture (Phase 5.1).

Defines capability metadata, input/output contracts, categories, risk levels,
and central registry for tool capabilities.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from schemas.base import BaseModel, Field


class CapabilityCategory(str, Enum):
    """Broad capability domains."""
    OBSERVE = "OBSERVE"
    CREATE = "CREATE"
    PUBLISH = "PUBLISH"
    ANALYZE = "ANALYZE"
    FILE_DATA = "FILE_DATA"


class RiskLevel(str, Enum):
    """Operational and business risk level for a capability."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PermissionLevel(str, Enum):
    """Required permissions for executing a capability."""
    READ_ONLY = "READ_ONLY"
    CREATE_LOCAL = "CREATE_LOCAL"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    PUBLISH = "PUBLISH"
    FINANCIAL_OR_HIGH_RISK = "FINANCIAL_OR_HIGH_RISK"
    ANALYTICS = "ANALYTICS"


class CostPolicy(str, Enum):
    """Execution cost policy."""
    FREE_LOCAL = "FREE_LOCAL"
    FREE_TIER_METERED = "FREE_TIER_METERED"
    PAID_METERED = "PAID_METERED"


class CapabilityDescriptor(BaseModel):
    """Comprehensive declaration of an operational or sensory capability."""
    capability_id: str = Field(..., description="Unique capability identifier, e.g. 'web_search'")
    name: str = Field(..., description="Human-readable capability name")
    category: CapabilityCategory = Field(..., description="Category: OBSERVE | CREATE | PUBLISH | ANALYZE | FILE_DATA")
    description: str = Field(..., description="Detailed description of what the capability does")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="Expected input parameters JSON schema")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="Expected output result JSON schema")
    required_permissions: List[PermissionLevel] = Field(default_factory=lambda: [PermissionLevel.READ_ONLY])
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    human_approval_required: bool = Field(default=False)
    supported_agents: List[str] = Field(default_factory=list, description="List of agent roles permitted to request this capability")
    provider: str = Field(default="system_local", description="Provider adapter name")
    availability: str = Field(default="AVAILABLE", description="AVAILABLE | DEGRADED | UNAVAILABLE | MOCK_ONLY")
    cost_policy: CostPolicy = Field(default=CostPolicy.FREE_LOCAL)
    timeout_policy: float = Field(default=30.0, description="Default timeout in seconds")
    retry_policy: Dict[str, Any] = Field(
        default_factory=lambda: {"max_retries": 1, "backoff_seconds": 1.0, "retryable_errors": ["TIMEOUT", "NETWORK_ERROR"]}
    )
    audit_policy: Dict[str, Any] = Field(
        default_factory=lambda: {"log_payload": True, "redact_secrets": True, "emit_receipt": True}
    )

    def fingerprint(self) -> str:
        """Cryptographic hash of the capability declaration."""
        raw = f"{self.capability_id}:{self.category.value}:{self.risk_level.value}:{self.human_approval_required}:{self.provider}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CapabilityRegistry:
    """Central repository and discovery engine for all system capabilities."""

    def __init__(self) -> None:
        self._capabilities: Dict[str, CapabilityDescriptor] = {}
        self._load_builtin_capabilities()

    def register_capability(self, descriptor: CapabilityDescriptor) -> None:
        """Register or update a capability."""
        cid = descriptor.capability_id.lower()
        self._capabilities[cid] = descriptor

    def get_capability(self, capability_id: str) -> Optional[CapabilityDescriptor]:
        """Retrieve capability descriptor by ID."""
        return self._capabilities.get(capability_id.lower())

    def list_capabilities(self, category: Optional[CapabilityCategory] = None) -> List[CapabilityDescriptor]:
        """List all capabilities, optionally filtered by category."""
        if category is None:
            return list(self._capabilities.values())
        return [c for c in self._capabilities.values() if c.category == category]

    def list_capabilities_for_agent(self, agent_id: str) -> List[CapabilityDescriptor]:
        """List capabilities available for a specific agent role."""
        aid = agent_id.lower()
        return [
            c for c in self._capabilities.values()
            if aid in [sa.lower() for sa in c.supported_agents] or "all" in [sa.lower() for sa in c.supported_agents]
        ]

    def _load_builtin_capabilities(self) -> None:
        """Register the default Phase 5.1 capability suite."""
        # 1. OBSERVE CATEGORY
        self.register_capability(
            CapabilityDescriptor(
                capability_id="web_search",
                name="Web Search",
                category=CapabilityCategory.OBSERVE,
                description="Search public web for qualitative market research, industry trends, and competitor signals.",
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["intelligence", "strategist", "cmo"],
                provider="search_adapter",
                timeout_policy=15.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="read_page",
                name="Read Webpage Content",
                category=CapabilityCategory.OBSERVE,
                description="Fetch and extract readable plain text and structured headings from a public URL.",
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["intelligence", "strategist", "cmo"],
                provider="http_adapter",
                timeout_policy=20.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="structured_data_retrieval",
                name="Structured Data Retrieval",
                category=CapabilityCategory.OBSERVE,
                description="Query structured external product feeds, schema.org JSON-LD, or OpenGraph datasets.",
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["intelligence", "performance", "cmo"],
                provider="data_retrieval_adapter",
                timeout_policy=15.0,
            )
        )

        # 2. CREATE CATEGORY
        self.register_capability(
            CapabilityDescriptor(
                capability_id="text_generation_support",
                name="Text Generation Support",
                category=CapabilityCategory.CREATE,
                description="Local drafting and copy refinement for ad copy, headlines, and scripts.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["creative", "strategist", "cmo"],
                provider="creative_text_adapter",
                timeout_policy=30.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="image_generation",
                name="Image Generation",
                category=CapabilityCategory.CREATE,
                description="Generate candidate visual assets, storyboards, or concept mockups.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.MEDIUM,
                human_approval_required=False,
                supported_agents=["creative", "cmo"],
                provider="image_gen_adapter",
                timeout_policy=45.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="image_editing",
                name="Image Editing & Formatting",
                category=CapabilityCategory.CREATE,
                description="Crop, resize, composite, or color-adjust visual creative assets.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["creative", "cmo"],
                provider="image_edit_adapter",
                timeout_policy=30.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="video_generation",
                name="Video Generation",
                category=CapabilityCategory.CREATE,
                description="Synthesize video sequences or animated creative assets from storyboards.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.MEDIUM,
                human_approval_required=False,
                supported_agents=["creative", "cmo"],
                provider="video_gen_adapter",
                timeout_policy=60.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="video_editing_rendering",
                name="Video Editing & Rendering",
                category=CapabilityCategory.CREATE,
                description="Assemble cuts, transitions, captions, and audio tracks for video campaigns.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["creative", "cmo"],
                provider="video_edit_adapter",
                timeout_policy=60.0,
            )
        )

        # 3. PUBLISH CATEGORY
        self.register_capability(
            CapabilityDescriptor(
                capability_id="social_publishing",
                name="Social Media Publishing",
                category=CapabilityCategory.PUBLISH,
                description="Publish authorized marketing assets directly to live platform accounts.",
                required_permissions=[PermissionLevel.PUBLISH, PermissionLevel.EXTERNAL_WRITE],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                supported_agents=["cmo"],
                provider="social_publish_adapter",
                timeout_policy=30.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="content_scheduling",
                name="Content Scheduling",
                category=CapabilityCategory.PUBLISH,
                description="Queue and schedule campaign releases on platform calendars.",
                required_permissions=[PermissionLevel.PUBLISH],
                risk_level=RiskLevel.HIGH,
                human_approval_required=True,
                supported_agents=["cmo"],
                provider="schedule_adapter",
                timeout_policy=20.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="platform_operations",
                name="Platform Operations & Budget Allocation",
                category=CapabilityCategory.PUBLISH,
                description="Modify ad campaign status, adjust live spend caps, or launch campaigns.",
                required_permissions=[PermissionLevel.FINANCIAL_OR_HIGH_RISK, PermissionLevel.EXTERNAL_WRITE],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                supported_agents=["cmo"],
                provider="ad_platform_adapter",
                timeout_policy=30.0,
            )
        )

        # 4. ANALYZE CATEGORY
        self.register_capability(
            CapabilityDescriptor(
                capability_id="analytics_retrieval",
                name="Analytics Retrieval",
                category=CapabilityCategory.ANALYZE,
                description="Fetch aggregated traffic, conversion, and performance telemetry.",
                required_permissions=[PermissionLevel.READ_ONLY, PermissionLevel.ANALYTICS],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["performance", "cmo", "strategist"],
                provider="analytics_adapter",
                timeout_policy=20.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="kpi_calculation",
                name="KPI & Conversion Calculation",
                category=CapabilityCategory.ANALYZE,
                description="Compute ROAS, CAC, conversion velocities, and funnel metrics.",
                required_permissions=[PermissionLevel.ANALYTICS],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["performance", "cmo", "strategist"],
                provider="kpi_calc_adapter",
                timeout_policy=15.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="attribution_data_access",
                name="Attribution Data Access",
                category=CapabilityCategory.ANALYZE,
                description="Access touchpoint sequences and attribution model weights.",
                required_permissions=[PermissionLevel.ANALYTICS],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["performance", "cmo"],
                provider="attribution_adapter",
                timeout_policy=20.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="experiment_result_analysis",
                name="Experiment Result Analysis",
                category=CapabilityCategory.ANALYZE,
                description="Calculate statistical significance, sample sizes, and p-values for A/B tests.",
                required_permissions=[PermissionLevel.ANALYTICS],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["performance", "cmo", "strategist"],
                provider="stats_analysis_adapter",
                timeout_policy=20.0,
            )
        )

        # 5. FILE / DATA CATEGORY
        self.register_capability(
            CapabilityDescriptor(
                capability_id="file_read",
                name="File Read",
                category=CapabilityCategory.FILE_DATA,
                description="Read local workspace files, research notes, and creative assets.",
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["cmo", "intelligence", "strategist", "creative", "performance"],
                provider="file_io_adapter",
                timeout_policy=10.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="file_write",
                name="File Write",
                category=CapabilityCategory.FILE_DATA,
                description="Save generated artifacts, reports, and working documents to disk.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["cmo", "creative", "performance", "intelligence"],
                provider="file_io_adapter",
                timeout_policy=15.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="structured_storage_query",
                name="Structured Storage Query",
                category=CapabilityCategory.FILE_DATA,
                description="Execute queries against local SQLite or structured JSON data stores.",
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["cmo", "intelligence", "performance", "strategist"],
                provider="db_storage_adapter",
                timeout_policy=20.0,
            )
        )
        self.register_capability(
            CapabilityDescriptor(
                capability_id="data_export",
                name="Data Export",
                category=CapabilityCategory.FILE_DATA,
                description="Export reports and creative packages to CSV, PDF, or JSON bundles.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                supported_agents=["cmo", "performance", "creative"],
                provider="export_adapter",
                timeout_policy=25.0,
            )
        )
