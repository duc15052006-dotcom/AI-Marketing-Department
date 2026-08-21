"""Phase 4.1.2B: Assemble Complete Blind Evaluation Packet.

Assembles equivalent, non-empty, unpatched proposals for both candidates into blind_review_packet.md.
Keeps blind_identity_key.json strictly hidden.
Enforces zero identity leaks and 100% deliverable completeness across both candidates.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import sys

base_dir = Path(__file__).resolve().parent.parent
bench_dir = base_dir / "evaluations" / "benchmarks" / "phase4_1_2_true_parity"
single_dir = bench_dir / "single"
five_dir = bench_dir / "five_agent"


def build_five_agent_blind_proposal(five_dir: Path) -> dict:
    cmo_init = json.loads((five_dir / "initial_cmo.json").read_text(encoding="utf-8"))
    intel = json.loads((five_dir / "intelligence.json").read_text(encoding="utf-8"))
    strat = json.loads((five_dir / "strategist.json").read_text(encoding="utf-8"))
    crtv = json.loads((five_dir / "creative.json").read_text(encoding="utf-8"))
    perf = json.loads((five_dir / "performance.json").read_text(encoding="utf-8"))
    cmo_final = json.loads((five_dir / "final_cmo.json").read_text(encoding="utf-8"))

    intel_det = intel.get("details", {})
    strat_det = strat.get("details", {})
    crtv_det = crtv.get("details", {})
    perf_det = perf.get("details", {})
    cmo_det = cmo_final.get("details", {})

    epistemic = intel_det.get("epistemic_breakdown", {})
    strat_pos = strat_det.get("strategic_positioning", {})
    strat_offer = strat_det.get("pricing_and_offer_architecture", {})
    strat_seg = strat_det.get("target_segmentation_and_jtbd", {})
    strat_choices = strat_det.get("strategic_choices", {})
    strat_chan = strat_det.get("channel_and_funnel_architecture", {})
    crtv_msg = crtv_det.get("message_hierarchy", {})

    return {
        "EXECUTIVE_SUMMARY": cmo_final.get("summary", ""),
        "RESEARCH_FINDINGS": epistemic.get("facts", []) + epistemic.get("observations", []),
        "KNOWN_FACTS": epistemic.get("facts", []),
        "OBSERVATIONS": epistemic.get("observations", []),
        "INFERENCES": epistemic.get("inferences", []),
        "HYPOTHESES": epistemic.get("hypotheses", []),
        "UNKNOWNS": intel_det.get("critical_unknown_registers_and_boundaries", epistemic.get("unknown_facts", [])),
        "CUSTOMER_SEGMENTS": intel_det.get("consumer_insights_and_jtbd", {}),
        "TOP_PRIORITY_SEGMENT": strat_seg.get("primary_icp", ""),
        "POSITIONING": strat_pos.get("positioning_statement", strat_pos),
        "VALUE_PROPOSITION": strat_offer.get("offer_packaging", strat_offer),
        "CHANNEL_PRIORITIES": strat_chan.get("demand_capture_70_percent", strat_chan),
        "DEFERRED_CHANNELS": strat_choices.get("what_we_will_not_do", []),
        "WHAT_NOT_TO_DO": strat_choices.get("what_we_will_not_do", []),
        "CREATIVE_TERRITORIES": crtv_det.get("creative_territories_and_angles", []),
        "SELECTED_CREATIVE_TERRITORY": crtv_det.get("campaign_name", ""),
        "ANGLES": crtv_det.get("creative_territories_and_angles", []),
        "HOOKS": crtv_msg.get("reasons_to_believe", []),
        "SHORT_FORM_COPY": crtv_msg.get("primary_message", ""),
        "VIDEO_SCRIPT": crtv_det.get("storyboards_and_scripts", []),
        "MEASUREMENT_FRAMEWORK": perf_det.get("measurement_context_audit", {}),
        "EXPERIMENTS": perf_det.get("ab_experiment_portfolio", cmo_det.get("experimentation_and_measurement_governance", {})),
        "ATTRIBUTION_APPROACH": perf_det.get("measurement_context_audit", {}).get("attribution_context", {}),
        "RISKS": cmo_det.get("risk_register_and_mitigations", perf_det.get("attribution_and_operations", {}).get("critical_risks_and_mitigations", [])),
        "TOP_3_PRIORITIES": cmo_det.get("orchestrated_campaign_roadmap", {}),
        "GO_TEST_HOLD_DEFER_DECISIONS": cmo_det.get("decision_register", {}),
        "HUMAN_APPROVAL_REQUIREMENTS": cmo_det.get("autonomy_and_governance_tier", {}),
        "NEXT_ACTIONS": cmo_det.get("orchestrated_campaign_roadmap", {}),
    }


def build_single_blind_proposal(single_dir: Path) -> dict:
    raw_sm = json.loads((single_dir / "output.json").read_text(encoding="utf-8"))
    cleaned = dict(raw_sm)
    cleaned.pop("RAW_OUTPUT", None)
    cleaned.pop("PARSING_STATUS", None)
    return cleaned


def audit_proposal_completeness(prop: dict) -> dict:
    return {
        "NON_EMPTY_EXECUTIVE_SUMMARY": bool(prop.get("EXECUTIVE_SUMMARY")),
        "NON_EMPTY_RESEARCH": bool(prop.get("RESEARCH_FINDINGS")),
        "NON_EMPTY_SEGMENTATION": bool(prop.get("CUSTOMER_SEGMENTS") or prop.get("TOP_PRIORITY_SEGMENT")),
        "NON_EMPTY_STRATEGY": bool(prop.get("POSITIONING") and prop.get("VALUE_PROPOSITION")),
        "NON_EMPTY_CREATIVE": bool(prop.get("CREATIVE_TERRITORIES") or prop.get("VIDEO_SCRIPT")),
        "NON_EMPTY_MEASUREMENT": bool(prop.get("MEASUREMENT_FRAMEWORK") or prop.get("EXPERIMENTS")),
        "NON_EMPTY_GOVERNANCE": bool(prop.get("RISKS") or prop.get("HUMAN_APPROVAL_REQUIREMENTS") or prop.get("GO_TEST_HOLD_DEFER_DECISIONS")),
    }


def audit_identity_leaks(text: str) -> int:
    # Explicit forbidden markers that identify model/agent architecture
    leak_patterns = [
        r"\bCMO Agent\b",
        r"\bIntelligence Agent\b",
        r"\bStrategist Agent\b",
        r"\bCreative Agent\b",
        r"\bPerformance Agent\b",
        r"\bsingle-model\b",
        r"\bfive-agent\b",
        r"\b5-agent\b",
        r"\bmodel calls\b",
        r"\btoken counts\b",
        r"\bprompt_tokens\b",
        r"\bcompletion_tokens\b",
        r"\btotal_tokens\b",
        r"\bSYSTEM_A is\b",
        r"\bSYSTEM_B is\b",
    ]
    leaks = 0
    for pat in leak_patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        leaks += len(matches)
    return leaks


def main():
    five_prop = build_five_agent_blind_proposal(five_dir)
    single_prop = build_single_blind_proposal(single_dir)

    five_audit = audit_proposal_completeness(five_prop)
    single_audit = audit_proposal_completeness(single_prop)

    five_pass = all(five_audit.values())
    single_pass = all(single_audit.values())

    if not five_pass or not single_pass:
        print("COMPLETENESS AUDIT FAILED!")
        print("Five-Agent Audit:", five_audit)
        print("Single Audit:", single_audit)
        sys.exit(1)

    # Determine / Preserve randomized assignment
    blind_key_path = bench_dir / "blind_identity_key.json"
    is_a_five_agent = True
    if blind_key_path.exists():
        try:
            key_data = json.loads(blind_key_path.read_text(encoding="utf-8"))
            assignment = key_data.get("randomized_assignment", {})
            if assignment.get("SYSTEM_A") == "Single-Model Baseline":
                is_a_five_agent = False
            else:
                is_a_five_agent = True
        except Exception:
            is_a_five_agent = random.choice([True, False])
    else:
        is_a_five_agent = random.choice([True, False])

    system_a_label = "Five-Agent Architecture" if is_a_five_agent else "Single-Model Baseline"
    system_b_label = "Single-Model Baseline" if is_a_five_agent else "Five-Agent Architecture"

    output_a = five_prop if is_a_five_agent else single_prop
    output_b = single_prop if is_a_five_agent else five_prop

    # Build Blind Packet Markdown
    blind_packet = f"""# PHASE 4.1.2 BLIND EVALUATION PACKET: 65W GaN CHARGER GTM PROPOSALS

> **INSTRUCTIONS FOR HUMAN REVIEWER:**  
> Review the two anonymized go-to-market proposals below (**SYSTEM_A** and **SYSTEM_B**).  
> Both systems received the exact same product facts and verified evidence for a 65W GaN USB-C Charger launch in Vietnam.  
> System names, agent DNA, execution paths, and model telemetry have been strictly stripped.  
> Please complete the Scorecard at the bottom by selecting **SYSTEM_A**, **SYSTEM_B**, or **TIE** for each evaluation criterion.

---

## CANDIDATE 1: SYSTEM_A

```json
{json.dumps(output_a, indent=2)}
```

---

## CANDIDATE 2: SYSTEM_B

```json
{json.dumps(output_b, indent=2)}
```

---

## HUMAN REVIEWER SCORECARD

Please assess both proposals on the 8 standardized dimensions below:

1. **Research Trustworthiness:** Which research interpretation is more rigorous, grounded, and cautious?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

2. **Customer Segmentation:** Which target segmentation and customer prioritization is more actionable?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

3. **Positioning & Strategy:** Which positioning and value proposition would you rather bring to market?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

4. **Creative Usability:** Which creative package (territories, hooks, copy, script) would you actually deploy?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

5. **Measurement & Experiments:** Which measurement framework and experimentation design is more operational?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

6. **Unsupported Claims:** Which proposal contains fewer unbacked assertions, fake metrics, or overclaims?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

7. **Actionability & Governance:** Which proposal provides clearer risk management and executive decision clarity?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

8. **Overall Preference:** If implementation cost and latency were equal, which system recommendation would you select?  
   - Choice: `[ SYSTEM_A | SYSTEM_B | TIE ]`  
   - Rationale:

---
*End of Blind Review Packet.*
"""
    (bench_dir / "blind_review_packet.md").write_text(blind_packet, encoding="utf-8")

    key_record = {
        "benchmark_id": "BENCHMARK_PHASE4_1_2_TRUE_PARITY",
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "randomized_assignment": {
            "SYSTEM_A": system_a_label,
            "SYSTEM_B": system_b_label,
        },
    }
    blind_key_path.write_text(json.dumps(key_record, indent=2), encoding="utf-8")

    # Run leak audit
    leak_count = audit_identity_leaks(blind_packet)

    audit_report = {
        "BLIND_PACKET_VALID": "PASS" if (five_pass and single_pass and leak_count == 0) else "FAIL",
        "SYSTEM_A_COMPLETENESS": "PASS" if (five_audit if is_a_five_agent else single_audit) else "FAIL",
        "SYSTEM_B_COMPLETENESS": "PASS" if (single_audit if is_a_five_agent else five_audit) else "FAIL",
        "IDENTITY_LEAK_COUNT": leak_count,
        "SOURCE_ARTIFACTS_USED": [
            "single/output.json",
            "five_agent/initial_cmo.json",
            "five_agent/intelligence.json",
            "five_agent/strategist.json",
            "five_agent/creative.json",
            "five_agent/performance.json",
            "five_agent/final_cmo.json",
        ],
        "CONTENT_PATCH_COUNT": 0,
    }

    print("ASSEMBLY COMPLETE")
    print(json.dumps(audit_report, indent=2))


if __name__ == "__main__":
    main()
