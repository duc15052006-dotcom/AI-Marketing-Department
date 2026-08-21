# PHASE 4.2: FIVE-AGENT HALLUCINATION & HANDOFF FAILURE ANALYSIS

> **DOCUMENT PURPOSE:**  
> Exhaustive forensic lineage audit and root-cause analysis of unsupported claim invention, assumption escalation, and final QA escapes in the frozen Phase 4.1.2 Five-Agent architecture.

---

## 1. Frozen Benchmark Artifacts & Hashes

| Artifact File | Relative Path | SHA256 Hash | Size (Bytes) |
|---|---|---|:---:|
| **Single Output** | `evaluations/benchmarks/phase4_1_2_true_parity/single/output.json` | `10b98a87f850ddcf92275b55c93635659400386b82a55c68dae8247ecb1f010f` | `13308` |
| **CMO Initial** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/initial_cmo.json` | `5eaa66f9d8e6573006012d02b2f793daa5079c2d0aca0ca65900e9322a17d1ca` | `4285` |
| **Intelligence** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/intelligence.json` | `e9a0f1b6ea8685a75d0ac0fd7ff071a1b8719c3717e2d20fa36062f4d6266d4f` | `6499` |
| **Strategist** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/strategist.json` | `f88d24a6e2b828d550d20a360b7f33279abdfeb1d429948129fd0b43db554ee9` | `8892` |
| **Creative** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/creative.json` | `b43469d7c89d75c86bf5f9dd898690d06af64b309daa5fd2d345ee03930a03a5` | `13614` |
| **Performance** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/performance.json` | `fd2ef669b17a60510afd797b84efb2509daf3ceb42a4c450541d1619ca83f8d7` | `14132` |
| **CMO Final** | `evaluations/benchmarks/phase4_1_2_true_parity/five_agent/final_cmo.json` | `61ac957c88dca22a9c6b302e3f5c0eea4c25c516553e16e1af57c93b7ca1a1a1` | `6959` |

---

## 2. Quantitative Summary Metrics

- **TOTAL_MATERIAL_CLAIMS:** **`20`**
- **SUPPORTED_CLAIMS:** **`6`** (30.0%)
- **UNSUPPORTED_CLAIMS:** **`14`** (70.0%)
- **UNSUPPORTED_BY_ORIGIN_AGENT:**
{
  "PERFORMANCE": 7,
  "STRATEGIST": 5,
  "INTELLIGENCE": 1,
  "CREATIVE": 1
}
- **PROPAGATION_COUNT:** **`24`** handoff propagation events across downstream stages.
- **FINAL_QA_ESCAPE_COUNT:** **`14`** unsupported claims approved and signed off in `final_cmo.json` (100% escape rate).

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
{
  "claim_text": "string",
  "claim_class": "FACT | OBSERVATION | INFERENCE | HYPOTHESIS | PROPOSAL",
  "source_type": "INPUT_SPEC | VERIFIED_EVIDENCE | HUMAN_AUTHORIZED | UNKNOWN",
  "source_ids": ["EVID-..."],
  "support_status": "SUPPORTED | TO_BE_ESTABLISHED | UNSUPPORTED",
  "allowed_usage": "FACT_AUTHORITY | TEST_PROPOSAL_ONLY | RESTRICTED"
}
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
