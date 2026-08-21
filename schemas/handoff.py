"""Inter-Agent Grounded Handoff Contracts (Phase 3D.2 / 3D.2.1).

Defines typed, bounded handoff contracts between specialized agents:
- GroundedIntelligenceHandoff (Intelligence -> Strategist)
- StrategicRecommendation & StrategicExperiment
- StrategicClaimType & MetricBaselineStatus
- StrategyEvaluationRecord
Enforces epistemic inheritance (uncertainties remain uncertain) and filters ungrounded claims.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional
import uuid
from schemas.base import BaseModel, Field


class RecommendationGroundingStatus(str, Enum):
    GROUNDED = "GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    UNGROUNDED = "UNGROUNDED"
    CONTRADICTED = "CONTRADICTED"


class StrategicClaimType(str, Enum):
    """Explicit epistemic classification of strategic assertions."""
    EVIDENCE_BACKED_RECOMMENDATION = "EVIDENCE_BACKED_RECOMMENDATION"
    STRATEGIC_INFERENCE = "STRATEGIC_INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    ASSUMPTION = "ASSUMPTION"
    FIRST_PARTY_CLAIM = "FIRST_PARTY_CLAIM"
    UNKNOWN = "UNKNOWN"


class MetricBaselineStatus(str, Enum):
    """Epistemic baseline classification for performance and experiment metrics."""
    EMPIRICAL_METRIC = "EMPIRICAL_METRIC"
    ASSUMED_TEST_THRESHOLD = "ASSUMED_TEST_THRESHOLD"
    HYPOTHESIZED_EFFECT = "HYPOTHESIZED_EFFECT"
    TO_BE_ESTABLISHED = "TO_BE_ESTABLISHED"


class StrategicExperiment(BaseModel):
    """Falsifiable tactical or positioning experiment designed by Strategist."""
    experiment_id: str = Field(default_factory=lambda: f"EXP-{uuid.uuid4().hex[:8].upper()}")
    hypothesis: str
    target_segment: str
    change_or_treatment: str
    primary_metric: str
    metric_status: MetricBaselineStatus = MetricBaselineStatus.TO_BE_ESTABLISHED
    secondary_metrics: List[str] = Field(default_factory=list)
    expected_signal: str
    time_or_sample_requirement: str
    stop_condition: str
    evidence_dependency: List[str] = Field(default_factory=list)


class StrategicRecommendation(BaseModel):
    """Structured strategic recommendation with backward traceability to evidence."""
    rec_id: str = Field(default_factory=lambda: f"STRAT-{uuid.uuid4().hex[:6].upper()}")
    title: str
    recommendation: str
    rationale: str
    claim_type: StrategicClaimType = StrategicClaimType.STRATEGIC_INFERENCE
    supported_by: List[str] = Field(default_factory=list, description="Cited Evidence IDs")
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    validation_test: str = ""
    stop_or_reconsider_condition: str = ""
    epistemic_tier: str = "INFERENCE"  # OBSERVATION | INFERENCE | HYPOTHESIS
    grounding_status: RecommendationGroundingStatus = RecommendationGroundingStatus.GROUNDED


class GroundedIntelligenceHandoff(BaseModel):
    """Clean, typed handoff contract from Intelligence Agent to Strategist Agent."""
    handoff_id: str = Field(default_factory=lambda: f"HNDF-INTEL-{uuid.uuid4().hex[:8].upper()}")
    task_id: str
    product_id: str
    brand_id: str
    research_question: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Evidence-backed validated findings (Filtered: only SUPPORTED and PARTIALLY_SUPPORTED claims)
    validated_findings: List[str] = Field(default_factory=list)
    facts: List[str] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    inferences: List[str] = Field(default_factory=list)
    hypotheses: List[str] = Field(default_factory=list)

    dimension_findings: Dict[str, Any] = Field(default_factory=dict)
    known_unknowns: List[str] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)

    confidence: str = "MEDIUM"
    confidence_rationale: str = ""
    research_limitations: List[str] = Field(default_factory=list)
    next_research_actions: str = ""


class GroundedStrategyOutput(BaseModel):
    """Complete structured output from Strategist agent."""
    summary: str
    target_segments: Dict[str, Any] = Field(default_factory=dict)  # observed vs hypothesized
    positioning: Dict[str, Any] = Field(default_factory=dict)
    value_proposition: Dict[str, Any] = Field(default_factory=dict)
    channel_priorities: Dict[str, Any] = Field(default_factory=dict)  # primary, secondary, deferred
    top_3_priorities: List[str] = Field(default_factory=list)
    what_not_to_do: List[str] = Field(default_factory=list)
    recommendations: List[StrategicRecommendation] = Field(default_factory=list)
    experiments: List[StrategicExperiment] = Field(default_factory=list)
    unknown_or_required_research: List[str] = Field(default_factory=list)
    confidence: str = "MEDIUM"
    confidence_rationale: str = ""


class GroundedCreativeBrief(BaseModel):
    """Clean, typed handoff contract from Strategist Agent to Creative Agent."""
    brief_id: str = Field(default_factory=lambda: f"BRIEF-STRAT-{uuid.uuid4().hex[:8].upper()}")
    task_id: str
    product_id: str
    brand_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    business_objective: str
    target_segments: Dict[str, Any] = Field(default_factory=dict)
    positioning: Dict[str, Any] = Field(default_factory=dict)
    value_proposition: str
    strategic_priorities: List[str] = Field(default_factory=list)
    deferred_channels: List[str] = Field(default_factory=list)
    what_not_to_do: List[str] = Field(default_factory=list)

    validated_recommendations: List[StrategicRecommendation] = Field(default_factory=list)
    strategic_hypotheses: List[str] = Field(default_factory=list)
    experiments: List[StrategicExperiment] = Field(default_factory=list)

    known_unknowns: List[str] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)
    claim_strength_constraints: List[str] = Field(default_factory=list)
    first_party_claims: List[str] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)

    creative_constraints: List[str] = Field(default_factory=list)
    success_definition: str = ""


class CreativeToPerformanceHandoff(BaseModel):
    """Handoff contract from Creative Agent to Performance Marketing Agent."""
    handoff_id: str = Field(default_factory=lambda: f"HNDF-CREATIVE-PERF-{uuid.uuid4().hex[:8].upper()}")
    task_id: str
    product_id: str
    brand_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    creative_asset_ids: List[str] = Field(default_factory=list)
    variant_ids: List[str] = Field(default_factory=list)
    creative_hypotheses: List[str] = Field(default_factory=list)
    target_segments: List[str] = Field(default_factory=list)
    message_variables: List[str] = Field(default_factory=list)
    cta_variables: List[str] = Field(default_factory=list)
    measurement_requirements: List[str] = Field(default_factory=list)
    unknown_baselines: List[str] = Field(default_factory=list)
    recommended_metrics: List[str] = Field(default_factory=list)
    evidence_lineage: Dict[str, Any] = Field(default_factory=dict)


class GroundedPerformanceBrief(BaseModel):
    """Clean, typed handoff contract into the Performance Marketing Agent."""
    brief_id: str = Field(default_factory=lambda: f"BRIEF-PERF-{uuid.uuid4().hex[:8].upper()}")
    task_id: str
    product_id: str
    brand_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    business_objective: str
    target_segments: Dict[str, Any] = Field(default_factory=dict)
    creative_asset_ids: List[str] = Field(default_factory=list)
    variant_ids: List[str] = Field(default_factory=list)
    creative_hypotheses: List[str] = Field(default_factory=list)
    message_variables: List[str] = Field(default_factory=list)
    hook_variables: List[str] = Field(default_factory=list)
    cta_variables: List[str] = Field(default_factory=list)
    channel_hypotheses: List[str] = Field(default_factory=list)

    known_unknowns: List[str] = Field(default_factory=list)
    unknown_baselines: List[str] = Field(default_factory=list)
    evidence_lineage: Dict[str, Any] = Field(default_factory=dict)
    strategy_lineage: Dict[str, Any] = Field(default_factory=dict)
    measurement_requirements: List[str] = Field(default_factory=list)
    creative_constraints: List[str] = Field(default_factory=list)
    claim_constraints: List[str] = Field(default_factory=list)


class PerformanceToCMOHandoff(BaseModel):
    """Handoff contract from Performance Marketing Agent to CMO Master Orchestrator."""
    handoff_id: str = Field(default_factory=lambda: f"HNDF-PERF-CMO-{uuid.uuid4().hex[:8].upper()}")
    task_id: str
    product_id: str
    brand_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    business_objective: str
    measurement_framework: Dict[str, Any] = Field(default_factory=dict)
    channel_priorities: Dict[str, Any] = Field(default_factory=dict)
    performance_hypotheses: List[str] = Field(default_factory=list)
    experiment_portfolio: List[Dict[str, Any]] = Field(default_factory=list)
    creative_variant_tests: List[Dict[str, Any]] = Field(default_factory=list)
    known_unknowns: List[str] = Field(default_factory=list)
    required_instrumentation: List[str] = Field(default_factory=list)
    economics_unknowns: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    decision_rules: List[Dict[str, Any]] = Field(default_factory=list)
    escalations: List[str] = Field(default_factory=list)
    candidate_learnings: List[Dict[str, Any]] = Field(default_factory=list)

    evidence_lineage: Dict[str, Any] = Field(default_factory=dict)
    strategy_lineage: Dict[str, Any] = Field(default_factory=dict)
    creative_lineage: Dict[str, Any] = Field(default_factory=dict)
    performance_confidence: str = "MEDIUM"


class GroundedCMOBrief(BaseModel):
    """Clean, typed handoff contract into the CMO Master Orchestrator."""
    brief_id: str = Field(default_factory=lambda: f"BRIEF-CMO-{uuid.uuid4().hex[:8].upper()}")
    task_id: str
    product_id: str
    brand_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    business_objective: str
    validated_intelligence_findings: List[str] = Field(default_factory=list)
    strategy_recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    creative_assets: Dict[str, Any] = Field(default_factory=dict)
    creative_hypotheses: List[str] = Field(default_factory=list)
    performance_hypotheses: List[str] = Field(default_factory=list)
    measurement_framework: Dict[str, Any] = Field(default_factory=dict)
    experiment_portfolio: List[Dict[str, Any]] = Field(default_factory=list)
    channel_priorities: Dict[str, Any] = Field(default_factory=dict)
    decision_rules: List[Dict[str, Any]] = Field(default_factory=list)

    known_unknowns: List[str] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)
    economics_unknowns: List[str] = Field(default_factory=list)
    budget_status: str = "NOT_CONFIGURED"
    stop_loss_status: str = "NOT_CONFIGURED"
    risks: List[str] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    candidate_learnings: List[Dict[str, Any]] = Field(default_factory=list)

    evidence_lineage: Dict[str, Any] = Field(default_factory=dict)
    strategy_lineage: Dict[str, Any] = Field(default_factory=dict)
    creative_lineage: Dict[str, Any] = Field(default_factory=dict)
    performance_lineage: Dict[str, Any] = Field(default_factory=dict)
    approval_requirements: List[str] = Field(default_factory=list)


class PerformanceHandoffPayload(BaseModel):
    """Structured Performance Marketing & Analytics handoff contract (Phase 4.3C.15 / Brain RC3)."""
    funnel_model: Dict[str, Any] = Field(default_factory=dict, description="Funnel stages, primary KPI per stage, leading indicators, guardrails")
    kpi_tree: Dict[str, Any] = Field(default_factory=dict, description="North star metric, secondary metrics, guardrail ceiling")
    attribution_architecture: Dict[str, Any] = Field(default_factory=dict, description="Event taxonomy, UTM parameters, identity strategy, conversion events, attribution model")
    tracking_requirements: List[str] = Field(default_factory=list, description="Specific tracking tags, SDK telemetry, server-side CAPI")
    experiment_backlog: List[Dict[str, Any]] = Field(default_factory=list, description="Structured experiment blueprints: hypothesis, intervention, audience, metric, decision rule")
    decision_rules: List[Dict[str, Any]] = Field(default_factory=list, description="Go / Test / Hold / Defer decision criteria")
    risks_and_guardrails: List[str] = Field(default_factory=list, description="Identified performance risks and guardrail ceilings")
    governance_requirements: List[str] = Field(default_factory=list, description="Metric owners, approval owners, claim sign-off, launch/pause triggers")
    human_approvals: List[str] = Field(default_factory=list, description="Explicit human approval requirements")
    unresolved_measurement_gaps: List[str] = Field(default_factory=list, description="Baselines required before scaling")

    def validate_completeness(self) -> Tuple[bool, List[str]]:
        """Validate 100% presence of mandatory top-level performance handoff fields."""
        missing = []
        if not self.funnel_model:
            missing.append("funnel_model")
        if not self.kpi_tree:
            missing.append("kpi_tree")
        if not self.attribution_architecture:
            missing.append("attribution_architecture")
        if not self.experiment_backlog:
            missing.append("experiment_backlog")
        if not self.governance_requirements:
            missing.append("governance_requirements")
        if not self.human_approvals:
            missing.append("human_approvals")
        return (len(missing) == 0, missing)

    @classmethod
    def deterministic_merge(
        cls,
        pass_a_payload: Dict[str, Any],
        pass_b_payload: Dict[str, Any]
    ) -> "PerformanceHandoffPayload":
        """Deterministic code merge of Performance Pass A (Measurement + Attribution) and Pass B (Experiments + Governance)."""
        merged_data = {
            "funnel_model": pass_a_payload.get("funnel_model", {}),
            "kpi_tree": pass_a_payload.get("kpi_tree", {}),
            "attribution_architecture": pass_a_payload.get("attribution_architecture", {}),
            "tracking_requirements": pass_a_payload.get("tracking_requirements", []),
            "unresolved_measurement_gaps": pass_a_payload.get("unresolved_measurement_gaps", []),
            "experiment_backlog": pass_b_payload.get("experiment_backlog", []),
            "decision_rules": pass_b_payload.get("decision_rules", []),
            "risks_and_guardrails": pass_b_payload.get("risks_and_guardrails", []),
            "governance_requirements": pass_b_payload.get("governance_requirements", []),
            "human_approvals": pass_b_payload.get("human_approvals", []),
        }
        for list_key in ["unresolved_measurement_gaps", "risks_and_guardrails", "human_approvals", "governance_requirements"]:
            extra = pass_a_payload.get(list_key, []) if list_key in pass_b_payload else pass_b_payload.get(list_key, [])
            if extra and isinstance(extra, list):
                for item in extra:
                    if item not in merged_data[list_key]:
                        merged_data[list_key].append(item)
        return cls(**merged_data)


class PreservationItem(BaseModel):
    """Individual item tracked in the Anti-Information-Loss Preservation Ledger."""
    item_id: str = Field(default_factory=lambda: f"ITEM-{uuid.uuid4().hex[:6].upper()}")
    source_agent: str
    category: str
    description: str
    status: str = "PRESERVED"  # PRESERVED | SUPERSEDED_WITH_REASON | DEFERRED | UNRESOLVED
    reason: str = ""


class ContradictionResolutionRecord(BaseModel):
    """Governed cross-agent contradiction resolution record."""
    conflict_id: str = Field(default_factory=lambda: f"CONF-{uuid.uuid4().hex[:6].upper()}")
    agents_involved: List[str] = Field(default_factory=list)
    topic: str
    options: List[str] = Field(default_factory=list)
    decision: str
    decision_basis: str
    confidence: str = "HIGH"
    human_approval_required: bool = False


class PreservationLedger(BaseModel):
    """Anti-Information-Loss Synthesis Ledger verifying 100% material specialist decision survival."""
    intelligence_critical_items: List[PreservationItem] = Field(default_factory=list)
    strategy_critical_items: List[PreservationItem] = Field(default_factory=list)
    creative_critical_items: List[PreservationItem] = Field(default_factory=list)
    performance_critical_items: List[PreservationItem] = Field(default_factory=list)
    resolved_contradictions: List[ContradictionResolutionRecord] = Field(default_factory=list)

    def total_critical_items(self) -> int:
        return (
            len(self.intelligence_critical_items)
            + len(self.strategy_critical_items)
            + len(self.creative_critical_items)
            + len(self.performance_critical_items)
        )

    def preserved_items_count(self) -> int:
        all_items = (
            self.intelligence_critical_items
            + self.strategy_critical_items
            + self.creative_critical_items
            + self.performance_critical_items
        )
        return sum(1 for item in all_items if item.status in ("PRESERVED", "SUPERSEDED_WITH_REASON", "DEFERRED"))

    def audit_preservation_rate(self) -> float:
        total = self.total_critical_items()
        if total == 0:
            return 1.0
        return self.preserved_items_count() / float(total)


class HandoffPackage(BaseModel):
    """Structured, bounded inter-agent handoff package avoiding raw chat history bloat (Phase 4.3C.5 / RC2)."""
    handoff_id: str = Field(default_factory=lambda: f"HNDF-{uuid.uuid4().hex[:8].upper()}")
    task_id: str
    from_agent: str
    to_agent: str
    context_version: str = "v2"
    source_stage_refs: List[str] = Field(default_factory=list)
    product_id: str
    brand_id: str
    objective: str
    project_context: str = ""
    product_facts: List[str] = Field(default_factory=list)
    verified_evidence_refs: List[str] = Field(default_factory=list)
    upstream_findings: Dict[str, Any] = Field(default_factory=dict)
    upstream_decisions: Dict[str, Any] = Field(default_factory=dict)
    performance_payload: Optional[PerformanceHandoffPayload] = None
    preservation_ledger: Optional[PreservationLedger] = None
    hypotheses: List[str] = Field(default_factory=list)
    allowed_claims: List[str] = Field(default_factory=list)
    prohibited_claims: List[str] = Field(default_factory=list)
    unverified_claims: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    required_next_output: str
    claim_register_refs: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def format_prompt_section(self) -> str:
        """Render a concise, high-signal prompt section from the structured handoff."""
        lines = [
            f"=== STRUCTURED HANDOFF [{self.handoff_id}] ===",
            f"FROM: {self.from_agent} -> TO: {self.to_agent} (Context Version: {self.context_version})",
            f"SOURCE STAGES: {', '.join(self.source_stage_refs) if self.source_stage_refs else 'ROOT'}",
            f"TARGET PRODUCT: {self.product_id} (Brand: {self.brand_id})",
            f"OBJECTIVE: {self.objective}",
        ]
        if self.project_context:
            lines.append(f"PROJECT CONTEXT: {self.project_context}")

        if self.product_facts:
            lines.append("PRODUCT FACTS (VERIFIED GROUND TRUTH):")
            for f in self.product_facts:
                lines.append(f"  - {f}")

        if self.verified_evidence_refs:
            lines.append(f"VERIFIED EVIDENCE REFS: {', '.join(self.verified_evidence_refs)}")

        if self.upstream_findings:
            lines.append("UPSTREAM FINDINGS:")
            for k, v in self.upstream_findings.items():
                if isinstance(v, (list, dict)):
                    lines.append(f"  - {k}: {json.dumps(v, ensure_ascii=False)}")
                else:
                    lines.append(f"  - {k}: {v}")

        if self.upstream_decisions:
            lines.append("UPSTREAM STRATEGIC & CREATIVE DECISIONS:")
            for k, v in self.upstream_decisions.items():
                if isinstance(v, (list, dict)):
                    lines.append(f"  - {k}: {json.dumps(v, ensure_ascii=False)}")
                else:
                    lines.append(f"  - {k}: {v}")

        if self.performance_payload:
            lines.append("STRUCTURED PERFORMANCE BLUEPRINT (PRESERVED):")
            if self.performance_payload.funnel_model:
                lines.append(f"  - FUNNEL_MODEL: {json.dumps(self.performance_payload.funnel_model, ensure_ascii=False)}")
            if self.performance_payload.kpi_tree:
                lines.append(f"  - KPI_TREE: {json.dumps(self.performance_payload.kpi_tree, ensure_ascii=False)}")
            if self.performance_payload.attribution_architecture:
                lines.append(f"  - ATTRIBUTION_ARCHITECTURE: {json.dumps(self.performance_payload.attribution_architecture, ensure_ascii=False)}")
            if self.performance_payload.experiment_backlog:
                lines.append(f"  - EXPERIMENT_BACKLOG: {json.dumps(self.performance_payload.experiment_backlog, ensure_ascii=False)}")
            if self.performance_payload.decision_rules:
                lines.append(f"  - DECISION_RULES: {json.dumps(self.performance_payload.decision_rules, ensure_ascii=False)}")
            if self.performance_payload.risks_and_guardrails:
                lines.append(f"  - RISKS_AND_GUARDRAILS: {json.dumps(self.performance_payload.risks_and_guardrails, ensure_ascii=False)}")
            if self.performance_payload.governance_requirements:
                lines.append(f"  - GOVERNANCE_REQUIREMENTS: {json.dumps(self.performance_payload.governance_requirements, ensure_ascii=False)}")
            if self.performance_payload.human_approvals:
                lines.append(f"  - HUMAN_APPROVALS: {json.dumps(self.performance_payload.human_approvals, ensure_ascii=False)}")
            if self.performance_payload.unresolved_measurement_gaps:
                lines.append(f"  - UNRESOLVED_MEASUREMENT_GAPS: {json.dumps(self.performance_payload.unresolved_measurement_gaps, ensure_ascii=False)}")

        if self.preservation_ledger:
            lines.append("ANTI-INFORMATION-LOSS PRESERVATION LEDGER:")
            lines.append(f"  - TOTAL_CRITICAL_ITEMS: {self.preservation_ledger.total_critical_items()}")
            lines.append(f"  - PRESERVATION_RATE: {self.preservation_ledger.audit_preservation_rate() * 100.0:.1f}%")

        if self.hypotheses:
            lines.append("HYPOTHESES TO TEST / VALIDATE:")
            for h in self.hypotheses:
                lines.append(f"  - [HYPOTHESIS] {h}")

        if self.allowed_claims:
            lines.append("ALLOWED CLAIMS (APPROVED / SUPPORTED):")
            for c in self.allowed_claims:
                lines.append(f"  - {c}")

        if self.prohibited_claims:
            lines.append("PROHIBITED / DISALLOWED CLAIMS:")
            for c in self.prohibited_claims:
                lines.append(f"  - [PROHIBITED] {c}")

        if self.unverified_claims:
            lines.append("UNVERIFIED CLAIMS / UNKNOWNS:")
            for c in self.unverified_claims:
                lines.append(f"  - [UNKNOWN] {c}")

        if self.open_questions:
            lines.append("OPEN QUESTIONS / RESEARCH GAPS:")
            for q in self.open_questions:
                lines.append(f"  - {q}")

        if self.contradictions:
            lines.append("IDENTIFIED CONTRADICTIONS / TENSIONS:")
            for cd in self.contradictions:
                lines.append(f"  - {json.dumps(cd, ensure_ascii=False)}")

        if self.risks:
            lines.append("IDENTIFIED RISKS:")
            for r in self.risks:
                lines.append(f"  - {r}")

        lines.append(f"REQUIRED OUTPUT FOR THIS STAGE:\n{self.required_next_output}")
        lines.append("=== END STRUCTURED HANDOFF ===")
        return "\n".join(lines)




