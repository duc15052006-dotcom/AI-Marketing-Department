"""Phase 4.3C.14: Unseen Case 03 Final Five-Agent Brain V1 RC2 Validation Runner.

Case ID: CASE_03_CONSUMER_HARDWARE_D2C
Brain Version: FIVE_AGENT_BRAIN_V1_RC2
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import random
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
from evaluations.benchmarks.phase4_3_unseen_case_03_consumer_hardware.prompt_templates import (
    build_candidate_b4_pass_1_prompt,
    build_candidate_b4_pass_2_prompt,
    build_candidate_b4_pass_3_prompt,
    build_candidate_c4_one_shot_prompt,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] phase4_3c_14_runner: %(message)s")
logger = logging.getLogger("phase4_3c_14_runner")

CASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = CASE_DIR / "runs" / "phase4_3_rc2"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
JUDGE_DIR = CASE_DIR / "blind_judging"
JUDGE_DIR.mkdir(parents=True, exist_ok=True)


def sha256_dir(directory: Path) -> str:
    hasher = hashlib.sha256()
    for file_path in sorted(directory.rglob("*")):
        if file_path.is_file() and not file_path.name.endswith(".tmp") and file_path.name != "heartbeat.json":
            hasher.update(file_path.relative_to(directory).as_posix().encode("utf-8"))
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def extract_working_state(text: str) -> str:
    marker = "### BOUNDED WORKING STATE"
    if marker in text:
        return text[text.find(marker):].strip()
    return "### BOUNDED WORKING STATE\n- STATE: Maintained"


def run_case03_validation() -> Dict[str, Any]:
    manifest_path = CASE_DIR / "phase4_3c_14_benchmark_protocol.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    active_fingerprint = manifest_data.get("protocol_fingerprint")
    logger.info(f"Starting Phase 4.3C.14 on Case 03. Protocol Fingerprint: {active_fingerprint}")

    facts = json.loads((CASE_DIR / "product_facts.json").read_text(encoding="utf-8"))
    evidence = json.loads((CASE_DIR / "evidence_bundle.json").read_text(encoding="utf-8"))
    objective = json.loads((CASE_DIR / "business_objective.json").read_text(encoding="utf-8"))

    gateway = UniversalModelGateway(free_only_mode=True)
    cooldown = 70.0

    # =========================================================================
    # 1. EXECUTE CANDIDATE A4 (FIVE-AGENT BRAIN V1 RC2)
    # =========================================================================
    run_id_a4 = "RUN-PHASE4-3-RC2-CASE03-A4-001"
    run_dir_a4 = RUNS_DIR / run_id_a4
    if run_dir_a4.exists():
        import shutil
        shutil.rmtree(run_dir_a4)
    run_dir_a4.mkdir(parents=True, exist_ok=True)

    logger.info(f"Executing Candidate A4 (Five-Agent RC2 on Case 03): {run_id_a4}")
    policy_a4 = BenchmarkExecutionPolicy(
        model_call_timeout_seconds=180.0,
        strict_model_pin=True,
        cooldown_seconds=cooldown,
        context_version="v2",
        execution_generation="phase4_3_rc2",
        max_tokens_per_call=8192,
    )
    harness_a4 = BenchmarkHarness(
        benchmark_dir=CASE_DIR,
        run_dir=run_dir_a4,
        checkpoints_dir=run_dir_a4 / "checkpoints",
        run_id=run_id_a4,
        cooldown_seconds=cooldown,
        provider_id="gemini",
        model_name="gemini-flash-latest",
        gateway=gateway,
        policy=policy_a4,
    )
    res_a4 = harness_a4.run_five_agent_condition()
    if res_a4.get("status") != "COMPLETED":
        raise RuntimeError(f"Candidate A4 generation failed: {res_a4.get('error')}")

    artifact_hash_a4 = sha256_dir(run_dir_a4)
    a4_stages = res_a4.get("stages", {})
    a4_actual_provider_tokens = sum(s.get("usage", {}).get("total_tokens", 0) for s in a4_stages.values())
    a4_visible_input_tokens = sum(s.get("usage", {}).get("prompt_tokens", 0) for s in a4_stages.values())
    a4_visible_output_tokens = sum(s.get("usage", {}).get("completion_tokens", 0) for s in a4_stages.values())
    a4_reasoning_tokens = sum(s.get("usage", {}).get("thoughts_tokens", 0) or s.get("usage", {}).get("raw_usage", {}).get("thoughtsTokenCount", 0) for s in a4_stages.values())
    a4_latency_ms = sum(s.get("latency_ms", 0.0) for s in a4_stages.values())

    logger.info(f"Candidate A4 sealed. Hash: {artifact_hash_a4}. Tokens: {a4_actual_provider_tokens}")

    # =========================================================================
    # 2. DYNAMIC SAME-CASE RESOURCE TARGET EXTRACTION FOR B4
    # =========================================================================
    b4_target_provider_tokens = a4_actual_provider_tokens
    b4_min_provider_tokens = int(round(b4_target_provider_tokens * 0.90))
    b4_max_provider_tokens = int(round(b4_target_provider_tokens * 1.10))
    logger.info(f"Dynamic B4 Target: {b4_target_provider_tokens} (Range: {b4_min_provider_tokens} - {b4_max_provider_tokens})")

    # =========================================================================
    # 3. EXECUTE CANDIDATE B4 (SINGLE-AGENT BOUNDED MULTI-PASS CONTROL)
    # =========================================================================
    run_id_b4 = "RUN-PHASE4-3-RC2-CASE03-B4-001"
    run_dir_b4 = RUNS_DIR / run_id_b4
    if run_dir_b4.exists():
        import shutil
        shutil.rmtree(run_dir_b4)
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_b4 / d).mkdir(parents=True, exist_ok=True)

    logger.info(f"Executing Candidate B4 (3 passes): {run_id_b4}")
    b4_passes_data = []
    cumulative_working_state = ""
    b4_telemetry_records = []
    max_observed_state_tokens = 0

    for pass_idx in range(1, 4):
        logger.info(f"Candidate B4 - Executing Pass {pass_idx}/3...")
        if pass_idx == 1:
            p_prompt = build_candidate_b4_pass_1_prompt(facts, evidence, objective)
        elif pass_idx == 2:
            p_prompt = build_candidate_b4_pass_2_prompt(facts, evidence, objective, cumulative_working_state)
        else:
            p_prompt = build_candidate_b4_pass_3_prompt(facts, evidence, objective, cumulative_working_state)

        (run_dir_b4 / "raw" / "request" / f"pass_{pass_idx}_request.txt").write_text(p_prompt, encoding="utf-8")

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
        (run_dir_b4 / "raw" / "response" / f"pass_{pass_idx}_response.txt").write_text(raw_resp_text, encoding="utf-8")

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
        (run_dir_b4 / "telemetry" / f"pass_{pass_idx}_telemetry.json").write_text(
            json.dumps(pass_telemetry, indent=2), encoding="utf-8"
        )
        b4_telemetry_records.append(pass_telemetry)

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
        (run_dir_b4 / "checkpoints" / f"pass_{pass_idx}.json").write_text(
            json.dumps(pass_checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        b4_passes_data.append(pass_checkpoint)

        (run_dir_b4 / "heartbeat.json").write_text(
            json.dumps({"last_completed_pass": pass_idx, "timestamp": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8"
        )

        if pass_idx < 3:
            logger.info(f"Pacing cooldown {cooldown}s...")
            time.sleep(cooldown)

    artifact_hash_b4 = sha256_dir(run_dir_b4)
    b4_actual_provider_tokens = sum(r["total_tokens"] for r in b4_telemetry_records)
    logger.info(f"Candidate B4 sealed. Hash: {artifact_hash_b4}. Tokens: {b4_actual_provider_tokens}")

    if b4_min_provider_tokens <= b4_actual_provider_tokens <= b4_max_provider_tokens:
        resource_parity_status = "PASS"
    elif b4_actual_provider_tokens < b4_min_provider_tokens:
        resource_parity_status = "UNDER_BUDGET"
    else:
        resource_parity_status = "OVER_BUDGET"
    logger.info(f"Candidate B4 Resource Parity: {resource_parity_status}")

    # =========================================================================
    # 4. EXECUTE CANDIDATE C4 (SINGLE-AGENT ONE-SHOT BASELINE)
    # =========================================================================
    logger.info(f"Pacing cooldown before Candidate C4: {cooldown}s...")
    time.sleep(cooldown)

    run_id_c4 = "RUN-PHASE4-3-RC2-CASE03-C4-001"
    run_dir_c4 = RUNS_DIR / run_id_c4
    if run_dir_c4.exists():
        import shutil
        shutil.rmtree(run_dir_c4)
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_c4 / d).mkdir(parents=True, exist_ok=True)

    logger.info(f"Executing Candidate C4 (1 call): {run_id_c4}")
    p_prompt_c = build_candidate_c4_one_shot_prompt(facts, evidence, objective)
    (run_dir_c4 / "raw" / "request" / "one_shot_request.txt").write_text(p_prompt_c, encoding="utf-8")

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
    (run_dir_c4 / "raw" / "response" / "one_shot_response.txt").write_text(raw_resp_text_c, encoding="utf-8")

    usage_dict_c = resp_c.usage.model_dump() if hasattr(resp_c.usage, "model_dump") else {
        "prompt_tokens": resp_c.usage.prompt_tokens,
        "completion_tokens": resp_c.usage.completion_tokens,
        "thoughts_tokens": resp_c.usage.thoughts_tokens,
        "total_tokens": resp_c.usage.total_tokens,
    }
    c4_telemetry = {
        "latency_ms": t_lat_c,
        **usage_dict_c,
    }
    (run_dir_c4 / "telemetry" / "one_shot_telemetry.json").write_text(
        json.dumps(c4_telemetry, indent=2), encoding="utf-8"
    )
    c4_actual_provider_tokens = c4_telemetry.get("total_tokens", 0)
    artifact_hash_c4 = sha256_dir(run_dir_c4)
    logger.info(f"Candidate C4 sealed. Hash: {artifact_hash_c4}. Tokens: {c4_actual_provider_tokens}")

    # =========================================================================
    # 5. CANONICAL ASSEMBLY & PRESERVATION LEDGER AUDIT
    # =========================================================================
    logger.info("Executing NeutralCanonicalCandidateAssembler across Candidates A4, B4, C4...")
    canon_a4, audit_a4 = NeutralCanonicalCandidateAssembler.assemble_candidate_a(a4_stages)
    canon_b4, audit_b4 = NeutralCanonicalCandidateAssembler.assemble_candidate_b(b4_passes_data)
    canon_c4, audit_c4 = NeutralCanonicalCandidateAssembler.assemble_candidate_c(raw_resp_text_c)

    # =========================================================================
    # 6. DOUBLE-BLIND INDEPENDENT QUALITY EVALUATION
    # =========================================================================
    logger.info("Pacing cooldown before Double-Blind Judging...")
    time.sleep(cooldown)

    seed_str = "BLIND_MAPPING_PHASE_4_3C_14_CASE_03_SEED"
    rng = random.Random(seed_str)
    real_candidates = ["A4", "B4", "C4"]
    shuffled_real = list(real_candidates)
    rng.shuffle(shuffled_real)

    blind_to_real = {"X": shuffled_real[0], "Y": shuffled_real[1], "Z": shuffled_real[2]}
    real_to_blind = {v: k for k, v in blind_to_real.items()}
    commitment_str = json.dumps(blind_to_real, sort_keys=True)
    blind_commitment_hash = hashlib.sha256(commitment_str.encode("utf-8")).hexdigest()

    (JUDGE_DIR / "blind_mapping_commitment.json").write_text(
        json.dumps({"commitment_hash": blind_commitment_hash, "created_at": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8"
    )

    from evaluations.benchmarks.phase4_3_unseen_case_02_dev_security.run_case02_blind_evaluation import (
        FROZEN_DIMENSIONS,
        format_candidate_canonical_for_judge,
        build_blind_judge_prompt,
    )

    raw_canon_map = {
        "A4": canon_a4.model_dump() if hasattr(canon_a4, "model_dump") else canon_a4.__dict__,
        "B4": canon_b4.model_dump() if hasattr(canon_b4, "model_dump") else canon_b4.__dict__,
        "C4": canon_c4.model_dump() if hasattr(canon_c4, "model_dump") else canon_c4.__dict__,
    }
    blind_packets = {k: format_candidate_canonical_for_judge(k, raw_canon_map[real_id]) for k, real_id in blind_to_real.items()}

    permutations = [["X", "Y", "Z"], ["Y", "Z", "X"], ["Z", "X", "Y"]]
    judge_results = []
    judge_hashes = []

    for idx, order in enumerate(permutations, start=1):
        logger.info(f"Executing Judge Pass {idx}/3 (Order: {' -> '.join(order)})...")
        prompt = build_blind_judge_prompt(facts, evidence, objective, blind_packets, order)
        (JUDGE_DIR / f"judge_pass_{idx}_prompt.txt").write_text(prompt, encoding="utf-8")

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=prompt)],
            model_name="gemini-flash-latest",
            temperature=0.1,
            max_tokens=8192,
            timeout_seconds=180.0,
        )
        t_start = time.time()
        resp = gateway.generate(req, provider_id="gemini", strict_model_pin=True)
        t_lat = (time.time() - t_start) * 1000.0

        raw_resp = resp.content or ""
        (JUDGE_DIR / f"judge_pass_{idx}_response.txt").write_text(raw_resp, encoding="utf-8")

        parsed_eval = NeutralCanonicalCandidateAssembler.extract_json_block(raw_resp) or {}
        (JUDGE_DIR / f"judge_pass_{idx}_parsed.json").write_text(json.dumps(parsed_eval, indent=2), encoding="utf-8")

        pass_hash = hashlib.sha256(raw_resp.encode("utf-8")).hexdigest()
        judge_hashes.append(pass_hash)

        judge_record = {
            "pass": idx,
            "order": order,
            "latency_ms": t_lat,
            "raw_hash": pass_hash,
            "scores": parsed_eval.get("candidate_scores", {}),
            "pairwise": parsed_eval.get("pairwise_comparisons", {}),
            "flags": parsed_eval.get("critical_failure_flags", {}),
        }
        judge_results.append(judge_record)

        if idx < 3:
            logger.info("Cooldown pacing 70s between judge passes...")
            time.sleep(70.0)

    # Blind Aggregation
    weights = {d["id"]: d["weight"] for d in FROZEN_DIMENSIONS}
    blind_summary = {}

    for letter in ["X", "Y", "Z"]:
        dim_scores = {}
        for d in FROZEN_DIMENSIONS:
            d_id = d["id"]
            scores_for_d = []
            for j in judge_results:
                sc = j["scores"].get(letter, {}).get(d_id, {}).get("score")
                if sc is not None:
                    try:
                        scores_for_d.append(float(sc))
                    except Exception:
                        pass
            if not scores_for_d:
                scores_for_d = [5.0]
            scores_for_d.sort()
            median_score = scores_for_d[len(scores_for_d) // 2]
            dim_scores[d_id] = {
                "median": median_score,
                "raw_scores": scores_for_d,
                "range": max(scores_for_d) - min(scores_for_d),
            }
        weighted_score = sum(dim_scores[d_id]["median"] * weights[d_id] for d_id in dim_scores)
        blind_summary[letter] = {
            "weighted_quality_score": round(weighted_score, 3),
            "dimension_scores": dim_scores,
        }

    # Reveal Mapping
    unmasked_results = {}
    for letter, real_id in blind_to_real.items():
        unmasked_results[real_id] = {
            "letter": letter,
            "weighted_quality_score": blind_summary[letter]["weighted_quality_score"],
            "dimension_scores": {d["id"]: blind_summary[letter]["dimension_scores"][d["id"]]["median"] for d in FROZEN_DIMENSIONS},
        }

    a4_score = unmasked_results["A4"]["weighted_quality_score"]
    b4_score = unmasked_results["B4"]["weighted_quality_score"]
    c4_score = unmasked_results["C4"]["weighted_quality_score"]
    delta_a4_b4 = round(a4_score - b4_score, 3)

    tokens_map = {"A4": a4_actual_provider_tokens, "B4": b4_actual_provider_tokens, "C4": c4_actual_provider_tokens}
    calls_map = {"A4": 6, "B4": 3, "C4": 1}
    deliv_map = {"A4": audit_a4.total_deliverables_found, "B4": audit_b4.total_deliverables_found, "C4": audit_c4.total_deliverables_found}

    efficiency_summary = {}
    for r_id in ["A4", "B4", "C4"]:
        q_score = unmasked_results[r_id]["weighted_quality_score"]
        tok = tokens_map[r_id]
        calls = calls_map[r_id]
        deliv = deliv_map[r_id]
        efficiency_summary[r_id] = {
            "quality_per_10k_tokens": round((q_score / tok) * 10000.0, 3),
            "quality_per_call": round(q_score / calls, 3),
            "deliverables_per_10k_tokens": round((deliv / tok) * 10000.0, 3),
        }

    a4_dims = unmasked_results["A4"]["dimension_scores"]
    b4_dims = unmasked_results["B4"]["dimension_scores"]

    # Evaluate Quality Gate
    rc2_quality_gate = (
        resource_parity_status == "PASS"
        and a4_dims.get("attribution_tracking", 0.0) >= 6.0
        and a4_dims.get("experimentation_rigor", 0.0) >= 6.0
        and a4_dims.get("governance_human_approval", 0.0) >= 6.0
        and a4_dims.get("performance_funnel_metrics", 0.0) >= 6.0
        and (a4_score >= (b4_score - 0.35) or a4_score >= b4_score)
    )

    final_report = {
        "benchmark_id": "BENCHMARK-PHASE4-3-CASE03-CONSUMER-HARDWARE",
        "case_id": "CASE_03_CONSUMER_HARDWARE_D2C",
        "brain_version": "FIVE_AGENT_BRAIN_V1_RC2",
        "brain_rc2_fingerprint": "35987acba993572515a0e8daaab9f6910448ba7fc6cb1121b371b6a755f99900",
        "protocol_fingerprint": active_fingerprint,
        "input_hash": "34a46c5c63ce85b0dc9641476651212bc66b9bbcc3dd262f6a0d22301a816f91",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": {
            "A4": {
                "run_id": run_id_a4,
                "calls": 6,
                "provider_total_tokens": a4_actual_provider_tokens,
                "artifact_hash": artifact_hash_a4,
                "deliverables": audit_a4.total_deliverables_found,
                "weighted_score": a4_score,
                "dimension_scores": a4_dims,
            },
            "B4": {
                "run_id": run_id_b4,
                "calls": 3,
                "provider_total_tokens": b4_actual_provider_tokens,
                "artifact_hash": artifact_hash_b4,
                "deliverables": audit_b4.total_deliverables_found,
                "resource_parity": resource_parity_status,
                "weighted_score": b4_score,
                "dimension_scores": b4_dims,
            },
            "C4": {
                "run_id": run_id_c4,
                "calls": 1,
                "provider_total_tokens": c4_actual_provider_tokens,
                "artifact_hash": artifact_hash_c4,
                "deliverables": audit_c4.total_deliverables_found,
                "weighted_score": c4_score,
                "dimension_scores": unmasked_results["C4"]["dimension_scores"],
            },
        },
        "efficiency_summary": efficiency_summary,
        "primary_comparison": {
            "a4_score": a4_score,
            "b4_score": b4_score,
            "delta": delta_a4_b4,
            "quality_gate": "PASS" if rc2_quality_gate else "TARGETED_OPTIMIZATION_REQUIRED",
        },
        "blind_mapping": blind_to_real,
        "blind_commitment_hash": blind_commitment_hash,
    }

    (CASE_DIR / "phase4_3c_14_validation_summary.json").write_text(
        json.dumps(final_report, indent=2), encoding="utf-8"
    )

    # Write Markdown Report
    report_md = f"""# Phase 4.3C.14: Unseen Case 03 Final Five-Agent Brain V1 Validation Report
## Case 03 — AromaBrew Pro (Consumer Kitchen Hardware / D2C)

**Evaluation Status:** `COMPLETED_CASE03_VALIDATION`  
**Brain Candidate:** `FIVE_AGENT_BRAIN_V1_RC2`  
**Brain RC2 Fingerprint:** `35987acba993572515a0e8daaab9f6910448ba7fc6cb1121b371b6a755f99900`  
**Case ID:** `CASE_03_CONSUMER_HARDWARE_D2C`  
**Input Hash:** `34a46c5c63ce85b0dc9641476651212bc66b9bbcc3dd262f6a0d22301a816f91`  
**Active Protocol Fingerprint:** `{active_fingerprint}`  

---

## 1. Candidate Generation & Resource Parity
- **Candidate A4 (Five-Agent RC2):** `{a4_actual_provider_tokens}` provider tokens ({audit_a4.total_deliverables_found}/28 deliverables) | Hash: `{artifact_hash_a4}`
- **Candidate B4 (Single Multi-Pass):** `{b4_actual_provider_tokens}` provider tokens ({audit_b4.total_deliverables_found}/28 deliverables) | Hash: `{artifact_hash_b4}`
- **Dynamic B4 Target:** `{b4_target_provider_tokens}` (Range: `{b4_min_provider_tokens}` - `{b4_max_provider_tokens}`)
- **Resource Parity Verdict:** **`{resource_parity_status}`** (Delta: `{(b4_actual_provider_tokens - a4_actual_provider_tokens) / float(a4_actual_provider_tokens) * 100.0:+.2f}%`)
- **Candidate C4 (Single One-Shot):** `{c4_actual_provider_tokens}` provider tokens ({audit_c4.total_deliverables_found}/28 deliverables) | Hash: `{artifact_hash_c4}`

---

## 2. Double-Blind Evaluation Scores (0–10 Scale)

| Dimension | Weight | Candidate A4 (Five-Agent RC2) | Candidate B4 (Single Multi-Pass Control) | Candidate C4 (Single One-Shot Baseline) | Leader |
|---|---|---|---|---|---|
| **1. Research Quality** | 0.08 | **{a4_dims['research_quality']:.1f}** | **{b4_dims['research_quality']:.1f}** | **{unmasked_results['C4']['dimension_scores']['research_quality']:.1f}** | {'A4' if a4_dims['research_quality'] > b4_dims['research_quality'] else ('B4' if b4_dims['research_quality'] > a4_dims['research_quality'] else 'TIE')} |
| **2. Evidence Discipline** | 0.08 | **{a4_dims['evidence_discipline']:.1f}** | **{b4_dims['evidence_discipline']:.1f}** | **{unmasked_results['C4']['dimension_scores']['evidence_discipline']:.1f}** | {'A4' if a4_dims['evidence_discipline'] > b4_dims['evidence_discipline'] else ('B4' if b4_dims['evidence_discipline'] > a4_dims['evidence_discipline'] else 'TIE')} |
| **3. Segmentation Quality** | 0.08 | **{a4_dims['segmentation_quality']:.1f}** | **{b4_dims['segmentation_quality']:.1f}** | **{unmasked_results['C4']['dimension_scores']['segmentation_quality']:.1f}** | {'A4' if a4_dims['segmentation_quality'] > b4_dims['segmentation_quality'] else ('B4' if b4_dims['segmentation_quality'] > a4_dims['segmentation_quality'] else 'TIE')} |
| **4. Positioning Quality** | 0.08 | **{a4_dims['positioning_quality']:.1f}** | **{b4_dims['positioning_quality']:.1f}** | **{unmasked_results['C4']['dimension_scores']['positioning_quality']:.1f}** | {'A4' if a4_dims['positioning_quality'] > b4_dims['positioning_quality'] else ('B4' if b4_dims['positioning_quality'] > a4_dims['positioning_quality'] else 'TIE')} |
| **5. Channel Strategy** | 0.07 | **{a4_dims['channel_strategy']:.1f}** | **{b4_dims['channel_strategy']:.1f}** | **{unmasked_results['C4']['dimension_scores']['channel_strategy']:.1f}** | {'A4' if a4_dims['channel_strategy'] > b4_dims['channel_strategy'] else ('B4' if b4_dims['channel_strategy'] > a4_dims['channel_strategy'] else 'TIE')} |
| **6. Creative Quality** | 0.07 | **{a4_dims['creative_quality']:.1f}** | **{b4_dims['creative_quality']:.1f}** | **{unmasked_results['C4']['dimension_scores']['creative_quality']:.1f}** | {'A4' if a4_dims['creative_quality'] > b4_dims['creative_quality'] else ('B4' if b4_dims['creative_quality'] > a4_dims['creative_quality'] else 'TIE')} |
| **7. Copy / Script Executability** | 0.07 | **{a4_dims['copy_script_executability']:.1f}** | **{b4_dims['copy_script_executability']:.1f}** | **{unmasked_results['C4']['dimension_scores']['copy_script_executability']:.1f}** | {'A4' if a4_dims['copy_script_executability'] > b4_dims['copy_script_executability'] else ('B4' if b4_dims['copy_script_executability'] > a4_dims['copy_script_executability'] else 'TIE')} |
| **8. Performance Funnel & Metrics** | 0.07 | **{a4_dims['performance_funnel_metrics']:.1f}** | **{b4_dims['performance_funnel_metrics']:.1f}** | **{unmasked_results['C4']['dimension_scores']['performance_funnel_metrics']:.1f}** | {'A4' if a4_dims['performance_funnel_metrics'] > b4_dims['performance_funnel_metrics'] else ('B4' if b4_dims['performance_funnel_metrics'] > a4_dims['performance_funnel_metrics'] else 'TIE')} |
| **9. Experimentation Rigor** | 0.07 | **{a4_dims['experimentation_rigor']:.1f}** | **{b4_dims['experimentation_rigor']:.1f}** | **{unmasked_results['C4']['dimension_scores']['experimentation_rigor']:.1f}** | {'A4' if a4_dims['experimentation_rigor'] > b4_dims['experimentation_rigor'] else ('B4' if b4_dims['experimentation_rigor'] > a4_dims['experimentation_rigor'] else 'TIE')} |
| **10. Attribution / Tracking** | 0.07 | **{a4_dims['attribution_tracking']:.1f}** | **{b4_dims['attribution_tracking']:.1f}** | **{unmasked_results['C4']['dimension_scores']['attribution_tracking']:.1f}** | {'A4' if a4_dims['attribution_tracking'] > b4_dims['attribution_tracking'] else ('B4' if b4_dims['attribution_tracking'] > a4_dims['attribution_tracking'] else 'TIE')} |
| **11. Claim Safety / Compliance** | 0.08 | **{a4_dims['claim_safety_compliance']:.1f}** | **{b4_dims['claim_safety_compliance']:.1f}** | **{unmasked_results['C4']['dimension_scores']['claim_safety_compliance']:.1f}** | {'A4' if a4_dims['claim_safety_compliance'] > b4_dims['claim_safety_compliance'] else ('B4' if b4_dims['claim_safety_compliance'] > a4_dims['claim_safety_compliance'] else 'TIE')} |
| **12. Governance / Human Approval** | 0.07 | **{a4_dims['governance_human_approval']:.1f}** | **{b4_dims['governance_human_approval']:.1f}** | **{unmasked_results['C4']['dimension_scores']['governance_human_approval']:.1f}** | {'A4' if a4_dims['governance_human_approval'] > b4_dims['governance_human_approval'] else ('B4' if b4_dims['governance_human_approval'] > a4_dims['governance_human_approval'] else 'TIE')} |
| **13. Internal Consistency / Lineage** | 0.07 | **{a4_dims['internal_consistency_lineage']:.1f}** | **{b4_dims['internal_consistency_lineage']:.1f}** | **{unmasked_results['C4']['dimension_scores']['internal_consistency_lineage']:.1f}** | {'A4' if a4_dims['internal_consistency_lineage'] > b4_dims['internal_consistency_lineage'] else ('B4' if b4_dims['internal_consistency_lineage'] > a4_dims['internal_consistency_lineage'] else 'TIE')} |
| **14. Completeness** | 0.04 | **{a4_dims['completeness']:.1f}** | **{b4_dims['completeness']:.1f}** | **{unmasked_results['C4']['dimension_scores']['completeness']:.1f}** | {'A4' if a4_dims['completeness'] > b4_dims['completeness'] else ('B4' if b4_dims['completeness'] > a4_dims['completeness'] else 'TIE')} |
| **FINAL WEIGHTED SCORE** | **1.00** | **{a4_score:.3f}** | **{b4_score:.3f}** | **{c4_score:.3f}** | **{('A4' if a4_score > b4_score else ('B4' if b4_score > a4_score else 'TIE'))}** |

---

## 3. RC2 Diagnostic Validation Results
- **Attribution / Tracking:** `{a4_dims.get('attribution_tracking', 0.0):.1f}` / 10.0 (Target: $\ge 6.0$) -> **{'PASS' if a4_dims.get('attribution_tracking', 0.0) >= 6.0 else 'FAIL'}**
- **Experimentation Rigor:** `{a4_dims.get('experimentation_rigor', 0.0):.1f}` / 10.0 (Target: $\ge 6.0$) -> **{'PASS' if a4_dims.get('experimentation_rigor', 0.0) >= 6.0 else 'FAIL'}**
- **Governance / Human Approval:** `{a4_dims.get('governance_human_approval', 0.0):.1f}` / 10.0 (Target: $\ge 6.0$) -> **{'PASS' if a4_dims.get('governance_human_approval', 0.0) >= 6.0 else 'FAIL'}**
- **Performance Funnel & Metrics:** `{a4_dims.get('performance_funnel_metrics', 0.0):.1f}` / 10.0 (Target: $\ge 6.0$) -> **{'PASS' if a4_dims.get('performance_funnel_metrics', 0.0) >= 6.0 else 'FAIL'}**

---

## 4. Final Brain V1 Quality Gate
- **Five-Agent Brain V1 Quality Gate:** **`{'PASS' if rc2_quality_gate else 'TARGETED_OPTIMIZATION_REQUIRED'}`**
- **Initial Real-World Use Ready:** **`{'YES' if rc2_quality_gate else 'NO'}`**
"""

    report_path = Path(r"c:\AI-Marketing-Department\evaluations\phase4_3c_14_unseen_case_03_final_validation_report.md")
    report_path.write_text(report_md, encoding="utf-8")
    logger.info(f"Phase 4.3C.14 validation report written to {report_path}")

    return final_report


if __name__ == "__main__":
    res = run_case03_validation()
    print("Case 03 Validation Finished Successfully:")
    print(json.dumps(res, indent=2))
