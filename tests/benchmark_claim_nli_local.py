"""Local Multilingual NLI Claim Verification Benchmark Runner (Phase CLAIM-BENCH-01R).

Executes real local inference using MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
on the 64-case benchmark dataset without touching production runtime code.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List
import numpy as np
import psutil
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_NAME = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
BENCHMARK_MATRIX_PATH = Path("tests/data/claim_verification_benchmark_matrix.json")
RESULTS_OUTPUT_PATH = Path("tests/data/claim_verification_benchmark_results.json")


def run_benchmark() -> Dict[str, Any]:
    process = psutil.Process()
    ram_before_mb = process.memory_info().rss / (1024 * 1024)

    print("=" * 70)
    print("CLAIM-BENCH-01R: LOCAL NLI EXECUTION BENCHMARK")
    print("=" * 70)
    print(f"Loading benchmark dataset from: {BENCHMARK_MATRIX_PATH}")
    with open(BENCHMARK_MATRIX_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    nli_cases = [c for c in cases if c.get("nli_required", True)]
    print(f"Total dataset cases: {len(cases)} | NLI required cases: {len(nli_cases)}")

    # 1. Model Loading & Verification
    print(f"\n[1] Loading Model & Tokenizer: {MODEL_NAME} (trust_remote_code=False)...")
    t0_load = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        trust_remote_code=False,
    )
    model.eval()
    t_load = time.perf_counter() - t0_load

    ram_after_mb = process.memory_info().rss / (1024 * 1024)
    ram_delta_mb = ram_after_mb - ram_before_mb

    config = model.config
    id2label = {int(k): v.lower() for k, v in config.id2label.items()}
    label2id = {k.lower(): int(v) for k, v in config.label2id.items()}

    print(f"Model successfully loaded in {t_load:.2f}s")
    print(f"RAM before: {ram_before_mb:.1f} MB | RAM after: {ram_after_mb:.1f} MB | Delta: {ram_delta_mb:.1f} MB")
    print(f"Model Class: {model.__class__.__name__} | Tokenizer Class: {tokenizer.__class__.__name__}")
    print(f"id2label: {id2label}")
    print(f"label2id: {label2id}")

    contra_idx = label2id["contradiction"]
    neutral_idx = label2id["neutral"]
    entail_idx = label2id["entailment"]

    # 2. Warmup
    print("\n[2] Warming up model...")
    for _ in range(5):
        inputs = tokenizer("Warmup premise", "Warmup hypothesis", return_tensors="pt")
        with torch.no_grad():
            _ = model(**inputs)

    # 3. Main Benchmark Execution
    print("\n[3] Executing NLI Inference on Benchmark Cases...")
    case_results: List[Dict[str, Any]] = []

    for idx, c in enumerate(nli_cases, 1):
        premise = c["evidence"]
        hypothesis = c["claim"]

        t0_inf = time.perf_counter()
        inputs = tokenizer(premise, hypothesis, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits[0]
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
        inf_duration_ms = (time.perf_counter() - t0_inf) * 1000.0

        p_contra = float(probs[contra_idx])
        p_neutral = float(probs[neutral_idx])
        p_entail = float(probs[entail_idx])

        argmax_idx = int(np.argmax(probs))
        predicted_argmax = id2label[argmax_idx].upper()

        res = {
            "case_id": c["case_id"],
            "language_mode": c["language_mode"],
            "claim_category": c["claim_category"],
            "claim": hypothesis,
            "evidence": premise,
            "expected_relation": c["expected_semantic_relation"],
            "predicted_argmax": predicted_argmax,
            "p_contradiction": round(p_contra, 6),
            "p_neutral": round(p_neutral, 6),
            "p_entailment": round(p_entail, 6),
            "latency_ms": round(inf_duration_ms, 2),
            "is_argmax_correct": (predicted_argmax == c["expected_semantic_relation"]),
        }
        case_results.append(res)
        print(f"[{idx:02d}/{len(nli_cases):02d}] {c['case_id']} ({c['language_mode']}): "
              f"Exp={c['expected_semantic_relation']} | Pred={predicted_argmax} "
              f"(Ent={p_entail:.3f}, Neu={p_neutral:.3f}, Con={p_contra:.3f}) [{inf_duration_ms:.1f}ms]")

    # 4. Multi-Source Constituent Tests
    print("\n[4] Running Multi-Source Decomposition Tests...")
    multi_source_tests = [
        {
            "test_id": "BM-MULTI-SRC-01-DECOMP",
            "claim": "Titanium casing paired with sapphire crystal glass creates our most durable flagship.",
            "source_a": "The outer enclosure is forged from Grade 5 aerospace titanium.",
            "source_b": "The display lens is protected by genuine synthetic sapphire crystal glass.",
        },
        {
            "test_id": "BM-MULTI-SRC-02-DECOMP",
            "claim": "Sản phẩm tích hợp chip xử lý AI và thời lượng pin 24 giờ cho trải nghiệm liền mạch.",
            "source_a": "Tài liệu A: Máy trang bị vi xử lý Neural Engine NPU chuyên dụng cho tác vụ AI.",
            "source_b": "Tài liệu B: Viên pin dung lượng lớn cung cấp thời gian sử dụng 24 giờ liên tục.",
        },
    ]
    multi_decomp_results = []
    for mst in multi_source_tests:
        # Source A alone
        inp_a = tokenizer(mst["source_a"], mst["claim"], truncation=True, return_tensors="pt")
        with torch.no_grad():
            p_a = torch.softmax(model(**inp_a).logits[0], dim=-1).cpu().numpy()
        # Source B alone
        inp_b = tokenizer(mst["source_b"], mst["claim"], truncation=True, return_tensors="pt")
        with torch.no_grad():
            p_b = torch.softmax(model(**inp_b).logits[0], dim=-1).cpu().numpy()
        # A + B concatenated
        concat_src = f"{mst['source_a']} --- {mst['source_b']}"
        inp_ab = tokenizer(concat_src, mst["claim"], truncation=True, return_tensors="pt")
        with torch.no_grad():
            p_ab = torch.softmax(model(**inp_ab).logits[0], dim=-1).cpu().numpy()

        decomp_res = {
            "test_id": mst["test_id"],
            "claim": mst["claim"],
            "source_a_p_entailment": round(float(p_a[entail_idx]), 4),
            "source_b_p_entailment": round(float(p_b[entail_idx]), 4),
            "source_ab_concat_p_entailment": round(float(p_ab[entail_idx]), 4),
            "source_ab_concat_p_neutral": round(float(p_ab[neutral_idx]), 4),
            "source_ab_concat_p_contradiction": round(float(p_ab[contra_idx]), 4),
        }
        multi_decomp_results.append(decomp_res)
        print(f"Decomp {mst['test_id']}: A={decomp_res['source_a_p_entailment']:.3f}, "
              f"B={decomp_res['source_b_p_entailment']:.3f} -> A+B={decomp_res['source_ab_concat_p_entailment']:.3f}")

    # 5. Latency Profiling (Batch Sizes 1, 8, 16)
    print("\n[5] Measuring Local CPU Latency Statistics...")
    sample_pairs = [(c["evidence"], c["claim"]) for c in nli_cases[:16]]

    # Batch 1: 30 iterations
    latencies_b1 = []
    for _ in range(30):
        p, h = sample_pairs[0]
        t0 = time.perf_counter()
        inp = tokenizer(p, h, truncation=True, return_tensors="pt")
        with torch.no_grad():
            _ = model(**inp)
        latencies_b1.append((time.perf_counter() - t0) * 1000.0)

    # Batch 8: 20 iterations
    latencies_b8 = []
    b8_pairs = sample_pairs[:8]
    for _ in range(20):
        p_list = [x[0] for x in b8_pairs]
        h_list = [x[1] for x in b8_pairs]
        t0 = time.perf_counter()
        inp = tokenizer(p_list, h_list, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            _ = model(**inp)
        latencies_b8.append((time.perf_counter() - t0) * 1000.0)

    # Batch 16: 10 iterations
    latencies_b16 = []
    b16_pairs = sample_pairs[:16]
    for _ in range(10):
        p_list = [x[0] for x in b16_pairs]
        h_list = [x[1] for x in b16_pairs]
        t0 = time.perf_counter()
        inp = tokenizer(p_list, h_list, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            _ = model(**inp)
        latencies_b16.append((time.perf_counter() - t0) * 1000.0)

    latency_stats = {
        "batch_1_per_pair_ms": {
            "count": len(latencies_b1),
            "mean": round(float(np.mean(latencies_b1)), 2),
            "median_p50": round(float(np.median(latencies_b1)), 2),
            "p95": round(float(np.percentile(latencies_b1, 95)), 2),
            "min": round(float(np.min(latencies_b1)), 2),
            "max": round(float(np.max(latencies_b1)), 2),
        },
        "batch_8_total_ms": {
            "count": len(latencies_b8),
            "mean": round(float(np.mean(latencies_b8)), 2),
            "median_p50": round(float(np.median(latencies_b8)), 2),
            "p95": round(float(np.percentile(latencies_b8, 95)), 2),
            "per_pair_mean_ms": round(float(np.mean(latencies_b8) / 8.0), 2),
        },
        "batch_16_total_ms": {
            "count": len(latencies_b16),
            "mean": round(float(np.mean(latencies_b16)), 2),
            "median_p50": round(float(np.median(latencies_b16)), 2),
            "p95": round(float(np.percentile(latencies_b16, 95)), 2),
            "per_pair_mean_ms": round(float(np.mean(latencies_b16) / 16.0), 2),
        },
    }

    # 6. Save Full Results
    final_output = {
        "benchmark_timestamp": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_NAME,
        "model_class": model.__class__.__name__,
        "tokenizer_class": tokenizer.__class__.__name__,
        "model_parameter_count": sum(p.numel() for p in model.parameters()),
        "python_version": sys.version,
        "torch_version": torch.__version__,
        "device": "cpu",
        "cuda_available": torch.cuda.is_available(),
        "ram_load_delta_mb": round(ram_delta_mb, 2),
        "model_load_time_seconds": round(t_load, 2),
        "dataset_total_cases": len(cases),
        "nli_case_count": len(nli_cases),
        "label_mapping": id2label,
        "latency_stats": latency_stats,
        "multi_source_decomposition": multi_decomp_results,
        "cases": case_results,
    }

    os.makedirs(RESULTS_OUTPUT_PATH.parent, exist_ok=True)
    with open(RESULTS_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print(f"\nRaw results successfully saved to: {RESULTS_OUTPUT_PATH}")
    return final_output


if __name__ == "__main__":
    import sys
    run_benchmark()
