# Phase 4.3C.11: V3 Frozen Fair Three-Way Live Candidate Generation Report
## Case 02 — SecureCode AI SEA

**Document Status:** `FROZEN_CANDIDATES_SEALED`  
**Execution Generation:** `phase4_3_v3`  
**Case ID:** `CASE_02_DEV_SECURITY_SEA`  
**Active Protocol Fingerprint:** `4585defccbe3870ddd6d1f4d6821043e4828e4e33ea3d5dcc38cbe3bf6324273`  
**Executed At:** `2026-08-19T07:15:13.422501+00:00`  
**Provider / Model:** `gemini` / `gemini-flash-latest` (`gemini-3.5-flash`)  
**Strict Model Pin:** `True` | **Max Output Tokens:** `8192`  

---

## 1. Active Protocol Verification
- **Expected Fingerprint:** `4585defccbe3870ddd6d1f4d6821043e4828e4e33ea3d5dcc38cbe3bf6324273`
- **Verified Fingerprint:** `4585defccbe3870ddd6d1f4d6821043e4828e4e33ea3d5dcc38cbe3bf6324273`
- **Protocol Integrity Status:** `PASS`
- **Frozen Hashes Verified:**
  - `BENCHMARK_INPUT_HASH`: `86266ab3a4a4eb73dea410df9f3679f5d78cda505e9fc5672c7468c107f37fea`
  - `PROMPT_HASH_A3`: `7a273412e6991d2f9e59c91360e4c0e534deeeadeb4c76761bfbdd5b9c13f0f0`
  - `PROMPT_HASH_B3`: `245481e8953b042c08824e58567308670b1430868277c2d2e2dd4ec6e606d450`
  - `PROMPT_HASH_C3`: `05c9e7bed0bfd2403bb54ef41458bea16cc0e9bb0c053a6ab4d24bc320e60e33`
  - `B3_PASS_1_HASH`: `dcf5035835b7914261080bf8aea86141e5db43f58518b86664c19c60d312501d`
  - `B3_PASS_2_HASH`: `e7ac78a853d27f58a97f8b383e12efadc734928031f92469290eabb4e48bd5d8`
  - `B3_PASS_3_HASH`: `953194ef4bb8493941488628f776219d6969f65a3b647ad5dbb1523bd6b86f9e`

---

## 2. Common Model Configuration
- **Provider:** `gemini`
- **Requested Model:** `gemini-flash-latest`
- **Resolved Model:** `gemini-3.5-flash`
- **Strict Model Pin:** `True`
- **Temperature:** `0.2` | **Top P:** `0.95` | **Top K:** `40`
- **Max Output Tokens:** `8192` (Identical across Candidate A3, B3, and C3)
- **Timeout:** `180.0s` | **Retry Policy:** `MAX_1_TRANSIENT_RETRY (503 / socket timeout only)`

---

## 3. Candidate A3 Fresh Execution (`RUN-PHASE4-3-V3-CASE02-A3-001`)
- **Architecture:** Role-Specialized Governed Five-Agent V3
- **Stages Executed:** 6 sequential stages (`CMO Initial` $ightarrow$ `Intelligence` $ightarrow$ `Strategist` $ightarrow$ `Creative` $ightarrow$ `Performance` $ightarrow$ `Final CMO`)
- **Status:** `SUCCESS` (6/6 stages completed)
- **Provider Total Tokens:** `27276`
- **Visible Input Tokens:** `4830`
- **Visible Output Tokens:** `9068`
- **Reasoning Tokens:** `13378`
- **End-to-End Latency:** `102426.8ms`
- **Artifact Hash:** `bb24e9e05a31198ba7ca287f27a71f5e1e361bbcc6730896769c7677aa1c605c`

---

## 4. Candidate A3 Handoff & Collaboration Integrity
- **Handoff Contract:** `HandoffPackage_v3`
- **5 Transport Edges Verified:** `PASS`
- **Semantic Utilization:** `PASS`
- **Claim Safety:** CMO Final Gate Authorized (Zero unverified claims permitted)
- **Case 01 Content Reuse:** `0` | **Simulated Artifacts:** `0`

---

## 5. Dynamic Same-Case Candidate B3 Resource Target Calculation
- **Firewall Extraction:** Extracted strictly `A3_ACTUAL_PROVIDER_TOTAL_TOKENS = 27276`
- **A3-to-B3 Content Leak Count:** `0` (Zero raw text, zero strategy, zero findings leaked)
- **Target Budget Formula:** `B3_RESOURCE_TARGET = 27276`
- **Target Budget Range ($\pm 10\%$):** `[24548, 30004]`

---

## 6. Candidate B3 Three-Pass Execution (`RUN-PHASE4-3-V3-CASE02-B3-001`)
- **Architecture:** Single-Agent Bounded Multi-Pass Control (Senior Strategic Marketing Director)
- **Logical Agent Identity Count:** `1` (Zero specialist personas injected)
- **Source Grounding Method:** `METHOD_A_SOURCE_BUNDLE_IN_ALL_PASSES`
- **Working Memory Mode:** `CUMULATIVE_BOUNDED` (Raw history recursion disabled)
- **Max Observed State Tokens:** `663` (Limit: $\le 1500$)
- **Status:** `SUCCESS` (3/3 passes completed)
- **Provider Total Tokens:** `29728`
- **End-to-End Latency:** `87129.4ms`
- **Artifact Hash:** `2b5e2ba1952cbcffe4cd96e263471945c8cee0a3520dafd0d8e97dbc82f13f2a`

---

## 7. Candidate B3 Resource Parity Status
- **Target Range:** `24548` to `30004`
- **Actual Tokens Consumed:** `29728`
- **Resource Parity Verdict:** `PASS`
- **Primary Evaluation Eligibility:** `PRIMARY_A3_VS_B3_COMPARISON_ELIGIBLE = YES`

---

## 8. Candidate C3 One-Shot Execution (`RUN-PHASE4-3-V3-CASE02-C3-001`)
- **Architecture:** Single-Agent One-Shot (Practical Baseline)
- **Calls Executed:** 1 direct model call requesting all 28 canonical deliverables
- **Status:** `SUCCESS`
- **Provider Total Tokens:** `9603`
- **End-to-End Latency:** `36991.2ms`
- **Artifact Hash:** `1e4702074316deb8b8f6dc235a3728969d1477333b752839e1922b492a443759`

---

## 9. Architecture-Neutral Canonical Assembly Results

| Metric | Candidate A3 (Five-Agent V3) | Candidate B3 (Single Multi-Pass) | Candidate C3 (Single One-Shot) |
|---|---|---|---|
| **Deliverables Found** | **21/28** | **21/28** | **18/28** |
| **Completeness %** | **75.0%** | **75.0%** | **64.3%** |
| **Content Patch Count** | **0** | **0** | **0** |
| **Semantic Rewrite Count** | **0** | **0** | **0** |
| **Fabricated Deliverables** | **0** | **0** | **0** |

---

## 10. Token & Usage Accounting Summary

| Candidate | Calls | Input Tokens | Output Tokens | Reasoning Tokens | Total Provider Tokens |
|---|---|---|---|---|---|
| **Candidate A3** | 6 | 4830 | 9068 | 13378 | **27276** |
| **Candidate B3** | 3 | 7100 | 14582 | 8046 | **29728** |
| **Candidate C3** | 1 | 1415 | 5662 | 2526 | **9603** |

---

## 11. Contamination & Invariants Audit
- `A3_TO_B3_CONTENT_LEAK_COUNT = 0`
- `A3_TO_C3_CONTENT_LEAK_COUNT = 0`
- `B3_TO_C3_CONTENT_LEAK_COUNT = 0`
- `CASE01_CONTENT_REUSE_COUNT = 0`
- `V1_REUSE_COUNT = 0`
- `SIMULATED_ARTIFACT_USED_COUNT = 0`
- `CONTENT_PATCH_COUNT = 0`
- `SEMANTIC_REWRITE_COUNT = 0`
- `FABRICATED_DELIVERABLE_COUNT = 0`
- `PROVIDER_TOKEN_ACCOUNTING_DELTA = 0`

---

## 12. Artifact Hashes & Sealing
- **Candidate A3:** `bb24e9e05a31198ba7ca287f27a71f5e1e361bbcc6730896769c7677aa1c605c`
- **Candidate B3:** `2b5e2ba1952cbcffe4cd96e263471945c8cee0a3520dafd0d8e97dbc82f13f2a`
- **Candidate C3:** `1e4702074316deb8b8f6dc235a3728969d1477333b752839e1922b492a443759`
- **Status:** `ALL THREE CANDIDATES CRYPTOGRAPHICALLY SEALED & IMMUTABLE`
