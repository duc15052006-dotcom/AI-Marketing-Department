"""Candidate B5 (Single-Agent 4-Pass Control) and Fail-Closed Judge Protocol (Phase 4.3C.15)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("phase4_3c_15_protocol")

# =============================================================================
# 1. CANDIDATE B5 CONTROL: 4-PASS SINGLE-AGENT BOUNDED ARCHITECTURE
# =============================================================================

B5_LOGICAL_AGENT_COUNT = 1
B5_PASS_COUNT = 4
MAX_BOUNDED_STATE_CHARS = 3000  # ~750 tokens bounded working memory

def build_candidate_b5_pass_1_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any]) -> str:
    return f"""You are the Senior Strategic Marketing Director (Single-Agent Multi-Pass Control — Pass 1/4).

[SOURCE GROUNDING - PASS 1 OF 4: RESEARCH, SEGMENTATION & POSITIONING]
VERIFIED PRODUCT FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

PASS 1 OBJECTIVE: Produce comprehensive Research Synthesis, Verified Facts, Observations, Inferences, Unknowns, Customer Segmentation, Beachhead ICP, Positioning Architecture, and Value Proposition.

REQUIRED DELIVERABLES IN THIS PASS:
1. EXECUTIVE SUMMARY
2. RESEARCH FINDINGS (KNOWN_FACTS, OBSERVATIONS, INFERENCES, UNKNOWNS)
3. CUSTOMER SEGMENTS & TOP PRIORITY BEACHHEAD
4. POSITIONING & VALUE PROPOSITION
5. CHANNEL PRIORITIES & DEFERRED CHANNELS

At the end of your response, output a structured state block:
### BOUNDED WORKING STATE
[SOURCE_GROUNDING] Key verified facts and constraints
[STRATEGIC_STATE] Core positioning, beachhead, and channel choices
[EPISTEMIC_STATE] Verified vs unverified items
[DECISION_STATE] Core trade-offs resolved
[DELIVERABLE_PROGRESS] Pass 1 deliverables completed
"""

def build_candidate_b5_pass_2_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any], working_state: str) -> str:
    return f"""You are the Senior Strategic Marketing Director (Single-Agent Multi-Pass Control — Pass 2/4).

[SOURCE GROUNDING - PASS 2 OF 4: CREATIVE & MESSAGING]
VERIFIED PRODUCT FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

[CUMULATIVE BOUNDED WORKING STATE FROM PASS 1]
{working_state[:MAX_BOUNDED_STATE_CHARS]}

PASS 2 OBJECTIVE: Develop high-converting Creative Territories, Message Angles, Hooks, Short-Form Ad Copy Variants, and Production-Ready Video Scripts grounded strictly in verified product mechanics.

REQUIRED DELIVERABLES IN THIS PASS:
1. CREATIVE TERRITORIES (3 distinct territories + Selected Lead)
2. MESSAGE ANGLES & VALUE HOOKS (Top 5 scroll-stopping hooks)
3. SHORT-FORM AD COPY VARIANTS (PAS, Social Proof, Technical Demo)
4. FULL VIDEO SCRIPT (30s Video Ad with Visual, Audio, and Voiceover cues)

At the end of your response, update the structured state:
### BOUNDED WORKING STATE
[STRATEGIC_STATE] Strategic positioning and beachhead
[CREATIVE_STATE] Selected territory, lead hook, and script format
[DECISION_STATE] Creative choices resolved
[DELIVERABLE_PROGRESS] Pass 1 & 2 deliverables completed
"""

def build_candidate_b5_pass_3_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any], working_state: str) -> str:
    return f"""You are the Senior Strategic Marketing Director (Single-Agent Multi-Pass Control — Pass 3/4).

[SOURCE GROUNDING - PASS 3 OF 4: PERFORMANCE, MEASUREMENT & GOVERNANCE]
VERIFIED PRODUCT FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

[CUMULATIVE BOUNDED WORKING STATE FROM PASS 1 & 2]
{working_state[:MAX_BOUNDED_STATE_CHARS]}

PASS 3 OBJECTIVE: Design the Measurement Framework, Event Tracking Taxonomy, Multi-Touch Attribution Strategy, Experimentation Backlog with Decision Rules, Governance, Risk Mitigation, and Human Approvals.

REQUIRED DELIVERABLES IN THIS PASS:
1. FULL-FUNNEL MEASUREMENT FRAMEWORK & KPI TARGETS
2. ATTRIBUTION ARCHITECTURE & EVENT TAXONOMY (UTMs, Pixel, Telemetry)
3. STRUCTURED EXPERIMENTATION BACKLOG (Falsifiable hypotheses, metrics, stopping criteria)
4. GOVERNANCE & RISK MITIGATION (Metric owners, claim compliance, launch/pause triggers)
5. HUMAN APPROVAL REQUIREMENTS

At the end of your response, update the structured state:
### BOUNDED WORKING STATE
[PERFORMANCE_STATE] Full funnel KPIs, attribution, experiments, and governance
[DELIVERABLE_PROGRESS] Pass 1, 2 & 3 deliverables completed
"""

def build_candidate_b5_pass_4_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any], working_state: str) -> str:
    return f"""You are the Senior Strategic Marketing Director (Single-Agent Multi-Pass Control — Pass 4/4: Cross-Plan Integration & Consistency QA).

[SOURCE GROUNDING - PASS 4 OF 4: CROSS-PLAN INTEGRATION & QA]
VERIFIED PRODUCT FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

[CUMULATIVE BOUNDED WORKING STATE FROM PASS 1, 2 & 3]
{working_state[:MAX_BOUNDED_STATE_CHARS]}

PASS 4 OBJECTIVE: Perform rigorous cross-plan consistency checks, resolve any conflicting claims or assumptions, verify end-to-end deliverable alignment (Strategy -> Creative -> Performance), and produce the Final Executive Decision Matrix with Top 3 Immediate Actions.

REQUIRED DELIVERABLES IN THIS PASS:
1. CROSS-PLAN CONTRADICTION & CONSISTENCY AUDIT
2. WHAT-NOT-TO-DO GUARDRAILS & RISK CEILINGS
3. FINAL GO / TEST / HOLD / DEFER DECISION MATRIX
4. TOP 3 IMMEDIATE NEXT ACTIONS

At the end of your response, update the structured state:
### BOUNDED WORKING STATE
[FINAL_STATE] Strategy, Creative, Performance, and Executive Governance fully synthesized and finalized
"""


# =============================================================================
# 2. FAIL-CLOSED BLIND JUDGE PROTOCOL
# =============================================================================

JUDGE_FAILURE_POLICY = "FAIL_CLOSED"
MIN_VALID_JUDGE_PASSES = 3

FROZEN_14_DIMENSIONS = [
    {"id": "research_quality", "name": "1. Research Quality", "weight": 0.08, "desc": "Depth of technical problem framing, consumer friction analysis, and market reality synthesis."},
    {"id": "evidence_discipline", "name": "2. Evidence Discipline", "weight": 0.08, "desc": "Strict distinction between verified facts vs unverified claims; zero hallucinated statistics."},
    {"id": "segmentation_quality", "name": "3. Segmentation Quality", "weight": 0.08, "desc": "Actionability, consumer demographic/behavioral clarity, and prioritization of beachhead persona."},
    {"id": "positioning_quality", "name": "4. Positioning Quality", "weight": 0.08, "desc": "Technical differentiation and value proposition sharpness."},
    {"id": "channel_strategy", "name": "5. Channel Strategy", "weight": 0.07, "desc": "Realism of acquisition channel mix and clear deferred channels."},
    {"id": "creative_quality", "name": "6. Creative Quality", "weight": 0.07, "desc": "Originality and resonance of concept territories."},
    {"id": "copy_script_executability", "name": "7. Copy / Script Executability", "weight": 0.07, "desc": "Production readiness of short-form ad copy and video scripts."},
    {"id": "performance_funnel_metrics", "name": "8. Performance Funnel & Metrics", "weight": 0.07, "desc": "Clarity of full-funnel conversion benchmarks, CAC payback, and KPIs."},
    {"id": "experimentation_rigor", "name": "9. Experimentation Rigor", "weight": 0.07, "desc": "Scientific structure of hypotheses, sample sizing, and testable A/B designs."},
    {"id": "attribution_tracking", "name": "10. Attribution / Tracking", "weight": 0.07, "desc": "Multi-touch attribution, event taxonomy, and product telemetry tracking."},
    {"id": "claim_safety_compliance", "name": "11. Claim Safety / Compliance", "weight": 0.08, "desc": "Absolute zero prohibited claims (no medical cures, no ungrounded guarantees)."},
    {"id": "governance_human_approval", "name": "12. Governance / Human Approval", "weight": 0.07, "desc": "Clarity of Go/Test/Hold/Defer decisions, risk mitigation, and human approval gates."},
    {"id": "internal_consistency_lineage", "name": "13. Internal Consistency / Lineage", "weight": 0.07, "desc": "End-to-end coherence between research, creative copy, and measurement KPIs."},
    {"id": "completeness", "name": "14. Completeness", "weight": 0.04, "desc": "Coverage of the 28-deliverable GTM proposal without ungrounded filler."},
]


def extract_scores_fail_closed(raw_response_text: str) -> Optional[Dict[str, float]]:
    """Extract 14 dimension scores strictly; return None (fail closed) if invalid or truncated."""
    if not raw_response_text or len(raw_response_text.strip()) == 0:
        return None

    scores: Dict[str, float] = {}

    # 1. Attempt JSON block parse
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response_text, re.DOTALL)
    candidate_json_str = match.group(1) if match else raw_response_text.strip()
    try:
        data = json.loads(candidate_json_str)
        cs = data.get("candidate_scores", data)
        for d in FROZEN_14_DIMENSIONS:
            d_id = d["id"]
            if d_id in cs:
                val = cs[d_id]
                if isinstance(val, dict) and "score" in val:
                    scores[d_id] = float(val["score"])
                elif isinstance(val, (int, float)):
                    scores[d_id] = float(val)
    except Exception:
        pass

    # 2. Fallback regex extraction (strictly for real numbers, never inserting default 5.0)
    if len(scores) < 14:
        for d in FROZEN_14_DIMENSIONS:
            d_id = d["id"]
            if d_id not in scores:
                pattern = re.compile(rf'"{d_id}"\s*:\s*\{{\s*"score"\s*:\s*([0-9\.]+)', re.IGNORECASE)
                m = pattern.search(raw_response_text)
                if m:
                    try:
                        scores[d_id] = float(m.group(1))
                    except Exception:
                        pass

    # Fail closed: must have all 14 scores
    if len(scores) == 14:
        return scores
    return None


def aggregate_judge_passes_fail_closed(
    valid_passes: List[Dict[str, float]],
    weights: Optional[Dict[str, float]] = None
) -> Tuple[bool, Optional[float], Optional[Dict[str, float]]]:
    """Aggregate median scores across valid judge passes under FAIL_CLOSED policy.
    
    Returns:
        (is_valid, weighted_quality_score, dimension_medians)
    """
    if len(valid_passes) < MIN_VALID_JUDGE_PASSES:
        logger.warning(f"Fail closed: only {len(valid_passes)}/{MIN_VALID_JUDGE_PASSES} valid judge passes available.")
        return (False, None, None)

    if weights is None:
        weights = {d["id"]: d["weight"] for d in FROZEN_14_DIMENSIONS}

    dim_medians = {}
    for d in FROZEN_14_DIMENSIONS:
        d_id = d["id"]
        vals = [p[d_id] for p in valid_passes if d_id in p]
        if len(vals) < MIN_VALID_JUDGE_PASSES:
            return (False, None, None)
        vals.sort()
        dim_medians[d_id] = vals[len(vals) // 2]

    weighted_score = sum(dim_medians[d_id] * weights[d_id] for d_id in dim_medians)
    return (True, round(weighted_score, 3), dim_medians)
