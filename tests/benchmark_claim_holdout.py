"""CLAIM-BENCH-02: Independent Holdout Benchmark Runner.

Evaluates NLI models on a frozen holdout set with:
- Frozen thresholds from calibration (tau_ent=0.90, tau_con=0.70)
- Deterministic governance guards (numeric, currency, entity, temporal, unit, scope)
- Compound vs atomic claim decomposition
- Multi-source strategies (individual, concatenated, atomic+individual)
- Backend comparison (PyTorch CPU, ONNX CPU, quantized ONNX)
- Smaller model comparison
- Latency profiling for 1/5/10 sequential and batched claims

Does NOT modify any production code.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import psutil

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOLDOUT_MATRIX_PATH = Path("tests/data/claim_verification_holdout_matrix.json")

PRIMARY_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
SMALLER_MODEL = "symanto/xlm-roberta-base-snli-mnli-anli-xnli"

TAU_ENTAILMENT = 0.90
TAU_CONTRADICTION = 0.70

RESULTS_DIR = Path("tests/data")

# ---------------------------------------------------------------------------
# Deterministic Guards (pure, reusable validators)
# ---------------------------------------------------------------------------

def _extract_numbers(text: str) -> List[float]:
    """Extract all numeric values from text, handling commas and decimals."""
    pattern = r'(?<!\w)(\d{1,3}(?:[,\.]\d{3})*(?:[,\.]\d+)?|\d+(?:[,\.]\d+)?)(?!\w)'
    matches = re.findall(pattern, text)
    results = []
    for m in matches:
        cleaned = m.replace(',', '')
        try:
            results.append(float(cleaned))
        except ValueError:
            pass
    return results


def _extract_currencies(text: str) -> List[str]:
    """Extract currency indicators."""
    currencies = []
    patterns = [
        (r'\$\s*[\d,\.]+', 'USD'),
        (r'[\d,\.]+\s*(?:USD|usd)', 'USD'),
        (r'[\d,\.]+\s*(?:VND|vnd|đ|đồng|dong)', 'VND'),
        (r'[\d,\.]+\s*(?:EUR|eur|€)', 'EUR'),
        (r'[\d,\.]+\s*(?:GBP|gbp|£)', 'GBP'),
        (r'[\d,\.]+\s*(?:triệu|trieu|tỷ|ty)\b', 'VND_UNIT'),
    ]
    for pat, cur in patterns:
        if re.search(pat, text, re.IGNORECASE):
            currencies.append(cur)
    return currencies


def _extract_units(text: str) -> List[str]:
    """Extract measurement units."""
    unit_patterns = [
        r'\b(\d+)\s*(mAh|Wh|kWh|kW|MW|W|V|A)\b',
        r'\b(\d+)\s*(kg|g|mg|lb|oz)\b',
        r'\b(\d+)\s*(km|m|cm|mm|miles?|ft|inch(?:es)?)\b',
        r'\b(\d+)\s*(giờ|phút|giây|hours?|mins?|minutes?|seconds?|s|hrs?)\b',
        r'\b(\d+)\s*(lít|ml|L|gallon|oz)\b',
        r'\b(\d+)\s*(GB|MB|TB|KB)\b',
        r'\b(\d+)\s*(Gbps|Mbps|Kbps)\b',
        r'\b(\d+)\s*(năm|tháng|ngày|years?|months?|days?|weeks?)\b',
    ]
    units = []
    for pat in unit_patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            units.append((match.group(1), match.group(2).lower()))
    return units


def _extract_years(text: str) -> List[int]:
    """Extract 4-digit years."""
    return [int(m) for m in re.findall(r'\b(19\d{2}|20\d{2})\b', text)]


def guard_numeric_mismatch(claim: str, evidence: str) -> Optional[str]:
    """Check if claim and evidence have conflicting numbers for same context."""
    claim_nums = _extract_numbers(claim)
    evidence_nums = _extract_numbers(evidence)
    if not claim_nums or not evidence_nums:
        return None
    # Only flag if claim contains a number NOT found in evidence
    # and the claim has specific quantitative assertions
    for cn in claim_nums:
        if cn not in evidence_nums and cn > 0:
            # Check if evidence has a number in similar magnitude (potential conflict)
            for en in evidence_nums:
                if en > 0 and abs(cn - en) / max(cn, en) > 0.05:
                    # Numbers differ significantly - potential mismatch
                    if cn > en * 1.3 or cn < en * 0.7:
                        return f"NUMERIC_MISMATCH: claim={cn} vs evidence={en}"
    return None


def guard_currency_mismatch(claim: str, evidence: str) -> Optional[str]:
    """Check for currency unit mismatches."""
    claim_cur = set(_extract_currencies(claim))
    evidence_cur = set(_extract_currencies(evidence))
    if claim_cur and evidence_cur and not claim_cur.intersection(evidence_cur):
        return f"CURRENCY_MISMATCH: claim={claim_cur} vs evidence={evidence_cur}"
    return None


def guard_temporal_mismatch(claim: str, evidence: str) -> Optional[str]:
    """Check for year/temporal mismatches."""
    claim_years = _extract_years(claim)
    evidence_years = _extract_years(evidence)
    if claim_years and evidence_years:
        for cy in claim_years:
            if cy not in evidence_years:
                for ey in evidence_years:
                    if abs(cy - ey) >= 1:
                        return f"TEMPORAL_MISMATCH: claim_year={cy} vs evidence_year={ey}"
    return None


def guard_entity_sku_mismatch(claim: str, evidence: str) -> Optional[str]:
    """Check if claim references a different product/SKU/entity than evidence."""
    # Extract model numbers / SKU patterns
    sku_pat = r'\b([A-Z]{2,}[-\s]?\d{2,}[A-Z]?\d*)\b'
    claim_skus = set(re.findall(sku_pat, claim))
    evidence_skus = set(re.findall(sku_pat, evidence))
    if claim_skus and evidence_skus and not claim_skus.intersection(evidence_skus):
        return f"ENTITY_SKU_MISMATCH: claim_SKUs={claim_skus} vs evidence_SKUs={evidence_skus}"
    return None


def guard_scope_mismatch(claim: str, evidence: str) -> Optional[str]:
    """Check if evidence scope doesn't cover claim scope."""
    scope_indicators = [
        (r'\b(toàn cầu|worldwide|global)\b', 'global'),
        (r'\b(Việt Nam|Vietnam)\b', 'vietnam'),
        (r'\b(châu Á|Asia|Asian)\b', 'asia'),
        (r'\b(châu Âu|Europe|European)\b', 'europe'),
        (r'\b(Bắc Mỹ|North America)\b', 'north_america'),
    ]
    claim_scope = set()
    evidence_scope = set()
    for pat, label in scope_indicators:
        if re.search(pat, claim, re.IGNORECASE):
            claim_scope.add(label)
        if re.search(pat, evidence, re.IGNORECASE):
            evidence_scope.add(label)
    if claim_scope and evidence_scope and not claim_scope.intersection(evidence_scope):
        if 'global' not in evidence_scope:
            return f"SCOPE_MISMATCH: claim={claim_scope} vs evidence={evidence_scope}"
    return None


def guard_execution_state(evidence: str) -> Optional[str]:
    """Check for non-live execution states in evidence."""
    state_patterns = [
        (r'\bMOCK\b', 'MOCK'),
        (r'\bSANDBOX\b', 'SANDBOX'),
        (r'\bERROR\b', 'ERROR'),
        (r'\bTIMEOUT\b', 'TIMEOUT'),
        (r'\bBLOCKED\b', 'BLOCKED'),
    ]
    for pat, label in state_patterns:
        if re.search(pat, evidence):
            return f"EXECUTION_STATE_{label}"
    return None


def run_all_deterministic_guards(claim: str, evidence: str) -> Optional[str]:
    """Run all deterministic guards. Returns first failure or None."""
    guards = [
        guard_execution_state,
        lambda c, e: guard_entity_sku_mismatch(c, e),
        lambda c, e: guard_currency_mismatch(c, e),
        lambda c, e: guard_numeric_mismatch(c, e),
        lambda c, e: guard_temporal_mismatch(c, e),
        lambda c, e: guard_scope_mismatch(c, e),
    ]
    # execution_state only takes evidence
    result = guard_execution_state(evidence)
    if result:
        return result
    for g in guards[1:]:
        result = g(claim, evidence)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# NLI Inference Helpers
# ---------------------------------------------------------------------------

def run_nli_inference(model, tokenizer, premise: str, hypothesis: str,
                      entail_idx: int, neutral_idx: int, contra_idx: int,
                      device: str = "cpu") -> Dict[str, Any]:
    """Run single NLI inference and return probabilities + latency."""
    import torch
    t0 = time.perf_counter()
    inputs = tokenizer(premise, hypothesis, truncation=True, max_length=512,
                       return_tensors="pt")
    if device != "cpu":
        inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits[0]
        probs = torch.softmax(logits, dim=-1).cpu().numpy()
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "p_entailment": float(probs[entail_idx]),
        "p_neutral": float(probs[neutral_idx]),
        "p_contradiction": float(probs[contra_idx]),
        "latency_ms": latency_ms,
    }


def run_nli_inference_onnx(session, tokenizer, premise: str, hypothesis: str,
                            label_order: List[str]) -> Dict[str, Any]:
    """Run single NLI inference using ONNX Runtime."""
    t0 = time.perf_counter()
    inputs = tokenizer(premise, hypothesis, truncation=True, max_length=512,
                       return_tensors="np")
    input_feed = {k: v for k, v in inputs.items()
                  if k in [i.name for i in session.get_inputs()]}
    outputs = session.run(None, input_feed)
    logits = outputs[0][0]
    # softmax
    exp_logits = np.exp(logits - np.max(logits))
    probs = exp_logits / exp_logits.sum()
    latency_ms = (time.perf_counter() - t0) * 1000.0

    result = {"latency_ms": latency_ms}
    for i, label in enumerate(label_order):
        result[f"p_{label}"] = float(probs[i])
    return result


def apply_threshold(p_ent: float, p_con: float,
                    tau_ent: float = TAU_ENTAILMENT,
                    tau_con: float = TAU_CONTRADICTION) -> str:
    """Apply frozen thresholds. Returns SUPPORTED/CONTRADICTED/INCONCLUSIVE."""
    if p_ent >= tau_ent:
        return "SUPPORTED"
    if p_con >= tau_con:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def compute_governance_decision(claim: str, evidence: str,
                                 nli_result: Dict[str, Any]) -> Dict[str, Any]:
    """Compute final governance decision: deterministic guard + NLI threshold."""
    guard_result = run_all_deterministic_guards(claim, evidence)
    if guard_result:
        return {
            "decision": "BLOCKED_BY_GUARD",
            "guard": guard_result,
            "nli_threshold_decision": apply_threshold(
                nli_result["p_entailment"], nli_result["p_contradiction"]),
        }

    threshold_decision = apply_threshold(
        nli_result["p_entailment"], nli_result["p_contradiction"])
    return {
        "decision": threshold_decision,
        "guard": None,
        "nli_threshold_decision": threshold_decision,
    }


# ---------------------------------------------------------------------------
# Backend: ONNX Export Helpers
# ---------------------------------------------------------------------------

def try_export_onnx(model, tokenizer, export_path: str) -> bool:
    """Try to export PyTorch model to ONNX. Returns True on success."""
    try:
        import torch
        dummy = tokenizer("premise", "hypothesis", truncation=True,
                          max_length=512, return_tensors="pt")
        input_names = list(dummy.keys())
        torch.onnx.export(
            model,
            tuple(dummy[k] for k in input_names),
            export_path,
            input_names=input_names,
            output_names=["logits"],
            dynamic_axes={name: {0: "batch", 1: "seq"} for name in input_names}
            | {"logits": {0: "batch"}},
            opset_version=14,
            do_constant_folding=True,
        )
        return True
    except Exception as e:
        print(f"ONNX export failed: {e}")
        return False


def try_quantize_onnx(input_path: str, output_path: str) -> bool:
    """Try to quantize ONNX model. Returns True on success."""
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(
            input_path, output_path,
            weight_type=QuantType.QUInt8,
        )
        return True
    except Exception as e:
        print(f"ONNX quantization failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Latency Profiling
# ---------------------------------------------------------------------------

def profile_latency(model, tokenizer, sample_pairs: List[Tuple[str, str]],
                    entail_idx: int, neutral_idx: int, contra_idx: int,
                    device: str = "cpu", model_label: str = "pytorch_cpu") -> Dict:
    """Profile latency for 1/5/10 claims sequential and batched."""
    import torch

    results = {}

    # Sequential latency: 1 claim
    seq1_times = []
    for _ in range(20):
        p, h = sample_pairs[0]
        res = run_nli_inference(model, tokenizer, p, h, entail_idx, neutral_idx, contra_idx, device)
        seq1_times.append(res["latency_ms"])
    results["sequential_1_claim_ms"] = {
        "mean": round(float(np.mean(seq1_times)), 2),
        "p50": round(float(np.median(seq1_times)), 2),
        "p95": round(float(np.percentile(seq1_times, 95)), 2),
    }

    # Sequential latency: 5 claims
    seq5_times = []
    for _ in range(10):
        total = 0
        for pair in sample_pairs[:5]:
            res = run_nli_inference(model, tokenizer, pair[0], pair[1],
                                   entail_idx, neutral_idx, contra_idx, device)
            total += res["latency_ms"]
        seq5_times.append(total)
    results["sequential_5_claims_ms"] = {
        "mean": round(float(np.mean(seq5_times)), 2),
        "p50": round(float(np.median(seq5_times)), 2),
        "p95": round(float(np.percentile(seq5_times, 95)), 2),
        "per_claim_mean": round(float(np.mean(seq5_times)) / 5, 2),
    }

    # Sequential latency: 10 claims
    seq10_times = []
    for _ in range(5):
        total = 0
        for pair in sample_pairs[:10]:
            res = run_nli_inference(model, tokenizer, pair[0], pair[1],
                                   entail_idx, neutral_idx, contra_idx, device)
            total += res["latency_ms"]
        seq10_times.append(total)
    results["sequential_10_claims_ms"] = {
        "mean": round(float(np.mean(seq10_times)), 2),
        "p50": round(float(np.median(seq10_times)), 2),
        "p95": round(float(np.percentile(seq10_times, 95)), 2),
        "per_claim_mean": round(float(np.mean(seq10_times)) / 10, 2),
    }

    # Batched latency: 5 claims
    batch5_times = []
    pairs5 = sample_pairs[:5]
    for _ in range(10):
        premises = [p[0] for p in pairs5]
        hypotheses = [p[1] for p in pairs5]
        t0 = time.perf_counter()
        inputs = tokenizer(premises, hypotheses, padding=True, truncation=True,
                           max_length=512, return_tensors="pt")
        if device != "cpu":
            inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            _ = model(**inputs)
        batch5_times.append((time.perf_counter() - t0) * 1000.0)
    results["batched_5_claims_ms"] = {
        "mean": round(float(np.mean(batch5_times)), 2),
        "p50": round(float(np.median(batch5_times)), 2),
        "p95": round(float(np.percentile(batch5_times, 95)), 2),
        "per_claim_mean": round(float(np.mean(batch5_times)) / 5, 2),
    }

    # Batched latency: 10 claims
    batch10_times = []
    pairs10 = sample_pairs[:10]
    for _ in range(5):
        premises = [p[0] for p in pairs10]
        hypotheses = [p[1] for p in pairs10]
        t0 = time.perf_counter()
        inputs = tokenizer(premises, hypotheses, padding=True, truncation=True,
                           max_length=512, return_tensors="pt")
        if device != "cpu":
            inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            _ = model(**inputs)
        batch10_times.append((time.perf_counter() - t0) * 1000.0)
    results["batched_10_claims_ms"] = {
        "mean": round(float(np.mean(batch10_times)), 2),
        "p50": round(float(np.median(batch10_times)), 2),
        "p95": round(float(np.percentile(batch10_times, 95)), 2),
        "per_claim_mean": round(float(np.mean(batch10_times)) / 10, 2),
    }

    return results


def profile_latency_onnx(session, tokenizer, sample_pairs: List[Tuple[str, str]],
                          label_order: List[str], model_label: str) -> Dict:
    """Profile ONNX latency for 1/5/10 sequential claims."""
    results = {}
    input_names = [i.name for i in session.get_inputs()]

    def run_one(premise, hypothesis):
        t0 = time.perf_counter()
        inputs = tokenizer(premise, hypothesis, truncation=True, max_length=512,
                           return_tensors="np")
        feed = {k: v for k, v in inputs.items() if k in input_names}
        _ = session.run(None, feed)
        return (time.perf_counter() - t0) * 1000.0

    # 1 claim
    times1 = [run_one(sample_pairs[0][0], sample_pairs[0][1]) for _ in range(20)]
    results["sequential_1_claim_ms"] = {
        "mean": round(float(np.mean(times1)), 2),
        "p50": round(float(np.median(times1)), 2),
        "p95": round(float(np.percentile(times1, 95)), 2),
    }

    # 5 claims sequential
    times5 = []
    for _ in range(10):
        total = sum(run_one(p[0], p[1]) for p in sample_pairs[:5])
        times5.append(total)
    results["sequential_5_claims_ms"] = {
        "mean": round(float(np.mean(times5)), 2),
        "per_claim_mean": round(float(np.mean(times5)) / 5, 2),
    }

    # 10 claims sequential
    times10 = []
    for _ in range(5):
        total = sum(run_one(p[0], p[1]) for p in sample_pairs[:10])
        times10.append(total)
    results["sequential_10_claims_ms"] = {
        "mean": round(float(np.mean(times10)), 2),
        "per_claim_mean": round(float(np.mean(times10)) / 10, 2),
    }

    return results


# ---------------------------------------------------------------------------
# Main Benchmark Runner
# ---------------------------------------------------------------------------

def run_holdout_benchmark():
    import torch

    process = psutil.Process()
    ram_before = process.memory_info().rss / (1024 * 1024)

    print("=" * 72)
    print("CLAIM-BENCH-02: INDEPENDENT HOLDOUT BENCHMARK")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Load holdout matrix
    # -----------------------------------------------------------------------
    print(f"\n[1] Loading holdout matrix from: {HOLDOUT_MATRIX_PATH}")
    with open(HOLDOUT_MATRIX_PATH, "r", encoding="utf-8") as f:
        holdout_data = json.load(f)

    if isinstance(holdout_data, dict):
        metadata = holdout_data.get("metadata", {})
        cases = holdout_data.get("cases", [])
    else:
        metadata = {}
        cases = holdout_data

    nli_cases = [c for c in cases if c.get("nli_required", True)]
    print(f"Total cases: {len(cases)} | NLI required: {len(nli_cases)}")
    print(f"Metadata: {json.dumps(metadata, indent=2)}")

    # -----------------------------------------------------------------------
    # Data quality pre-check
    # -----------------------------------------------------------------------
    print("\n[2] Pre-run data quality check...")
    quality_flags = []
    for c in nli_cases:
        # Check for very short claims/evidence
        if len(c.get("claim", "")) < 10:
            quality_flags.append((c["case_id"], "SHORT_CLAIM"))
        if len(c.get("evidence", "")) < 15:
            quality_flags.append((c["case_id"], "SHORT_EVIDENCE"))
        # Check for missing fields
        for field in ["case_id", "claim", "evidence", "expected_semantic_relation", "language_mode"]:
            if field not in c:
                quality_flags.append((c["case_id"], f"MISSING_{field.upper()}"))
    corrections_count = len(quality_flags)
    print(f"Quality flags: {corrections_count}")
    for qf in quality_flags:
        print(f"  {qf[0]}: {qf[1]}")

    # -----------------------------------------------------------------------
    # Load primary model (mDeBERTa)
    # -----------------------------------------------------------------------
    print(f"\n[3] Loading primary model: {PRIMARY_MODEL}")
    t0_load = time.perf_counter()
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(PRIMARY_MODEL, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        PRIMARY_MODEL, trust_remote_code=False)
    model.eval()
    t_load = time.perf_counter() - t0_load
    ram_after_model = process.memory_info().rss / (1024 * 1024)

    config = model.config
    id2label = {int(k): v.lower() for k, v in config.id2label.items()}
    label2id = {k.lower(): int(v) for k, v in config.label2id.items()}
    entail_idx = label2id["entailment"]
    neutral_idx = label2id["neutral"]
    contra_idx = label2id["contradiction"]

    print(f"Model loaded in {t_load:.2f}s | RAM delta: {ram_after_model - ram_before:.1f} MB")
    print(f"id2label: {id2label}")

    # Warmup
    for _ in range(5):
        _ = run_nli_inference(model, tokenizer, "warmup premise", "warmup hypothesis",
                              entail_idx, neutral_idx, contra_idx)

    # -----------------------------------------------------------------------
    # Run mDeBERTa on ALL holdout NLI cases with frozen thresholds
    # -----------------------------------------------------------------------
    print(f"\n[4] Running mDeBERTa on {len(nli_cases)} holdout cases "
          f"(tau_ent={TAU_ENTAILMENT}, tau_con={TAU_CONTRADICTION})...")

    mdeberta_results = []
    for idx, c in enumerate(nli_cases, 1):
        nli = run_nli_inference(model, tokenizer, c["evidence"], c["claim"],
                                entail_idx, neutral_idx, contra_idx)
        gov = compute_governance_decision(c["claim"], c["evidence"], nli)

        argmax_labels = {entail_idx: "ENTAILMENT", neutral_idx: "NEUTRAL",
                         contra_idx: "CONTRADICTION"}
        probs_arr = [nli["p_entailment"], nli["p_neutral"], nli["p_contradiction"]]
        argmax_label = argmax_labels[int(np.argmax(probs_arr))]

        result = {
            "case_id": c["case_id"],
            "language_mode": c.get("language_mode", "UNKNOWN"),
            "claim_category": c.get("claim_category", "UNKNOWN"),
            "claim": c["claim"],
            "evidence": c["evidence"],
            "expected_relation": c["expected_semantic_relation"],
            "predicted_argmax": argmax_label,
            "p_entailment": round(nli["p_entailment"], 6),
            "p_neutral": round(nli["p_neutral"], 6),
            "p_contradiction": round(nli["p_contradiction"], 6),
            "threshold_decision": gov["nli_threshold_decision"],
            "deterministic_guard": gov["guard"],
            "final_governance_decision": gov["decision"],
            "latency_ms": round(nli["latency_ms"], 2),
            "is_argmax_correct": argmax_label == c["expected_semantic_relation"],
        }
        mdeberta_results.append(result)

        status = "✓" if result["is_argmax_correct"] else "✗"
        print(f"[{idx:03d}/{len(nli_cases):03d}] {status} {c['case_id']} "
              f"({c.get('language_mode', '?')}): "
              f"Exp={c['expected_semantic_relation']} | Pred={argmax_label} "
              f"(E={nli['p_entailment']:.3f} N={nli['p_neutral']:.3f} "
              f"C={nli['p_contradiction']:.3f}) "
              f"Thresh={gov['nli_threshold_decision']} "
              f"Gov={gov['decision']} [{nli['latency_ms']:.0f}ms]")

    # -----------------------------------------------------------------------
    # Compound vs Atomic Claim Analysis
    # -----------------------------------------------------------------------
    print("\n[5] Compound vs Atomic Claim Analysis...")
    compound_cases = [c for c in cases if c.get("is_compound", False)]
    compound_groups = defaultdict(list)
    for c in cases:
        cg = c.get("compound_group")
        if cg:
            compound_groups[cg].append(c)

    atomic_results = {}
    for group_name, group_cases in compound_groups.items():
        print(f"\n  Group: {group_name}")
        group_results = {}
        for c in group_cases:
            nli = run_nli_inference(model, tokenizer, c["evidence"], c["claim"],
                                    entail_idx, neutral_idx, contra_idx)
            td = apply_threshold(nli["p_entailment"], nli["p_contradiction"])
            group_results[c["case_id"]] = {
                "claim": c["claim"],
                "is_compound": c.get("is_compound", False),
                "p_entailment": round(nli["p_entailment"], 6),
                "p_neutral": round(nli["p_neutral"], 6),
                "p_contradiction": round(nli["p_contradiction"], 6),
                "threshold_decision": td,
                "expected_relation": c["expected_semantic_relation"],
            }
            comp_label = "[COMPOUND]" if c.get("is_compound") else "[ATOMIC] "
            print(f"    {comp_label} {c['case_id']}: "
                  f"E={nli['p_entailment']:.3f} → {td} "
                  f"(expected: {c['expected_semantic_relation']})")
        atomic_results[group_name] = group_results

    # -----------------------------------------------------------------------
    # Multi-Source Strategy Comparison
    # -----------------------------------------------------------------------
    print("\n[6] Multi-Source Strategy Comparison...")
    multi_source_cases = [c for c in cases if c.get("claim_category") == "MULTI_SOURCE"
                          or "MSR" in c.get("case_id", "")]
    multi_source_analysis = []
    for c in multi_source_cases:
        evidence_text = c.get("evidence", "")
        # Try to split on common multi-source separators
        sources = []
        for sep in ["---", "|||", "Nguồn A:", "Source A:", "Nguon A:"]:
            if sep in evidence_text:
                parts = evidence_text.split(sep)
                sources = [p.strip() for p in parts if p.strip()]
                break
        if not sources:
            sources = [evidence_text]

        # Strategy A: whole claim + Source A
        # Strategy B: whole claim + Source B
        # Strategy C: whole claim + A+B concatenated
        strategies = {}
        for i, src in enumerate(sources):
            src_label = chr(65 + i)  # A, B, C...
            nli = run_nli_inference(model, tokenizer, src, c["claim"],
                                    entail_idx, neutral_idx, contra_idx)
            strategies[f"whole_claim_source_{src_label}"] = {
                "p_entailment": round(nli["p_entailment"], 6),
                "p_contradiction": round(nli["p_contradiction"], 6),
                "threshold_decision": apply_threshold(nli["p_entailment"],
                                                       nli["p_contradiction"]),
            }

        # Strategy C: all sources concatenated
        concat_evidence = " --- ".join(sources)
        nli_concat = run_nli_inference(model, tokenizer, concat_evidence, c["claim"],
                                        entail_idx, neutral_idx, contra_idx)
        strategies["whole_claim_all_concat"] = {
            "p_entailment": round(nli_concat["p_entailment"], 6),
            "p_contradiction": round(nli_concat["p_contradiction"], 6),
            "threshold_decision": apply_threshold(nli_concat["p_entailment"],
                                                   nli_concat["p_contradiction"]),
        }

        analysis = {
            "case_id": c["case_id"],
            "claim": c["claim"],
            "source_count": len(sources),
            "strategies": strategies,
            "expected_relation": c["expected_semantic_relation"],
        }
        multi_source_analysis.append(analysis)
        print(f"  {c['case_id']}: {len(sources)} sources")
        for sk, sv in strategies.items():
            print(f"    {sk}: E={sv['p_entailment']:.3f} → {sv['threshold_decision']}")

    # -----------------------------------------------------------------------
    # Latency profiling: primary model
    # -----------------------------------------------------------------------
    print("\n[7] Latency profiling: mDeBERTa PyTorch CPU...")
    sample_pairs = [(c["evidence"], c["claim"]) for c in nli_cases[:12]]
    primary_latency = profile_latency(model, tokenizer, sample_pairs,
                                       entail_idx, neutral_idx, contra_idx,
                                       device="cpu", model_label="mdeberta_pytorch_cpu")
    print(f"  1-claim seq: {primary_latency['sequential_1_claim_ms']['mean']:.0f}ms")
    print(f"  5-claims seq: {primary_latency['sequential_5_claims_ms']['mean']:.0f}ms")
    print(f"  10-claims seq: {primary_latency['sequential_10_claims_ms']['mean']:.0f}ms")
    print(f"  5-claims batch: {primary_latency['batched_5_claims_ms']['mean']:.0f}ms")
    print(f"  10-claims batch: {primary_latency['batched_10_claims_ms']['mean']:.0f}ms")

    # Save primary model results
    primary_output = {
        "benchmark_phase": "CLAIM-BENCH-02",
        "benchmark_type": "holdout",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_id": PRIMARY_MODEL,
        "model_class": model.__class__.__name__,
        "backend": "pytorch_cpu",
        "device": "cpu",
        "python_version": sys.version,
        "torch_version": torch.__version__,
        "frozen_thresholds": {
            "tau_entailment": TAU_ENTAILMENT,
            "tau_contradiction": TAU_CONTRADICTION,
        },
        "holdout_total_cases": len(cases),
        "nli_case_count": len(nli_cases),
        "pre_run_corrections": corrections_count,
        "quality_flags": quality_flags,
        "label_mapping": id2label,
        "model_load_time_seconds": round(t_load, 2),
        "ram_delta_mb": round(ram_after_model - ram_before, 2),
        "latency_profile": primary_latency,
        "compound_atomic_analysis": atomic_results,
        "multi_source_analysis": multi_source_analysis,
        "cases": mdeberta_results,
    }

    primary_results_path = RESULTS_DIR / "claim_verification_holdout_results_mdeberta.json"
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(primary_results_path, "w", encoding="utf-8") as f:
        json.dump(primary_output, f, ensure_ascii=False, indent=2)
    print(f"\nPrimary model results saved to: {primary_results_path}")

    # -----------------------------------------------------------------------
    # ONNX backend
    # -----------------------------------------------------------------------
    print("\n[8] ONNX Backend Benchmark...")
    onnx_results = {"status": "NOT_TESTED", "reason": ""}
    quantized_onnx_results = {"status": "NOT_TESTED", "reason": ""}

    try:
        import onnxruntime as ort
        onnx_available = True
        print(f"  onnxruntime version: {ort.__version__}")
    except ImportError:
        onnx_available = False
        onnx_results["reason"] = "onnxruntime not installed"
        quantized_onnx_results["reason"] = "onnxruntime not installed"
        print("  onnxruntime not available - ONNX tests NOT_TESTED")

    onnx_model_path = str(RESULTS_DIR / "mdeberta_benchmark.onnx")
    onnx_quant_path = str(RESULTS_DIR / "mdeberta_benchmark_quant.onnx")

    if onnx_available:
        # Export to ONNX
        print("  Exporting model to ONNX...")
        export_ok = try_export_onnx(model, tokenizer, onnx_model_path)
        if export_ok:
            print("  ONNX export successful. Running benchmark...")
            session = ort.InferenceSession(onnx_model_path,
                                            providers=["CPUExecutionProvider"])
            label_order = [id2label[i] for i in range(len(id2label))]

            # Run on all holdout cases
            onnx_case_results = []
            for c in nli_cases:
                nli = run_nli_inference_onnx(session, tokenizer, c["evidence"],
                                              c["claim"], label_order)
                p_ent = nli.get("p_entailment", 0)
                p_con = nli.get("p_contradiction", 0)
                td = apply_threshold(p_ent, p_con)
                guard = run_all_deterministic_guards(c["claim"], c["evidence"])
                gov_decision = "BLOCKED_BY_GUARD" if guard else td
                onnx_case_results.append({
                    "case_id": c["case_id"],
                    "p_entailment": round(p_ent, 6),
                    "p_contradiction": round(p_con, 6),
                    "threshold_decision": td,
                    "final_governance_decision": gov_decision,
                    "latency_ms": round(nli["latency_ms"], 2),
                })

            # Latency profiling
            onnx_latency = profile_latency_onnx(session, tokenizer, sample_pairs,
                                                  label_order, "onnx_cpu")

            onnx_results = {
                "status": "TESTED",
                "onnxruntime_version": ort.__version__,
                "model_size_mb": round(os.path.getsize(onnx_model_path) / (1024*1024), 2),
                "latency_profile": onnx_latency,
                "cases": onnx_case_results,
            }
            print(f"  ONNX CPU 1-claim: {onnx_latency['sequential_1_claim_ms']['mean']:.0f}ms")
            print(f"  ONNX CPU 5-claims: {onnx_latency['sequential_5_claims_ms']['mean']:.0f}ms")
            print(f"  ONNX CPU 10-claims: {onnx_latency['sequential_10_claims_ms']['mean']:.0f}ms")

            # Save ONNX results
            onnx_output_path = RESULTS_DIR / "claim_verification_holdout_results_onnx.json"
            with open(onnx_output_path, "w", encoding="utf-8") as f:
                json.dump({"benchmark_phase": "CLAIM-BENCH-02",
                           "backend": "onnx_cpu", **onnx_results},
                          f, ensure_ascii=False, indent=2)

            # Try quantized ONNX
            print("  Attempting ONNX quantization...")
            quant_ok = try_quantize_onnx(onnx_model_path, onnx_quant_path)
            if quant_ok:
                q_session = ort.InferenceSession(onnx_quant_path,
                                                  providers=["CPUExecutionProvider"])
                # Latency profiling
                quant_latency = profile_latency_onnx(q_session, tokenizer, sample_pairs,
                                                      label_order, "onnx_quant_cpu")

                # Run on holdout
                quant_case_results = []
                for c in nli_cases:
                    nli = run_nli_inference_onnx(q_session, tokenizer, c["evidence"],
                                                  c["claim"], label_order)
                    p_ent = nli.get("p_entailment", 0)
                    p_con = nli.get("p_contradiction", 0)
                    td = apply_threshold(p_ent, p_con)
                    guard = run_all_deterministic_guards(c["claim"], c["evidence"])
                    gov_decision = "BLOCKED_BY_GUARD" if guard else td
                    quant_case_results.append({
                        "case_id": c["case_id"],
                        "p_entailment": round(p_ent, 6),
                        "p_contradiction": round(p_con, 6),
                        "threshold_decision": td,
                        "final_governance_decision": gov_decision,
                        "latency_ms": round(nli["latency_ms"], 2),
                    })

                quantized_onnx_results = {
                    "status": "TESTED",
                    "model_size_mb": round(os.path.getsize(onnx_quant_path) / (1024*1024), 2),
                    "latency_profile": quant_latency,
                    "cases": quant_case_results,
                }
                print(f"  Quantized ONNX 1-claim: {quant_latency['sequential_1_claim_ms']['mean']:.0f}ms")

                quant_output_path = RESULTS_DIR / "claim_verification_holdout_results_onnx_quant.json"
                with open(quant_output_path, "w", encoding="utf-8") as f:
                    json.dump({"benchmark_phase": "CLAIM-BENCH-02",
                               "backend": "onnx_quantized_cpu", **quantized_onnx_results},
                              f, ensure_ascii=False, indent=2)
            else:
                quantized_onnx_results["reason"] = "Quantization failed"
        else:
            onnx_results["reason"] = "ONNX export failed"
            quantized_onnx_results["reason"] = "ONNX export failed (prerequisite)"

    # Clean up ONNX files from tests/data (they're benchmark artifacts, not test data)
    for onnx_file in [onnx_model_path, onnx_quant_path]:
        if os.path.exists(onnx_file):
            try:
                os.remove(onnx_file)
            except OSError:
                pass

    # -----------------------------------------------------------------------
    # CUDA backend check
    # -----------------------------------------------------------------------
    print("\n[9] CUDA Backend Check...")
    cuda_results = {"status": "NOT_TESTED", "reason": ""}
    if torch.cuda.is_available():
        print(f"  CUDA available: {torch.cuda.get_device_name(0)}")
        try:
            model_cuda = model.to("cuda")
            # Warmup
            for _ in range(5):
                _ = run_nli_inference(model_cuda, tokenizer, "warmup", "warmup",
                                      entail_idx, neutral_idx, contra_idx, "cuda")
            cuda_latency = profile_latency(model_cuda, tokenizer, sample_pairs,
                                            entail_idx, neutral_idx, contra_idx,
                                            device="cuda", model_label="mdeberta_cuda")
            cuda_results = {
                "status": "TESTED",
                "gpu_name": torch.cuda.get_device_name(0),
                "latency_profile": cuda_latency,
            }
            print(f"  CUDA 1-claim: {cuda_latency['sequential_1_claim_ms']['mean']:.0f}ms")
            model.to("cpu")  # Move back to CPU for continued use
        except Exception as e:
            cuda_results["reason"] = f"CUDA inference failed: {e}"
            print(f"  CUDA inference failed: {e}")
    else:
        cuda_results["reason"] = (
            "torch.cuda.is_available()=False. The benchmark venv installed "
            "torch+cpu. A CUDA-enabled PyTorch build would be needed to test GPU."
        )
        print(f"  {cuda_results['reason']}")

    # -----------------------------------------------------------------------
    # Smaller model comparison
    # -----------------------------------------------------------------------
    print(f"\n[10] Loading smaller model: {SMALLER_MODEL}")
    smaller_results = {"status": "NOT_TESTED", "reason": ""}
    try:
        ram_before_small = process.memory_info().rss / (1024 * 1024)
        t0_small = time.perf_counter()
        small_tokenizer = AutoTokenizer.from_pretrained(SMALLER_MODEL, use_fast=True)
        small_model = AutoModelForSequenceClassification.from_pretrained(
            SMALLER_MODEL, trust_remote_code=False)
        small_model.eval()
        t_small_load = time.perf_counter() - t0_small
        ram_after_small = process.memory_info().rss / (1024 * 1024)

        small_config = small_model.config
        small_id2label = {int(k): v.lower() for k, v in small_config.id2label.items()}
        small_label2id = {k.lower(): int(v) for k, v in small_config.label2id.items()}

        # Determine label indices (may differ between models)
        small_entail_idx = small_label2id.get("entailment", 0)
        small_neutral_idx = small_label2id.get("neutral", 1)
        small_contra_idx = small_label2id.get("contradiction", 2)

        print(f"  Loaded in {t_small_load:.2f}s | RAM delta: {ram_after_small - ram_before_small:.1f} MB")
        print(f"  id2label: {small_id2label}")
        print(f"  Parameters: {sum(p.numel() for p in small_model.parameters()):,}")

        # Warmup
        for _ in range(5):
            _ = run_nli_inference(small_model, small_tokenizer, "warmup", "warmup",
                                  small_entail_idx, small_neutral_idx, small_contra_idx)

        # Run on all holdout cases with SAME frozen thresholds
        small_case_results = []
        for idx, c in enumerate(nli_cases, 1):
            nli = run_nli_inference(small_model, small_tokenizer, c["evidence"], c["claim"],
                                    small_entail_idx, small_neutral_idx, small_contra_idx)
            gov = compute_governance_decision(c["claim"], c["evidence"], nli)

            probs_arr = [nli["p_entailment"], nli["p_neutral"], nli["p_contradiction"]]
            argmax_idx = int(np.argmax(probs_arr))
            argmax_labels = {0: "ENTAILMENT", 1: "NEUTRAL", 2: "CONTRADICTION"}
            # Map based on actual indices
            idx_to_label = {small_entail_idx: "ENTAILMENT",
                           small_neutral_idx: "NEUTRAL",
                           small_contra_idx: "CONTRADICTION"}
            predicted = idx_to_label[int(np.argmax([nli["p_entailment"],
                                                     nli["p_neutral"],
                                                     nli["p_contradiction"]]))]
            # Fix: argmax should be over the correct mapping
            prob_map = {
                "ENTAILMENT": nli["p_entailment"],
                "NEUTRAL": nli["p_neutral"],
                "CONTRADICTION": nli["p_contradiction"],
            }
            predicted = max(prob_map, key=prob_map.get)

            result = {
                "case_id": c["case_id"],
                "language_mode": c.get("language_mode", "UNKNOWN"),
                "claim_category": c.get("claim_category", "UNKNOWN"),
                "expected_relation": c["expected_semantic_relation"],
                "predicted_argmax": predicted,
                "p_entailment": round(nli["p_entailment"], 6),
                "p_neutral": round(nli["p_neutral"], 6),
                "p_contradiction": round(nli["p_contradiction"], 6),
                "threshold_decision": gov["nli_threshold_decision"],
                "deterministic_guard": gov["guard"],
                "final_governance_decision": gov["decision"],
                "latency_ms": round(nli["latency_ms"], 2),
                "is_argmax_correct": predicted == c["expected_semantic_relation"],
            }
            small_case_results.append(result)

            status = "✓" if result["is_argmax_correct"] else "✗"
            if idx % 20 == 0 or idx == len(nli_cases):
                print(f"  [{idx:03d}/{len(nli_cases):03d}] Progress...")

        # Latency profiling
        small_latency = profile_latency(small_model, small_tokenizer, sample_pairs,
                                         small_entail_idx, small_neutral_idx,
                                         small_contra_idx, device="cpu",
                                         model_label="xlmr_pytorch_cpu")

        smaller_results = {
            "status": "TESTED",
            "model_id": SMALLER_MODEL,
            "model_class": small_model.__class__.__name__,
            "parameter_count": sum(p.numel() for p in small_model.parameters()),
            "load_time_seconds": round(t_small_load, 2),
            "ram_delta_mb": round(ram_after_small - ram_before_small, 2),
            "id2label": small_id2label,
            "latency_profile": small_latency,
            "cases": small_case_results,
        }

        # Save smaller model results
        small_output_path = RESULTS_DIR / "claim_verification_holdout_results_xlmr.json"
        with open(small_output_path, "w", encoding="utf-8") as f:
            json.dump({"benchmark_phase": "CLAIM-BENCH-02",
                       "model_id": SMALLER_MODEL,
                       "backend": "pytorch_cpu",
                       "frozen_thresholds": {"tau_entailment": TAU_ENTAILMENT,
                                              "tau_contradiction": TAU_CONTRADICTION},
                       **smaller_results}, f, ensure_ascii=False, indent=2)
        print(f"  Smaller model results saved to: {small_output_path}")
        print(f"  1-claim seq: {small_latency['sequential_1_claim_ms']['mean']:.0f}ms")

    except Exception as e:
        smaller_results["reason"] = f"Failed to load/run: {e}"
        print(f"  Smaller model failed: {e}")
        traceback.print_exc()

    # -----------------------------------------------------------------------
    # Generate summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("BENCHMARK SUMMARY")
    print("=" * 72)

    summary = {
        "benchmark_phase": "CLAIM-BENCH-02",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frozen_thresholds": {
            "tau_entailment": TAU_ENTAILMENT,
            "tau_contradiction": TAU_CONTRADICTION,
        },
        "holdout_total_cases": len(cases),
        "nli_cases": len(nli_cases),
        "pre_run_corrections": corrections_count,
        "primary_model": PRIMARY_MODEL,
        "primary_backend": "pytorch_cpu",
        "onnx_status": onnx_results.get("status", "NOT_TESTED"),
        "quantized_onnx_status": quantized_onnx_results.get("status", "NOT_TESTED"),
        "cuda_status": cuda_results.get("status", "NOT_TESTED"),
        "cuda_reason": cuda_results.get("reason", ""),
        "smaller_model_status": smaller_results.get("status", "NOT_TESTED"),
    }

    summary_path = RESULTS_DIR / "claim_verification_holdout_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nSummary saved to: {summary_path}")
    print(f"All results files in: {RESULTS_DIR}")
    print("\nDone.")


if __name__ == "__main__":
    run_holdout_benchmark()
