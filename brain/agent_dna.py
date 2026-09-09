"""Provider-neutral semantic DNA for the five permanent marketing agents.

The long-form ``.agents/agents/*/agent.md`` files remain rich operating prompts.
This module deliberately does not mirror that prose. It defines only stable,
machine-checkable cognitive authority boundaries that must survive prompt edits,
model/provider swaps, and future runtime implementations.

The Brain owns *who is responsible for what*. It does not grant permission to
execute tools, spend money, publish campaigns, choose providers, or manipulate
runtime state. Live execution authority always remains outside this module.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Type, TypeVar

from brain.contracts import BrainAgentId
from schemas.base import BaseModel, Field, ValidationError


class AgentFunction(str, Enum):
    EXECUTIVE_ORCHESTRATION = "EXECUTIVE_ORCHESTRATION"
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    CONTENT_AND_DISTRIBUTION = "CONTENT_AND_DISTRIBUTION"
    CREATIVE_PRODUCTION = "CREATIVE_PRODUCTION"
    PERFORMANCE_AND_MEASUREMENT = "PERFORMANCE_AND_MEASUREMENT"


class EpistemicPosture(str, Enum):
    EVIDENCE_GOVERNANCE = "EVIDENCE_GOVERNANCE"
    EVIDENCE_DISCOVERY = "EVIDENCE_DISCOVERY"
    EVIDENCE_DEPENDENT_CONTENT = "EVIDENCE_DEPENDENT_CONTENT"
    EVIDENCE_DEPENDENT_CREATION = "EVIDENCE_DEPENDENT_CREATION"
    EMPIRICAL_MEASUREMENT = "EMPIRICAL_MEASUREMENT"


E = TypeVar("E", bound=Enum)
_TAG_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


_EXPECTED_FUNCTION: Dict[BrainAgentId, AgentFunction] = {
    BrainAgentId.CMO: AgentFunction.EXECUTIVE_ORCHESTRATION,
    BrainAgentId.INTELLIGENCE: AgentFunction.MARKET_INTELLIGENCE,
    BrainAgentId.CONTENT: AgentFunction.CONTENT_AND_DISTRIBUTION,
    BrainAgentId.CREATIVE: AgentFunction.CREATIVE_PRODUCTION,
    BrainAgentId.PERFORMANCE: AgentFunction.PERFORMANCE_AND_MEASUREMENT,
}

_EXPECTED_EPISTEMIC_POSTURE: Dict[BrainAgentId, EpistemicPosture] = {
    BrainAgentId.CMO: EpistemicPosture.EVIDENCE_GOVERNANCE,
    BrainAgentId.INTELLIGENCE: EpistemicPosture.EVIDENCE_DISCOVERY,
    BrainAgentId.CONTENT: EpistemicPosture.EVIDENCE_DEPENDENT_CONTENT,
    BrainAgentId.CREATIVE: EpistemicPosture.EVIDENCE_DEPENDENT_CREATION,
    BrainAgentId.PERFORMANCE: EpistemicPosture.EMPIRICAL_MEASUREMENT,
}


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _enum(value: object, enum_cls: Type[E], field_name: str) -> E:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().upper())
        except ValueError:
            pass
    raise ValidationError(
        f"{field_name} must be one of: {', '.join(item.value for item in enum_cls)}"
    )


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field_name} must be a boolean")
    return value


def _semantic_tags(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of semantic tags")
    result: List[str] = []
    seen = set()
    for raw in value:
        tag = _required_text(raw, field_name)
        if not _TAG_RE.fullmatch(tag):
            raise ValidationError(
                f"{field_name} entries must be UPPER_SNAKE_CASE semantic identifiers"
            )
        if tag in seen:
            raise ValidationError(f"duplicate {field_name} entry: {tag}")
        seen.add(tag)
        result.append(tag)
    if not result:
        raise ValidationError(f"{field_name} must contain at least one semantic tag")
    return result


def resolve_permanent_agent(value: object) -> BrainAgentId:
    """Resolve one of the five canonical identities, with one legacy read alias.

    ``STRATEGIST`` was used by historical snapshots before the product contract
    was corrected. It is accepted only as an input compatibility label and is
    immediately normalized to CONTENT; it never becomes a sixth identity.
    """

    if isinstance(value, BrainAgentId):
        return value
    if isinstance(value, str) and value.strip():
        normalized = value.strip().upper()
        if normalized == "STRATEGIST":
            return BrainAgentId.CONTENT
        try:
            return BrainAgentId(normalized)
        except ValueError:
            pass
    raise ValidationError(
        "agent_id must be one of exactly five permanent agents: "
        + ", ".join(agent.value for agent in BrainAgentId)
    )


def _handoff_targets(value: object, owner: BrainAgentId) -> List[BrainAgentId]:
    if not isinstance(value, list):
        raise ValidationError("primary_handoff_targets must be a list")
    result: List[BrainAgentId] = []
    seen = set()
    for raw in value:
        target = resolve_permanent_agent(raw)
        if target == owner:
            raise ValidationError("primary_handoff_targets cannot contain the profile itself")
        if target in seen:
            raise ValidationError(f"duplicate primary handoff target: {target.value}")
        seen.add(target)
        result.append(target)
    if not result:
        raise ValidationError("primary_handoff_targets must contain at least one peer")
    return result


class AgentDNAProfile(BaseModel):
    """Stable semantic authority profile for one permanent marketing agent."""

    agent_id: BrainAgentId
    function: AgentFunction
    mission: str
    epistemic_posture: EpistemicPosture
    owned_responsibilities: List[str] = Field(default_factory=list)
    forbidden_authorities: List[str] = Field(default_factory=list)
    primary_handoff_targets: List[BrainAgentId] = Field(default_factory=list)
    commercial_signoff_authority: bool = False
    live_execution_authority: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        self.agent_id = resolve_permanent_agent(self.agent_id)
        self.function = _enum(self.function, AgentFunction, "function")
        self.epistemic_posture = _enum(
            self.epistemic_posture, EpistemicPosture, "epistemic_posture"
        )
        self.mission = _required_text(self.mission, "mission")
        self.owned_responsibilities = _semantic_tags(
            self.owned_responsibilities, "owned_responsibilities"
        )
        self.forbidden_authorities = _semantic_tags(
            self.forbidden_authorities, "forbidden_authorities"
        )
        self.primary_handoff_targets = _handoff_targets(
            self.primary_handoff_targets, self.agent_id
        )
        self.commercial_signoff_authority = _strict_bool(
            self.commercial_signoff_authority, "commercial_signoff_authority"
        )
        self.live_execution_authority = _strict_bool(
            self.live_execution_authority, "live_execution_authority"
        )

        expected_function = _EXPECTED_FUNCTION[self.agent_id]
        if self.function != expected_function:
            raise ValidationError(
                f"{self.agent_id.value} function must remain {expected_function.value}"
            )

        expected_posture = _EXPECTED_EPISTEMIC_POSTURE[self.agent_id]
        if self.epistemic_posture != expected_posture:
            raise ValidationError(
                f"{self.agent_id.value} epistemic_posture must remain {expected_posture.value}"
            )

        should_signoff = self.agent_id == BrainAgentId.CMO
        if self.commercial_signoff_authority != should_signoff:
            raise ValidationError(
                "semantic commercial sign-off authority belongs only to CMO"
            )

        if self.live_execution_authority:
            raise ValidationError(
                "Brain DNA cannot grant live execution authority; execution is a governed Body responsibility"
            )

        overlap = set(self.owned_responsibilities) & set(self.forbidden_authorities)
        if overlap:
            raise ValidationError(
                "owned_responsibilities and forbidden_authorities cannot overlap: "
                + ", ".join(sorted(overlap))
            )


_CANONICAL_PROFILES: Dict[BrainAgentId, AgentDNAProfile] = {
    BrainAgentId.CMO: AgentDNAProfile(
        agent_id=BrainAgentId.CMO,
        function=AgentFunction.EXECUTIVE_ORCHESTRATION,
        mission=(
            "Own marketing strategy and commercial governance, decompose goals for "
            "specialists, audit evidence quality, and integrate specialist outputs."
        ),
        epistemic_posture=EpistemicPosture.EVIDENCE_GOVERNANCE,
        owned_responsibilities=[
            "TASK_DECOMPOSITION",
            "COMMERCIAL_GOVERNANCE",
            "MARKETING_STRATEGY_FORMULATION",
            "POSITIONING_AND_GTM_GOVERNANCE",
            "SPECIALIST_QUALITY_REVIEW",
            "RESOURCE_ALLOCATION_REASONING",
        ],
        forbidden_authorities=[
            "PRIMARY_MARKET_RESEARCH",
            "PRIMARY_CONTENT_PRODUCTION",
            "PRIMARY_CREATIVE_PRODUCTION",
            "PRIMARY_PERFORMANCE_ANALYSIS",
            "LIVE_EXECUTION",
        ],
        primary_handoff_targets=[
            BrainAgentId.INTELLIGENCE,
            BrainAgentId.CONTENT,
            BrainAgentId.CREATIVE,
            BrainAgentId.PERFORMANCE,
        ],
        commercial_signoff_authority=True,
        live_execution_authority=False,
    ),
    BrainAgentId.INTELLIGENCE: AgentDNAProfile(
        agent_id=BrainAgentId.INTELLIGENCE,
        function=AgentFunction.MARKET_INTELLIGENCE,
        mission=(
            "Reduce commercial uncertainty through research, source verification, "
            "contradiction discovery, and evidence-grounded market synthesis."
        ),
        epistemic_posture=EpistemicPosture.EVIDENCE_DISCOVERY,
        owned_responsibilities=[
            "EVIDENCE_DISCOVERY",
            "SOURCE_VERIFICATION",
            "UNCERTAINTY_REDUCTION",
            "CONTRADICTION_DISCOVERY",
        ],
        forbidden_authorities=[
            "FINAL_COMMERCIAL_SIGNOFF",
            "PRIMARY_STRATEGY_FORMULATION",
            "PRIMARY_CONTENT_PRODUCTION",
            "PRIMARY_CREATIVE_PRODUCTION",
            "PRIMARY_INTERNAL_PERFORMANCE_ANALYSIS",
            "LIVE_EXECUTION",
        ],
        primary_handoff_targets=[
            BrainAgentId.CONTENT,
            BrainAgentId.CMO,
        ],
        commercial_signoff_authority=False,
        live_execution_authority=False,
    ),
    BrainAgentId.CONTENT: AgentDNAProfile(
        agent_id=BrainAgentId.CONTENT,
        function=AgentFunction.CONTENT_AND_DISTRIBUTION,
        mission=(
            "Turn verified evidence and CMO strategy into truthful messaging systems, "
            "editorial plans, copy, scripts, SEO briefs, and channel-ready content."
        ),
        epistemic_posture=EpistemicPosture.EVIDENCE_DEPENDENT_CONTENT,
        owned_responsibilities=[
            "CONTENT_STRATEGY",
            "MESSAGE_ARCHITECTURE",
            "COPY_AND_SCRIPT",
            "EDITORIAL_PLANNING",
            "SEO_CONTENT_BRIEFING",
            "CHANNEL_CONTENT_ADAPTATION",
        ],
        forbidden_authorities=[
            "PRIMARY_MARKET_RESEARCH",
            "FINAL_COMMERCIAL_SIGNOFF",
            "PRIMARY_CREATIVE_ASSET_PRODUCTION",
            "PRIMARY_PERFORMANCE_ANALYSIS",
            "INVENT_PRODUCT_OR_EVIDENCE_FACTS",
            "LIVE_EXECUTION",
        ],
        primary_handoff_targets=[
            BrainAgentId.CMO,
            BrainAgentId.CREATIVE,
            BrainAgentId.PERFORMANCE,
        ],
        commercial_signoff_authority=False,
        live_execution_authority=False,
    ),
    BrainAgentId.CREATIVE: AgentDNAProfile(
        agent_id=BrainAgentId.CREATIVE,
        function=AgentFunction.CREATIVE_PRODUCTION,
        mission=(
            "Translate approved evidence-backed messaging into visual concepts, "
            "storyboards, asset systems, and production specifications."
        ),
        epistemic_posture=EpistemicPosture.EVIDENCE_DEPENDENT_CREATION,
        owned_responsibilities=[
            "CONCEPT_DEVELOPMENT",
            "VISUAL_DIRECTION",
            "CREATIVE_PRODUCTION_SPECIFICATION",
            "ASSET_SYSTEM_DESIGN",
        ],
        forbidden_authorities=[
            "PRIMARY_MARKET_RESEARCH",
            "PRIMARY_CONTENT_STRATEGY",
            "PRIMARY_COPY_OWNERSHIP",
            "FINAL_COMMERCIAL_SIGNOFF",
            "PRIMARY_PERFORMANCE_ANALYSIS",
            "INVENT_PRODUCT_OR_EVIDENCE_FACTS",
            "LIVE_EXECUTION",
        ],
        primary_handoff_targets=[
            BrainAgentId.CONTENT,
            BrainAgentId.PERFORMANCE,
            BrainAgentId.CMO,
        ],
        commercial_signoff_authority=False,
        live_execution_authority=False,
    ),
    BrainAgentId.PERFORMANCE: AgentDNAProfile(
        agent_id=BrainAgentId.PERFORMANCE,
        function=AgentFunction.PERFORMANCE_AND_MEASUREMENT,
        mission=(
            "Validate measurement integrity, diagnose funnels and experiments, quantify "
            "commercial performance, and return evidence-backed learning to the team."
        ),
        epistemic_posture=EpistemicPosture.EMPIRICAL_MEASUREMENT,
        owned_responsibilities=[
            "MEASUREMENT_VALIDATION",
            "FUNNEL_DIAGNOSIS",
            "EXPERIMENT_ANALYSIS",
            "LEARNING_EXTRACTION",
        ],
        forbidden_authorities=[
            "PRIMARY_MARKET_RESEARCH",
            "FINAL_COMMERCIAL_SIGNOFF",
            "PRIMARY_CONTENT_PRODUCTION",
            "PRIMARY_CREATIVE_PRODUCTION",
            "LIVE_EXECUTION",
        ],
        primary_handoff_targets=[
            BrainAgentId.CMO,
            BrainAgentId.CONTENT,
            BrainAgentId.CREATIVE,
        ],
        commercial_signoff_authority=False,
        live_execution_authority=False,
    ),
}


def get_agent_profile(agent_id: object) -> AgentDNAProfile:
    """Return a detached copy so callers cannot mutate canonical policy authority."""

    resolved = resolve_permanent_agent(agent_id)
    return _CANONICAL_PROFILES[resolved].model_copy(deep=True)


def canonical_agent_profiles() -> List[AgentDNAProfile]:
    """Return detached canonical profiles in stable five-agent order."""

    order = (
        BrainAgentId.CMO,
        BrainAgentId.INTELLIGENCE,
        BrainAgentId.CONTENT,
        BrainAgentId.CREATIVE,
        BrainAgentId.PERFORMANCE,
    )
    return [_CANONICAL_PROFILES[agent_id].model_copy(deep=True) for agent_id in order]
