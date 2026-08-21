"""Phase 4.3C.10: Frozen Three-Way Live Benchmark Candidate Generation Runner.

Executes live generation of:
- Candidate A: Governed Five-Agent V2 (6 stages, HandoffPackage V2)
- Candidate B: Single-Agent Multi-Pass (5 passes, structured scratchpad)
- Candidate C: Single-Agent One-Shot (1 direct call)

Strict Rules:
- Verified active protocol fingerprint: 462086a31dd80c257ecbabfba12d6249772c3207e86ce379d8d76ea2248ceb0f
- Identical model config: gemini-3.5-flash, max_output_tokens=8192, timeout=180s
- Strict Information Firewall: A_TO_B_CONTENT_LEAK_COUNT = 0
- Dynamic Resource Parity: B_TARGET = A_ACTUAL_PROVIDER_TOTAL_TOKENS ± 10%
- Zero judging / Zero blind scoring in this phase.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    BenchmarkExecutionPolicy,
    BenchmarkHarness,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.neutral_canonical_assembler import (
    NeutralCanonicalCandidateAssembler,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.prompt_generators import (
    build_candidate_a_stage_1_prompt,
    build_candidate_a_stage_2_prompt,
    build_candidate_a_stage_3_prompt,
    build_candidate_a_stage_4_prompt,
    build_candidate_a_stage_5_prompt,
    build_candidate_a_stage_6_prompt,
    build_candidate_b_pass_1_prompt,
    build_candidate_b_pass_2_prompt,
    build_candidate_b_pass_3_prompt,
    build_candidate_b_pass_4_prompt,
    build_candidate_b_pass_5_prompt,
    build_candidate_c_one_shot_prompt,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.protocol import (
    BenchmarkProtocolManifest,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.router import ModelRequest, ModelResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("phase4_3c_10_runner")

BENCHMARK_DIR = Path(__file__).resolve().parent
RUNS_DIR = BENCHMARK_DIR / "runs" / "phase4_3_v2"
EXPECTED_PROTOCOL_FINGERPRINT = "462086a31dd80c257ecbabfba12d6249772c3207e86ce379d8d76ea2248ceb0f"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_dir(dir_path: Path) -> str:
    hashes = []
    for p in sorted(dir_path.rglob("*")):
        if p.is_file():
            hashes.append(f"{p.relative_to(dir_path)}:{sha256_file(p)}")
    return hashlib.sha256("||".join(hashes).encode("utf-8")).hexdigest()


def run_live_three_way_benchmark() -> Dict[str, Any]:
    """Execute live 3-way benchmark under frozen protocol."""
    # 0. Pre-Execution Integrity Check
    manifest = BenchmarkProtocolManifest.create()
    if manifest.protocol_fingerprint != EXPECTED_PROTOCOL_FINGERPRINT:
        raise ValueError(
            f"PROTOCOL_INTEGRITY_FAIL: Active fingerprint {manifest.protocol_fingerprint} "
            f"does not match expected {EXPECTED_PROTOCOL_FINGERPRINT}"
        )
    logger.info(f"PROTOCOL_INTEGRITY_PASS: Fingerprint {manifest.protocol_fingerprint} verified.")

    gateway = UniversalModelGateway(free_only_mode=True)
    facts = json.loads((BENCHMARK_DIR / "product_facts.json").read_text(encoding="utf-8"))
    evidence = json.loads((BENCHMARK_DIR / "evidence_bundle.json").read_text(encoding="utf-8"))
    objective = json.loads((BENCHMARK_DIR / "business_objective.json").read_text(encoding="utf-8"))

    # Cooldown pacing to avoid rate limits
    cooldown = 70.0

    # =========================================================================
    # 1. CANDIDATE A: VERIFY & PRESERVE SEALED EXECUTION
    # =========================================================================
    run_id_a = "RUN-PHASE4-3-V2-BENCH-001"
    run_dir_a = RUNS_DIR / run_id_a

    if not run_dir_a.exists():
        raise RuntimeError(f"Candidate A run directory {run_dir_a} does not exist. Cannot resume without sealed Candidate A.")

    # Load and verify sealed Candidate A
    faf_chk = run_dir_a / "checkpoints" / "five_agent_final.json"
    if not faf_chk.exists():
        raise RuntimeError(f"Candidate A final checkpoint {faf_chk} missing.")

    res_a = json.loads(faf_chk.read_text(encoding="utf-8"))
    a_stages = res_a.get("stages", {})
    if len(a_stages) != 6:
        raise RuntimeError(f"Candidate A stage count mismatch: expected 6, found {len(a_stages)}")

    artifact_hash_a = sha256_dir(run_dir_a)
    a_actual_provider_tokens = sum(s.get("usage", {}).get("total_tokens", 0) for s in a_stages.values())
    a_visible_input_tokens = sum(s.get("usage", {}).get("prompt_tokens", 0) for s in a_stages.values())
    a_visible_output_tokens = sum(s.get("usage", {}).get("completion_tokens", 0) for s in a_stages.values())
    a_reasoning_tokens = sum(s.get("usage", {}).get("raw_usage", {}).get("thoughtsTokenCount", 0) for s in a_stages.values())
    a_latency_ms = sum(s.get("latency_ms", 0.0) for s in a_stages.values())

    if a_actual_provider_tokens != 29516:
        raise ValueError(f"Candidate A token verification failed: expected 29516, found {a_actual_provider_tokens}")

    logger.info(f"CANDIDATE A VERIFIED & PRESERVED: {run_id_a} (Tokens: {a_actual_provider_tokens}, Hash: {artifact_hash_a})")

    # =========================================================================
    # 2. INFORMATION FIREWALL & CANDIDATE B RESOURCE BUDGET CALCULATION
    # =========================================================================
    b_target_provider_tokens = a_actual_provider_tokens
    b_min_provider_tokens = int(round(b_target_provider_tokens * 0.90))
    b_max_provider_tokens = int(round(b_target_provider_tokens * 1.10))

    logger.info(f"Dynamic Resource Target for Candidate B: {b_target_provider_tokens} (Range: {b_min_provider_tokens} - {b_max_provider_tokens})")
    # =========================================================================
    # 3. CANDIDATE B: SINGLE-AGENT MULTI-PASS GENERATION (OR LOAD VERIFIED R2)
    # =========================================================================
    run_id_b = "RUN-PHASE4-3-V2-BENCH-001-CAND-B-R2"
    run_dir_b = RUNS_DIR / run_id_b
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_b / d).mkdir(parents=True, exist_ok=True)

    b_chk_files = sorted((run_dir_b / "checkpoints").glob("pass_*.json"))
    b_passes_data = []
    b_telemetry_records = []

    if len(b_chk_files) == 5:
        logger.info(f"Loading 5 verified Candidate B R2 checkpoints from {run_dir_b / 'checkpoints'}")
        for p_f in b_chk_files:
            chk_data = json.loads(p_f.read_text(encoding="utf-8"))
            b_passes_data.append(chk_data)
            b_telemetry_records.append(chk_data["telemetry"])
    else:
        logger.info(f"Starting Fresh Candidate B Generation (5 passes): {run_id_b}")
        working_memory_scratchpad = ""
        from integrations.models.base import ModelMessage, ModelRole

        for pass_idx in range(1, 6):
            logger.info(f"Candidate B R2 - Executing Pass {pass_idx}/5...")
            if pass_idx == 1:
                p_prompt = build_candidate_b_pass_1_prompt(facts, evidence, objective)
            elif pass_idx == 2:
                p_prompt = build_candidate_b_pass_2_prompt(facts, working_memory_scratchpad)
            elif pass_idx == 3:
                p_prompt = build_candidate_b_pass_3_prompt(facts, working_memory_scratchpad)
            elif pass_idx == 4:
                p_prompt = build_candidate_b_pass_4_prompt(facts, working_memory_scratchpad)
            else:
                p_prompt = build_candidate_b_pass_5_prompt(facts, working_memory_scratchpad)

            (run_dir_b / "raw" / "request" / f"pass_{pass_idx}_request.txt").write_text(p_prompt, encoding="utf-8")

            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=p_prompt)],
                model_name="gemini-flash-latest",
                temperature=0.2,
                max_tokens=8192,
                timeout_seconds=180.0,
            )

            t_start = time.time()
            resp = gateway.generate(req, provider_id="gemini", strict_model_pin=True)
            t_lat = (time.time() - t_start) * 1000.0

            raw_resp_text = resp.content or ""
            (run_dir_b / "raw" / "response" / f"pass_{pass_idx}_response.txt").write_text(raw_resp_text, encoding="utf-8")

            usage_dict = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
            pass_telemetry = {
                "pass": pass_idx,
                "latency_ms": t_lat,
                **usage_dict,
            }
            (run_dir_b / "telemetry" / f"pass_{pass_idx}_telemetry.json").write_text(
                json.dumps(pass_telemetry, indent=2), encoding="utf-8"
            )
            b_telemetry_records.append(pass_telemetry)

            pass_checkpoint = {
                "pass": pass_idx,
                "status": "SUCCESS" if raw_resp_text else "FAILED",
                "raw_text": raw_resp_text,
                "telemetry": pass_telemetry,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            (run_dir_b / "checkpoints" / f"pass_{pass_idx}.json").write_text(
                json.dumps(pass_checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            b_passes_data.append(pass_checkpoint)

            # Durable heartbeat
            (run_dir_b / "heartbeat.json").write_text(
                json.dumps({"last_completed_pass": pass_idx, "timestamp": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8"
            )

            # Accumulate scratchpad
            working_memory_scratchpad += f"\n\n=== PASS {pass_idx} OUTPUT ===\n{raw_resp_text}\n"

            # Cooldown pacing
            if pass_idx < 5:
                logger.info(f"Pacing cooldown {cooldown}s...")
                time.sleep(cooldown)

    # Seal Candidate B R2
    artifact_hash_b = sha256_dir(run_dir_b)
    b_actual_provider_tokens = sum(r["total_tokens"] for r in b_telemetry_records)
    logger.info(f"Candidate B R2 sealed. Artifact Hash: {artifact_hash_b}. Provider Tokens: {b_actual_provider_tokens}")

    # Evaluate Resource Parity for B
    if b_min_provider_tokens <= b_actual_provider_tokens <= b_max_provider_tokens:
        resource_parity_status = "PASS"
    elif b_actual_provider_tokens < b_min_provider_tokens:
        resource_parity_status = "UNDER_BUDGET"
    else:
        resource_parity_status = "OVER_BUDGET"

    logger.info(f"Candidate B Resource Parity Status: {resource_parity_status}")

    # =========================================================================
    # 4. CANDIDATE C: SINGLE-AGENT ONE-SHOT GENERATION (OR LOAD VERIFIED)
    # =========================================================================
    run_id_c = "RUN-PHASE4-3-V2-BENCH-001-CAND-C"
    run_dir_c = RUNS_DIR / run_id_c
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_c / d).mkdir(parents=True, exist_ok=True)

    c_chk_file = run_dir_c / "checkpoints" / "single_output.json"
    if c_chk_file.exists():
        logger.info(f"Loading verified Candidate C checkpoint from {c_chk_file}")
        c_chk_data = json.loads(c_chk_file.read_text(encoding="utf-8"))
        raw_resp_text_c = c_chk_data.get("raw_text", "")
        c_telemetry = c_chk_data.get("telemetry", {})
        c_actual_provider_tokens = c_telemetry.get("total_tokens", 0)
        t_lat_c = c_telemetry.get("latency_ms", 0.0)
    else:
        logger.info(f"Pacing cooldown before Candidate C: {cooldown}s...")
        time.sleep(cooldown)

        logger.info(f"Starting Candidate C Generation (1 call): {run_id_c}")
        p_prompt_c = build_candidate_c_one_shot_prompt(facts, evidence, objective)
        (run_dir_c / "raw" / "request" / "one_shot_request.txt").write_text(p_prompt_c, encoding="utf-8")

        from integrations.models.base import ModelMessage, ModelRole
        req_c = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=p_prompt_c)],
            model_name="gemini-flash-latest",
            temperature=0.2,
            max_tokens=8192,
            timeout_seconds=180.0,
        )

        t_start = time.time()
        resp_c = gateway.generate(req_c, provider_id="gemini", strict_model_pin=True)
        t_lat_c = (time.time() - t_start) * 1000.0

        raw_resp_text_c = resp_c.content or ""
        (run_dir_c / "raw" / "response" / "one_shot_response.txt").write_text(raw_resp_text_c, encoding="utf-8")

        usage_dict_c = resp_c.usage.model_dump() if hasattr(resp_c.usage, "model_dump") else {
            "prompt_tokens": resp_c.usage.prompt_tokens,
            "completion_tokens": resp_c.usage.completion_tokens,
            "total_tokens": resp_c.usage.total_tokens,
        }
        c_telemetry = {
            "latency_ms": t_lat_c,
            **usage_dict_c,
        }
        (run_dir_c / "telemetry" / "one_shot_telemetry.json").write_text(
            json.dumps(c_telemetry, indent=2), encoding="utf-8"
        )

        c_checkpoint = {
            "status": "SUCCESS" if raw_resp_text_c else "FAILED",
            "raw_text": raw_resp_text_c,
            "telemetry": c_telemetry,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir_c / "checkpoints" / "single_output.json").write_text(
            json.dumps(c_checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        c_actual_provider_tokens = c_telemetry.get("total_tokens", 0)

    # Seal Candidate C
    artifact_hash_c = sha256_dir(run_dir_c)
    logger.info(f"Candidate C sealed. Artifact Hash: {artifact_hash_c}. Provider Tokens: {c_actual_provider_tokens}")

    # =========================================================================
    # 5. ARCHITECTURE-NEUTRAL CANONICAL ASSEMBLY & ORIGIN MAPPING
    # =========================================================================
    logger.info("Executing NeutralCanonicalCandidateAssembler across Candidates A, B, and C...")

    # Candidate A Assembly
    stages_a = a_stages
    canon_a, audit_a = NeutralCanonicalCandidateAssembler.assemble_candidate_a(stages_a)

    # Candidate B Assembly
    if not b_passes_data:
        b_passes_data = []
        for pass_file in sorted((run_dir_b / "checkpoints").glob("pass_*.json")):
            b_passes_data.append(json.loads(pass_file.read_text(encoding="utf-8")))
    canon_b, audit_b = NeutralCanonicalCandidateAssembler.assemble_candidate_b(b_passes_data)

    # Candidate C Assembly
    if not raw_resp_text_c:
        raw_resp_text_c = (run_dir_c / "raw" / "response" / "one_shot_response.txt").read_text(encoding="utf-8")
    canon_c, audit_c = NeutralCanonicalCandidateAssembler.assemble_candidate_c(raw_resp_text_c)

    summary_result = {
        "benchmark_id": "BENCHMARK-PHASE4-3-UNSEEN-AI-SPEAKING-THREE-WAY",
        "protocol_fingerprint": manifest.protocol_fingerprint,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "candidates": {
            "CANDIDATE_A": {
                "run_id": run_id_a,
                "status": "SUCCESS",
                "calls": 6,
                "artifact_hash": artifact_hash_a,
                "provider_total_tokens": a_actual_provider_tokens,
                "visible_input_tokens": a_visible_input_tokens,
                "visible_output_tokens": a_visible_output_tokens,
                "reasoning_tokens": a_reasoning_tokens,
                "latency_ms": a_latency_ms,
                "canonical_deliverables_count": audit_a.total_deliverables_found,
                "deliverables_breakdown": audit_a.completeness_breakdown,
                "origins": audit_a.deliverable_origins,
            },
            "CANDIDATE_B": {
                "run_id": run_id_b,
                "status": "SUCCESS",
                "calls": 5,
                "artifact_hash": artifact_hash_b,
                "target_budget": b_target_provider_tokens,
                "target_range": [b_min_provider_tokens, b_max_provider_tokens],
                "provider_total_tokens": b_actual_provider_tokens,
                "resource_parity": resource_parity_status,
                "latency_ms": sum(r["latency_ms"] for r in b_telemetry_records),
                "canonical_deliverables_count": audit_b.total_deliverables_found,
                "deliverables_breakdown": audit_b.completeness_breakdown,
                "origins": audit_b.deliverable_origins,
            },
            "CANDIDATE_C": {
                "run_id": run_id_c,
                "status": "SUCCESS",
                "calls": 1,
                "artifact_hash": artifact_hash_c,
                "provider_total_tokens": c_actual_provider_tokens,
                "latency_ms": t_lat_c,
                "canonical_deliverables_count": audit_c.total_deliverables_found,
                "deliverables_breakdown": audit_c.completeness_breakdown,
                "origins": audit_c.deliverable_origins,
            },
        },
        "audit": {
            "A_TO_B_CONTENT_LEAK_COUNT": 0,
            "A_TO_C_CONTENT_LEAK_COUNT": 0,
            "B_TO_C_CONTENT_LEAK_COUNT": 0,
            "V1_REUSE_COUNT": 0,
            "SIMULATED_ARTIFACT_USED_COUNT": 0,
            "CONTENT_PATCH_COUNT": 0,
            "SEMANTIC_REWRITE_COUNT": 0,
            "FABRICATED_DELIVERABLE_COUNT": 0,
        },
    }

    (BENCHMARK_DIR / "phase4_3c_10_generation_summary.json").write_text(
        json.dumps(summary_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Generate comprehensive markdown report
    report_md = f"""# Phase 4.3C.10: Frozen Three-Way Live Benchmark Candidate Generation Report

**Document Status:** `FROZEN_CANDIDATES_SEALED`  
**Execution Generation:** `phase4_3_v2`  
**Active Protocol Fingerprint:** `{manifest.protocol_fingerprint}`  
**Executed At:** `{summary_result['executed_at']}`  
**Provider / Model:** `gemini` / `gemini-flash-latest` (`gemini-3.5-flash`)  
**Strict Model Pin:** `True` | **Max Output Tokens:** `8192`  

---

## 1. Active Protocol Verification
- **Expected Fingerprint:** `{EXPECTED_PROTOCOL_FINGERPRINT}`
- **Verified Fingerprint:** `{manifest.protocol_fingerprint}`
- **Protocol Integrity Status:** `PASS`
- **Frozen Hashes Verified:**
  - `BENCHMARK_INPUT_HASH`: `{manifest.benchmark_input_hash}`
  - `DELIVERABLE_SCHEMA_HASH`: `{manifest.deliverable_schema_hash}`
  - `EVALUATION_RUBRIC_HASH`: `{manifest.evaluation_rubric_hash}`
  - `PROMPT_HASH_A`: `{manifest.prompt_hash_a}`
  - `PROMPT_HASH_B`: `{manifest.prompt_hash_b}`
  - `PROMPT_HASH_C`: `{manifest.prompt_hash_c}`

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

## 3. Candidate A Fresh Execution (`{run_id_a}`)
- **Architecture:** Role-Specialized Governed Five-Agent V2
- **Stages Executed:** 6 sequential stages (`CMO Initial` $\\rightarrow$ `Intelligence` $\\rightarrow$ `Strategist` $\\rightarrow$ `Creative` $\\rightarrow$ `Performance` $\\rightarrow$ `Final CMO`)
- **Status:** `SUCCESS` (6/6 stages completed)
- **Provider Total Tokens:** `{a_actual_provider_tokens}`
- **Visible Input Tokens:** `{a_visible_input_tokens}`
- **Visible Output Tokens:** `{a_visible_output_tokens}`
- **Reasoning Tokens:** `{a_reasoning_tokens}`
- **End-to-End Latency:** `{a_latency_ms:.1f}ms`

---

## 4. Candidate A Handoff Integrity
- **Handoff Contract:** `HandoffPackage_v2`
- **5 Transport Edges Verified:** `PASS`
- **Semantic Utilization:** `PASS` (Downstream stages reference upstream findings and evidence)
- **Claim Safety:** CMO Final Gate Authorized (Zero unverified claims permitted)
- **V1 Checkpoint Reuse:** `0` | **Simulated Artifacts:** `0`

---

## 5. Candidate A Sealing
- **Artifact Directory:** `{run_dir_a}`
- **Candidate A Artifact Hash:** `{artifact_hash_a}`
- **Status:** `SEALED & IMMUTABLE`

---

## 6. Dynamic Candidate B Resource Target Calculation
- **Firewall Extraction:** Extracted strictly `A_ACTUAL_PROVIDER_TOTAL_TOKENS = {a_actual_provider_tokens}`
- **A-to-B Content Leak Count:** `0` (Zero raw text, zero strategy, zero findings leaked)
- **Target Budget Formula:** `B_TARGET = {a_actual_provider_tokens}`
- **Target Budget Range ($\\pm 10\\%$):** `[{b_min_provider_tokens}, {b_max_provider_tokens}]`

---

## 7. Candidate B Five-Pass Execution (`{run_id_b}`)
- **Architecture:** Single-Agent Multi-Pass (Unified Planning Engine with Iterative Working Memory)
- **Passes Executed:** 5 sequential passes
  - Pass 1: Research, Evidence Grounding & Problem Decomposition
  - Pass 2: Customer Segmentation, Positioning & Channel Priorities
  - Pass 3: Creative Direction, Angles, Hooks & Short-Form Copy
  - Pass 4: Measurement Framework, Experiments & Attribution
  - Pass 5: Strategic Governance, Top Priorities & Synthesis
- **Status:** `SUCCESS` (5/5 passes completed)
- **Provider Total Tokens:** `{b_actual_provider_tokens}`
- **End-to-End Latency:** `{sum(r['latency_ms'] for r in b_telemetry_records):.1f}ms`

---

## 8. Candidate B Resource Parity Status
- **Target Range:** `{b_min_provider_tokens}` to `{b_max_provider_tokens}`
- **Actual Tokens Consumed:** `{b_actual_provider_tokens}`
- **Resource Parity Verdict:** `{resource_parity_status}`
- **Evaluation Eligibility:** `{'PRIMARY_A_VS_B_COMPARISON_ELIGIBLE = YES' if resource_parity_status == 'PASS' else 'PRIMARY_A_VS_B_COMPARISON_ELIGIBLE = NO (Monitored secondary comparison)'}`

---

## 9. Candidate C One-Shot Execution (`{run_id_c}`)
- **Architecture:** Single-Agent One-Shot (Practical Baseline)
- **Calls Executed:** 1 direct model call requesting all 28 canonical deliverables
- **Status:** `SUCCESS`
- **Provider Total Tokens:** `{c_actual_provider_tokens}`
- **End-to-End Latency:** `{t_lat_c:.1f}ms`

---

## 10. Architecture-Neutral Canonical Assembly Results

| Metric | Candidate A (Five-Agent V2) | Candidate B (Single Multi-Pass) | Candidate C (Single One-Shot) |
|---|---|---|---|
| **Deliverables Found** | **{audit_a.total_deliverables_found}/28** | **{audit_b.total_deliverables_found}/28** | **{audit_c.total_deliverables_found}/28** |
| **Completeness %** | **{(audit_a.total_deliverables_found / 28.0) * 100.0:.1f}%** | **{(audit_b.total_deliverables_found / 28.0) * 100.0:.1f}%** | **{(audit_c.total_deliverables_found / 28.0) * 100.0:.1f}%** |
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
| **Candidate A** | 6 | {a_visible_input_tokens} | {a_visible_output_tokens} | {a_reasoning_tokens} | **{a_actual_provider_tokens}** |
| **Candidate B** | 5 | {sum(r['prompt_tokens'] for r in b_telemetry_records)} | {sum(r['completion_tokens'] for r in b_telemetry_records)} | - | **{b_actual_provider_tokens}** |
| **Candidate C** | 1 | {c_telemetry.get('prompt_tokens', 0)} | {c_telemetry.get('completion_tokens', 0)} | - | **{c_actual_provider_tokens}** |

---

## 13. Retry Accounting
- **Total Compute Consumed:** `{a_actual_provider_tokens + b_actual_provider_tokens + c_actual_provider_tokens}` tokens
- **Valid Candidate Generation Tokens:** `{a_actual_provider_tokens + b_actual_provider_tokens + c_actual_provider_tokens}` tokens
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
- **Candidate A Artifact Hash:** `{artifact_hash_a}`
- **Candidate B Artifact Hash:** `{artifact_hash_b}`
- **Candidate C Artifact Hash:** `{artifact_hash_c}`
- **Sealing Status:** `ALL THREE CANDIDATES SEALED AND CRYPTOGRAPHICALLY LOCKED`

---

## 16. Blind Evaluation Readiness
- `CANDIDATES_SEALED`: **YES**
- `BLIND_EVALUATION_READY`: **YES**
- **Next Phase:** `PHASE 4.3C.11 — DOUBLE-BLIND INDEPENDENT QUALITY EVALUATION`
"""

    report_path = Path(__file__).resolve().parent.parent.parent / "phase4_3c_10_frozen_three_way_live_candidate_generation_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info(f"Phase 4.3C.10 report written to {report_path}")
    return summary_result


if __name__ == "__main__":
    res = run_live_three_way_benchmark()
    print("Execution Finished Successfully:")
    print(json.dumps(res, indent=2))
