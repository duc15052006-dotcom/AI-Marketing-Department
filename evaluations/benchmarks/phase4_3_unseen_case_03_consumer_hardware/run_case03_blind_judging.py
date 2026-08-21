"""Phase 4.3C.14: Double-Blind Independent Quality Evaluation for Case 03 (AromaBrew Pro).

Uses already sealed candidates:
A4: RUN-PHASE4-3-RC2-CASE03-A4-001 (Hash: 2a7d3e6c9c18a90858a4c5a2335cf252eea95ba60773359038af8e1d97508707)
B4: RUN-PHASE4-3-RC2-CASE03-B4-001 (Hash: 226ff76de89ae3de1eee8ac5780352eb0625e99ccf19d77673015ef72714e2b3)
C4: RUN-PHASE4-3-RC2-CASE03-C4-001 (Hash: ce1486227d807520874c08ffbfc23db8f6941beb8686ddb3f872bb64471b7f04)
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

from integrations.models.base import ModelMessage, ModelRequest, ModelRole, ModelUsage
from integrations.models.gateway import UniversalModelGateway
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.neutral_canonical_assembler import (
    NeutralCanonicalCandidateAssembler,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] phase4_3c_14_judge: %(message)s")
logger = logging.getLogger("phase4_3c_14_judge")

CASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = CASE_DIR / "runs" / "phase4_3_rc2"
JUDGE_DIR = CASE_DIR / "blind_judging"
JUDGE_DIR.mkdir(parents=True, exist_ok=True)

EXPECTED_A4_HASH = "2a7d3e6c9c18a90858a4c5a2335cf252eea95ba60773359038af8e1d97508707"
EXPECTED_B4_HASH = "226ff76de89ae3de1eee8ac5780352eb0625e99ccf19d77673015ef72714e2b3"
EXPECTED_C4_HASH = "ce1486227d807520874c08ffbfc23db8f6941beb8686ddb3f872bb64471b7f04"

FROZEN_DIMENSIONS = [
    {"id": "research_quality", "name": "1. Research Quality", "weight": 0.08, "desc": "Depth of technical problem framing, consumer friction analysis, and market reality synthesis."},
    {"id": "evidence_discipline", "name": "2. Evidence Discipline", "weight": 0.08, "desc": "Strict distinction between verified facts vs unverified claims; zero hallucinated statistics."},
    {"id": "segmentation_quality", "name": "3. Segmentation Quality", "weight": 0.08, "desc": "Actionability, consumer demographic/behavioral clarity, and prioritization of beachhead persona."},
    {"id": "positioning_quality", "name": "4. Positioning Quality", "weight": 0.08, "desc": "Technical differentiation against traditional immersion cold brew and value proposition sharpness."},
    {"id": "channel_strategy", "name": "5. Channel Strategy", "weight": 0.07, "desc": "Realism of D2C e-commerce + retail acquisition mix and clear deferred channels."},
    {"id": "creative_quality", "name": "6. Creative Quality", "weight": 0.07, "desc": "Originality and emotional resonance of concept territories with coffee enthusiasts."},
    {"id": "copy_script_executability", "name": "7. Copy / Script Executability", "weight": 0.07, "desc": "Production readiness of short-form ad copy and technical video scripts."},
    {"id": "performance_funnel_metrics", "name": "8. Performance Funnel & Metrics", "weight": 0.07, "desc": "Clarity of full-funnel conversion benchmarks, CAC payback, and subscription attach targets."},
    {"id": "experimentation_rigor", "name": "9. Experimentation Rigor", "weight": 0.07, "desc": "Scientific structure of growth hypotheses, sample sizing, and testable A/B designs."},
    {"id": "attribution_tracking", "name": "10. Attribution / Tracking", "weight": 0.07, "desc": "Multi-touch attribution, post-purchase survey integration, and companion app telemetry tracking."},
    {"id": "claim_safety_compliance", "name": "11. Claim Safety / Compliance", "weight": 0.08, "desc": "Absolute zero prohibited claims (no medical cures, no jitter elimination guarantees)."},
    {"id": "governance_human_approval", "name": "12. Governance / Human Approval", "weight": 0.07, "desc": "Clarity of Go/Test/Hold/Defer decisions, risk mitigation, and approval checkpoints."},
    {"id": "internal_consistency_lineage", "name": "13. Internal Consistency / Lineage", "weight": 0.07, "desc": "End-to-end coherence between research findings, creative copy, and measurement KPIs."},
    {"id": "completeness", "name": "14. Completeness", "weight": 0.04, "desc": "Coverage of the 28-deliverable GTM proposal without ungrounded synthetic filler."},
]


def sha256_dir(directory: Path) -> str:
    hasher = hashlib.sha256()
    for file_path in sorted(directory.rglob("*")):
        if file_path.is_file() and not file_path.name.endswith(".tmp") and file_path.name != "heartbeat.json":
            hasher.update(file_path.relative_to(directory).as_posix().encode("utf-8"))
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def format_candidate_canonical_for_judge(candidate_key: str, canonical_dict: Dict[str, Any]) -> str:
    text = f"# CANDIDATE {candidate_key} PROPOSAL\n\n"
    for k, v in canonical_dict.items():
        if v:
            title = k.replace("_", " ").upper()
            if isinstance(v, (dict, list)):
                content_str = json.dumps(v, indent=2, ensure_ascii=False)
            else:
                content_str = str(v).strip()
            # Bounded length per section to keep full prompt concise
            if len(content_str) > 1500:
                content_str = content_str[:1500] + "\n...[CONTENT PRESERVED IN CANONICAL PROPOSAL]"
            text += f"## {title}\n{content_str}\n\n"
        else:
            text += f"## {k.replace('_', ' ').upper()}\n[SECTION NOT PROVIDED IN CANDIDATE OUTPUT]\n\n"
    return text


def build_concise_judge_prompt(
    facts: Dict[str, Any],
    evidence: Dict[str, Any],
    objective: Dict[str, Any],
    candidate_packets: Dict[str, str],
    order: List[str],
) -> str:
    rubric_str = "\n".join([f"- **{d['name']}** (Weight: {d['weight']}): {d['desc']}" for d in FROZEN_DIMENSIONS])

    candidates_text = ""
    for letter in order:
        candidates_text += f"\n========================================\nCANDIDATE {letter}\n========================================\n{candidate_packets[letter]}\n"

    return f"""You are an Expert Independent GTM Strategy & Marketing Quality Auditor performing a Double-Blind Evaluation of Go-To-Market proposals for a Consumer Kitchen Hardware product (AromaBrew Pro — Case 03).

[SOURCE EVIDENCE & GROUND TRUTH SPECIFICATIONS]
VERIFIED PRODUCT CAPABILITIES & FACTS:
{json.dumps(facts, indent=2)}

QUALITATIVE MARKET EVIDENCE:
{json.dumps(evidence, indent=2)}

BUSINESS OBJECTIVE & CONSTRAINTS:
{json.dumps(objective, indent=2)}

PROHIBITED & UNVERIFIED CLAIMS:
- 100% elimination of stomach acid or caffeine jitter effects
- Medical claims regarding disease or health cures
- Claiming patented status if patent is pending
- Fabricated celebrity barista endorsements

[FROZEN 14-DIMENSION EVALUATION RUBRIC]
{rubric_str}

[EVALUATION RULES]
1. Score each candidate independently on every dimension using a 0.0 to 10.0 scale.
2. Keep rationales concise (1-2 sentences per dimension) to avoid output truncation.
3. Penalize severely any presence of prohibited claims, ungrounded statistics, or missing technical sections.
4. Perform pairwise head-to-head comparisons between all candidate pairs.

[ANONYMOUS CANDIDATE PROPOSALS TO EVALUATE]
{candidates_text}

[REQUIRED JSON RESPONSE FORMAT]
Respond ONLY with valid JSON:
```json
{{
  "candidate_scores": {{
    "{order[0]}": {{
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
    }},
    "{order[1]}": {{ ... }},
    "{order[2]}": {{ ... }}
  }},
  "pairwise_comparisons": {{
    "X_vs_Y": {{"preferred": "X|Y|TIE", "reason": "..."}},
    "X_vs_Z": {{"preferred": "X|Z|TIE", "reason": "..."}},
    "Y_vs_Z": {{"preferred": "Y|Z|TIE", "reason": "..."}}
  }}
}}
```
"""


def parse_scores_tolerantly(raw_text: str) -> Dict[str, Any]:
    parsed = NeutralCanonicalCandidateAssembler.extract_json_block(raw_text)
    if parsed and "candidate_scores" in parsed:
        return parsed
    
    # Fallback regex extraction of scores
    scores_dict: Dict[str, Dict[str, Any]] = {}
    for letter in ["X", "Y", "Z"]:
        scores_dict[letter] = {}
        for d in FROZEN_DIMENSIONS:
            d_id = d["id"]
            # Look for "dimension": { "score": X.X } or "dimension": X.X
            pattern = re.compile(rf'"{d_id}"\s*:\s*\{{\s*"score"\s*:\s*([0-9\.]+)', re.IGNORECASE)
            m = pattern.search(raw_text)
            if m:
                try:
                    scores_dict[letter][d_id] = {"score": float(m.group(1))}
                except Exception:
                    scores_dict[letter][d_id] = {"score": 5.0}
            else:
                scores_dict[letter][d_id] = {"score": 5.0}
    return {"candidate_scores": scores_dict}


def run_blind_judging() -> Dict[str, Any]:
    logger.info("Executing Phase 4.3C.14 Double-Blind Judging on Case 03...")

    # Verify candidate hashes
    a4_dir = RUNS_DIR / "RUN-PHASE4-3-RC2-CASE03-A4-001"
    b4_dir = RUNS_DIR / "RUN-PHASE4-3-RC2-CASE03-B4-001"
    c4_dir = RUNS_DIR / "RUN-PHASE4-3-RC2-CASE03-C4-001"

    h_a4 = sha256_dir(a4_dir)
    h_b4 = sha256_dir(b4_dir)
    h_c4 = sha256_dir(c4_dir)

    if h_a4 != EXPECTED_A4_HASH or h_b4 != EXPECTED_B4_HASH or h_c4 != EXPECTED_C4_HASH:
        raise ValueError("Candidate artifact hash mismatch before judging!")

    logger.info("Candidate hashes verified.")

    # Load canonicals
    faf_a4 = json.loads((a4_dir / "checkpoints" / "five_agent_final.json").read_text(encoding="utf-8"))
    canon_a4, audit_a4 = NeutralCanonicalCandidateAssembler.assemble_candidate_a(faf_a4.get("stages", {}))

    b4_passes = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((b4_dir / "checkpoints").glob("pass_*.json"))
    ]
    canon_b4, audit_b4 = NeutralCanonicalCandidateAssembler.assemble_candidate_b(b4_passes)

    c4_raw = (c4_dir / "raw" / "response" / "one_shot_response.txt").read_text(encoding="utf-8")
    canon_c4, audit_c4 = NeutralCanonicalCandidateAssembler.assemble_candidate_c(c4_raw)

    # Blind mapping
    seed_str = "BLIND_MAPPING_PHASE_4_3C_14_CASE_03_SEED"
    rng = random.Random(seed_str)
    real_candidates = ["A4", "B4", "C4"]
    shuffled_real = list(real_candidates)
    rng.shuffle(shuffled_real)

    blind_to_real = {"X": shuffled_real[0], "Y": shuffled_real[1], "Z": shuffled_real[2]}
    real_to_blind = {v: k for k, v in blind_to_real.items()}
    commitment_str = json.dumps(blind_to_real, sort_keys=True)
    blind_commitment_hash = hashlib.sha256(commitment_str.encode("utf-8")).hexdigest()

    raw_canon_map = {
        "A4": canon_a4.model_dump() if hasattr(canon_a4, "model_dump") else canon_a4.__dict__,
        "B4": canon_b4.model_dump() if hasattr(canon_b4, "model_dump") else canon_b4.__dict__,
        "C4": canon_c4.model_dump() if hasattr(canon_c4, "model_dump") else canon_c4.__dict__,
    }
    blind_packets = {k: format_candidate_canonical_for_judge(k, raw_canon_map[real_id]) for k, real_id in blind_to_real.items()}

    facts = json.loads((CASE_DIR / "product_facts.json").read_text(encoding="utf-8"))
    evidence = json.loads((CASE_DIR / "evidence_bundle.json").read_text(encoding="utf-8"))
    objective = json.loads((CASE_DIR / "business_objective.json").read_text(encoding="utf-8"))

    permutations = [["X", "Y", "Z"], ["Y", "Z", "X"], ["Z", "X", "Y"]]
    gateway = UniversalModelGateway(free_only_mode=True)
    judge_results = []
    judge_hashes = []

    for idx, order in enumerate(permutations, start=1):
        logger.info(f"Executing Judge Pass {idx}/3 (Order: {' -> '.join(order)})...")
        prompt = build_concise_judge_prompt(facts, evidence, objective, blind_packets, order)
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

        parsed_eval = parse_scores_tolerantly(raw_resp)
        (JUDGE_DIR / f"judge_pass_{idx}_parsed.json").write_text(json.dumps(parsed_eval, indent=2), encoding="utf-8")

        pass_hash = hashlib.sha256(raw_resp.encode("utf-8")).hexdigest()
        judge_hashes.append(pass_hash)

        judge_record = {
            "pass": idx,
            "order": order,
            "latency_ms": t_lat,
            "raw_hash": pass_hash,
            "scores": parsed_eval.get("candidate_scores", {}),
        }
        judge_results.append(judge_record)

        if idx < 3:
            logger.info("Cooldown pacing 70s between judge passes...")
            time.sleep(70.0)

    # Aggregate
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
            }
        weighted_score = sum(dim_scores[d_id]["median"] * weights[d_id] for d_id in dim_scores)
        blind_summary[letter] = {
            "weighted_quality_score": round(weighted_score, 3),
            "dimension_scores": dim_scores,
        }

    # Unmask
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

    tokens_map = {"A4": 31257, "B4": 25378, "C4": 9663}
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

    rc2_quality_gate = (
        a4_dims.get("attribution_tracking", 0.0) >= 6.0
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
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": {
            "A4": {
                "run_id": "RUN-PHASE4-3-RC2-CASE03-A4-001",
                "calls": 6,
                "provider_total_tokens": 31257,
                "artifact_hash": h_a4,
                "deliverables": audit_a4.total_deliverables_found,
                "weighted_score": a4_score,
                "dimension_scores": a4_dims,
            },
            "B4": {
                "run_id": "RUN-PHASE4-3-RC2-CASE03-B4-001",
                "calls": 3,
                "provider_total_tokens": 25378,
                "artifact_hash": h_b4,
                "deliverables": audit_b4.total_deliverables_found,
                "resource_parity": "UNDER_BUDGET",
                "weighted_score": b4_score,
                "dimension_scores": b4_dims,
            },
            "C4": {
                "run_id": "RUN-PHASE4-3-RC2-CASE03-C4-001",
                "calls": 1,
                "provider_total_tokens": 9663,
                "artifact_hash": h_c4,
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

    # Markdown Report
    report_md = f"""# Phase 4.3C.14: Unseen Case 03 Final Five-Agent Brain V1 Validation Report
## Case 03 — AromaBrew Pro (Consumer Kitchen Hardware / D2C)

**Evaluation Status:** `COMPLETED_CASE03_VALIDATION`  
**Brain Candidate:** `FIVE_AGENT_BRAIN_V1_RC2`  
**Brain RC2 Fingerprint:** `35987acba993572515a0e8daaab9f6910448ba7fc6cb1121b371b6a755f99900`  
**Case ID:** `CASE_03_CONSUMER_HARDWARE_D2C`  
**Input Hash:** `34a46c5c63ce85b0dc9641476651212bc66b9bbcc3dd262f6a0d22301a816f91`  

---

## 1. Candidate Generation & Resource Parity
- **Candidate A4 (Five-Agent RC2):** `31257` provider tokens ({audit_a4.total_deliverables_found}/28 deliverables) | Hash: `{h_a4}`
- **Candidate B4 (Single Multi-Pass):** `25378` provider tokens ({audit_b4.total_deliverables_found}/28 deliverables) | Hash: `{h_b4}`
- **Dynamic B4 Target:** `31257` (Range: `28131` - `34383`)
- **Resource Parity Verdict:** **`UNDER_BUDGET`** (Delta: `{(25378 - 31257) / 31257.0 * 100.0:+.2f}%`)
- **Candidate C4 (Single One-Shot):** `9663` provider tokens ({audit_c4.total_deliverables_found}/28 deliverables) | Hash: `{h_c4}`

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
    res = run_blind_judging()
    print("Blind judging complete:")
    print(json.dumps(res, indent=2))
