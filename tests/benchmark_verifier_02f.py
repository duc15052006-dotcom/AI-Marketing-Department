"""PROD-VERIFIER-02F — challenger provisioning + policy benchmark runner.

Explicit benchmark flow ONLY (never invoked by verify_claim). Network is used
here solely to provision candidate snapshots; scoring is LOCAL_ONLY.

Usage:
    .verifier-venv/Scripts/python.exe tests/benchmark_verifier_02f.py provision <model_id> <sha>
    .verifier-venv/Scripts/python.exe tests/benchmark_verifier_02f.py bench
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PIN_PROD = "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"
CHALLENGERS = {
    "ernie-m-large-mnli-xnli": (
        "MoritzLaurer/ernie-m-large-mnli-xnli",
        "4cf4554a07ef38d458c40a1397cd88a1dd3cfc0a"),
    "mdeberta-v3-base-mnli-xnli": (
        "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"),
}
ALLOW_PATTERNS = [
    "config.json", "tokenizer.json", "tokenizer_config.json",
    "special_tokens_map.json", "spm.model", "sentencepiece*",
    "model.safetensors",
]


def cache_root() -> Path:
    from config.authority import get_runtime_config
    return Path(get_runtime_config().verifier_cache_root or
                Path.home() / ".ai_marketing_department" / "verifier_model_cache")


def sha256_file(p: Path):
    h = hashlib.sha256()
    n = 0
    with open(p, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b); n += len(b)
    return h.hexdigest(), n


def provision_challenger(name: str, model_id: str, revision: str) -> None:
    from huggingface_hub import snapshot_download
    root = cache_root()
    base = root / "challengers" / name / revision
    manifest_path = root / "challengers" / f"{name}-{revision[:12]}.manifest.json"

    print(f"[provision-challenger] {name} @ {revision[:12]}…")
    resolved = Path(snapshot_download(
        repo_id=model_id, revision=revision,
        allow_patterns=ALLOW_PATTERNS,
        cache_dir=str(root / "hub")))
    base.mkdir(parents=True, exist_ok=True)
    for item in resolved.rglob("*"):
        if item.is_file():
            rel = item.relative_to(resolved)
            dest = base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_bytes(item.read_bytes())
    (base / ".provisioned_revision").write_text(revision, encoding="utf-8")

    entries = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name != ".provisioned_revision":
            h, size = sha256_file(p)
            entries.append({"path": p.relative_to(base).as_posix(),
                            "sha256": h, "size": size})
    manifest = {"manifest_version": 1, "model_id": model_id,
                "model_revision": revision, "files": entries,
                "trust_label": "PROVISIONED/HASH_VERIFIED_LOCAL",
                "role": "BENCHMARK_CHALLENGER"}
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    os_replace(tmp, manifest_path)
    print(f"[provision-challenger] done: {manifest_path.name} ({len(entries)} files)")


import os  # noqa: E402


def os_replace(a, b):
    os.replace(a, b)


def run_bench() -> dict:
    from runtime.verifier_worker.client import SidecarClaimVerifier

    dataset = json.loads((REPO / "tests/data/verifier_challenge_dataset_v1.json")
                         .read_text(encoding="utf-8"))
    cases = [c for c in dataset["cases"] if c.get("nli_required")]
    holdout = json.loads((REPO / "tests/data/claim_verification_holdout_matrix.json")
                         .read_text(encoding="utf-8"))["cases"]
    holdout = [dict(c, gold_relation=c["expected_semantic_relation"],
                    category="HOLDOUT_" + c["language_mode"])
               for c in holdout if c.get("nli_required")]
    all_cases = holdout + cases

    models = [("production-mdeberta-mnli-xnli",
               "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
               PIN_PROD, None, None)]
    for name, (mid, sha) in CHALLENGERS.items():
        root = cache_root()
        snap = root / "challengers" / name / sha
        man = root / "challengers" / f"{name}-{sha[:12]}.manifest.json"
        if snap.is_dir() and man.is_file():
            models.append((name, mid, sha, str(snap), str(man)))
        else:
            print(f"[bench] SKIP {name}: not provisioned")

    results = {}
    venv_py = REPO / ".verifier-venv/Scripts/python.exe"
    for label, mid, sha, snap, man in models:
        print(f"\n[bench] === {label} ({sha[:12]}) over {len(all_cases)} cases ===")
        client = SidecarClaimVerifier(
            interpreter_executable=str(venv_py),
            worker_script=REPO / "runtime/verifier_worker/main.py",
            model_id=mid, model_revision=sha,
            startup_timeout_s=60.0, claim_timeout_s=120.0,
            snapshot_dir_override=snap, manifest_path_override=man)
        rows = []
        load_wall_ms = None
        try:
            t_load0 = time.monotonic()
            first_done = False
            deadline_gate = time.monotonic() + 900.0
            for c in all_cases:
                d = min(deadline_gate, time.monotonic() + 60.0)
                t0 = time.monotonic()
                r = client.verify_claim(c["claim"], c["evidence"],
                                        deadline_monotonic=d)
                if not first_done:
                    load_wall_ms = round((time.monotonic()-t_load0)*1000)
                    first_done = True
                argmax = (r.semantic_scores.argmax_label if r.semantic_scores else "NONE").upper()
                rows.append({
                    "case_id": c["case_id"], "lang": c["language_mode"],
                    "category": c["category"], "gold": c["gold_relation"],
                    "argmax": argmax,
                    "p_ent": r.semantic_scores.p_entailment if r.semantic_scores else None,
                    "p_con": r.semantic_scores.p_contradiction if r.semantic_scores else None,
                    "verdict": r.verdict.value,
                    "latency_ms": round((time.monotonic()-t0)*1000, 1),
                })
        finally:
            client.close()

        def metrics(rows_subset):
            ent_gold = [r for r in rows_subset if r["gold"] == "ENTAILMENT"]
            con_gold = [r for r in rows_subset if r["gold"] == "CONTRADICTION"]
            sup = [r for r in rows_subset if r["verdict"] == "SUPPORTED"]
            con = [r for r in rows_subset if r["verdict"] == "CONTRADICTED"]
            inc = [r for r in rows_subset if r["verdict"] not in ("SUPPORTED", "CONTRADICTED")]
            false_sup = [r for r in sup if r["gold"] != "ENTAILMENT"]
            sup_tp = sum(1 for r in sup if r["gold"] == "ENTAILMENT")
            con_tp = sum(1 for r in con if r["gold"] == "CONTRADICTION")
            correct_block = sum(1 for r in rows_subset
                                if r["gold"] != "ENTAILMENT" and r["verdict"] != "SUPPORTED")
            wrong_block = sum(1 for r in ent_gold if r["verdict"] != "SUPPORTED")
            non_ent = len(rows_subset) - len(ent_gold)
            return {
                "n": len(rows_subset),
                "raw_argmax_accuracy": round(sum(1 for r in rows_subset
                    if (r["argmax"] == "ENTAILMENT" and r["gold"] == "ENTAILMENT")
                    or (r["argmax"] == "CONTRADICTION" and r["gold"] == "CONTRADICTION")
                    or (r["argmax"] == "NEUTRAL" and r["gold"] == "NEUTRAL"))
                    / max(len(rows_subset), 1), 4),
                "supported_precision": round(sup_tp / max(len(sup), 1), 4),
                "supported_recall": round(sup_tp / max(len(ent_gold), 1), 4),
                "false_supported_count": len(false_sup),
                "false_supported_rate": round(len(false_sup) / max(len(rows_subset), 1), 4),
                "contradicted_recall": round(con_tp / max(len(con_gold), 1), 4),
                "contradicted_precision": round(con_tp / max(len(con), 1), 4),
                "abstention_rate": round(len(inc) / max(len(rows_subset), 1), 4),
                "correct_block_rate": round(correct_block / max(non_ent, 1), 4),
                "wrong_block_rate": round(wrong_block / max(len(ent_gold), 1), 4),
            }

        def breakdown(key_fn):
            out = {}
            keys = sorted({key_fn(r) for r in rows})
            for k in keys:
                sub = [r for r in rows if key_fn(r) == k]
                m = metrics(sub)
                m["latency_avg_ms"] = round(sum(r["latency_ms"] for r in sub)/max(len(sub),1), 1)
                out[k] = m
            return out

        overall = metrics(rows)
        overall["latency_avg_ms"] = round(sum(r["latency_ms"] for r in rows)/max(len(rows),1), 1)
        results[label] = {
            "model_id": mid, "revision": sha,
            "overall": overall,
            "by_language": breakdown(lambda r: r["lang"]),
            "by_category_group": breakdown(lambda r: (
                "ADVERSARIAL" if r["category"].startswith(("injection",)) else
                "NUMERIC_UNIT" if "numeric" in r["category"] or "unit" in r["category"] else
                "NEGATION" if "negation" in r["category"] else
                "OVERCLAIM_PARTIAL" if any(x in r["category"] for x in ("partial","overclaim","causal","correlation")) else
                "QUANTIFIER" if "quantifier" in r["category"] else
                "ENTITY_BRAND_SWAP" if "swap" in r["category"] or "brand" in r["category"] else
                "VI_NOISE" if "vi_" in r["category"] else
                "MIXED_TERMS" if "mixed_terms" in r["category"] else
                "DATE_PRICE_PCT" if any(x in r["category"] for x in ("date","price","percentage")) else
                "FORMAT" if any(x in r["category"] for x in ("quoted","html","markdown","unicode","near_context")) else
                r["category"])),
            "load_plus_first_inference_ms": load_wall_ms,
            "rows": rows,
        }

    out_path = REPO / "tests/data/verifier_benchmark_02f_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[bench] results -> {out_path}")
    return results


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "provision":
        name = sys.argv[2]
        mid, sha = CHALLENGERS[name]
        provision_challenger(name, mid, sha)
    elif len(sys.argv) >= 2 and sys.argv[1] == "bench":
        res = run_bench()
        for label, data in res.items():
            o = data["overall"]
            print(f"\n== {label} ==")
            print(json.dumps(o, indent=1))
