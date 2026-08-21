"""Agent Infrastructure Access Contract (Phase 5.1).

Defines the formal Role-Based Access Control (RBAC) and data store access matrix
for the Five-Agent Department: CMO, Intelligence, Strategist, Creative, and Performance.
Guarantees permanent logical agent count = 5 and zero Agent 6.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from knowledge.models import SourceType
from memory.models import MemoryType
from schemas.base import BaseModel, Field
from tools.capabilities import CapabilityCategory, PermissionLevel

PERMANENT_FIVE_AGENTS: Set[str] = {
    "cmo",
    "intelligence",
    "strategist",
    "creative",
    "performance",
}


class AgentAccessProfile(BaseModel):
    """Specification of storage and capability access boundaries for an agent role."""
    agent_id: str
    role_title: str
    allowed_capability_categories: List[CapabilityCategory]
    permission_levels: List[PermissionLevel]
    allowed_knowledge_sources: List[SourceType]
    allowed_memory_types: List[MemoryType]
    can_request_human_approval: bool = False
    can_access_raw_telemetry: bool = False
    can_record_learning_events: bool = False


class AgentAccessMatrix:
    """Central authority governing storage and capability access across the Five-Agent Brain."""

    PROFILES: Dict[str, AgentAccessProfile] = {
        # 1. CMO
        "cmo": AgentAccessProfile(
            agent_id="cmo",
            role_title="Chief Marketing Officer & Master Orchestrator",
            allowed_capability_categories=[
                CapabilityCategory.OBSERVE,
                CapabilityCategory.CREATE,
                CapabilityCategory.PUBLISH,
                CapabilityCategory.ANALYZE,
                CapabilityCategory.FILE_DATA,
            ],
            permission_levels=[
                PermissionLevel.READ_ONLY,
                PermissionLevel.CREATE_LOCAL,
                PermissionLevel.EXTERNAL_WRITE,
                PermissionLevel.PUBLISH,
                PermissionLevel.FINANCIAL_OR_HIGH_RISK,
                PermissionLevel.ANALYTICS,
            ],
            allowed_knowledge_sources=list(SourceType),
            allowed_memory_types=list(MemoryType),
            can_request_human_approval=True,
            can_access_raw_telemetry=True,
            can_record_learning_events=True,
        ),
        # 2. Intelligence
        "intelligence": AgentAccessProfile(
            agent_id="intelligence",
            role_title="Market, Consumer & Competitor Intelligence Specialist",
            allowed_capability_categories=[
                CapabilityCategory.OBSERVE,
                CapabilityCategory.FILE_DATA,
            ],
            permission_levels=[
                PermissionLevel.READ_ONLY,
                PermissionLevel.CREATE_LOCAL,
            ],
            allowed_knowledge_sources=[
                SourceType.PRODUCT_GROUND_TRUTH,
                SourceType.BRAND_GUIDELINE,
                SourceType.MARKET_RESEARCH,
                SourceType.CUSTOMER_RESEARCH,
                SourceType.COMPETITOR_INTELLIGENCE,
                SourceType.HISTORICAL_REPORT,
            ],
            allowed_memory_types=[
                MemoryType.WORKING_MEMORY,
                MemoryType.EPISODIC_MEMORY,
                MemoryType.SUCCESS_FAILURE_MEMORY,
                MemoryType.USER_BRAND_PREFERENCE_MEMORY,
            ],
            can_request_human_approval=False,
            can_access_raw_telemetry=False,
            can_record_learning_events=False,
        ),
        # 3. Strategist
        "strategist": AgentAccessProfile(
            agent_id="strategist",
            role_title="Marketing Strategy & Growth Specialist",
            allowed_capability_categories=[
                CapabilityCategory.OBSERVE,
                CapabilityCategory.CREATE,
                CapabilityCategory.ANALYZE,
                CapabilityCategory.FILE_DATA,
            ],
            permission_levels=[
                PermissionLevel.READ_ONLY,
                PermissionLevel.CREATE_LOCAL,
                PermissionLevel.ANALYTICS,
            ],
            allowed_knowledge_sources=[
                SourceType.PRODUCT_GROUND_TRUTH,
                SourceType.BRAND_GUIDELINE,
                SourceType.MARKET_RESEARCH,
                SourceType.CUSTOMER_RESEARCH,
                SourceType.COMPETITOR_INTELLIGENCE,
                SourceType.MARKETING_SOP,
                SourceType.HISTORICAL_REPORT,
            ],
            allowed_memory_types=[
                MemoryType.WORKING_MEMORY,
                MemoryType.EPISODIC_MEMORY,
                MemoryType.DECISION_MEMORY,
                MemoryType.EXPERIMENT_MEMORY,
                MemoryType.SUCCESS_FAILURE_MEMORY,
                MemoryType.USER_BRAND_PREFERENCE_MEMORY,
            ],
            can_request_human_approval=False,
            can_access_raw_telemetry=False,
            can_record_learning_events=False,
        ),
        # 4. Creative
        "creative": AgentAccessProfile(
            agent_id="creative",
            role_title="Creative Director & Copywriter",
            allowed_capability_categories=[
                CapabilityCategory.CREATE,
                CapabilityCategory.FILE_DATA,
            ],
            permission_levels=[
                PermissionLevel.READ_ONLY,
                PermissionLevel.CREATE_LOCAL,
            ],
            allowed_knowledge_sources=[
                SourceType.PRODUCT_GROUND_TRUTH,
                SourceType.BRAND_GUIDELINE,
                SourceType.MARKETING_SOP,
            ],
            allowed_memory_types=[
                MemoryType.WORKING_MEMORY,
                MemoryType.EPISODIC_MEMORY,
                MemoryType.SUCCESS_FAILURE_MEMORY,
                MemoryType.USER_BRAND_PREFERENCE_MEMORY,
            ],
            can_request_human_approval=False,
            can_access_raw_telemetry=False,
            can_record_learning_events=False,
        ),
        # 5. Performance
        "performance": AgentAccessProfile(
            agent_id="performance",
            role_title="Performance Marketing & Analytics Specialist",
            allowed_capability_categories=[
                CapabilityCategory.ANALYZE,
                CapabilityCategory.OBSERVE,
                CapabilityCategory.FILE_DATA,
            ],
            permission_levels=[
                PermissionLevel.READ_ONLY,
                PermissionLevel.ANALYTICS,
                PermissionLevel.CREATE_LOCAL,
            ],
            allowed_knowledge_sources=[
                SourceType.PRODUCT_GROUND_TRUTH,
                SourceType.BRAND_GUIDELINE,
                SourceType.MARKETING_SOP,
                SourceType.PLATFORM_POLICY,
                SourceType.HISTORICAL_REPORT,
            ],
            allowed_memory_types=[
                MemoryType.WORKING_MEMORY,
                MemoryType.EPISODIC_MEMORY,
                MemoryType.DECISION_MEMORY,
                MemoryType.EXPERIMENT_MEMORY,
                MemoryType.SUCCESS_FAILURE_MEMORY,
            ],
            can_request_human_approval=False,
            can_access_raw_telemetry=True,
            can_record_learning_events=True,
        ),
    }

    @classmethod
    def get_profile(cls, agent_id: str) -> Optional[AgentAccessProfile]:
        """Retrieve access profile for a recognized agent."""
        return cls.PROFILES.get(agent_id.lower())

    @classmethod
    def validate_agent_count(cls) -> bool:
        """Enforce strict permanent logical agent count = 5."""
        return len(cls.PROFILES) == 5 and set(cls.PROFILES.keys()) == PERMANENT_FIVE_AGENTS

    @classmethod
    def can_access_knowledge_source(cls, agent_id: str, source_type: SourceType) -> bool:
        prof = cls.get_profile(agent_id)
        if not prof:
            return False
        return source_type in prof.allowed_knowledge_sources

    @classmethod
    def can_access_memory_type(cls, agent_id: str, memory_type: MemoryType) -> bool:
        prof = cls.get_profile(agent_id)
        if not prof:
            return False
        return memory_type in prof.allowed_memory_types
