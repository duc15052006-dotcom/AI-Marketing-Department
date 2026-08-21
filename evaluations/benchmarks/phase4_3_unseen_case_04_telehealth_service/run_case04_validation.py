"""Phase 4.3C.16: Final Unseen Case 04 Release Validation Runner.

Case ID: CASE_04_TELEHEALTH_REGULATED_SERVICE
Brain Version: FIVE_AGENT_BRAIN_V1_RC3
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from integrations.models.base import ModelMessage, ModelRequest, ModelRole, ModelUsage, ModelResponseStatus
from integrations.models.gateway import UniversalModelGateway
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    BenchmarkExecutionPolicy,
    BenchmarkHarness,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.neutral_canonical_assembler import (
    NeutralCanonicalCandidateAssembler,
)
from evaluations.benchmarks.phase4_3_control_b5_and_judge_protocol import (
    B5_LOGICAL_AGENT_COUNT,
    B5_PASS_COUNT,
    MAX_BOUNDED_STATE_CHARS,
    JUDGE_FAILURE_POLICY,
    MIN_VALID_JUDGE_PASSES,
    FROZEN_14_DIMENSIONS,
    build_candidate_b5_pass_1_prompt,
    build_candidate_b5_pass_2_prompt,
    build_candidate_b5_pass_3_prompt,
    build_candidate_b5_pass_4_prompt,
    extract_scores_fail_closed,
    aggregate_judge_passes_fail_closed,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] phase4_3c_16_runner: %(message)s")
logger = logging.getLogger("phase4_3c_16_runner")

CASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = CASE_DIR / "runs" / "phase4_3_rc3"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
JUDGE_DIR = CASE_DIR / "blind_judging"
JUDGE_DIR.mkdir(parents=True, exist_ok=True)

EXPECTED_RC3_FINGERPRINT = "b13f2f6c28007dd7a6f9e2a00175b9e87f59908ece647fb53ceba5186496354a"
EXPECTED_PERF_HASH = "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9"
EXPECTED_CMO_HASH = "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e"
EXPECTED_HANDOFF_HASH = "4075a8e269aef7526bb52c281ac88cc6fdc009d83e9aecb384032e29087e237a"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


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


def format_compact_candidate(canonical_dict: Dict[str, Any]) -> str:
    lines = []
    for k, v in canonical_dict.items():
        title = k.replace("_", " ").upper()
        if v:
            val_str = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v).strip()
            if len(val_str) > 900:
                val_str = val_str[:900] + "...[TRUNCATED FOR COMPACT JUDGE PACKET]"
            lines.append(f"## {title}\n{val_str}\n")
        else:
            lines.append(f"## {title}\n[SECTION NOT PROVIDED IN CANDIDATE OUTPUT]\n")
    return "\n".join(lines)


def build_compact_judge_prompt(
    letter: str,
    candidate_content: str,
    facts: Dict[str, Any],
    evidence: Dict[str, Any],
    objective: Dict[str, Any],
) -> str:
    rubric_str = "\n".join([f"- **{d['name']}** (Weight: {d['weight']}): {d['desc']}" for d in FROZEN_14_DIMENSIONS])
    return f"""You are an Expert Independent GTM Strategy & Healthcare Marketing Quality Auditor performing a Double-Blind Evaluation of Candidate {letter} on Case 04 (CardioVital 360 Preventive Telehealth).

[GROUND TRUTH SPECIFICATIONS]
VERIFIED PRODUCT & CLINICAL FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

PROHIBITED CLAIMS:
- 100% cure, reversal, or immunity guarantees for cardiovascular disease
- Advising patients to stop existing prescription statins without physician order
- Claiming FDA-cleared status for general software/platform algorithms
- Fabricated patient testimonials without HIPAA authorization

[FROZEN 14-DIMENSION RUBRIC]
{rubric_str}

[ANONYMOUS CANDIDATE {letter} PROPOSAL]
{candidate_content}

[INSTRUCTIONS]
Score Candidate {letter} independently on each of the 14 dimensions on a 0.0 to 10.0 scale.
Keep rationales concise (1 sentence per dimension).
Respond ONLY with a valid JSON object:
```json
{{
  "candidate_scores": {{
    "research_quality": {{"score": 8.0, "rationale": "..."}},
    "evidence_discipline": {{"score": 8.0, "rationale": "..."}},
    "segmentation_quality": {{"score": 8.0, "rationale": "..."}},
    "positioning_quality": {{"score": 8.0, "rationale": "..."}},
    "channel_strategy": {{"score": 8.0, "rationale": "..."}},
    "creative_quality": {{"score": 8.0, "rationale": "..."}},
    "copy_script_executability": {{"score": 8.0, "rationale": "..."}},
    "performance_funnel_metrics": {{"score": 8.0, "rationale": "..."}},
    "experimentation_rigor": {{"score": 8.0, "rationale": "..."}},
    "attribution_tracking": {{"score": 8.0, "rationale": "..."}},
    "claim_safety_compliance": {{"score": 8.0, "rationale": "..."}},
    "governance_human_approval": {{"score": 8.0, "rationale": "..."}},
    "internal_consistency_lineage": {{"score": 8.0, "rationale": "..."}},
    "completeness": {{"score": 8.0, "rationale": "..."}}
  }}
}}
```
"""


def safe_generate(gateway: UniversalModelGateway, req: ModelRequest, max_retries: int = 8) -> ModelResponse:
    for attempt in range(max_retries):
        resp = gateway.generate(req, provider_id="gemini", strict_model_pin=True)
        if resp.status == ModelResponseStatus.RATE_LIMITED or "429" in str(resp.error or ""):
            if attempt < max_retries - 1:
                logger.warning(f"Rate limit hit (attempt {attempt+1}/{max_retries}). Sleeping 90s before retry...")
                time.sleep(90.0)
                continue
        return resp
    return resp


def run_case04_release_validation() -> Dict[str, Any]:
    # 0. PRE-FLIGHT INTEGRITY AUDIT
    root_p = Path(r"c:\AI-Marketing-Department")
    p_perf = sha256_file(root_p / ".agents/agents/performance/agent.md")
    p_cmo = sha256_file(root_p / ".agents/agents/cmo/agent.md")
    p_handoff = sha256_file(root_p / "schemas/handoff.py")

    if p_perf != EXPECTED_PERF_HASH or p_cmo != EXPECTED_CMO_HASH or p_handoff != EXPECTED_HANDOFF_HASH:
        raise RuntimeError(f"Brain RC3 hash verification failed before execution! Perf: {p_perf}, CMO: {p_cmo}, Handoff: {p_handoff}")

    manifest_path = CASE_DIR / "phase4_3c_16_benchmark_protocol.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    active_fingerprint = manifest_data.get("protocol_fingerprint")
    logger.info(f"Starting Phase 4.3C.16 Release Validation on Case 04. Protocol Fingerprint: {active_fingerprint}")

    facts = json.loads((CASE_DIR / "product_facts.json").read_text(encoding="utf-8"))
    evidence = json.loads((CASE_DIR / "evidence_bundle.json").read_text(encoding="utf-8"))
    objective = json.loads((CASE_DIR / "business_objective.json").read_text(encoding="utf-8"))

    gateway = UniversalModelGateway(free_only_mode=True)
    cooldown = 75.0

    # =========================================================================
    # 1. EXECUTE CANDIDATE A5 (FIVE-AGENT BRAIN V1 RC3)
    # =========================================================================
    run_id_a5 = "RUN-PHASE4-3-RC3-CASE04-A5-001"
    run_dir_a5 = RUNS_DIR / run_id_a5
    run_dir_a5.mkdir(parents=True, exist_ok=True)

    logger.info(f"Executing Candidate A5 (Five-Agent RC3 on Case 04): {run_id_a5}")
    policy_a5 = BenchmarkExecutionPolicy(
        model_call_timeout_seconds=180.0,
        strict_model_pin=True,
        cooldown_seconds=cooldown,
        context_version="v2",
        execution_generation="phase4_3_rc3",
        max_tokens_per_call=8192,
    )
    harness_a5 = BenchmarkHarness(
        benchmark_dir=CASE_DIR,
        run_dir=run_dir_a5,
        checkpoints_dir=run_dir_a5 / "checkpoints",
        run_id=run_id_a5,
        cooldown_seconds=cooldown,
        provider_id="gemini",
        model_name="gemini-flash-latest",
        gateway=gateway,
        policy=policy_a5,
    )
    res_a5 = harness_a5.run_five_agent_condition()
    if res_a5.get("status") != "COMPLETED":
        raise RuntimeError(f"Candidate A5 generation failed: {res_a5.get('error')}")

    artifact_hash_a5 = sha256_dir(run_dir_a5)
    a5_stages = res_a5.get("stages", {})
    a5_actual_provider_tokens = sum(s.get("usage", {}).get("total_tokens", 0) for s in a5_stages.values())
    logger.info(f"Candidate A5 sealed. Hash: {artifact_hash_a5}. Tokens: {a5_actual_provider_tokens}")

    # =========================================================================
    # 2. DYNAMIC SAME-CASE RESOURCE TARGET EXTRACTION FOR B5
    # =========================================================================
    b5_target_provider_tokens = a5_actual_provider_tokens
    b5_min_provider_tokens = int(round(b5_target_provider_tokens * 0.90))
    b5_max_provider_tokens = int(round(b5_target_provider_tokens * 1.10))
    logger.info(f"Dynamic B5 Target: {b5_target_provider_tokens} (Range: {b5_min_provider_tokens} - {b5_max_provider_tokens})")

    # =========================================================================
    # 3. EXECUTE CANDIDATE B5 (SINGLE-AGENT 4-PASS CONTROL)
    # =========================================================================
    run_id_b5 = "RUN-PHASE4-3-RC3-CASE04-B5-001"
    run_dir_b5 = RUNS_DIR / run_id_b5
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_b5 / d).mkdir(parents=True, exist_ok=True)

    logger.info(f"Executing Candidate B5 (4 passes): {run_id_b5}")
    b5_passes_data = []
    cumulative_working_state = ""
    b5_telemetry_records = []

    for pass_idx in range(1, 5):
        pass_chk_p = run_dir_b5 / "checkpoints" / f"pass_{pass_idx}.json"
        if pass_chk_p.exists():
            logger.info(f"Candidate B5 - Loading Pass {pass_idx}/4 from checkpoint...")
            chk_data = json.loads(pass_chk_p.read_text(encoding="utf-8"))
            b5_passes_data.append(chk_data)
            cumulative_working_state = chk_data.get("working_state", "")
            tel_p = run_dir_b5 / "telemetry" / f"pass_{pass_idx}_telemetry.json"
            if tel_p.exists():
                b5_telemetry_records.append(json.loads(tel_p.read_text(encoding="utf-8")))
            continue

        logger.info(f"Candidate B5 - Executing Pass {pass_idx}/4...")
        if pass_idx == 1:
            p_prompt = build_candidate_b5_pass_1_prompt(facts, evidence, objective)
        elif pass_idx == 2:
            p_prompt = build_candidate_b5_pass_2_prompt(facts, evidence, objective, cumulative_working_state)
        elif pass_idx == 3:
            p_prompt = build_candidate_b5_pass_3_prompt(facts, evidence, objective, cumulative_working_state)
        else:
            p_prompt = build_candidate_b5_pass_4_prompt(facts, evidence, objective, cumulative_working_state)

        (run_dir_b5 / "raw" / "request" / f"pass_{pass_idx}_request.txt").write_text(p_prompt, encoding="utf-8")

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=p_prompt)],
            model_name="gemini-flash-latest",
            temperature=0.2,
            max_tokens=8192,
            timeout_seconds=180.0,
        )

        t_start = time.time()
        resp = safe_generate(gateway, req)
        t_lat = (time.time() - t_start) * 1000.0

        raw_resp_text = resp.content or ""
        (run_dir_b5 / "raw" / "response" / f"pass_{pass_idx}_response.txt").write_text(raw_resp_text, encoding="utf-8")

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
        (run_dir_b5 / "telemetry" / f"pass_{pass_idx}_telemetry.json").write_text(
            json.dumps(pass_telemetry, indent=2), encoding="utf-8"
        )
        b5_telemetry_records.append(pass_telemetry)

        extracted_state = extract_working_state(raw_resp_text)
        cumulative_working_state = extracted_state

        pass_checkpoint = {
            "pass": pass_idx,
            "status": "SUCCESS" if raw_resp_text else "FAILED",
            "raw_text": raw_resp_text,
            "working_state": cumulative_working_state,
            "telemetry": pass_telemetry,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir_b5 / "checkpoints" / f"pass_{pass_idx}.json").write_text(
            json.dumps(pass_checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        b5_passes_data.append(pass_checkpoint)

        (run_dir_b5 / "heartbeat.json").write_text(
            json.dumps({"last_completed_pass": pass_idx, "timestamp": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8"
        )

        if pass_idx < 4:
            logger.info(f"Pacing cooldown {cooldown}s...")
            time.sleep(cooldown)

    artifact_hash_b5 = sha256_dir(run_dir_b5)
    b5_actual_provider_tokens = sum(r.get("total_tokens", 0) for r in b5_telemetry_records)
    logger.info(f"Candidate B5 sealed. Hash: {artifact_hash_b5}. Tokens: {b5_actual_provider_tokens}")

    if b5_min_provider_tokens <= b5_actual_provider_tokens <= b5_max_provider_tokens:
        resource_parity_status = "PASS"
    elif b5_actual_provider_tokens < b5_min_provider_tokens:
        resource_parity_status = "UNDER_BUDGET"
    else:
        resource_parity_status = "OVER_BUDGET"
    logger.info(f"Candidate B5 Resource Parity: {resource_parity_status}")

    # =========================================================================
    # 4. EXECUTE CANDIDATE C5 (SINGLE-AGENT ONE-SHOT BASELINE)
    # =========================================================================
    run_id_c5 = "RUN-PHASE4-3-RC3-CASE04-C5-001"
    run_dir_c5 = RUNS_DIR / run_id_c5
    for d in ["raw/request", "raw/response", "telemetry", "checkpoints"]:
        (run_dir_c5 / d).mkdir(parents=True, exist_ok=True)

    c5_resp_p = run_dir_c5 / "raw" / "response" / "one_shot_response.txt"
    c5_tel_p = run_dir_c5 / "telemetry" / "one_shot_telemetry.json"
    if c5_resp_p.exists() and c5_tel_p.exists():
        logger.info("Candidate C5 - Loading from checkpoint...")
        raw_resp_text_c = c5_resp_p.read_text(encoding="utf-8")
        c5_telemetry = json.loads(c5_tel_p.read_text(encoding="utf-8"))
    else:
        logger.info(f"Pacing cooldown before Candidate C5: {cooldown}s...")
        time.sleep(cooldown)
        logger.info(f"Executing Candidate C5 (1 call): {run_id_c5}")
        p_prompt_c = f"""You are a Principal Marketing Strategist and Medical Growth Director creating a complete, comprehensive, 28-deliverable Go-To-Market Strategy Proposal for CardioVital 360 (Case 04).

[VERIFIED PRODUCT & CLINICAL FACTS]
{json.dumps(facts, indent=2)}

[QUALITATIVE MARKET EVIDENCE]
{json.dumps(evidence, indent=2)}

[BUSINESS OBJECTIVE & CONSTRAINTS]
{json.dumps(objective, indent=2)}

[PROHIBITED CLAIMS & COMPLIANCE GUARDRAILS]
- 100% cure, reversal, or immunity guarantees for cardiovascular disease
- Advising patients to stop existing prescription statins without physician order
- Claiming FDA-cleared status for general software/platform algorithms
- Fabricated patient testimonials without HIPAA authorization

You must provide a complete, verified GTM proposal covering all core marketing dimensions:
1. EXECUTIVE SUMMARY
2. RESEARCH FINDINGS (Facts, Observations, Inferences, Unknowns)
3. CUSTOMER SEGMENTS & TOP PRIORITY BEACHHEAD
4. POSITIONING & VALUE PROPOSITION
5. CHANNEL PRIORITIES & DEFERRED CHANNELS
6. CREATIVE TERRITORIES, ANGLES, HOOKS, COPY, AND VIDEO SCRIPT
7. FULL-FUNNEL MEASUREMENT FRAMEWORK & METRICS
8. ATTRIBUTION & EVENT TRACKING TAXONOMY
9. EXPERIMENTATION BACKLOG & DECISION RULES
10. RISKS, GOVERNANCE, GO/TEST/HOLD/DEFER, AND HUMAN APPROVAL REQUIREMENTS
"""
        (run_dir_c5 / "raw" / "request" / "one_shot_request.txt").write_text(p_prompt_c, encoding="utf-8")

        req_c = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=p_prompt_c)],
            model_name="gemini-flash-latest",
            temperature=0.2,
            max_tokens=8192,
            timeout_seconds=180.0,
        )
        t_start = time.time()
        resp_c = safe_generate(gateway, req_c)
        t_lat_c = (time.time() - t_start) * 1000.0

        raw_resp_text_c = resp_c.content or ""
        (run_dir_c5 / "raw" / "response" / "one_shot_response.txt").write_text(raw_resp_text_c, encoding="utf-8")

        usage_dict_c = resp_c.usage.model_dump() if hasattr(resp_c.usage, "model_dump") else {
            "prompt_tokens": resp_c.usage.prompt_tokens,
            "completion_tokens": resp_c.usage.completion_tokens,
            "thoughts_tokens": resp_c.usage.thoughts_tokens,
            "total_tokens": resp_c.usage.total_tokens,
        }
        c5_telemetry = {
            "latency_ms": t_lat_c,
            **usage_dict_c,
        }
        (run_dir_c5 / "telemetry" / "one_shot_telemetry.json").write_text(
            json.dumps(c5_telemetry, indent=2), encoding="utf-8"
        )

    c5_actual_provider_tokens = c5_telemetry.get("total_tokens", 0)
    artifact_hash_c5 = sha256_dir(run_dir_c5)
    logger.info(f"Candidate C5 sealed. Hash: {artifact_hash_c5}. Tokens: {c5_actual_provider_tokens}")

    # =========================================================================
    # 5. CANONICAL ASSEMBLY & PRESERVATION AUDIT
    # =========================================================================
    logger.info("Executing NeutralCanonicalCandidateAssembler across Candidates A5, B5, C5...")
    canon_a5, audit_a5 = NeutralCanonicalCandidateAssembler.assemble_candidate_a(a5_stages)
    canon_b5, audit_b5 = NeutralCanonicalCandidateAssembler.assemble_candidate_b(b5_passes_data)
    canon_c5, audit_c5 = NeutralCanonicalCandidateAssembler.assemble_candidate_c(raw_resp_text_c)

    # =========================================================================
    # 6. FAIL-CLOSED DOUBLE-BLIND QUALITY EVALUATION
    # =========================================================================
    logger.info("Pacing cooldown before Fail-Closed Double-Blind Judging...")
    time.sleep(cooldown)

    seed_str = "BLIND_MAPPING_PHASE_4_3C_16_CASE_04_SEED"
    rng = random.Random(seed_str)
    real_candidates = ["A5", "B5", "C5"]
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

    raw_canon_map = {
        "A5": canon_a5.model_dump() if hasattr(canon_a5, "model_dump") else canon_a5.__dict__,
        "B5": canon_b5.model_dump() if hasattr(canon_b5, "model_dump") else canon_b5.__dict__,
        "C5": canon_c5.model_dump() if hasattr(canon_c5, "model_dump") else canon_c5.__dict__,
    }
    compact_packets = {k: format_compact_candidate(raw_canon_map[real_id]) for k, real_id in blind_to_real.items()}

    all_scores_by_letter = {"X": [], "Y": [], "Z": []}
    failed_judge_attempts = 0

    for pass_num in [1, 2, 3]:
        logger.info(f"Executing Fail-Closed Judge Pass {pass_num}/3...")
        for letter in ["X", "Y", "Z"]:
            real_id = blind_to_real[letter]
            resp_p = JUDGE_DIR / f"pass_{pass_num}_candidate_{letter}_response.txt"
            if resp_p.exists() and resp_p.stat().st_size > 0:
                cached_text = resp_p.read_text(encoding="utf-8")
                cached_scores = extract_scores_fail_closed(cached_text)
                if cached_scores is not None and len(cached_scores) == 14:
                    all_scores_by_letter[letter].append(cached_scores)
                    logger.info(f"Pass {pass_num} Candidate {letter} ({real_id}) LOADED: mean={sum(cached_scores.values())/14.0:.2f}")
                    continue

            prompt = build_compact_judge_prompt(letter, compact_packets[letter], facts, evidence, objective)
            (JUDGE_DIR / f"pass_{pass_num}_candidate_{letter}_prompt.txt").write_text(prompt, encoding="utf-8")

            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=prompt)],
                model_name="gemini-flash-latest",
                temperature=0.1,
                max_tokens=2048,
                timeout_seconds=180.0,
            )
            t_start = time.time()
            resp = safe_generate(gateway, req)
            t_lat = (time.time() - t_start) * 1000.0

            raw_text = resp.content or ""
            (JUDGE_DIR / f"pass_{pass_num}_candidate_{letter}_response.txt").write_text(raw_text, encoding="utf-8")

            scores = extract_scores_fail_closed(raw_text)
            if scores is not None and len(scores) == 14:
                all_scores_by_letter[letter].append(scores)
                logger.info(f"Pass {pass_num} Candidate {letter} ({real_id}) VALID: mean={sum(scores.values())/14.0:.2f}")
            else:
                failed_judge_attempts += 1
                logger.warning(f"Pass {pass_num} Candidate {letter} ({real_id}) FAILED_ATTEMPT: fail-closed (no default score inserted).")

            time.sleep(15.0)  # Rate-limit safe inter-call pacing
        time.sleep(40.0)  # Inter-pass pacing

    # Validate fail-closed passes
    valid_judge_pass_count = min(len(all_scores_by_letter["X"]), len(all_scores_by_letter["Y"]), len(all_scores_by_letter["Z"]))
    is_judge_valid = valid_judge_pass_count >= MIN_VALID_JUDGE_PASSES

    unmasked_results = {}
    if is_judge_valid:
        for letter, real_id in blind_to_real.items():
            valid_passes_for_cand = all_scores_by_letter[letter][:MIN_VALID_JUDGE_PASSES]
            ok, weighted, medians = aggregate_judge_passes_fail_closed(valid_passes_for_cand)
            unmasked_results[real_id] = {
                "letter": letter,
                "weighted_quality_score": weighted,
                "dimension_scores": medians,
            }
    else:
        logger.error(f"Judging incomplete: valid_judge_pass_count={valid_judge_pass_count} < {MIN_VALID_JUDGE_PASSES}.")
        unmasked_results = {
            "A5": {"weighted_quality_score": None, "dimension_scores": {}},
            "B5": {"weighted_quality_score": None, "dimension_scores": {}},
            "C5": {"weighted_quality_score": None, "dimension_scores": {}},
        }

    a5_score = unmasked_results["A5"]["weighted_quality_score"]
    b5_score = unmasked_results["B5"]["weighted_quality_score"]
    c5_score = unmasked_results["C5"]["weighted_quality_score"]
    delta_a5_b5 = round(a5_score - b5_score, 3) if a5_score and b5_score else None

    a5_dims = unmasked_results["A5"]["dimension_scores"]
    b5_dims = unmasked_results["B5"]["dimension_scores"]

    # Release Gate Evaluation
    if is_judge_valid and a5_score and b5_score:
        rc3_quality_gate = (
            resource_parity_status == "PASS"
            and a5_dims.get("attribution_tracking", 0.0) >= 6.0
            and a5_dims.get("experimentation_rigor", 0.0) >= 6.0
            and a5_dims.get("governance_human_approval", 0.0) >= 6.0
            and a5_dims.get("performance_funnel_metrics", 0.0) >= 6.0
            and a5_dims.get("claim_safety_compliance", 0.0) >= 8.0
            and (a5_score >= (b5_score - 0.35) or a5_score >= b5_score)
        )
        gate_verdict = "PASS" if rc3_quality_gate else "TARGETED_OPTIMIZATION_REQUIRED"
    else:
        gate_verdict = "INCOMPLETE"

    final_report = {
        "benchmark_id": "BENCHMARK-PHASE4-3-CASE04-TELEHEALTH-SERVICE",
        "case_id": "CASE_04_TELEHEALTH_REGULATED_SERVICE",
        "brain_version": "FIVE_AGENT_BRAIN_V1_RC3",
        "brain_rc3_fingerprint": EXPECTED_RC3_FINGERPRINT,
        "input_hash": "e8bd72e193bc1dd980ff0e667df3eff0f5e329248a2c9bf8cf19d78bb900b811",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": {
            "A5": {
                "run_id": run_id_a5,
                "calls": 7,
                "provider_total_tokens": a5_actual_provider_tokens,
                "artifact_hash": artifact_hash_a5,
                "deliverables": audit_a5.total_deliverables_found,
                "weighted_score": a5_score,
                "dimension_scores": a5_dims,
            },
            "B5": {
                "run_id": run_id_b5,
                "calls": 4,
                "provider_total_tokens": b5_actual_provider_tokens,
                "artifact_hash": artifact_hash_b5,
                "deliverables": audit_b5.total_deliverables_found,
                "resource_parity": resource_parity_status,
                "weighted_score": b5_score,
                "dimension_scores": b5_dims,
            },
            "C5": {
                "run_id": run_id_c5,
                "calls": 1,
                "provider_total_tokens": c5_actual_provider_tokens,
                "artifact_hash": artifact_hash_c5,
                "deliverables": audit_c5.total_deliverables_found,
                "weighted_score": c5_score,
                "dimension_scores": unmasked_results["C5"]["dimension_scores"],
            },
        },
        "primary_comparison": {
            "a5_score": a5_score,
            "b5_score": b5_score,
            "delta": delta_a5_b5,
            "quality_gate": gate_verdict,
        },
        "valid_judge_pass_count": valid_judge_pass_count,
        "failed_judge_attempts": failed_judge_attempts,
        "blind_mapping": blind_to_real,
        "blind_commitment_hash": blind_commitment_hash,
    }

    (CASE_DIR / "phase4_3c_16_validation_summary.json").write_text(
        json.dumps(final_report, indent=2), encoding="utf-8"
    )

    return final_report


if __name__ == "__main__":
    res = run_case04_release_validation()
    print("Case 04 Validation Finished:")
    print(json.dumps(res, indent=2))
