"""Phase 4.3C.6: Blind Review Packet Assembler and Leak Auditor.

Normalizes both candidate proposals into CanonicalProposal contracts,
enforces the 7-category Completeness Gate, randomizes system assignment (SYSTEM_A vs SYSTEM_B),
and writes an isolated blind identity key and clean blind review packet.

Zero identity leaks. Zero content patching.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from schemas.canonical import (
    CanonicalProposal,
    CandidateNormalizer,
    audit_canonical_completeness,
)

logger = logging.getLogger("assemble_blind_packet")

COMPLETENESS_INPUT_CONTRACT = "CANONICAL_PROPOSAL"


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Helper to parse clean JSON or markdown-wrapped JSON from raw text using CandidateNormalizer."""
    parsed, _ = CandidateNormalizer.extract_json_object(text)
    if parsed and isinstance(parsed, dict):
        return CandidateNormalizer.unwrap_root_wrapper(parsed)
    return {}


def build_single_blind_proposal(single_file: Path, run_fingerprint: Optional[str] = None) -> Dict[str, Any]:
    """Normalize Single-Model Baseline candidate into canonical deliverable structure."""
    if not single_file.exists():
        return {}

    try:
        single_data = json.loads(single_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    # If run fingerprint is specified, verify ownership
    if run_fingerprint and single_data.get("run_fingerprint") != run_fingerprint:
        logger.warning(f"Single candidate run fingerprint mismatch. Expected {run_fingerprint}, got {single_data.get('run_fingerprint')}")
        return {}

    if single_data.get("canonical_proposal"):
        return single_data["canonical_proposal"]

    # Fallback to parsed_output or raw_text extraction
    parsed = single_data.get("parsed_output")
    if parsed and isinstance(parsed, dict) and parsed != {"raw": ""}:
        unwrapped = CandidateNormalizer.unwrap_root_wrapper(parsed)
        return CandidateNormalizer.canonicalize_keys(unwrapped)

    raw_text = single_data.get("raw_text", "")
    norm_res = CandidateNormalizer.normalize_candidate(
        raw_text=raw_text,
        condition_id="SINGLE_MODEL_BASELINE",
        run_fingerprint=run_fingerprint or single_data.get("run_fingerprint", ""),
    )

    if norm_res.status == "SUCCESS" and norm_res.canonical_proposal:
        return norm_res.canonical_proposal.model_dump()

    return {}


def build_five_agent_blind_proposal(chk_dir: Path, five_agent_file: Path, run_fingerprint: Optional[str] = None) -> Dict[str, Any]:
    """Assemble complete Five-Agent candidate proposal across specialist stage outputs or Final CMO."""
    if not five_agent_file.exists():
        return {}

    try:
        five_data = json.loads(five_agent_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    # If run fingerprint is specified, verify ownership
    if run_fingerprint and five_data.get("run_fingerprint") != run_fingerprint:
        logger.warning(f"Five-Agent candidate run fingerprint mismatch. Expected {run_fingerprint}, got {five_data.get('run_fingerprint')}")
        return {}

    # 1. Check for canonical_proposal in five_agent_final
    if five_data.get("canonical_proposal"):
        return five_data["canonical_proposal"]

    # 2. Check Stage 6 Final CMO output
    stages = five_data.get("stages", {})
    cmo_final_data = stages.get("final_cmo")
    if not cmo_final_data:
        stage_6_file = chk_dir / "five_agent_stage_6_final_cmo.json"
        if stage_6_file.exists():
            try:
                cmo_final_data = json.loads(stage_6_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    if cmo_final_data and isinstance(cmo_final_data, dict):
        raw_text = cmo_final_data.get("raw_text", "")
        norm_res = CandidateNormalizer.normalize_candidate(
            raw_text=raw_text,
            condition_id="FIVE_AGENT_GOVERNED",
            run_fingerprint=run_fingerprint or five_data.get("run_fingerprint", ""),
        )
        if norm_res.status == "SUCCESS" and norm_res.canonical_proposal:
            is_comp, _ = audit_canonical_completeness(norm_res.canonical_proposal)
            if is_comp:
                return norm_res.canonical_proposal.model_dump()

    # 3. Assemble composite across individual stages if present
    def get_stage_dict(stage_key: str, filename: str) -> Dict[str, Any]:
        stage_obj = stages.get(stage_key, {})
        raw = stage_obj.get("raw_text", "") if isinstance(stage_obj, dict) else ""
        if not raw:
            fpath = chk_dir / filename
            if fpath.exists():
                try:
                    f_data = json.loads(fpath.read_text(encoding="utf-8"))
                    raw = f_data.get("raw_text", "")
                except Exception:
                    pass
        parsed, _ = CandidateNormalizer.extract_json_object(raw)
        if parsed and isinstance(parsed, dict):
            return CandidateNormalizer.unwrap_root_wrapper(parsed)
        return {}

    cmo_init = get_stage_dict("cmo_initial", "five_agent_stage_1_cmo.json")
    intel = get_stage_dict("intelligence", "five_agent_stage_2_intel.json")
    strat = get_stage_dict("strategist", "five_agent_stage_3_strat.json")
    crtv = get_stage_dict("creative", "five_agent_stage_4_crtv.json")
    perf = get_stage_dict("performance", "five_agent_stage_5_perf.json")
    cmo_fin = get_stage_dict("final_cmo", "five_agent_stage_6_final_cmo.json")

    combined: Dict[str, Any] = {}
    for d in (cmo_init, intel, strat, crtv, perf, cmo_fin):
        if isinstance(d, dict):
            combined.update(d)

    if combined:
        return CandidateNormalizer.canonicalize_keys(combined)

    return {}


def audit_proposal_completeness(proposal: Dict[str, Any]) -> Tuple[bool, Dict[str, bool]]:
    """Audit candidate proposal across the 7 mandatory categories using canonical completeness."""
    return audit_canonical_completeness(proposal)


def audit_identity_leaks(text: str) -> int:
    """Scan text for prohibited identity leaks, provider tokens, model names, or system tags."""
    leak_patterns = [
        r"\bSingle Model\b",
        r"\bSingle-Model\b",
        r"\bGoverned Five-Agent\b",
        r"\bFive-Agent\b",
        r"\bgemini-flash-latest\b",
        r"\bmistralai/mistral-large-2512\b",
        r"\bxkiro\b",
        r"\bprompt_tokens\b",
        r"\bcompletion_tokens\b",
        r"\btotal_tokens\b",
        r"\bGovernedExecutionPipeline\b",
        r"\bClaimRegister\b",
        r"\bSYSTEM_A is\b",
        r"\bSYSTEM_B is\b",
    ]
    leaks = 0
    for pat in leak_patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        leaks += len(matches)
    return leaks


def format_markdown_proposal(system_label: str, proposal: Dict[str, Any]) -> str:
    """Format canonical proposal into standardized, neutral markdown presentation."""
    md = [f"# CANDIDATE PROPOSAL: {system_label}\n"]

    for section_key, section_val in proposal.items():
        # Skip internal metadata fields
        if section_key.startswith("_") or section_key in (
            "benchmark_id", "run_id", "run_fingerprint", "condition_id",
            "source_raw_hash", "canonical_hash", "provider_requested",
            "provider_resolved", "model_requested", "model_resolved",
            "execution_generation", "candidate_schema_version",
            "content_patch_count", "semantic_rewrite_count", "created_at",
        ):
            continue

        title = section_key.upper()
        md.append(f"## {title}\n")
        if isinstance(section_val, dict):
            for sub_k, sub_v in section_val.items():
                sub_title = sub_k.replace("_", " ").title()
                if isinstance(sub_v, list):
                    md.append(f"### {sub_title}")
                    for item in sub_v:
                        md.append(f"- {json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item}")
                    md.append("")
                else:
                    md.append(f"**{sub_title}**: {sub_v}\n")
        elif isinstance(section_val, list):
            for item in section_val:
                if isinstance(item, dict):
                    item_title = item.get("name") or item.get("id") or item.get("territory_name") or item.get("segment_name") or "Item"
                    md.append(f"### {item_title}")
                    for ik, iv in item.items():
                        md.append(f"- **{ik}**: {iv}")
                    md.append("")
                else:
                    md.append(f"- {item}")
            md.append("")
        else:
            md.append(f"{section_val}\n")

    return "\n".join(md)


def assemble_blind_packet(
    benchmark_dir: Optional[Path] = None,
    run_dir: Optional[Path] = None,
    run_fingerprint: Optional[str] = None,
    seed: int = 42,
) -> Tuple[Path, Path]:
    """Assemble randomized, leak-free, validated blind review packet from CanonicalProposals."""
    bench_dir = benchmark_dir or Path(__file__).resolve().parent
    active_run_dir = run_dir

    if active_run_dir is None:
        # Check if there is a versioned run directory under runs/phase4_3_v2/
        v2_runs_dir = bench_dir / "runs" / "phase4_3_v2"
        if v2_runs_dir.exists():
            v2_subdirs = [p for p in v2_runs_dir.iterdir() if p.is_dir()]
            if v2_subdirs:
                v2_subdirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                active_run_dir = v2_subdirs[0]

    if active_run_dir is None:
        active_run_dir = bench_dir

    chk_dir = active_run_dir / "checkpoints"
    if not chk_dir.exists():
        chk_dir = bench_dir / "checkpoints"

    single_file = chk_dir / "single_output.json"
    five_agent_file = chk_dir / "five_agent_final.json"

    # Build canonical proposals
    single_prop = build_single_blind_proposal(single_file, run_fingerprint=run_fingerprint)
    five_prop = build_five_agent_blind_proposal(chk_dir, five_agent_file, run_fingerprint=run_fingerprint)

    # Validate Completeness Gate
    single_valid, single_audit = audit_proposal_completeness(single_prop)
    five_valid, five_audit = audit_proposal_completeness(five_prop)

    if not single_valid or not five_valid:
        logger.error(
            f"Completeness Gate Failed. Single Valid: {single_valid} ({single_audit}), Five-Agent Valid: {five_valid} ({five_audit})"
        )
        raise ValueError(
            f"Cannot assemble blind packet: One or both candidates failed completeness gate. Single: {single_valid}, Five: {five_valid}"
        )

    # Randomize assignment
    rng = random.Random(seed)
    mapping = ["SINGLE_MODEL", "FIVE_AGENT"]
    rng.shuffle(mapping)

    system_a_identity = mapping[0]
    system_b_identity = mapping[1]

    system_a_prop = single_prop if system_a_identity == "SINGLE_MODEL" else five_prop
    system_b_prop = five_prop if system_b_identity == "FIVE_AGENT" else single_prop

    # Format proposals
    packet_md = [
        "# Phase 4.3 Double-Blind Review Packet",
        f"**Generated**: {datetime.now(timezone.utc).isoformat()}",
        f"**Randomization Seed**: {seed}\n",
        "## Evaluation Instructions",
        "Review both Candidate Proposals (SYSTEM_A and SYSTEM_B) strictly on their strategic merit, evidence discipline, and creative viability.",
        "---\n",
        format_markdown_proposal("SYSTEM_A", system_a_prop),
        "\n---\n",
        format_markdown_proposal("SYSTEM_B", system_b_prop),
    ]
    full_packet_text = "\n".join(packet_md)

    # Leak Audit
    leaks = audit_identity_leaks(full_packet_text)
    if leaks > 0:
        raise ValueError(f"CRITICAL: Identity leak auditor detected {leaks} leaks in blind packet.")

    # Write artifacts
    key_path = bench_dir / "blind_identity_key.json"
    packet_path = bench_dir / "blind_review_packet.md"

    identity_key_data = {
        "benchmark_id": "PHASE4_3_UNSEEN_AI_ENGLISH_APP",
        "randomization_seed": seed,
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "run_fingerprint": run_fingerprint or "",
        "SYSTEM_A": system_a_identity,
        "SYSTEM_B": system_b_identity,
        "assignments": {
            "SYSTEM_A": system_a_identity,
            "SYSTEM_B": system_b_identity,
        },
        "leak_check": "PASS (0 leaks detected)",
    }

    key_path.write_text(json.dumps(identity_key_data, indent=2), encoding="utf-8")
    packet_path.write_text(full_packet_text, encoding="utf-8")

    logger.info(f"Blind packet assembled successfully at {packet_path}")
    logger.info(f"Blind identity key saved at {key_path}")

    return key_path, packet_path


def assemble_three_way_blind_packet(
    candidate_a_prop: Dict[str, Any],
    candidate_b_prop: Dict[str, Any],
    candidate_c_prop: Dict[str, Any],
    bench_dir: Path,
    seed: int = 42,
    run_fingerprint: Optional[str] = None,
) -> Tuple[Path, Path]:
    """Assemble a 3-way double-blind review packet (Candidate X, Candidate Y, Candidate Z)."""
    # Randomize 3-way assignment
    rng = random.Random(seed)
    candidates = [
        ("CANDIDATE_A_FIVE_AGENT", candidate_a_prop),
        ("CANDIDATE_B_SINGLE_MULTI_PASS", candidate_b_prop),
        ("CANDIDATE_C_SINGLE_ONE_SHOT", candidate_c_prop),
    ]
    rng.shuffle(candidates)

    labels = ["Candidate X", "Candidate Y", "Candidate Z"]
    assignments = {}
    packet_sections = [
        "# Phase 4.3 Three-Way Double-Blind Review Packet",
        f"**Generated**: {datetime.now(timezone.utc).isoformat()}",
        f"**Randomization Seed**: {seed}\n",
        "## Evaluation Instructions",
        "Review all three Candidate Proposals (Candidate X, Candidate Y, and Candidate Z) across the 14 evaluation dimensions.",
        "Assess strategic merit, evidence discipline, and creative executability without architectural bias.",
        "---\n",
    ]

    for label, (cand_id, prop) in zip(labels, candidates):
        assignments[label] = cand_id
        packet_sections.append(format_markdown_proposal(label, prop))
        packet_sections.append("\n---\n")

    full_packet_text = "\n".join(packet_sections)

    # Leak Audit
    leaks = audit_identity_leaks(full_packet_text)
    if leaks > 0:
        raise ValueError(f"CRITICAL: Identity leak auditor detected {leaks} leaks in 3-way blind packet.")

    key_path = bench_dir / "blind_three_way_identity_key.json"
    packet_path = bench_dir / "blind_three_way_review_packet.md"

    identity_key_data = {
        "benchmark_id": "PHASE4_3_UNSEEN_AI_ENGLISH_APP_THREE_WAY",
        "randomization_seed": seed,
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "run_fingerprint": run_fingerprint or "",
        "assignments": assignments,
        "leak_check": f"PASS (0 leaks detected, count={leaks})",
    }

    key_path.write_text(json.dumps(identity_key_data, indent=2), encoding="utf-8")
    packet_path.write_text(full_packet_text, encoding="utf-8")

    logger.info(f"3-Way Blind packet assembled successfully at {packet_path}")
    logger.info(f"3-Way Blind identity key saved at {key_path}")

    return key_path, packet_path

