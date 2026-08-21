"""Prompt Builders for Candidate B4 (Single-Agent Multi-Pass) and Candidate C4 (One-Shot) on Case 03."""

import json
from typing import Any, Dict

def build_candidate_b4_pass_1_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any]) -> str:
    return f"""You are the Senior Strategic Marketing Director designing a comprehensive Go-To-Market strategy for AromaBrew Pro (Case 03).

[SOURCE GROUNDING - PASS 1 OF 3]
VERIFIED PRODUCT FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

PASS 1 OBJECTIVE: Produce in-depth Research Synthesis, Verified Facts, Observations, Inferences, Unknowns, Customer Segmentation, Beachhead ICP, Positioning, and Value Proposition.

REQUIRED SECTIONS TO DELIVER IN THIS PASS:
1. EXECUTIVE SUMMARY
2. RESEARCH FINDINGS (KNOWN_FACTS, OBSERVATIONS, INFERENCES, UNKNOWNS)
3. CUSTOMER SEGMENTS & TOP PRIORITY BEACHHEAD
4. POSITIONING & VALUE PROPOSITION
5. CHANNEL PRIORITIES & DEFERRED CHANNELS

At the end of your response, maintain the structured state:
### BOUNDED WORKING STATE
[SOURCE_GROUNDING] Key verified facts and constraints
[STRATEGIC_STATE] Core positioning, beachhead, and channel choices
[EPISTEMIC_STATE] Verified vs unverified items
[DECISION_STATE] Core trade-offs resolved
[DELIVERABLE_PROGRESS] Pass 1 deliverables completed
"""

def build_candidate_b4_pass_2_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any], working_state: str) -> str:
    return f"""You are the Senior Strategic Marketing Director continuing the Go-To-Market proposal for AromaBrew Pro (Case 03).

[SOURCE GROUNDING - PASS 2 OF 3]
VERIFIED PRODUCT FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

[CUMULATIVE BOUNDED WORKING STATE FROM PASS 1]
{working_state}

PASS 2 OBJECTIVE: Develop high-converting Creative Territories, Message Angles, Hooks, Short-Form Ad Copy Variants, and Production-Ready Video Scripts grounded strictly in verified product mechanics (12-minute acoustic extraction, sediment-free filtration).

REQUIRED SECTIONS TO DELIVER IN THIS PASS:
1. CREATIVE TERRITORIES (3 distinct territories + Selected Lead)
2. MESSAGE ANGLES & VALUE HOOKS (Top 5 scroll-stopping hooks)
3. SHORT-FORM AD COPY VARIANTS (Problem-Agitate-Solve, Social Proof, Technical Demo)
4. FULL VIDEO SCRIPT (30s D2C Video Ad with Visual, Audio, and Voiceover cues)

At the end of your response, update the structured state:
### BOUNDED WORKING STATE
[SOURCE_GROUNDING] Key verified facts and constraints
[STRATEGIC_STATE] Strategic positioning and beachhead
[CREATIVE_STATE] Selected territory, lead hook, and script format
[DECISION_STATE] Creative choices resolved
[DELIVERABLE_PROGRESS] Pass 1 & 2 deliverables completed
"""

def build_candidate_b4_pass_3_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any], working_state: str) -> str:
    return f"""You are the Senior Strategic Marketing Director finalizing the Go-To-Market proposal for AromaBrew Pro (Case 03).

[SOURCE GROUNDING - PASS 3 OF 3]
VERIFIED PRODUCT FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

[CUMULATIVE BOUNDED WORKING STATE FROM PASS 1 & 2]
{working_state}

PASS 3 OBJECTIVE: Design the Measurement Framework, Event Tracking Taxonomy, Multi-Touch Attribution Strategy, Experimentation Backlog with Decision Rules, Governance, Risk Mitigation, and Final Executive Decision Matrix.

REQUIRED SECTIONS TO DELIVER IN THIS PASS:
1. FULL-FUNNEL MEASUREMENT FRAMEWORK & KPI TARGETS
2. ATTRIBUTION ARCHITECTURE & EVENT TAXONOMY (UTMs, Pixel, Telemetry)
3. STRUCTURED EXPERIMENTATION BACKLOG (3 A/B test blueprints with hypotheses, metrics, and stopping criteria)
4. GOVERNANCE & RISK MITIGATION (Go/Test/Hold/Defer, Claim safety, human approval requirements)
5. TOP 3 IMMEDIATE NEXT ACTIONS

At the end of your response, update the structured state:
### BOUNDED WORKING STATE
[FINAL_STATE] Strategy, Creative, Measurement, and Governance finalized
"""

def build_candidate_c4_one_shot_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any]) -> str:
    return f"""You are a Principal Marketing Strategist and Growth Director creating a complete, comprehensive, 28-deliverable Go-To-Market Strategy Proposal for AromaBrew Pro (Case 03).

[VERIFIED PRODUCT FACTS]
{json.dumps(facts, indent=2)}

[QUALITATIVE MARKET EVIDENCE]
{json.dumps(evidence, indent=2)}

[BUSINESS OBJECTIVE & CONSTRAINTS]
{json.dumps(objective, indent=2)}

[PROHIBITED CLAIMS]
- 100% elimination of stomach acid or caffeine jitter effects
- Medical claims regarding disease or health cures
- Claiming patented status if patent is pending
- Fabricated celebrity endorsements

You must provide a complete, verified GTM proposal covering all core marketing dimensions:
1. EXECUTIVE SUMMARY
2. RESEARCH FINDINGS (Facts, Observations, Inferences, Unknowns)
3. CUSTOMER SEGMENTS & TOP PRIORITY BEACHHEAD
4. POSITIONING & VALUE PROPOSITION
5. CHANNEL PRIORITIES & DEFERRED CHANNELS
6. CREATIVE TERRITORIES, ANGLES, HOOKS, COPY, AND VIDEO SCRIPT
7. FULL-FUNNEL MEASUREMENT FRAMEWORK & METRICS
8. ATTRIBUTION & EVENT TRACKING TAXONOMY
9. EXPERIMENTATION BACKLOG & DECISION RULES
10. RISKS, GOVERNANCE, GO/TEST/HOLD/DEFER, AND HUMAN APPROVAL REQUIREMENTS
"""
