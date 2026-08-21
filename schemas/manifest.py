"""Phase 4.3C.6: Benchmark Run Manifest and Deterministic Fingerprint Schema.

Defines:
1. BenchmarkRunManifest: Authoritative metadata container for a versioned benchmark execution run.
2. compute_run_fingerprint: Deterministic SHA-256 calculation over immutable benchmark inputs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional
from schemas.base import BaseModel, Field


def compute_run_fingerprint(
    benchmark_id: str,
    execution_generation: str,
    handoff_contract_version: str,
    benchmark_spec_hash: str,
    product_facts_hash: str,
    evidence_bundle_hash: str,
    single_prompt_hash: str,
    provider_id: str,
    requested_model: str,
    strict_model_pin: bool,
    model_call_timeout_seconds: float,
    benchmark_schema_version: str = "v2",
    candidate_schema_version: str = "v2",
) -> str:
    """Compute a deterministic, timestamp-free SHA-256 fingerprint for a benchmark run."""
    fingerprint_dict = {
        "benchmark_id": benchmark_id,
        "benchmark_schema_version": benchmark_schema_version,
        "benchmark_spec_hash": benchmark_spec_hash,
        "candidate_schema_version": candidate_schema_version,
        "evidence_bundle_hash": evidence_bundle_hash,
        "execution_generation": execution_generation,
        "handoff_contract_version": handoff_contract_version,
        "model_call_timeout_seconds": float(model_call_timeout_seconds),
        "product_facts_hash": product_facts_hash,
        "provider_id": provider_id,
        "requested_model": requested_model,
        "single_prompt_hash": single_prompt_hash,
        "strict_model_pin": bool(strict_model_pin),
    }
    canonical_json = json.dumps(fingerprint_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class BenchmarkRunManifest(BaseModel):
    """Authoritative metadata and provenance manifest for a benchmark execution run."""
    benchmark_id: str = "BENCHMARK-PHASE4-3-UNSEEN-AI-SPEAKING"
    run_id: str
    execution_generation: str = "phase4_3_v2"
    handoff_contract_version: str = "v2"
    benchmark_schema_version: str = "v2"
    candidate_schema_version: str = "v2"
    benchmark_spec_hash: str
    product_facts_hash: str
    evidence_bundle_hash: str
    single_prompt_hash: str
    provider_id: str
    requested_model: str
    strict_model_pin: bool = True
    model_call_timeout_seconds: float = 180.0
    run_fingerprint: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        benchmark_id: str,
        run_id: str,
        execution_generation: str,
        handoff_contract_version: str,
        benchmark_spec_hash: str,
        product_facts_hash: str,
        evidence_bundle_hash: str,
        single_prompt_hash: str,
        provider_id: str,
        requested_model: str,
        strict_model_pin: bool = True,
        model_call_timeout_seconds: float = 180.0,
        benchmark_schema_version: str = "v2",
        candidate_schema_version: str = "v2",
    ) -> BenchmarkRunManifest:
        fingerprint = compute_run_fingerprint(
            benchmark_id=benchmark_id,
            execution_generation=execution_generation,
            handoff_contract_version=handoff_contract_version,
            benchmark_spec_hash=benchmark_spec_hash,
            product_facts_hash=product_facts_hash,
            evidence_bundle_hash=evidence_bundle_hash,
            single_prompt_hash=single_prompt_hash,
            provider_id=provider_id,
            requested_model=requested_model,
            strict_model_pin=strict_model_pin,
            model_call_timeout_seconds=model_call_timeout_seconds,
            benchmark_schema_version=benchmark_schema_version,
            candidate_schema_version=candidate_schema_version,
        )
        return cls(
            benchmark_id=benchmark_id,
            run_id=run_id,
            execution_generation=execution_generation,
            handoff_contract_version=handoff_contract_version,
            benchmark_schema_version=benchmark_schema_version,
            candidate_schema_version=candidate_schema_version,
            benchmark_spec_hash=benchmark_spec_hash,
            product_facts_hash=product_facts_hash,
            evidence_bundle_hash=evidence_bundle_hash,
            single_prompt_hash=single_prompt_hash,
            provider_id=provider_id,
            requested_model=requested_model,
            strict_model_pin=strict_model_pin,
            model_call_timeout_seconds=model_call_timeout_seconds,
            run_fingerprint=fingerprint,
        )
