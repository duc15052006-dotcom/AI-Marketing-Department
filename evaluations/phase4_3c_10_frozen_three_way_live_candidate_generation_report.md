# Phase 4.3C.10: Frozen Three-Way Live Benchmark Candidate Generation Report

**Document Status:** `FROZEN_CANDIDATES_SEALED`  
**Execution Generation:** `phase4_3_v2`  
**Active Protocol Fingerprint:** `462086a31dd80c257ecbabfba12d6249772c3207e86ce379d8d76ea2248ceb0f`  
**Executed At:** `2026-08-19T06:33:11.410378+00:00`  
**Provider / Model:** `gemini` / `gemini-flash-latest` (`gemini-3.5-flash`)  
**Strict Model Pin:** `True` | **Max Output Tokens:** `8192`  

---

## 1. Active Protocol Verification
- **Expected Fingerprint:** `462086a31dd80c257ecbabfba12d6249772c3207e86ce379d8d76ea2248ceb0f`
- **Verified Fingerprint:** `462086a31dd80c257ecbabfba12d6249772c3207e86ce379d8d76ea2248ceb0f`
- **Protocol Integrity Status:** `PASS`
- **Frozen Hashes Verified:**
  - `BENCHMARK_INPUT_HASH`: `ec155c53ffbca8b5ae52d358803092d3c876e0de30fb24ed0e824dfad1dbd8a5`
  - `DELIVERABLE_SCHEMA_HASH`: `61a9f7d1ba756b72aeb91ffc5746bdf7433e960673147823bff2d91c565abf68`
  - `EVALUATION_RUBRIC_HASH`: `c5e990a9b2fbe4e1a850f8bdf5a254c69d3468a62529d2e147569d412528f605`
  - `PROMPT_HASH_A`: `d7a41db2aeddd8e5f1c5346b65a293c8f58c2f64022a7b05de93eac09060dd45`
  - `PROMPT_HASH_B`: `a9ccf32deabfb4a361c44a5efc20a66e159d2ebc424805b1a7d70b185335ed62`
  - `PROMPT_HASH_C`: `28c830ccf3839c0919c82e7347b0c12a4f141c6ebcc92370a08bc261fa1858b5`

---

## 2. Common Model Configuration
- **Provider:** `gemini`
- **Requested Model:** `gemini-flash-latest`
- **Resolved Model:** `gemini-3.5-flash`
- **Strict Model Pin:** `True`
- **Temperature:** `0.2` | **Top P:** `0.95` | **Top K:** `40`
- **Max Output Tokens:** `8192` (Identical across Candidate A, B, and C)
- **Timeout:** `180.0s` | **Retry Policy:** `MAX_1_TRANSIENT_RETRY (503 / socket timeout only)`

---

## 3. Candidate A Fresh Execution (`RUN-PHASE4-3-V2-BENCH-001`)
- **Architecture:** Role-Specialized Governed Five-Agent V2
- **Stages Executed:** 6 sequential stages (`CMO Initial` $\rightarrow$ `Intelligence` $\rightarrow$ `Strategist` $\rightarrow$ `Creative` $\rightarrow$ `Performance` $\rightarrow$ `Final CMO`)
- **Status:** `SUCCESS` (6/6 stages completed)
- **Provider Total Tokens:** `29516`
- **Visible Input Tokens:** `6263`
- **Visible Output Tokens:** `10514`
- **Reasoning Tokens:** `0`
- **End-to-End Latency:** `147021.0ms`

---

## 4. Candidate A Handoff Integrity
- **Handoff Contract:** `HandoffPackage_v2`
- **5 Transport Edges Verified:** `PASS`
- **Semantic Utilization:** `PASS` (Downstream stages reference upstream findings and evidence)
- **Claim Safety:** CMO Final Gate Authorized (Zero unverified claims permitted)
- **V1 Checkpoint Reuse:** `0` | **Simulated Artifacts:** `0`

---

## 5. Candidate A Sealing
- **Artifact Directory:** `C:\AI-Marketing-Department\evaluations\benchmarks\phase4_3_unseen_ai_speaking\runs\phase4_3_v2\RUN-PHASE4-3-V2-BENCH-001`
- **Candidate A Artifact Hash:** `402f852fa12f700f818a690af47b3402dea6f79f3616e758d3f21a08b2425d94`
- **Status:** `SEALED & IMMUTABLE`

---

## 6. Dynamic Candidate B Resource Target Calculation
- **Firewall Extraction:** Extracted strictly `A_ACTUAL_PROVIDER_TOTAL_TOKENS = 29516`
- **A-to-B Content Leak Count:** `0` (Zero raw text, zero strategy, zero findings leaked)
- **Target Budget Formula:** `B_TARGET = 29516`
- **Target Budget Range ($\pm 10\%$):** `[26564, 32468]`

---

## 7. Candidate B Five-Pass Execution (`RUN-PHASE4-3-V2-BENCH-001-CAND-B-R2`)
- **Architecture:** Single-Agent Multi-Pass (Unified Planning Engine with Iterative Working Memory)
- **Passes Executed:** 5 sequential passes
  - Pass 1: Research, Evidence Grounding & Problem Decomposition
  - Pass 2: Customer Segmentation, Positioning & Channel Priorities
  - Pass 3: Creative Direction, Angles, Hooks & Short-Form Copy
  - Pass 4: Measurement Framework, Experiments & Attribution
  - Pass 5: Strategic Governance, Top Priorities & Synthesis
- **Status:** `SUCCESS` (5/5 passes completed)
- **Provider Total Tokens:** `59382`
- **End-to-End Latency:** `151688.8ms`

---

## 8. Candidate B Resource Parity Status
- **Target Range:** `26564` to `32468`
- **Actual Tokens Consumed:** `59382`
- **Resource Parity Verdict:** `OVER_BUDGET`
- **Evaluation Eligibility:** `PRIMARY_A_VS_B_COMPARISON_ELIGIBLE = NO (Monitored secondary comparison)`

---

## 9. Candidate C One-Shot Execution (`RUN-PHASE4-3-V2-BENCH-001-CAND-C`)
- **Architecture:** Single-Agent One-Shot (Practical Baseline)
- **Calls Executed:** 1 direct model call requesting all 28 canonical deliverables
- **Status:** `SUCCESS`
- **Provider Total Tokens:** `10304`
- **End-to-End Latency:** `50412.1ms`

---

## 10. Architecture-Neutral Canonical Assembly Results

| Metric | Candidate A (Five-Agent V2) | Candidate B (Single Multi-Pass) | Candidate C (Single One-Shot) |
|---|---|---|---|
| **Deliverables Found** | **21/28** | **23/28** | **12/28** |
| **Completeness %** | **75.0%** | **82.1%** | **42.9%** |
| **Content Patch Count** | **0** | **0** | **0** |
| **Semantic Rewrite Count** | **0** | **0** | **0** |
| **Fabricated Deliverables** | **0** | **0** | **0** |

---

## 11. Deliverable Origin Maps
All deliverables extracted with `CONTENT_MUTATED = FALSE` and `FABRICATED = FALSE` under `PARTIAL_IMMUTABLE_SALVAGE`. Detailed JSON maps stored in `phase4_3c_10_generation_summary.json`.

---

## 12. Token & Usage Accounting Summary

| Candidate | Calls | Input Tokens | Output Tokens | Reasoning Tokens | Total Provider Tokens |
|---|---|---|---|---|---|
| **Candidate A** | 6 | 6263 | 10514 | 0 | **29516** |
| **Candidate B** | 5 | 30462 | 15937 | - | **59382** |
| **Candidate C** | 1 | 2116 | 2024 | - | **10304** |

---

## 13. Retry Accounting
- **Total Compute Consumed:** `99202` tokens
- **Valid Candidate Generation Tokens:** `99202` tokens
- **Failed Transient Retries:** `0`

---

## 14. Contamination & Integrity Audit
- `A_TO_B_CONTENT_LEAK_COUNT`: **0**
- `A_TO_C_CONTENT_LEAK_COUNT`: **0**
- `B_TO_C_CONTENT_LEAK_COUNT`: **0**
- `HISTORICAL_A_CONTENT_REUSE_COUNT`: **0**
- `V1_REUSE_COUNT`: **0**
- `SIMULATED_ARTIFACT_USED_COUNT`: **0**
- `OFFLINE_FIXTURE_AS_LIVE_COUNT`: **0**

---

## 15. Candidate Artifact Hashes
- **Candidate A Artifact Hash:** `402f852fa12f700f818a690af47b3402dea6f79f3616e758d3f21a08b2425d94`
- **Candidate B Artifact Hash:** `cab444d8e65a974cd4dc498845a5e1b19d50bd5840f6cdfb2ac7d30c5983fd2e`
- **Candidate C Artifact Hash:** `068f8db3050fbe0faecbedbf9d66c386f447e9f60f2daca6d6a95b3086f678d3`
- **Sealing Status:** `ALL THREE CANDIDATES SEALED AND CRYPTOGRAPHICALLY LOCKED`

---

## 16. Blind Evaluation Readiness
- `CANDIDATES_SEALED`: **YES**
- `BLIND_EVALUATION_READY`: **YES**
- **Next Phase:** `PHASE 4.3C.11 — DOUBLE-BLIND INDEPENDENT QUALITY EVALUATION`
