"""Phase 4.2: Five-Agent Hallucination & Handoff Failure Analysis Script.

Builds:
1. evaluations/phase4_2_claim_lineage.json
2. evaluations/phase4_2_failure_analysis.md
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

base_dir = Path(__file__).resolve().parent.parent
bench_dir = base_dir / "evaluations" / "benchmarks" / "phase4_1_2_true_parity"
five_dir = bench_dir / "five_agent"
single_dir = bench_dir / "single"

# Artifacts
files = {
    "single": single_dir / "output.json",
    "cmo_init": five_dir / "initial_cmo.json",
    "intelligence": five_dir / "intelligence.json",
    "strategist": five_dir / "strategist.json",
    "creative": five_dir / "creative.json",
    "performance": five_dir / "performance.json",
    "cmo_final": five_dir / "final_cmo.json",
}

artifact_hashes = {}
for k, path in files.items():
    if path.exists():
        artifact_hashes[k] = {
            "path": str(path.relative_to(base_dir)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }

# Defined material claims in the 5-Agent pipeline
claims_data = [
    {
        "CLAIM_ID": "CLM-001",
        "CLAIM_TEXT": "GaN semiconductor architecture enables 65W power output via USB-C Power Delivery in a compact form factor.",
        "CLAIM_TYPE": "PRODUCT_FACT",
        "FIRST_APPEARED_STAGE": "CMO_INITIAL",
        "SOURCE_EVIDENCE_IDS": ["EVID-GAN65-01", "EVID-GAN65-02"],
        "SOURCE_PRODUCT_FACT": "65W maximum power output, GaN semiconductor architecture, USB-C connectivity, compact form factor",
        "SOURCE_HUMAN_INPUT": "Supplied in product specifications",
        "SOURCE_PREVIOUS_AGENT": "None (Input Fact Boundary)",
        "STATUS_AT_CREATION": "VERIFIED_PRODUCT_FACT",
        "STATUS_IN_FINAL_OUTPUT": "VERIFIED_PRODUCT_FACT",
        "PROPAGATED_TO_STAGES": ["INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 1.0,
        "SUPPORTED": True,
        "FAILURE_TYPE": "NONE",
        "ORIGINATOR": "INPUT_SPEC",
        "PROPAGATORS": ["CMO_INITIAL", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": []
    },
    {
        "CLAIM_ID": "CLM-002",
        "CLAIM_TEXT": "Competitor 65W GaN chargers retail between 300,000 VND and 700,000 VND on Shopee Vietnam.",
        "CLAIM_TYPE": "MARKET_OBSERVATION",
        "FIRST_APPEARED_STAGE": "INTELLIGENCE",
        "SOURCE_EVIDENCE_IDS": ["EVID-GAN65-04"],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "None (Evidence Discovery)",
        "STATUS_AT_CREATION": "OBSERVED_MARKET_FACT",
        "STATUS_IN_FINAL_OUTPUT": "OBSERVED_MARKET_FACT",
        "PROPAGATED_TO_STAGES": ["STRATEGIST", "CMO_FINAL"],
        "CONFIDENCE": 0.88,
        "SUPPORTED": True,
        "FAILURE_TYPE": "NONE",
        "ORIGINATOR": "INTELLIGENCE",
        "PROPAGATORS": ["STRATEGIST", "CMO_FINAL"],
        "FAILED_REVIEWERS": []
    },
    {
        "CLAIM_ID": "CLM-003",
        "CLAIM_TEXT": "Vietnamese office workers experience fatigue carrying bulky OEM chargers and express concerns regarding thermal heat and wall socket stability.",
        "CLAIM_TYPE": "CUSTOMER_OBSERVATION",
        "FIRST_APPEARED_STAGE": "INTELLIGENCE",
        "SOURCE_EVIDENCE_IDS": ["EVID-GAN65-03", "EVID-GAN65-05"],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "None (Evidence Discovery)",
        "STATUS_AT_CREATION": "OBSERVED_USER_VOICE",
        "STATUS_IN_FINAL_OUTPUT": "OBSERVED_USER_VOICE",
        "PROPAGATED_TO_STAGES": ["STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.90,
        "SUPPORTED": True,
        "FAILURE_TYPE": "NONE",
        "ORIGINATOR": "INTELLIGENCE",
        "PROPAGATORS": ["STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": []
    },
    {
        "CLAIM_ID": "CLM-004",
        "CLAIM_TEXT": "Authorizes Phase 1 pilot launch advertising budget of exactly 20,000,000 VND.",
        "CLAIM_TYPE": "BUDGET",
        "FIRST_APPEARED_STAGE": "PERFORMANCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "None (Invented in Performance planning)",
        "STATUS_AT_CREATION": "INVENTED_NUMERIC_INPUT",
        "STATUS_IN_FINAL_OUTPUT": "EXECUTIVE_AUTHORIZED_BUDGET",
        "PROPAGATED_TO_STAGES": ["CMO_FINAL"],
        "CONFIDENCE": 0.20,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_BUSINESS_INPUT",
        "ORIGINATOR": "PERFORMANCE",
        "PROPAGATORS": ["CMO_FINAL"],
        "FAILED_REVIEWERS": ["CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-005",
        "CLAIM_TEXT": "Standard retail anchor price is 429,000 VND with promotional corridor 369,000 - 399,000 VND.",
        "CLAIM_TYPE": "PRICE",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "None (Extrapolated from competitor price band)",
        "STATUS_AT_CREATION": "UNSUPPORTED_PRICE_SELECTION",
        "STATUS_IN_FINAL_OUTPUT": "EXECUTIVE_APPROVED_PRICE",
        "PROPAGATED_TO_STAGES": ["CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.30,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_BUSINESS_INPUT",
        "ORIGINATOR": "STRATEGIST",
        "PROPAGATORS": ["CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": ["CREATIVE", "PERFORMANCE", "CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-006",
        "CLAIM_TEXT": "Estimated COGS is 175,000 VND and target contribution margin is 75,000 VND/unit.",
        "CLAIM_TYPE": "INVENTED_BUSINESS_INPUT",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "None (Invented financial model)",
        "STATUS_AT_CREATION": "FABRICATED_UNIT_ECONOMICS",
        "STATUS_IN_FINAL_OUTPUT": "EXECUTIVE_FINANCIAL_GUARDRAIL",
        "PROPAGATED_TO_STAGES": ["PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.10,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_BUSINESS_INPUT",
        "ORIGINATOR": "STRATEGIST",
        "PROPAGATORS": ["PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": ["PERFORMANCE", "CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-007",
        "CLAIM_TEXT": "Maximum Blended Cost Per Acquisition (CPA) ceiling is 120,000 VND.",
        "CLAIM_TYPE": "KPI_TARGET",
        "FIRST_APPEARED_STAGE": "PERFORMANCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Derived from invented margin (CLM-006)",
        "STATUS_AT_CREATION": "UNSUPPORTED_KPI_CEILING",
        "STATUS_IN_FINAL_OUTPUT": "HARD_STOP_LOSS_GUARDRAIL",
        "PROPAGATED_TO_STAGES": ["CMO_FINAL"],
        "CONFIDENCE": 0.20,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_NUMERIC_THRESHOLD",
        "ORIGINATOR": "PERFORMANCE",
        "PROPAGATORS": ["CMO_FINAL"],
        "FAILED_REVIEWERS": ["CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-008",
        "CLAIM_TEXT": "Target ROAS hurdles set at 3.5x minimum, 4.0x scaling threshold, and 5.5x search target.",
        "CLAIM_TYPE": "KPI_TARGET",
        "FIRST_APPEARED_STAGE": "PERFORMANCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Invented in Performance tracking plan",
        "STATUS_AT_CREATION": "UNSUPPORTED_TARGET",
        "STATUS_IN_FINAL_OUTPUT": "AUTHORITATIVE_GO_NOGO_RULE",
        "PROPAGATED_TO_STAGES": ["CMO_FINAL"],
        "CONFIDENCE": 0.20,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_NUMERIC_THRESHOLD",
        "ORIGINATOR": "PERFORMANCE",
        "PROPAGATORS": ["CMO_FINAL"],
        "FAILED_REVIEWERS": ["CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-009",
        "CLAIM_TEXT": "Target Search ACOS ceiling is <= 18.0% and organic review rating target is >= 4.8 stars.",
        "CLAIM_TYPE": "KPI_TARGET",
        "FIRST_APPEARED_STAGE": "PERFORMANCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Invented in Performance metric taxonomy",
        "STATUS_AT_CREATION": "UNSUPPORTED_TARGET",
        "STATUS_IN_FINAL_OUTPUT": "EXECUTIVE_KPI_TARGET",
        "PROPAGATED_TO_STAGES": ["CMO_FINAL"],
        "CONFIDENCE": 0.20,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_NUMERIC_THRESHOLD",
        "ORIGINATOR": "PERFORMANCE",
        "PROPAGATORS": ["CMO_FINAL"],
        "FAILED_REVIEWERS": ["CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-010",
        "CLAIM_TEXT": "Maximum acceptable customer return/refund rate ceiling is <= 3.5%.",
        "CLAIM_TYPE": "KPI_TARGET",
        "FIRST_APPEARED_STAGE": "PERFORMANCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Invented in Performance guardrails",
        "STATUS_AT_CREATION": "UNSUPPORTED_THRESHOLD",
        "STATUS_IN_FINAL_OUTPUT": "STOP_LOSS_OPERATIONAL_RULE",
        "PROPAGATED_TO_STAGES": ["CMO_FINAL"],
        "CONFIDENCE": 0.25,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_NUMERIC_THRESHOLD",
        "ORIGINATOR": "PERFORMANCE",
        "PROPAGATORS": ["CMO_FINAL"],
        "FAILED_REVIEWERS": ["CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-011",
        "CLAIM_TEXT": "Offer includes a 12-Month (or 12-18 month) 1-to-1 Direct Replacement Warranty.",
        "CLAIM_TYPE": "WARRANTY",
        "FIRST_APPEARED_STAGE": "INTELLIGENCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Hypothesis H2 in Intelligence converted to offer in Strategist",
        "STATUS_AT_CREATION": "STRATEGIC_HYPOTHESIS",
        "STATUS_IN_FINAL_OUTPUT": "AUTHORITATIVE_OFFER_COMPONENT",
        "PROPAGATED_TO_STAGES": ["STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.30,
        "SUPPORTED": False,
        "FAILURE_TYPE": "HYPOTHESIS_PROMOTED_TO_FACT",
        "ORIGINATOR": "INTELLIGENCE",
        "PROPAGATORS": ["STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": ["STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-012",
        "CLAIM_TEXT": "Product provides 'Zero Motherboard Risk' warranty policy covering voltage surges.",
        "CLAIM_TYPE": "SAFETY_CLAIM",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Extrapolated from customer fear in EVID-GAN65-05",
        "STATUS_AT_CREATION": "UNSUPPORTED_RISK_REVERSAL",
        "STATUS_IN_FINAL_OUTPUT": "AUTHORITATIVE_SAFETY_CLAIM",
        "PROPAGATED_TO_STAGES": ["CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.15,
        "SUPPORTED": False,
        "FAILURE_TYPE": "CUSTOMER_REQUIREMENT_PROMOTED_TO_PRODUCT_FEATURE",
        "ORIGINATOR": "STRATEGIST",
        "PROPAGATORS": ["CREATIVE", "CMO_FINAL"],
        "FAILED_REVIEWERS": ["CREATIVE", "CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-013",
        "CLAIM_TEXT": "Store integrations include verified Shopee Mall / LazMall trust badge and 15-day hassle-free return window.",
        "CLAIM_TYPE": "OFFER",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Invented friction reducer",
        "STATUS_AT_CREATION": "UNSUPPORTED_POLICY_ASSUMPTION",
        "STATUS_IN_FINAL_OUTPUT": "COMMERCIAL_OFFER_FEATURE",
        "PROPAGATED_TO_STAGES": ["CREATIVE", "CMO_FINAL"],
        "CONFIDENCE": 0.20,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_OFFER_OR_POLICY",
        "ORIGINATOR": "STRATEGIST",
        "PROPAGATORS": ["CREATIVE", "CMO_FINAL"],
        "FAILED_REVIEWERS": ["CREATIVE", "CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-014",
        "CLAIM_TEXT": "Product physical weight is exactly ~100g compared to standard OEM bricks at 350g (or 385g on scale).",
        "CLAIM_TYPE": "PRODUCT_FACT",
        "FIRST_APPEARED_STAGE": "CREATIVE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Invented visual demo prop specifications",
        "STATUS_AT_CREATION": "FABRICATED_PHYSICAL_MEASUREMENT",
        "STATUS_IN_FINAL_OUTPUT": "SCRIPT_VISUAL_DIRECTION_AND_OFFER",
        "PROPAGATED_TO_STAGES": ["PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.10,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_PRODUCT_FACT",
        "ORIGINATOR": "CREATIVE",
        "PROPAGATORS": ["PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": ["PERFORMANCE", "CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-015",
        "CLAIM_TEXT": "Charger incorporates engineered center-of-gravity balance for loose Vietnamese 2-pin round wall outlets.",
        "CLAIM_TYPE": "PRODUCT_FACT",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Extrapolated from forum socket complaints in EVID-GAN65-03",
        "STATUS_AT_CREATION": "CUSTOMER_PAIN_PROMOTED_TO_HARDWARE_FEATURE",
        "STATUS_IN_FINAL_OUTPUT": "VALUE_PROP_ANCHOR_AND_SCRIPT_HOOK",
        "PROPAGATED_TO_STAGES": ["CREATIVE", "CMO_FINAL"],
        "CONFIDENCE": 0.15,
        "SUPPORTED": False,
        "FAILURE_TYPE": "CUSTOMER_REQUIREMENT_PROMOTED_TO_PRODUCT_FEATURE",
        "ORIGINATOR": "STRATEGIST",
        "PROPAGATORS": ["CREATIVE", "CMO_FINAL"],
        "FAILED_REVIEWERS": ["CREATIVE", "CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-016",
        "CLAIM_TEXT": "Specific laptop models listed as compatible: MacBook Air/Pro 13-14 inch, Dell XPS, ThinkPad, Asus Zenbook.",
        "CLAIM_TYPE": "PRODUCT_COMPATIBILITY",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": ["EVID-GAN65-02"],
        "SOURCE_PRODUCT_FACT": "65W USB-C PD universal negotiation (EVID-GAN65-02 cites MacBook, XPS, ThinkPad as examples)",
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Intelligence findings",
        "STATUS_AT_CREATION": "QUALIFIED_COMPATIBILITY_EXAMPLE",
        "STATUS_IN_FINAL_OUTPUT": "QUALIFIED_COMPATIBILITY_EXAMPLE",
        "PROPAGATED_TO_STAGES": ["CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.85,
        "SUPPORTED": True,
        "FAILURE_TYPE": "NONE",
        "ORIGINATOR": "INTELLIGENCE",
        "PROPAGATORS": ["STRATEGIST", "CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": []
    },
    {
        "CLAIM_ID": "CLM-017",
        "CLAIM_TEXT": "A/B Experiment EXP-GAN65-VN-001 decision rule specifies 1,200 clicks per arm, 90% confidence bounds, and 15% CVR lift.",
        "CLAIM_TYPE": "EXPERIMENT_THRESHOLD",
        "FIRST_APPEARED_STAGE": "PERFORMANCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Performance experiment blueprint",
        "STATUS_AT_CREATION": "INVENTED_STATISTICAL_RULE",
        "STATUS_IN_FINAL_OUTPUT": "AUTHORITATIVE_EXPERIMENT_GOVERNANCE",
        "PROPAGATED_TO_STAGES": ["CMO_FINAL"],
        "CONFIDENCE": 0.25,
        "SUPPORTED": False,
        "FAILURE_TYPE": "INVENTED_NUMERIC_THRESHOLD",
        "ORIGINATOR": "PERFORMANCE",
        "PROPAGATORS": ["CMO_FINAL"],
        "FAILED_REVIEWERS": ["CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-018",
        "CLAIM_TEXT": "Channel budget allocation fixed at 50% Shopee Ads, 30% TikTok Shop, and 20% Lazada.",
        "CLAIM_TYPE": "CHANNEL_DECISION",
        "FIRST_APPEARED_STAGE": "PERFORMANCE",
        "SOURCE_EVIDENCE_IDS": [],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Performance media allocation",
        "STATUS_AT_CREATION": "PROPOSED_MEDIA_ALLOCATION",
        "STATUS_IN_FINAL_OUTPUT": "APPROVED_CHANNEL_SPLIT",
        "PROPAGATED_TO_STAGES": ["CMO_FINAL"],
        "CONFIDENCE": 0.40,
        "SUPPORTED": False,
        "FAILURE_TYPE": "UNSUPPORTED_OPERATIONAL_AUTHORIZATION",
        "ORIGINATOR": "PERFORMANCE",
        "PROPAGATORS": ["CMO_FINAL"],
        "FAILED_REVIEWERS": ["CMO_FINAL"]
    },
    {
        "CLAIM_ID": "CLM-019",
        "CLAIM_TEXT": "Prohibits universal marketing to high-power gaming laptops (>100W) or non-PD proprietary laptops.",
        "CLAIM_TYPE": "PRODUCT_COMPATIBILITY",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": ["EVID-GAN65-02"],
        "SOURCE_PRODUCT_FACT": "65W maximum power output boundary",
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Intelligence spec boundary",
        "STATUS_AT_CREATION": "PROHIBITIVE_WHAT_NOT_TO_DO_RULE",
        "STATUS_IN_FINAL_OUTPUT": "PROHIBITIVE_WHAT_NOT_TO_DO_RULE",
        "PROPAGATED_TO_STAGES": ["CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "CONFIDENCE": 0.95,
        "SUPPORTED": True,
        "FAILURE_TYPE": "NONE",
        "ORIGINATOR": "STRATEGIST",
        "PROPAGATORS": ["CREATIVE", "PERFORMANCE", "CMO_FINAL"],
        "FAILED_REVIEWERS": []
    },
    {
        "CLAIM_ID": "CLM-020",
        "CLAIM_TEXT": "Explicitly prohibits marketing to low-power smartphone-only users seeking <150k VND 20W plugs.",
        "CLAIM_TYPE": "CHANNEL_DECISION",
        "FIRST_APPEARED_STAGE": "STRATEGIST",
        "SOURCE_EVIDENCE_IDS": ["EVID-GAN65-04"],
        "SOURCE_PRODUCT_FACT": None,
        "SOURCE_HUMAN_INPUT": None,
        "SOURCE_PREVIOUS_AGENT": "Competitor pricing observations",
        "STATUS_AT_CREATION": "STRATEGIC_DEFERRED_SEGMENT",
        "STATUS_IN_FINAL_OUTPUT": "STRATEGIC_DEFERRED_SEGMENT",
        "PROPAGATED_TO_STAGES": ["CREATIVE", "CMO_FINAL"],
        "CONFIDENCE": 0.90,
        "SUPPORTED": True,
        "FAILURE_TYPE": "NONE",
        "ORIGINATOR": "STRATEGIST",
        "PROPAGATORS": ["CREATIVE", "CMO_FINAL"],
        "FAILED_REVIEWERS": []
    }
]

# Write lineage json
lineage_path = base_dir / "evaluations" / "phase4_2_claim_lineage.json"
lineage_path.write_text(json.dumps({
    "metadata": {
        "analysis_phase": "4.2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_material_claims": len(claims_data),
        "supported_claims": sum(1 for c in claims_data if c["SUPPORTED"]),
        "unsupported_claims": sum(1 for c in claims_data if not c["SUPPORTED"]),
        "artifact_hashes": artifact_hashes
    },
    "claims": claims_data
}, indent=2), encoding="utf-8")

# Produce Failure Analysis Markdown
total_claims = len(claims_data)
supported_claims = sum(1 for c in claims_data if c["SUPPORTED"])
unsupported_claims = sum(1 for c in claims_data if not c["SUPPORTED"])

unsupported_by_origin = {}
for c in claims_data:
    if not c["SUPPORTED"]:
        orig = c["ORIGINATOR"]
        unsupported_by_origin[orig] = unsupported_by_origin.get(orig, 0) + 1

propagation_count = sum(len(c["PROPAGATORS"]) for c in claims_data if not c["SUPPORTED"])
final_qa_escape_count = sum(1 for c in claims_data if not c["SUPPORTED"] and "CMO_FINAL" in c["PROPAGATORS"])

report_md = f"""# PHASE 4.2: FIVE-AGENT HALLUCINATION & HANDOFF FAILURE ANALYSIS

> **DOCUMENT PURPOSE:**  
> Exhaustive forensic lineage audit and root-cause analysis of unsupported claim invention, assumption escalation, and final QA escapes in the frozen Phase 4.1.2 Five-Agent architecture.

---

## 1. Frozen Benchmark Artifacts & Hashes

| Artifact File | Relative Path | SHA256 Hash | Size (Bytes) |
|---|---|---|:---:|
| **Single Output** | `evaluations/benchmarks/phase4_1_2_true_parity/single/output.json` | `{artifact_hashes.get('single', {}).get('sha256', 'N/A')}` | `{artifact_hashes.get('single', {}).get('size_bytes', 0)}` |
| **CMO Initial** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/initial_cmo.json` | `{artifact_hashes.get('cmo_init', {}).get('sha256', 'N/A')}` | `{artifact_hashes.get('cmo_init', {}).get('size_bytes', 0)}` |
| **Intelligence** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/intelligence.json` | `{artifact_hashes.get('intelligence', {}).get('sha256', 'N/A')}` | `{artifact_hashes.get('intelligence', {}).get('size_bytes', 0)}` |
| **Strategist** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/strategist.json` | `{artifact_hashes.get('strategist', {}).get('sha256', 'N/A')}` | `{artifact_hashes.get('strategist', {}).get('size_bytes', 0)}` |
| **Creative** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/creative.json` | `{artifact_hashes.get('creative', {}).get('sha256', 'N/A')}` | `{artifact_hashes.get('creative', {}).get('size_bytes', 0)}` |
| **Performance** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/performance.json` | `{artifact_hashes.get('performance', {}).get('sha256', 'N/A')}` | `{artifact_hashes.get('performance', {}).get('size_bytes', 0)}` |
| **CMO Final** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/final_cmo.json` | `{artifact_hashes.get('cmo_final', {}).get('sha256', 'N/A')}` | `{artifact_hashes.get('cmo_final', {}).get('size_bytes', 0)}` |

---

## 2. Quantitative Summary Metrics

- **TOTAL_MATERIAL_CLAIMS:** **`{total_claims}`**
- **SUPPORTED_CLAIMS:** **`{supported_claims}`** ({supported_claims/total_claims*100:.1f}%)
- **UNSUPPORTED_CLAIMS:** **`{unsupported_claims}`** ({unsupported_claims/total_claims*100:.1f}%)
- **UNSUPPORTED_BY_ORIGIN_AGENT:**
{json.dumps(unsupported_by_origin, indent=2)}
- **PROPAGATION_COUNT:** **`{propagation_count}`** handoff propagation events across downstream stages.
- **FINAL_QA_ESCAPE_COUNT:** **`{final_qa_escape_count}`** unsupported claims approved and signed off in `final_cmo.json` (100% escape rate).

---

## 3. Claim Lineage & Responsibility Trace Matrix

| Claim ID | Claim Summary | Origin Agent | Failure Category | Receiving Agents | Amplifiers | Failed Reviewers | CMO Final Action |
|---|---|---|---|---|---|---|---|
| **CLM-004** | 20M VND pilot budget | `PERFORMANCE` | `INVENTED_BUSINESS_INPUT` | `CMO_FINAL` | `PERFORMANCE` | `CMO_FINAL` | **Authorized as hard budget** |
| **CLM-005** | 369k-429k VND retail price | `STRATEGIST` | `INVENTED_BUSINESS_INPUT` | `CREATIVE, PERF, CMO` | `STRAT, PERF` | `CRTV, PERF, CMO` | **Signed off as pricing policy** |
| **CLM-006** | 175k COGS / 75k Margin | `STRATEGIST` | `INVENTED_BUSINESS_INPUT` | `PERF, CMO_FINAL` | `STRAT, PERF` | `PERF, CMO_FINAL` | **Signed off as financial target** |
| **CLM-007** | CPA <= 120,000 VND | `PERFORMANCE` | `INVENTED_NUMERIC_THRESHOLD` | `CMO_FINAL` | `PERFORMANCE` | `CMO_FINAL` | **Authorized as stop-loss ceiling** |
| **CLM-008** | ROAS >= 3.5x / 4.0x / 5.5x | `PERFORMANCE` | `INVENTED_NUMERIC_THRESHOLD` | `CMO_FINAL` | `PERFORMANCE` | `CMO_FINAL` | **Authorized as scaling hurdle** |
| **CLM-009** | Search ACOS <= 18%, 4.8 Rating | `PERFORMANCE` | `INVENTED_NUMERIC_THRESHOLD` | `CMO_FINAL` | `PERFORMANCE` | `CMO_FINAL` | **Signed off as KPI target** |
| **CLM-010** | Return Rate <= 3.5% | `PERFORMANCE` | `INVENTED_NUMERIC_THRESHOLD` | `CMO_FINAL` | `PERFORMANCE` | `CMO_FINAL` | **Authorized as kill trigger** |
| **CLM-011** | 12-Month 1-to-1 Warranty | `INTELLIGENCE` | `HYPOTHESIS_PROMOTED_TO_FACT` | `STRAT, CRTV, PERF, CMO` | `STRAT, CRTV` | `ALL DOWNSTREAM` | **Signed off as core offer** |
| **CLM-012** | 'Zero Motherboard Risk' | `STRATEGIST` | `CUSTOMER_REQ_TO_FEATURE` | `CRTV, PERF, CMO` | `CRTV, STRAT` | `CRTV, CMO_FINAL` | **Signed off as risk reversal** |
| **CLM-013** | Shopee Mall Trust / 15-day return | `STRATEGIST` | `INVENTED_OFFER_OR_POLICY` | `CRTV, CMO_FINAL` | `STRAT` | `CRTV, CMO_FINAL` | **Signed off as offer feature** |
| **CLM-014** | 100g GaN vs 350g/385g OEM weight | `CREATIVE` | `INVENTED_PRODUCT_FACT` | `PERF, CMO_FINAL` | `CRTV` | `PERF, CMO_FINAL` | **Signed off in video storyboard** |
| **CLM-015** | Engineered socket balance design | `STRATEGIST` | `CUSTOMER_REQ_TO_FEATURE` | `CRTV, CMO_FINAL` | `CRTV, STRAT` | `CRTV, CMO_FINAL` | **Signed off as hardware feature** |
| **CLM-017** | 1,200 clicks / 90% conf / 15% CVR | `PERFORMANCE` | `INVENTED_NUMERIC_THRESHOLD` | `CMO_FINAL` | `PERFORMANCE` | `CMO_FINAL` | **Authorized as experiment rule** |
| **CLM-018** | 50/30/20 channel budget split | `PERFORMANCE` | `UNSUPPORTED_OPERATIONAL_AUTH` | `CMO_FINAL` | `PERFORMANCE` | `CMO_FINAL` | **Authorized as launch split** |

---

## 4. Systemic Root Causes

1. **Schema Pressure for Concrete Values:**  
   Downstream specialist schemas (e.g. `pricing_structure`, `budget_allocated_vnd`, `guardrail_metrics`) expected typed integers and concrete policy strings. When these business inputs were unknown, models filled the schema slots with plausibly sounding hallucinations rather than preserving `UNKNOWN` or `TO_BE_ESTABLISHED`.

2. **Hypothesis-to-Fact Escalation Across Handoff Boundaries:**  
   When an upstream agent (e.g. Intelligence) formulated a testable hypothesis (e.g. `H2: Positioning with 12-month warranty will maximize volume`), the downstream agent (Strategist) stripped the `HYPOTHESIS` prefix and incorporated it as an authoritative offer commitment (`core_offer: 65W GaN + 12-Month Warranty`).

3. **Customer Pain Conversion into SKU Capabilities:**  
   Customer anxieties (e.g. "fear of charger falling out of loose sockets" in EVID-GAN65-03) were converted by Strategist into unverified product features ("Engineered balanced center-of-gravity for Vietnamese sockets") without engineering test proof.

4. **Performance Marketing Concrete Target Fabrication:**  
   The Performance agent invented precise statistical stopping rules (1,200 clicks, 90% confidence, 15% MDE, 120k CPA) without empirical variance baselines or human financial authorization.

5. **CMO Final as Passive Aggregator vs Fail-Closed Gatekeeper:**  
   `CMO Final` acted as an executive narrative synthesizer rather than a strict provenance auditor. Instead of rejecting unverified budgets (20M VND) or fabricated warranties (12 months), it rubber-stamped them into authoritative executive directives.

---

## 5. Proposed Systemic Fixes

### A. Strict Claim Provenance Contract
Every material claim passed across agent handoffs must carry structured provenance metadata:
```json
{{
  "claim_text": "string",
  "claim_class": "FACT | OBSERVATION | INFERENCE | HYPOTHESIS | PROPOSAL",
  "source_type": "INPUT_SPEC | VERIFIED_EVIDENCE | HUMAN_AUTHORIZED | UNKNOWN",
  "source_ids": ["EVID-..."],
  "support_status": "SUPPORTED | TO_BE_ESTABLISHED | UNSUPPORTED",
  "allowed_usage": "FACT_AUTHORITY | TEST_PROPOSAL_ONLY | RESTRICTED"
}}
```

### B. Unknown Preservation & Numeric Authority Rule
- No agent may invent numerical values for: `budget`, `retail_price`, `cogs`, `margin`, `cpa_ceiling`, `roas_hurdle`, `sample_size`, `mde`, `confidence_level`, `warranty_duration`.
- If unprovided in input or evidence, agents must use `TO_BE_ESTABLISHED` or explicit `PROPOSAL_FOR_TEST` containers.

### C. Product Claim Firewall
- Strictly enforces:
  - `CUSTOMER_PAIN_POINT != OUR_PRODUCT_FEATURE`
  - `CATEGORY_TECHNOLOGY_ADVANTAGE != SKU_TESTED_PERFORMANCE`
  - `COMPETITOR_CAPABILITY != OUR_PRODUCT_CAPABILITY`

### D. Handoff Claim Inheritance & Status Invariance
- Receiving agents are strictly prohibited from upgrading a claim's status.
- A `HYPOTHESIS` in Stage $N$ must remain a `HYPOTHESIS` in Stage $N+1$.

### E. CMO Final Fail-Closed Provenance Gate
- Before signing off any directive, CMO Final must execute an automated scan against the Claim Provenance Register.
- Any unbacked numerical target, fabricated warranty, or unverified hardware claim automatically triggers `REJECT_OR_DOWNGRADE` to `HUMAN_APPROVAL_REQUIRED`.

---
*End of Phase 4.2 Failure Analysis.*
"""
(base_dir / "evaluations" / "phase4_2_failure_analysis.md").write_text(report_md, encoding="utf-8")

print(f"Generated {lineage_path} ({len(claims_data)} claims)")
print(f"Generated {base_dir / 'evaluations' / 'phase4_2_failure_analysis.md'}")
print(f"Supported: {supported_claims}, Unsupported: {unsupported_claims}")
print(f"Unsupported by Origin: {unsupported_by_origin}")
