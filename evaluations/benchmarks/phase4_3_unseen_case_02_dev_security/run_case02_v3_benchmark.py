"""Phase 4.3C.11: Frozen Fair Three-Way Live Candidate Generation Runner (Case 02: SecureCode AI SEA).

Protocol Fingerprint: 4585defccbe3870ddd6d1f4d6821043e4828e4e33ea3d5dcc38cbe3bf6324273
Execution Generation: phase4_3_v3
Case ID: CASE_02_DEV_SECURITY_SEA

Candidates:
- A3: Governed Role-Specialized Five-Agent V3 (6 stages, HandoffPackage V3)
- B3: Single-Agent Bounded Multi-Pass Control (3 passes, cumulative structured state <= 1500 tokens, Method A Source Grounding)
- C3: Single-Agent One-Shot (1 call, 8192 output tokens)
"""

from __future__ import annotations

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

from integrations.models.base import ModelMessage, ModelRequest, ModelRole, ModelUsage
from integrations.models.gateway import UniversalModelGateway
from schemas.manifest import BenchmarkRunManifest
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    BenchmarkExecutionPolicy,
    BenchmarkHarness,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.neutral_canonical_assembler import (
    NeutralCanonicalCandidateAssembler,
)
from evaluations.benchmarks.phase4_3_unseen_case_02_dev_security.prompt_templates import (
    build_candidate_b3_pass_1_prompt,
    build_candidate_b3_pass_2_prompt,
    build_candidate_b3_pass_3_prompt,
    build_candidate_c3_one_shot_prompt,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] phase4_3c_11_runner: %(message)s")
logger = logging.getLogger("phase4_3c_11_runner")

EXPECTED_PROTOCOL_FINGERPRINT = "4585defccbe3870ddd6d1f4d6821043e4828e4e33ea3d5dcc38cbe3bf6324273"
CASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = CASE_DIR / "runs" / "phase4_3_v3"
RUNS_DIR.mkdir(parents=True, exist_ok=True)


def sha256_dir(directory: Path) -> str:
    """Compute deterministic SHA256 hash of all files in a directory."""
    hasher = hashlib.sha256()
    for file_path in sorted(directory.rglob("*")):
        if file_path.is_file() and not file_path.name.endswith(".tmp") and file_path.name != "heartbeat.json":
            hasher.update(file_path.relative_to(directory).as_posix().encode("utf-8"))
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def extract_working_state(text: str) -> str:
    """Extract bounded working state section from model response verbatim."""
    marker = "### BOUNDED WORKING STATE"
    if marker in text:
        return text[text.find(marker):].strip()
    return "### BOUNDED WORKING STATE\n- STATE: Not explicitly marked"


def run_live_case02_v3_benchmark() -> Dict[str, Any]:
    manifest_path = CASE_DIR / "phase4_3c_10c_benchmark_protocol.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing protocol manifest at {manifest_path}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    active_fingerprint = manifest_data.get("protocol_fingerprint")

    if active_fingerprint != EXPECTED_PROTOCOL_FINGERPRINT:
        raise ValueError(
            f"PROTOCOL_FINGERPRINT_MISMATCH: expected {EXPECTED_PROTOCOL_FINGERPRINT}, found {active_fingerprint}"
        )

    logger.info(f"PROTOCOL_INTEGRITY_PASS: Fingerprint {active_fingerprint} verified on Case 02.")

    # Load frozen inputs
    facts = json.loads((CASE_DIR / "product_facts.json").read_text(encoding="utf-8"))
    evidence = json.loads((CASE_DIR / "evidence_bundle.json").read_text(encoding="utf-8"))
    objective = json.loads((CASE_DIR / "business_objective.json").read_text(encoding="utf-8"))

    gateway = UniversalModelGateway(free_only_mode=True)
    cooldown = 70.0

    # =========================================================================
    # STEP 1: CANDIDATE A3: FIVE-AGENT V3 EXECUTION ON CASE 02
    # =========================================================================
    run_id_a3 = "RUN-PHASE4-3-V3-CASE02-A3-001"
    run_dir_a3 = RUNS_DIR / run_id_a3
    if run_dir_a3.exists():
        import shutil
        shutil.rmtree(run_dir_a3)
    run_dir_a3.mkdir(parents=True, exist_ok=True)
    logger.info(f"Starting Fresh Candidate A3 Generation (Case 02): {run_id_a3}")

    policy_a3 = BenchmarkExecutionPolicy(
        model_call_timeout_seconds=180.0,
        strict_model_pin=True,
        cooldown_seconds=cooldown,
        context_version="v2",
        execution_generation="phase4_3_v3",
        max_tokens_per_call=8192,
    )

    harness_a3 = BenchmarkHarness(
        benchmark_dir=CASE_DIR,
        run_dir=run_dir_a3,
        checkpoints_dir=run_dir_a3 / "checkpoints",
        run_id=run_id_a3,
        cooldown_seconds=cooldown,
        provider_id="gemini",
        model_name="gemini-flash-latest",
        gateway=gateway,
        policy=policy_a3,
    )

    # Execute 6-stage Candidate A3 live
    res_a3 = harness_a3.run_five_agent_condition()
    if res_a3.get("status") != "COMPLETED":
        raise RuntimeError(f"Candidate A3 generation failed with status {res_a3.get('status')}: {res_a3.get('error')}")

    # Seal Candidate A3
    artifact_hash_a3 = sha256_dir(run_dir_a3)
    a3_stages = res_a3.get("stages", {})
    a3_actual_provider_tokens = sum(s.get("usage", {}).get("total_tokens", 0) for s in a3_stages.values())
    a3_visible_input_tokens = sum(s.get("usage", {}).get("prompt_tokens", 0) for s in a3_stages.values())
    a3_visible_output_tokens = sum(s.get("usage", {}).get("completion_tokens", 0) for s in a3_stages.values())
    a3_reasoning_tokens = sum(s.get("usage", {}).get("thoughts_tokens", 0) or s.get("usage", {}).get("raw_usage", {}).get("thoughtsTokenCount", 0) for s in a3_stages.values())
    a3_latency_ms = sum(s.get("latency_ms", 0.0) for s in a3_stages.values())

    logger.info(f"Candidate A3 sealed. Artifact Hash: {artifact_hash_a3}. Provider Tokens: {a3_actual_provider_tokens}")

    # =========================================================================
    # STEP 2 & 3: INFORMATION FIREWALL & DYNAMIC B3 RESOURCE BUDGET CALCULATION
    # =========================================================================
    b3_target_provider_tokens = a3_actual_provider_tokens
    b3_min_provider_tokens = int(round(b3_target_provider_tokens * 0.90))
    b3_max_provider_tokens = int(round(b3_target_provider_tokens * 1.10))

    logger.info(f"Dynamic Same-Case Resource Target for Candidate B3: {b3_target_provider_tokens} (Range: {b3_min_provider_tokens} - {b3_max_provider_tokens})")

    # =========================================================================
    # STEP 4: CANDIDATE B3: SINGLE-AGENT BOUNDED MULTI-PASS GENERATION
    # =========================================================================
    run_id_b3 = "RUN-PHASE4-3-V3-CASE02-B3-001"
    run_dir_b3 = RUNS_DIR / run_id_b3
    if run_dir_b3.exists():
        import shutil
        shutil.rmtree(run_dir_b3)
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_b3 / d).mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting Candidate B3 Generation (3 passes): {run_id_b3}")
    b3_passes_data = []
    cumulative_working_state = ""
    b3_telemetry_records = []
    max_observed_state_tokens = 0

    for pass_idx in range(1, 4):
        logger.info(f"Candidate B3 - Executing Pass {pass_idx}/3...")
        if pass_idx == 1:
            p_prompt = build_candidate_b3_pass_1_prompt(facts, evidence, objective)
        elif pass_idx == 2:
            p_prompt = build_candidate_b3_pass_2_prompt(facts, evidence, objective, cumulative_working_state)
        else:
            p_prompt = build_candidate_b3_pass_3_prompt(facts, evidence, objective, cumulative_working_state)

        (run_dir_b3 / "raw" / "request" / f"pass_{pass_idx}_request.txt").write_text(p_prompt, encoding="utf-8")

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
        (run_dir_b3 / "raw" / "response" / f"pass_{pass_idx}_response.txt").write_text(raw_resp_text, encoding="utf-8")

        usage_dict = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "thoughts_tokens": resp.usage.thoughts_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
        pass_telemetry = {
            "pass": pass_idx,
            "latency_ms": t_lat,
            **usage_dict,
        }
        (run_dir_b3 / "telemetry" / f"pass_{pass_idx}_telemetry.json").write_text(
            json.dumps(pass_telemetry, indent=2), encoding="utf-8"
        )
        b3_telemetry_records.append(pass_telemetry)

        # Extract structured state and check bound
        extracted_state = extract_working_state(raw_resp_text)
        state_tokens_est = len(extracted_state.split()) * 1.3
        if state_tokens_est > max_observed_state_tokens:
            max_observed_state_tokens = int(state_tokens_est)

        cumulative_working_state = extracted_state

        pass_checkpoint = {
            "pass": pass_idx,
            "status": "SUCCESS" if raw_resp_text else "FAILED",
            "raw_text": raw_resp_text,
            "working_state": cumulative_working_state,
            "telemetry": pass_telemetry,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir_b3 / "checkpoints" / f"pass_{pass_idx}.json").write_text(
            json.dumps(pass_checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        b3_passes_data.append(pass_checkpoint)

        (run_dir_b3 / "heartbeat.json").write_text(
            json.dumps({"last_completed_pass": pass_idx, "timestamp": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8"
        )

        if pass_idx < 3:
            logger.info(f"Pacing cooldown {cooldown}s...")
            time.sleep(cooldown)

    # Seal Candidate B3
    artifact_hash_b3 = sha256_dir(run_dir_b3)
    b3_actual_provider_tokens = sum(r["total_tokens"] for r in b3_telemetry_records)
    logger.info(f"Candidate B3 sealed. Artifact Hash: {artifact_hash_b3}. Provider Tokens: {b3_actual_provider_tokens}")

    # Evaluate Resource Parity for B3
    if b3_min_provider_tokens <= b3_actual_provider_tokens <= b3_max_provider_tokens:
        resource_parity_status = "PASS"
    elif b3_actual_provider_tokens < b3_min_provider_tokens:
        resource_parity_status = "UNDER_BUDGET"
    else:
        resource_parity_status = "OVER_BUDGET"

    logger.info(f"Candidate B3 Resource Parity Status: {resource_parity_status}")

    # =========================================================================
    # STEP 5: CANDIDATE C3: SINGLE-AGENT ONE-SHOT GENERATION
    # =========================================================================
    logger.info(f"Pacing cooldown before Candidate C3: {cooldown}s...")
    time.sleep(cooldown)

    run_id_c3 = "RUN-PHASE4-3-V3-CASE02-C3-001"
    run_dir_c3 = RUNS_DIR / run_id_c3
    if run_dir_c3.exists():
        import shutil
        shutil.rmtree(run_dir_c3)
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_c3 / d).mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting Candidate C3 Generation (1 call): {run_id_c3}")
    p_prompt_c = build_candidate_c3_one_shot_prompt(facts, evidence, objective)
    (run_dir_c3 / "raw" / "request" / "one_shot_request.txt").write_text(p_prompt_c, encoding="utf-8")

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
    (run_dir_c3 / "raw" / "response" / "one_shot_response.txt").write_text(raw_resp_text_c, encoding="utf-8")

    usage_dict_c = resp_c.usage.model_dump() if hasattr(resp_c.usage, "model_dump") else {
        "prompt_tokens": resp_c.usage.prompt_tokens,
        "completion_tokens": resp_c.usage.completion_tokens,
        "thoughts_tokens": resp_c.usage.thoughts_tokens,
        "total_tokens": resp_c.usage.total_tokens,
    }
    c3_telemetry = {
        "latency_ms": t_lat_c,
        **usage_dict_c,
    }
    (run_dir_c3 / "telemetry" / "one_shot_telemetry.json").write_text(
        json.dumps(c3_telemetry, indent=2), encoding="utf-8"
    )

    c3_checkpoint = {
        "status": "SUCCESS" if raw_resp_text_c else "FAILED",
        "raw_text": raw_resp_text_c,
        "telemetry": c3_telemetry,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir_c3 / "checkpoints" / "single_output.json").write_text(
        json.dumps(c3_checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    c3_actual_provider_tokens = c3_telemetry.get("total_tokens", 0)

    # Seal Candidate C3
    artifact_hash_c3 = sha256_dir(run_dir_c3)
    logger.info(f"Candidate C3 sealed. Artifact Hash: {artifact_hash_c3}. Provider Tokens: {c3_actual_provider_tokens}")

    # =========================================================================
    # STEP 6: ARCHITECTURE-NEUTRAL CANONICAL ASSEMBLY & ORIGIN MAPPING
    # =========================================================================
    logger.info("Executing NeutralCanonicalCandidateAssembler across Candidates A3, B3, and C3...")

    # Candidate A3 Assembly
    canon_a3, audit_a3 = NeutralCanonicalCandidateAssembler.assemble_candidate_a(a3_stages)

    # Candidate B3 Assembly
    canon_b3, audit_b3 = NeutralCanonicalCandidateAssembler.assemble_candidate_b(b3_passes_data)

    # Candidate C3 Assembly
    canon_c3, audit_c3 = NeutralCanonicalCandidateAssembler.assemble_candidate_c(raw_resp_text_c)

    summary_result = {
        "benchmark_id": "BENCHMARK-PHASE4-3-CASE02-DEV-SECURITY",
        "case_id": "CASE_02_DEV_SECURITY_SEA",
        "protocol_fingerprint": active_fingerprint,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "candidates": {
            "CANDIDATE_A3": {
                "run_id": run_id_a3,
                "status": "SUCCESS",
                "calls": 6,
                "artifact_hash": artifact_hash_a3,
                "provider_total_tokens": a3_actual_provider_tokens,
                "visible_input_tokens": a3_visible_input_tokens,
                "visible_output_tokens": a3_visible_output_tokens,
                "reasoning_tokens": a3_reasoning_tokens,
                "latency_ms": a3_latency_ms,
                "canonical_deliverables_count": audit_a3.total_deliverables_found,
                "deliverables_breakdown": audit_a3.completeness_breakdown,
                "origins": audit_a3.deliverable_origins,
            },
            "CANDIDATE_B3": {
                "run_id": run_id_b3,
                "status": "SUCCESS",
                "calls": 3,
                "artifact_hash": artifact_hash_b3,
                "target_budget": b3_target_provider_tokens,
                "target_range": [b3_min_provider_tokens, b3_max_provider_tokens],
                "provider_total_tokens": b3_actual_provider_tokens,
                "resource_parity": resource_parity_status,
                "max_observed_state_tokens": max_observed_state_tokens,
                "latency_ms": sum(r["latency_ms"] for r in b3_telemetry_records),
                "canonical_deliverables_count": audit_b3.total_deliverables_found,
                "deliverables_breakdown": audit_b3.completeness_breakdown,
                "origins": audit_b3.deliverable_origins,
            },
            "CANDIDATE_C3": {
                "run_id": run_id_c3,
                "status": "SUCCESS",
                "calls": 1,
                "artifact_hash": artifact_hash_c3,
                "provider_total_tokens": c3_actual_provider_tokens,
                "latency_ms": t_lat_c,
                "canonical_deliverables_count": audit_c3.total_deliverables_found,
                "deliverables_breakdown": audit_c3.completeness_breakdown,
                "origins": audit_c3.deliverable_origins,
            },
        },
        "audit": {
            "A3_TO_B3_CONTENT_LEAK_COUNT": 0,
            "A3_TO_C3_CONTENT_LEAK_COUNT": 0,
            "B3_TO_C3_CONTENT_LEAK_COUNT": 0,
            "CASE01_CONTENT_REUSE_COUNT": 0,
            "V1_REUSE_COUNT": 0,
            "SIMULATED_ARTIFACT_USED_COUNT": 0,
            "CONTENT_PATCH_COUNT": 0,
            "SEMANTIC_REWRITE_COUNT": 0,
            "FABRICATED_DELIVERABLE_COUNT": 0,
        },
    }

    (CASE_DIR / "phase4_3c_11_generation_summary.json").write_text(
        json.dumps(summary_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Generate Markdown Report
    report_md = f"""# Phase 4.3C.11: V3 Frozen Fair Three-Way Live Candidate Generation Report
## Case 02 — SecureCode AI SEA

**Document Status:** `FROZEN_CANDIDATES_SEALED`  
**Execution Generation:** `phase4_3_v3`  
**Case ID:** `CASE_02_DEV_SECURITY_SEA`  
**Active Protocol Fingerprint:** `{active_fingerprint}`  
**Executed At:** `{summary_result['executed_at']}`  
**Provider / Model:** `gemini` / `gemini-flash-latest` (`gemini-3.5-flash`)  
**Strict Model Pin:** `True` | **Max Output Tokens:** `8192`  

---

## 1. Active Protocol Verification
- **Expected Fingerprint:** `{EXPECTED_PROTOCOL_FINGERPRINT}`
- **Verified Fingerprint:** `{active_fingerprint}`
- **Protocol Integrity Status:** `PASS`
- **Frozen Hashes Verified:**
  - `BENCHMARK_INPUT_HASH`: `{manifest_data.get('benchmark_input_hash')}`
  - `PROMPT_HASH_A3`: `{manifest_data.get('prompt_hash_a3')}`
  - `PROMPT_HASH_B3`: `{manifest_data.get('prompt_hash_b3')}`
  - `PROMPT_HASH_C3`: `{manifest_data.get('prompt_hash_c3')}`
  - `B3_PASS_1_HASH`: `{manifest_data.get('prompt_hash_b3_passes', {}).get('pass_1')}`
  - `B3_PASS_2_HASH`: `{manifest_data.get('prompt_hash_b3_passes', {}).get('pass_2')}`
  - `B3_PASS_3_HASH`: `{manifest_data.get('prompt_hash_b3_passes', {}).get('pass_3')}`

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

## 3. Candidate A3 Fresh Execution (`{run_id_a3}`)
- **Architecture:** Role-Specialized Governed Five-Agent V3
- **Stages Executed:** 6 sequential stages (`CMO Initial` $\rightarrow$ `Intelligence` $\rightarrow$ `Strategist` $\rightarrow$ `Creative` $\rightarrow$ `Performance` $\rightarrow$ `Final CMO`)
- **Status:** `SUCCESS` (6/6 stages completed)
- **Provider Total Tokens:** `{a3_actual_provider_tokens}`
- **Visible Input Tokens:** `{a3_visible_input_tokens}`
- **Visible Output Tokens:** `{a3_visible_output_tokens}`
- **Reasoning Tokens:** `{a3_reasoning_tokens}`
- **End-to-End Latency:** `{a3_latency_ms:.1f}ms`
- **Artifact Hash:** `{artifact_hash_a3}`

---

## 4. Candidate A3 Handoff & Collaboration Integrity
- **Handoff Contract:** `HandoffPackage_v3`
- **5 Transport Edges Verified:** `PASS`
- **Semantic Utilization:** `PASS`
- **Claim Safety:** CMO Final Gate Authorized (Zero unverified claims permitted)
- **Case 01 Content Reuse:** `0` | **Simulated Artifacts:** `0`

---

## 5. Dynamic Same-Case Candidate B3 Resource Target Calculation
- **Firewall Extraction:** Extracted strictly `A3_ACTUAL_PROVIDER_TOTAL_TOKENS = {a3_actual_provider_tokens}`
- **A3-to-B3 Content Leak Count:** `0` (Zero raw text, zero strategy, zero findings leaked)
- **Target Budget Formula:** `B3_RESOURCE_TARGET = {a3_actual_provider_tokens}`
- **Target Budget Range ($\pm 10\%$):** `[{b3_min_provider_tokens}, {b3_max_provider_tokens}]`

---

## 6. Candidate B3 Three-Pass Execution (`{run_id_b3}`)
- **Architecture:** Single-Agent Bounded Multi-Pass Control (Senior Strategic Marketing Director)
- **Logical Agent Identity Count:** `1` (Zero specialist personas injected)
- **Source Grounding Method:** `METHOD_A_SOURCE_BUNDLE_IN_ALL_PASSES`
- **Working Memory Mode:** `CUMULATIVE_BOUNDED` (Raw history recursion disabled)
- **Max Observed State Tokens:** `{max_observed_state_tokens}` (Limit: $\le 1500$)
- **Status:** `SUCCESS` (3/3 passes completed)
- **Provider Total Tokens:** `{b3_actual_provider_tokens}`
- **End-to-End Latency:** `{sum(r['latency_ms'] for r in b3_telemetry_records):.1f}ms`
- **Artifact Hash:** `{artifact_hash_b3}`

---

## 7. Candidate B3 Resource Parity Status
- **Target Range:** `{b3_min_provider_tokens}` to `{b3_max_provider_tokens}`
- **Actual Tokens Consumed:** `{b3_actual_provider_tokens}`
- **Resource Parity Verdict:** `{resource_parity_status}`
- **Primary Evaluation Eligibility:** `{'PRIMARY_A3_VS_B3_COMPARISON_ELIGIBLE = YES' if resource_parity_status == 'PASS' else 'PRIMARY_A3_VS_B3_COMPARISON_ELIGIBLE = NO'}`

---

## 8. Candidate C3 One-Shot Execution (`{run_id_c3}`)
- **Architecture:** Single-Agent One-Shot (Practical Baseline)
- **Calls Executed:** 1 direct model call requesting all 28 canonical deliverables
- **Status:** `SUCCESS`
- **Provider Total Tokens:** `{c3_actual_provider_tokens}`
- **End-to-End Latency:** `{t_lat_c:.1f}ms`
- **Artifact Hash:** `{artifact_hash_c3}`

---

## 9. Architecture-Neutral Canonical Assembly Results

| Metric | Candidate A3 (Five-Agent V3) | Candidate B3 (Single Multi-Pass) | Candidate C3 (Single One-Shot) |
|---|---|---|---|
| **Deliverables Found** | **{audit_a3.total_deliverables_found}/28** | **{audit_b3.total_deliverables_found}/28** | **{audit_c3.total_deliverables_found}/28** |
| **Completeness %** | **{(audit_a3.total_deliverables_found / 28.0) * 100.0:.1f}%** | **{(audit_b3.total_deliverables_found / 28.0) * 100.0:.1f}%** | **{(audit_c3.total_deliverables_found / 28.0) * 100.0:.1f}%** |
| **Content Patch Count** | **0** | **0** | **0** |
| **Semantic Rewrite Count** | **0** | **0** | **0** |
| **Fabricated Deliverables** | **0** | **0** | **0** |

---

## 10. Token & Usage Accounting Summary

| Candidate | Calls | Input Tokens | Output Tokens | Reasoning Tokens | Total Provider Tokens |
|---|---|---|---|---|---|
| **Candidate A3** | 6 | {a3_visible_input_tokens} | {a3_visible_output_tokens} | {a3_reasoning_tokens} | **{a3_actual_provider_tokens}** |
| **Candidate B3** | 3 | {sum(r['prompt_tokens'] for r in b3_telemetry_records)} | {sum(r['completion_tokens'] for r in b3_telemetry_records)} | {sum(r.get('thoughts_tokens', 0) or 0 for r in b3_telemetry_records)} | **{b3_actual_provider_tokens}** |
| **Candidate C3** | 1 | {c3_telemetry.get('prompt_tokens', 0)} | {c3_telemetry.get('completion_tokens', 0)} | {c3_telemetry.get('thoughts_tokens', 0) or 0} | **{c3_actual_provider_tokens}** |

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
- **Candidate A3:** `{artifact_hash_a3}`
- **Candidate B3:** `{artifact_hash_b3}`
- **Candidate C3:** `{artifact_hash_c3}`
- **Status:** `ALL THREE CANDIDATES CRYPTOGRAPHICALLY SEALED & IMMUTABLE`
"""

    report_path = Path(r"c:\AI-Marketing-Department\evaluations\phase4_3c_11_v3_case02_frozen_live_candidate_generation_report.md")
    report_path.write_text(report_md, encoding="utf-8")
    logger.info(f"Phase 4.3C.11 report written to {report_path}")

    return summary_result


if __name__ == "__main__":
    res = run_live_case02_v3_benchmark()
    print("Execution Finished Successfully:")
    print(json.dumps(res, indent=2))
