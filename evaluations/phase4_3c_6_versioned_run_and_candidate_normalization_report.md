# Phase 4.3C.6: Versioned Benchmark Run Integrity & Canonical Candidate Normalization Report

**Timestamp**: 2026-08-18T09:28:00Z  
**Execution Generation**: `phase4_3_v2`  
**Run ID**: `RUN-PHASE4-3-V2-001`  
**Deterministic Run Fingerprint**: `9d4259dd764b39352e89fa6b27e69a0378ce5bb18a54d5bce1354bb47f48039d` (Dynamic SHA-256 over immutable inputs)  
**Provider / Model Pinned**: `xkiro` / `mistralai/mistral-large-2512`  
**Benchmark Domain**: AI English Speaking App (Vietnam) (`PROD_UNSEEN_AI_SPEAK_VN`)  
**Strict Policy**: Free-Only Mode (`FREE_ONLY_MODE = TRUE`), Zero LLM Output Mutation (`CONTENT_PATCH_COUNT = 0`, `SEMANTIC_REWRITE_COUNT = 0`), Zero Live Calls in Verification Phase (`LIVE_CALLS = 0`).

---

## 1. Executive Summary

Phase 4.3C.6 establishes strict **Versioned Benchmark Run Integrity** and a deterministic **Canonical Proposal Normalization Engine** across the marketing department benchmark suite.

### Key Defect Diagnoses and Resolutions:
1. **Confirmed Defect A (V1 Checkpoint Reuse Attack Prevented)**:
   - Historical V1 Five-Agent checkpoints (which lacked structured handoff text, containing only 22–24 prompt tokens) have been frozen and sealed under `runs/phase4_3_v1/historical/`.
   - All V2 run operations enforce immutable run ownership (`run_fingerprint`, `execution_generation == "phase4_3_v2"`, `context_version == "v2"`). V1 checkpoints fail-closed with `V1_REUSE_IN_V2 = FALSE`.
2. **Confirmed Defect B (Single Output Syntax & Truncation Forensic Resolution)**:
   - The live Single output from xKiro (`mistralai/mistral-large-2512`) produced 18,487 characters.
   - Deep forensic examination revealed the generation hit the provider's max output token limit of 4,096 tokens (`completion_tokens = 4096`), truncating midway through `hooks.short_form_hooks` and omitting trailing deliverables and closing braces.
   - The deterministic normalizer strictly fails closed on incomplete syntax (`NORMALIZATION_FAILED`) with **0 hallucinated content patching** and **0 fabricated closing braces** (`SINGLE_RECOVERABLE_WITHOUT_MODEL_CALL = FALSE`).
3. **Artifact Layer Separation**:
   - Enforced three-way artifact separation: `raw/` (unmodified model wire text), `parsed/` (extracted JSON/AST structures), and `canonical/` (`CanonicalProposal` conforming to all 28 deliverables across 7 categories).
4. **Blind Review Packet & Completeness Gate**:
   - `assemble_blind_packet.py` now consumes exclusively `CanonicalProposal` objects. If either candidate fails the 7-category completeness gate, packet generation fails closed (`0 leaked identities`).

---

## 2. Frozen Historical V1 Artifacts

All 10 historical V1 artifacts have been verified and archived in `evaluations/benchmarks/phase4_3_unseen_ai_speaking/runs/phase4_3_v1/historical/`:

| Artifact Name | Historical Status | SHA-256 Checksum |
| :--- | :--- | :--- |
| `claim_register_checkpoint.json` | FROZEN_V1 | `417d3ef2c8be341ff4d09f22e9eb46c363d30965bc9f93e8b07aaea3721329d6` |
| `final_cmo_audit.json` | FROZEN_V1 | `4c63f0a55bab99687632d1acb048721843967100da926bbbf3440cd343e35d20` |
| `five_agent_final.json` | FROZEN_V1 | `f03b357b6622ad3d33ab89195c6382c4e6ffc6ed45d69fd35d86923ce77e15dc` |
| `five_agent_stage_1_cmo.json` | FROZEN_V1 | `37dfebe62e9b139d86b4d999f4e3303a958219ed12c7b2de0d79945f4bb99e54` |
| `five_agent_stage_2_intel.json` | FROZEN_V1 | `092bea2152ba99aa91facfdd6ac0795731abe30d9811ab8df869d2eb6f3d606c` |
| `five_agent_stage_3_strat.json` | FROZEN_V1 | `c83db3ebac66ddfa3a89dca62e41e9c717cafcc6ea92bc3299faed9bc8dce4a5` |
| `five_agent_stage_4_crtv.json` | FROZEN_V1 | `c825ce59409c6277880afcac6bc6793a16d4b91825e2d54972ccaa04b606599f` |
| `five_agent_stage_5_perf.json` | FROZEN_V1 | `150ab0526ada21273b0269ea353d10c65e7cc437a96666dd31bf268c0bd6663b` |
| `five_agent_stage_6_final_cmo.json` | FROZEN_V1 | `6852ba4948db5056b55f3ecf7ae7c18420312dee37a30e941b5c4ccd4cbc3cfb` |
| `single_output.json` | FROZEN_V1 | `c550e127055bfde5f85aa353d5e3bbb163652846159595d7e119c0e9f61bd0f9` |

---

## 3. Architecture & Contract Specifications

### 3.1 Benchmark Run Manifest (`schemas/manifest.py`)
`BenchmarkRunManifest` holds immutable run parameters and computes a deterministic `RUN_FINGERPRINT` over:
- `benchmark_id`
- `execution_generation` (`phase4_3_v2`)
- `handoff_contract_version` (`v2`)
- `benchmark_schema_version` (`v2`)
- `candidate_schema_version` (`v2`)
- `benchmark_spec_hash`, `product_facts_hash`, `evidence_bundle_hash`, `single_prompt_hash`
- `provider_id` (`xkiro` / `gemini`)
- `requested_model` (`mistralai/mistral-large-2512`)
- `strict_model_pin` (`True`)
- `model_call_timeout_seconds` (`180.0`)

### 3.2 Canonical Proposal Schema & Normalizer (`schemas/canonical.py`)
- Standardizes all 28 required deliverable keys:
  - `EXECUTIVE_SUMMARY`
  - `RESEARCH_FINDINGS`, `KNOWN_FACTS`, `OBSERVATIONS`, `INFERENCES`, `HYPOTHESES`, `UNKNOWNS`
  - `CUSTOMER_SEGMENTS`, `TOP_PRIORITY_SEGMENT`
  - `POSITIONING`, `VALUE_PROPOSITION`, `CHANNEL_PRIORITIES`, `DEFERRED_CHANNELS`, `WHAT_NOT_TO_DO`
  - `CREATIVE_TERRITORIES`, `SELECTED_CREATIVE_TERRITORY`, `ANGLES`, `HOOKS`, `SHORT_FORM_COPY`, `VIDEO_SCRIPT`
  - `MEASUREMENT_FRAMEWORK`, `EXPERIMENTS`, `ATTRIBUTION_APPROACH`
  - `RISKS`, `TOP_3_PRIORITIES`, `GO_TEST_HOLD_DEFER_DECISIONS`, `HUMAN_APPROVAL_REQUIREMENTS`, `NEXT_ACTIONS`
- Unwraps neutral container keys: `go_to_market_strategy`, `gtm_strategy`, `proposal`, `candidate`, `output`, `strategy`.
- Normalizes casing (`snake_case` $\rightarrow$ canonical uppercase) without modifying content.
- Enforces strict contract invariant: `content_patch_count == 0` and `semantic_rewrite_count == 0`.

---

## 4. Single Model Recovery Assessment

```
Candidate: Single Model Baseline (xKiro mistralai/mistral-large-2512)
Wire Length: 18,487 chars
Usage Telemetry: prompt_tokens=2,159, completion_tokens=4,096 (PROVIDER_LIMIT_HIT)
Syntax: Truncated JSON code fence ending at line 406 (short_form_hooks)
Deterministic Normalizer Outcome: NORMALIZATION_FAILED
Content Patch Attempted: 0
Synthesized Closing Braces: 0
SINGLE_RECOVERABLE_WITHOUT_MODEL_CALL = FALSE
```

**Conclusion**: Single Model generation hit xKiro's completion token ceiling (4,096 tokens). In accordance with benchmark rigor, no synthetic text or closing brackets were injected. A fresh live model run with concise formatting constraints or higher output tokens will be required when live runs are unblocked.

---

## 5. Verification & Test Suite Summary

- **Total Test Modules**: 45 modules
- **Total Tests Executed**: 463 tests
- **Pass Rate**: 100% (463 passed, 0 failed, 0 errors)
- **Live Calls Made During Testing**: 0 (100% offline mocks and frozen fixtures)

### Targeted Test Suite (`tests/test_phase4_3c_6_versioned_run_integrity.py`):
- `test_run_manifest_and_fingerprint_determinism`: PASS
- `test_run_fingerprint_mismatch_rejection`: PASS
- `test_v1_checkpoints_rejected_in_v2`: PASS
- `test_valid_v2_checkpoint_accepted`: PASS
- `test_deterministic_json_extraction_formats`: PASS
- `test_neutral_root_wrapper_unwrapping`: PASS
- `test_canonical_key_normalization`: PASS
- `test_malformed_truncated_json_fails_closed`: PASS
- `test_real_current_single_raw_output_fixture_audit`: PASS
- `test_full_offline_canonical_pipeline_and_blind_packet`: PASS
- `test_blind_packet_rejects_v1_and_raw_candidates`: PASS
- `test_learning_ready_provenance_metadata`: PASS
- `test_single_adoption_parity_validation`: PASS
- `test_static_bypass_audit`: PASS

---

## 6. Stop Condition & Integrity Guarantee

In accordance with explicit instructions:
- **NO LIVE MODEL CALLS WERE MADE**.
- **NO NETWORK CALLS WERE MADE**.
- **NO LIVE FIVE-AGENT V2 WAS RUN**.
- **NO LIVE SINGLE WAS RUN**.
- **NO LIVE BLIND PACKET WAS ASSEMBLED FROM INCOMPLETE CANDIDATES**.
- **ALL HISTORICAL LIVE ARTIFACTS REMAIN 100% IMMUTABLE**.
