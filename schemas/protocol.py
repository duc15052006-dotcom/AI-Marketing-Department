"""Agent Communication Protocol and Envelope Schemas.

Implements the standard typed task envelope, epistemic tiers,
agent execution lifecycle models, collaboration traces, contradiction records,
and governance models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from schemas.base import BaseModel, Field, ValidationError, field_validator


class EpistemicType(str, Enum):
    """The four strict epistemic tiers of agent statements."""
    FACT = "FACT"
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"


class AgentRole(str, Enum):
    """The five permanent marketing agents."""
    CMO = "CMO"
    INTELLIGENCE = "INTELLIGENCE"
    STRATEGIST = "STRATEGIST"
    CREATIVE = "CREATIVE"
    PERFORMANCE = "PERFORMANCE"


class TaskStatus(str, Enum):
    """Status lifecycle of an agent task."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    REJECTED = "REJECTED"


class HandoffType(str, Enum):
    """Classification of inter-agent collaboration handoffs."""
    DELEGATION = "DELEGATION"
    EVIDENCE_REQUEST = "EVIDENCE_REQUEST"
    REVIEW_FEEDBACK = "REVIEW_FEEDBACK"
    STRATEGIC_DIRECTIVE = "STRATEGIC_DIRECTIVE"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DECISION_PROPOSAL = "DECISION_PROPOSAL"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"


class PermissionMode(str, Enum):
    """Operational autonomy and permission modes."""
    MANUAL = "MANUAL"
    SUPERVISED = "SUPERVISED"
    AUTONOMOUS = "AUTONOMOUS"


class ApprovalState(str, Enum):
    """State of an operational action request."""
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_REQUIRED = "NOT_REQUIRED"


class LearningTier(str, Enum):
    """Promotion governance tiers for organizational learnings."""
    OBSERVATION = "OBSERVATION"
    CANDIDATE_LEARNING = "CANDIDATE_LEARNING"
    VALIDATED_LEARNING = "VALIDATED_LEARNING"


class TaskEnvelope(BaseModel):
    """Standard task envelope for all inter-agent communication."""
    task_id: str = Field(..., description="Unique task identifier, e.g. TASK-20260816-001")
    parent_task_id: Optional[str] = Field(None, description="Parent task ID if delegated, null if root task")
    objective: str = Field(..., min_length=5, description="Clear, unambiguous objective statement")
    business_context: str = Field(..., description="Strategic context and rationale")
    product_id: str = Field(..., description="Target product ID for workspace isolation")
    brand_id: str = Field(..., description="Target brand ID")

    # Epistemic declarations
    known_facts: List[str] = Field(default_factory=list, description="Verified facts")
    unknown_facts: List[str] = Field(default_factory=list, description="Identified knowledge gaps")
    assumptions: List[str] = Field(default_factory=list, description="Working assumptions")
    hypotheses: List[str] = Field(default_factory=list, description="Falsifiable hypotheses to test")

    # Ownership and access
    owner_agent: AgentRole = Field(..., description="Primary agent responsible for task execution")
    supporting_agents: List[AgentRole] = Field(default_factory=list, description="Supporting agents")

    tools_allowed: List[str] = Field(default_factory=list, description="Whitelisted tools permitted for this task")
    data_allowed: List[str] = Field(default_factory=list, description="Whitelisted filesystem or memory paths")

    # Quality and acceptance criteria
    evidence_required: bool = Field(default=True, description="Whether claims must link to verified evidence")
    output_schema: str = Field(..., description="Expected output entity or schema name")
    success_criteria: List[str] = Field(default_factory=list, description="Measurable checklist of completion")

    # Confidence and risk
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence rating between 0.0 and 1.0")
    risks: List[str] = Field(default_factory=list, description="Identified risks")
    blockers: List[str] = Field(default_factory=list, description="Current blockers")

    # Flow control
    escalation_rule: str = Field(..., description="Condition under which task must escalate")
    next_action: str = Field(..., description="Next downstream stage upon task completion")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("confidence")
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValidationError("Confidence must be between 0.0 and 1.0")
        return v


class EpistemicStatement(BaseModel):
    """An individual statement strictly classified into an epistemic tier."""
    tier: EpistemicType = Field(..., description="FACT, OBSERVATION, INFERENCE, or HYPOTHESIS")
    statement: str = Field(..., min_length=3)
    evidence_references: List[str] = Field(default_factory=list, description="Evidence or Source IDs")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AgentResult(BaseModel):
    """Standardized output payload returned by an agent upon task completion."""
    task_id: str = Field(..., description="Referenced task ID")
    owner_agent: AgentRole = Field(..., description="Agent role")
    status: TaskStatus = Field(default=TaskStatus.COMPLETED)
    payload: dict[str, Any] = Field(default_factory=dict, description="Structured output payload")
    epistemic_breakdown: List[EpistemicStatement] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    execution_duration_seconds: float = Field(ge=0.0, default=0.0)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None


class CollaborationTrace(BaseModel):
    """Auditable collaboration record tracking handoffs across agents without exposing private chain-of-thought."""
    trace_id: str = Field(..., description="Unique trace identifier, e.g. TRACE-20260816-0001")
    task_id: str = Field(..., description="Associated task identifier")
    from_agent: AgentRole = Field(..., description="Originating agent role")
    to_agent: AgentRole = Field(..., description="Receiving agent role")
    handoff_type: HandoffType = Field(..., description="Type of collaborative handoff")
    input_summary: str = Field(..., description="Concise, decision-useful summary of inputs")
    facts_preserved: List[str] = Field(default_factory=list, description="Verified facts passed downstream")
    assumptions_preserved: List[str] = Field(default_factory=list, description="Explicit assumptions passed downstream")
    unknowns_preserved: List[str] = Field(default_factory=list, description="Explicit unknowns passed downstream")
    output_reference: Optional[str] = Field(None, description="Path or identifier of resulting output entity")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: TaskStatus = Field(default=TaskStatus.COMPLETED)


class ContradictionRecord(BaseModel):
    """Formal record preserving cross-agent disagreements for CMO resolution."""
    conflict_id: str = Field(..., description="Unique conflict identifier")
    claim_a: str = Field(..., description="First competing assertion")
    agent_a: AgentRole = Field(..., description="Agent advocating Claim A")
    evidence_a: List[str] = Field(default_factory=list, description="Evidence references supporting Claim A")
    claim_b: str = Field(..., description="Second competing assertion")
    agent_b: AgentRole = Field(..., description="Agent advocating Claim B")
    evidence_b: List[str] = Field(default_factory=list, description="Evidence references supporting Claim B")
    type_of_conflict: str = Field(..., description="Category: e.g. FEASIBILITY_VS_CREATIVE, DEMAND_VS_UNIT_ECONOMICS")
    missing_evidence: List[str] = Field(default_factory=list, description="Information required to objectively settle")
    resolution_owner: AgentRole = Field(default=AgentRole.CMO, description="Executive decider (CMO)")
    resolution_outcome: Optional[str] = Field(
        None,
        description="ACCEPT_A | ACCEPT_B | LIMITED_TEST | REQUEST_MORE_EVIDENCE | DEFER | REJECT_BOTH"
    )
    resolution_rationale: Optional[str] = Field(None, description="Documented business rationale for resolution")


class ActionRequest(BaseModel):
    """Operational mutation or publishing request governed by the permission engine."""
    action_id: str = Field(..., description="Unique action identifier")
    agent_name: AgentRole = Field(..., description="Agent requesting the operation")
    product_id: str = Field(..., description="Target product context")
    campaign_id: str = Field(..., description="Target campaign context")
    platform_target: str = Field(..., description="Platform target, e.g. Meta Ads API, TikTok API")
    requested_action: str = Field(..., description="Exact mutation requested")
    permission_mode: PermissionMode = Field(default=PermissionMode.SUPERVISED)
    approval_state: ApprovalState = Field(default=ApprovalState.PENDING_APPROVAL)
    payload: dict[str, Any] = Field(default_factory=dict, description="Execution parameters")
    risks: List[str] = Field(default_factory=list, description="Financial or brand risks")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CandidateLearningRecord(BaseModel):
    """Structured organizational learning proposal subject to CMO promotion governance."""
    learning_id: str = Field(..., description="Unique learning identifier")
    tier: LearningTier = Field(default=LearningTier.CANDIDATE_LEARNING)
    product_id: str = Field(..., description="Originating product ID")
    audience_segment: str = Field(..., description="Target audience cohort")
    channel_and_format: str = Field(..., description="Platform, placement, and format")
    creative_component: str = Field(..., description="Specific creative or strategic mechanism")
    empirical_observation: str = Field(..., description="Exact metric telemetry and sample size")
    validated_insight: str = Field(..., description="Underlying commercial or customer truth")
    confounders_monitored: List[str] = Field(default_factory=list, description="Monitored confounding factors")
    scope_of_applicability: str = Field(..., description="Specific domain/category boundaries where valid")
    retest_required: bool = Field(default=True, description="Whether re-testing is mandatory before permanent validation")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
