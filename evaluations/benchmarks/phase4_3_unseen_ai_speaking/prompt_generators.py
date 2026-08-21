"""Prompt generators for the Fair Three-Way Benchmark (Candidates A, B, and C).

Strict Requirements:
1. All candidates receive identical initial source facts, evidence bundle, and business objective.
2. Candidate B uses ONE logical single-agent identity with an iterative working-memory scratchpad (no disguised specialist personas).
3. Candidate C uses a direct single one-shot prompt requesting all 28 canonical deliverables.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from schemas.handoff import HandoffPackage


def build_candidate_a_stage_1_prompt(facts: Dict[str, Any], evidence: Dict[str, Any]) -> str:
    """Candidate A - Stage 1: CMO Initial Decomposition Prompt."""
    return (
        f"Decompose business objective for {facts['product_id']}:\n"
        f"Facts: {json.dumps(facts, ensure_ascii=False)}\n"
        f"Evidence: {json.dumps(evidence, ensure_ascii=False)}"
    )


def build_candidate_a_stage_2_prompt(handoff: HandoffPackage, evidence: Dict[str, Any]) -> str:
    """Candidate A - Stage 2: Intelligence Specialist Prompt."""
    return (
        f"You are the Intelligence Specialist.\n\n"
        f"{handoff.format_prompt_section()}\n\n"
        f"Evidence Bundle:\n"
        f"{json.dumps(evidence, indent=2, ensure_ascii=False)}"
    )


def build_candidate_a_stage_3_prompt(handoff: HandoffPackage) -> str:
    """Candidate A - Stage 3: Strategic Marketing Director Prompt."""
    return f"You are the Strategic Marketing Director.\n\n{handoff.format_prompt_section()}"


def build_candidate_a_stage_4_prompt(handoff: HandoffPackage) -> str:
    """Candidate A - Stage 4: Creative Director & Copywriter Prompt."""
    return f"You are the Creative Director and Copywriter.\n\n{handoff.format_prompt_section()}"


def build_candidate_a_stage_5_prompt(handoff: HandoffPackage) -> str:
    """Candidate A - Stage 5: Performance Marketing Specialist Prompt."""
    return f"You are the Performance Marketing & Analytics Specialist.\n\n{handoff.format_prompt_section()}"


def build_candidate_a_stage_6_prompt(handoff: HandoffPackage) -> str:
    """Candidate A - Stage 6: Final CMO Governance Prompt."""
    return (
        f"You are the Chief Marketing Officer presiding over final governance.\n\n"
        f"{handoff.format_prompt_section()}\n\n"
        f"Required JSON Structure:\n"
        f"- executive_summary\n"
        f"- known_facts\n"
        f"- observations\n"
        f"- inferences\n"
        f"- hypotheses\n"
        f"- unknowns\n"
        f"- customer_segments\n"
        f"- top_priority_segment\n"
        f"- positioning\n"
        f"- value_proposition\n"
        f"- channel_priorities\n"
        f"- deferred_channels\n"
        f"- what_not_to_do\n"
        f"- creative_territories\n"
        f"- selected_creative_territory\n"
        f"- angles\n"
        f"- hooks\n"
        f"- short_form_copy\n"
        f"- video_script\n"
        f"- measurement_framework\n"
        f"- experiments\n"
        f"- attribution_approach\n"
        f"- risks\n"
        f"- top_3_priorities\n"
        f"- go_test_hold_defer_decisions\n"
        f"- human_approval_requirements\n"
        f"- next_actions\n"
    )


# -----------------------------------------------------------------------------
# CANDIDATE B: Single-Agent Multi-Pass (Neutral Memory Scratchpad)
# -----------------------------------------------------------------------------

def build_candidate_b_pass_1_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any]) -> str:
    """Candidate B - Pass 1: Research, Evidence Grounding & Problem Decomposition."""
    return (
        "You are an AI Marketing Planning Engine developing a comprehensive Go-To-Market strategy.\n\n"
        "=== PASS 1 / 5: RESEARCH, EVIDENCE GROUNDING & PROBLEM DECOMPOSITION ===\n\n"
        "Your task in Pass 1 is to analyze the source facts, evidence bundle, and business objective. "
        "Structure all grounded findings, known facts, customer pain points, JTBD, and unknowns.\n\n"
        f"PRODUCT FACTS:\n{json.dumps(facts, indent=2, ensure_ascii=False)}\n\n"
        f"EVIDENCE BUNDLE:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}\n\n"
        f"BUSINESS OBJECTIVE:\n{json.dumps(objective, indent=2, ensure_ascii=False)}\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "Produce detailed Pass 1 working notes: Executive Summary context, Known Facts, Observations, Inferences, and Unknowns."
    )


def build_candidate_b_pass_2_prompt(facts: Dict[str, Any], scratchpad: str) -> str:
    """Candidate B - Pass 2: Customer Segmentation, Positioning & Channel Priorities."""
    return (
        "You are an AI Marketing Planning Engine continuing development of the Go-To-Market strategy.\n\n"
        "=== PASS 2 / 5: CUSTOMER SEGMENTATION, POSITIONING & CHANNEL STRATEGY ===\n\n"
        f"PRODUCT FACTS:\n{json.dumps(facts, indent=2, ensure_ascii=False)}\n\n"
        f"ACCUMULATED WORKING MEMORY (FROM PREVIOUS PASSES):\n{scratchpad}\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "Based on your Pass 1 research, develop:\n"
        "1. Customer Segments & Top Priority Segment\n"
        "2. Core Positioning & Value Proposition\n"
        "3. Channel Priorities (Primary, Secondary, Deferred channels with rationale)\n"
        "4. 'What-Not-To-Do' Guardrails and Strategic Hypotheses."
    )


def build_candidate_b_pass_3_prompt(facts: Dict[str, Any], scratchpad: str) -> str:
    """Candidate B - Pass 3: Creative Direction, Message Angles, Hooks & Copy."""
    return (
        "You are an AI Marketing Planning Engine continuing development of the Go-To-Market strategy.\n\n"
        "=== PASS 3 / 5: CREATIVE DIRECTION, MESSAGE ANGLES & PRODUCTION ASSETS ===\n\n"
        f"PRODUCT FACTS:\n{json.dumps(facts, indent=2, ensure_ascii=False)}\n\n"
        f"ACCUMULATED WORKING MEMORY (FROM PREVIOUS PASSES):\n{scratchpad}\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "Translate your strategic positioning into creative deliverables:\n"
        "1. 3 Distinct Creative Territories & Selected Lead Territory with Rationale\n"
        "2. Message Angles & High-Converting Scroll-Stopping Hooks\n"
        "3. Short-Form Ad Copy Variants\n"
        "4. Full 30-45s Video Script (with visual, audio, and CTA cues)\n"
        "Ensure 100% compliance with verified product facts (zero unverified fluency or score promises)."
    )


def build_candidate_b_pass_4_prompt(facts: Dict[str, Any], scratchpad: str) -> str:
    """Candidate B - Pass 4: Performance Funnel, Attribution Architecture & Experiments."""
    return (
        "You are an AI Marketing Planning Engine continuing development of the Go-To-Market strategy.\n\n"
        "=== PASS 4 / 5: MEASUREMENT FRAMEWORK, ATTRIBUTION & EXPERIMENTATION ===\n\n"
        f"PRODUCT FACTS:\n{json.dumps(facts, indent=2, ensure_ascii=False)}\n\n"
        f"ACCUMULATED WORKING MEMORY (FROM PREVIOUS PASSES):\n{scratchpad}\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "Design the execution and measurement framework:\n"
        "1. Full-Funnel Measurement Framework (Primary KPIs, Guardrail metrics)\n"
        "2. Attribution Approach (SKAdNetwork 4.0, MMP postbacks, UTM taxonomy)\n"
        "3. Structured Experiment Blueprints (Hypothesis, Treatment vs Control, Stop condition)\n"
        "4. Risk Matrix & Mitigation Strategy."
    )


def build_candidate_b_pass_5_prompt(facts: Dict[str, Any], scratchpad: str) -> str:
    """Candidate B - Pass 5: Governance Decisions, Action Plan & Canonical 28-Deliverable Assembly."""
    return (
        "You are an AI Marketing Planning Engine concluding development of the Go-To-Market strategy.\n\n"
        "=== PASS 5 / 5: STRATEGIC GOVERNANCE, TOP PRIORITIES & CANONICAL ASSEMBLY ===\n\n"
        f"PRODUCT FACTS:\n{json.dumps(facts, indent=2, ensure_ascii=False)}\n\n"
        f"ACCUMULATED WORKING MEMORY (FROM ALL PREVIOUS PASSES):\n{scratchpad}\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "Synthesize all accumulated work into the final, authoritative 28-deliverable Go-To-Market proposal. "
        "Resolve any ambiguities and output a valid JSON object matching all 28 canonical deliverable sections:\n"
        "- executive_summary\n- known_facts\n- observations\n- inferences\n- hypotheses\n- unknowns\n"
        "- customer_segments\n- top_priority_segment\n- positioning\n- value_proposition\n- channel_priorities\n"
        "- deferred_channels\n- what_not_to_do\n- creative_territories\n- selected_creative_territory\n"
        "- angles\n- hooks\n- short_form_copy\n- video_script\n- measurement_framework\n- experiments\n"
        "- attribution_approach\n- risks\n- top_3_priorities\n- go_test_hold_defer_decisions\n"
        "- human_approval_requirements\n- next_actions\n"
    )


# -----------------------------------------------------------------------------
# CANDIDATE C: Single-Agent One-Shot (Practical Baseline)
# -----------------------------------------------------------------------------

def build_candidate_c_one_shot_prompt(facts: Dict[str, Any], evidence: Dict[str, Any], objective: Dict[str, Any]) -> str:
    """Candidate C: Direct Single One-Shot Prompt for All 28 Deliverables."""
    return (
        "You are a Senior Chief Marketing Officer. Develop a complete, production-grade Go-To-Market (GTM) proposal "
        "for the product described below, strictly adhering to the provided product facts and evidence bundle.\n\n"
        f"PRODUCT FACTS:\n{json.dumps(facts, indent=2, ensure_ascii=False)}\n\n"
        f"EVIDENCE BUNDLE:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}\n\n"
        f"BUSINESS OBJECTIVE:\n{json.dumps(objective, indent=2, ensure_ascii=False)}\n\n"
        "REQUIREMENTS:\n"
        "Return a single, comprehensive, valid JSON object containing all 28 required deliverable sections:\n"
        "1. executive_summary (string)\n"
        "2. known_facts (list of strings)\n"
        "3. observations (list of strings)\n"
        "4. inferences (list of strings)\n"
        "5. hypotheses (list of strings)\n"
        "6. unknowns (list of strings)\n"
        "7. customer_segments (list of objects/strings)\n"
        "8. top_priority_segment (string or object)\n"
        "9. positioning (string)\n"
        "10. value_proposition (string)\n"
        "11. channel_priorities (list of objects)\n"
        "12. deferred_channels (list of objects)\n"
        "13. what_not_to_do (list of strings)\n"
        "14. creative_territories (list of objects)\n"
        "15. selected_creative_territory (string or object)\n"
        "16. angles (list of strings/objects)\n"
        "17. hooks (list of strings/objects)\n"
        "18. short_form_copy (list of objects)\n"
        "19. video_script (object with visual, audio, voiceover, cta)\n"
        "20. measurement_framework (object with primary, secondary, guardrail metrics)\n"
        "21. experiments (list of structured experiment objects)\n"
        "22. attribution_approach (object)\n"
        "23. risks (list of risk & mitigation objects)\n"
        "24. top_3_priorities (list of 3 strings)\n"
        "25. go_test_hold_defer_decisions (object)\n"
        "26. human_approval_requirements (list of strings)\n"
        "27. next_actions (list of concrete next steps)\n"
    )
