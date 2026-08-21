"""Phase 4.3C.10D / Phase 4.3 V3 Frozen Benchmark Prompt Templates (Case 02: SecureCode AI SEA).

Protocol Invariants:
- A3: Five-Agent V3 (Role-specialized governed multi-agent architecture)
- B3: Single-Agent Bounded Multi-Pass Control (3 sequential passes with cumulative structured state <= 1500 tokens, Method A Source Grounding)
- C3: Single-Agent One-Shot (Practical baseline requesting full 28 deliverables in 1 call)
- Identity Invariance: Exactly 1 logical agent identity (Senior Strategic Marketing Director)
- Memory Invariance: Cumulative structured working state without raw response recursion
"""

import json
from typing import Any, Dict


def build_candidate_b3_pass_1_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any]) -> str:
    return f"""You are a Senior Strategic Marketing Director formulating an end-to-end Go-To-Market (GTM) strategy for an innovative B2B developer security product.

[PRODUCT CAPABILITIES & VERIFIED FACTS]
{json.dumps(facts, indent=2)}

[MARKET EVIDENCE & RESEARCH FINDINGS]
{json.dumps(evidence, indent=2)}

[BUSINESS OBJECTIVE]
{json.dumps(objective, indent=2)}

[PASS 1 OBJECTIVE: STRATEGIC GROUNDING, SEGMENTATION & POSITIONING]
Perform comprehensive research synthesis, customer segmentation, technical positioning, and channel strategy.

Provide your output as a comprehensive, well-structured document covering:
1. Executive Summary & Problem Framing
2. Verified Known Facts vs Critical Unknowns
3. Market Observations, Inferences & Testable Hypotheses
4. Target Customer Segmentation & Top Priority Segment
5. Technical Positioning Architecture & Value Proposition
6. Channel Priorities, Deferred Channels & Guardrails (What Not To Do)

At the end of your response, provide the cumulative structured working memory state:
### BOUNDED WORKING STATE
[SOURCE_GROUNDING]
- VERIFIED_FACT_IDS: (List of verified product capability IDs used)
- EVIDENCE_IDS: (List of evidence findings used)
- OBJECTIVE_SUMMARY: (Core business goal)

[STRATEGIC_STATE]
- LEAD_SEGMENT: (Primary customer target)
- CORE_POSITIONING: (Executive positioning statement)
- VALUE_PROPOSITION: (Technical differentiation summary)
- PRIORITY_CHANNELS: (Top GTM channels)
- DEFERRED_CHANNELS: (De-prioritized channels)

[EPISTEMIC_STATE]
- VERIFIED_FACTS: (Ground truth facts)
- HYPOTHESES: (Testable assumptions)
- UNKNOWNS: (Information gaps)
- PROHIBITED_CLAIMS: (Boundary constraints)

[DECISION_STATE]
- KEY_DECISIONS: (Strategic choices made)
- RISKS: (Top identified risks)
- UNRESOLVED_CONTRADICTIONS: (Tensions to resolve)

[DELIVERABLE_PROGRESS]
- COMPLETED_KEYS: executive_summary, known_facts, observations, inferences, hypotheses, unknowns, customer_segments, top_priority_segment, positioning, value_proposition, channel_priorities, deferred_channels, what_not_to_do
- REMAINING_KEYS: creative_territories, selected_creative_territory, angles, hooks, short_form_copy, video_script, measurement_framework, experiments, attribution_approach, risks, top_3_priorities, go_test_hold_defer_decisions, human_approval_requirements, next_actions, claim_governance
"""


def build_candidate_b3_pass_2_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any], cumulative_working_state: str) -> str:
    return f"""You are a Senior Strategic Marketing Director continuing the Go-To-Market strategy.

[PRODUCT CAPABILITIES & VERIFIED FACTS]
{json.dumps(facts, indent=2)}

[MARKET EVIDENCE & RESEARCH FINDINGS]
{json.dumps(evidence, indent=2)}

[BUSINESS OBJECTIVE]
{json.dumps(objective, indent=2)}

[CUMULATIVE BOUNDED WORKING STATE FROM PASS 1]
{cumulative_working_state}

[PASS 2 OBJECTIVE: CREATIVE CONCEPTS, MESSAGING ANGLES & COPY PRODUCTION]
Develop the creative architecture and production assets aligned strictly with the strategic positioning established in Pass 1.

Provide your output covering:
1. Creative Concept Territories (minimum 3 distinct angles) & Selected Primary Territory
2. Messaging Angles tailored to Developer & Engineering Leadership personas
3. High-Conversion Hooks for Social & Video
4. Short-Form Ad Copy & Headline Sets
5. Complete 30-60 Second Video / Interactive Demo Script with visual cues, audio, and dialogue

At the end of your response, provide the updated cumulative structured working memory state (preserving Pass 1 strategic decisions and appending creative state):
### BOUNDED WORKING STATE
(Preserve all existing [SOURCE_GROUNDING], [STRATEGIC_STATE], [EPISTEMIC_STATE], [DECISION_STATE] from Pass 1)

[CREATIVE_STATE]
- SELECTED_TERRITORY: (Chosen primary creative angle)
- KEY_HOOK: (Primary narrative hook)
- MESSAGING_PILLARS: (Core technical messaging pillars)
- DEMO_CONCEPT: (Core product demonstration concept)

[DELIVERABLE_PROGRESS]
- COMPLETED_KEYS: (Updated list of completed keys from Pass 1 + Pass 2)
- REMAINING_KEYS: measurement_framework, experiments, attribution_approach, risks, top_3_priorities, go_test_hold_defer_decisions, human_approval_requirements, next_actions, claim_governance
"""


def build_candidate_b3_pass_3_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any], cumulative_working_state: str) -> str:
    return f"""You are a Senior Strategic Marketing Director finalizing the Go-To-Market strategy.

[PRODUCT CAPABILITIES & VERIFIED FACTS]
{json.dumps(facts, indent=2)}

[MARKET EVIDENCE & RESEARCH FINDINGS]
{json.dumps(evidence, indent=2)}

[BUSINESS OBJECTIVE]
{json.dumps(objective, indent=2)}

[CUMULATIVE BOUNDED WORKING STATE FROM PASSES 1 & 2]
{cumulative_working_state}

[PASS 3 OBJECTIVE: MEASUREMENT, FUNNEL ECONOMICS, EXPERIMENTATION & GOVERNANCE]
Establish the analytics measurement framework, growth experimentation backlog, risk management matrix, and final executive governance decisions.

Provide your output covering:
1. Full-Funnel Measurement Framework & Target KPIs (CAC, Trial Conversion, Payback)
2. Growth Experimentation Backlog (A/B testing hypotheses, sample size, metrics)
3. Attribution & Tracking Architecture (multi-touch, product telemetry)
4. Comprehensive Risk Matrix & Mitigation Strategies
5. Top 3 Strategic Priorities for Immediate Execution
6. Go / Test / Hold / Defer Governance Matrix
7. Human Approval Requirements & Claim Compliance Gates
8. Immediate 30-60-90 Day Action Plan

At the end of your response, provide the finalized cumulative structured working memory state:
### BOUNDED WORKING STATE
(Preserve all prior [SOURCE_GROUNDING], [STRATEGIC_STATE], [EPISTEMIC_STATE], [DECISION_STATE], and [CREATIVE_STATE])

[EXECUTION_STATE]
- MEASUREMENT_PRIORITIES: (Top funnel metrics & payback target)
- EXPERIMENT_PRIORITIES: (Primary growth experiments)
- GOVERNANCE_REQUIREMENTS: (Human approval & claim gates)

[DELIVERABLE_PROGRESS]
- COMPLETED_KEYS: ALL 28 CANONICAL DELIVERABLES COMPLETED
- REMAINING_KEYS: NONE
"""


def build_candidate_c3_one_shot_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any]) -> str:
    return f"""You are a Chief Marketing Officer creating a complete, production-grade Go-To-Market (GTM) Strategy for a B2B developer security product.

[VERIFIED PRODUCT FACTS]
{json.dumps(facts, indent=2)}

[MARKET EVIDENCE]
{json.dumps(evidence, indent=2)}

[BUSINESS OBJECTIVE]
{json.dumps(objective, indent=2)}

[REQUIREMENT: FULL 28-DELIVERABLE GO-TO-MARKET PROPOSAL]
Generate a complete, exhaustive, and rigorously detailed GTM proposal covering all aspects of:
1. Executive Summary & Strategic Foundations (Known Facts, Observations, Inferences, Hypotheses, Unknowns)
2. Target Segmentation & Technical Positioning (Customer Segments, Top Segment, Positioning Architecture, Value Prop, Channel Priorities, Deferred Channels, What Not To Do)
3. Creative Architecture & Multimedia Production (Creative Territories, Selected Territory, Angles, Hooks, Short-Form Copy, 30-Second Production Video Script)
4. Measurement Framework & Experimentation (KPIs, Experiments Backlog, Attribution Approach)
5. Executive Governance & Implementation (Risks Matrix, Top 3 Priorities, Go/Test/Hold/Defer Decisions, Human Approval Requirements, Immediate Next Actions, Claim Governance)

Be comprehensive, rigorous, and ensure all claims respect the verified product facts and prohibited claim boundaries.
"""
