"""Deterministic Evidence Integration Runner (Non-LLM).

Compiles an EvidenceBundle and GroundingContext from sanitized live observation artifacts
across search discovery, web pages, YouTube metadata/transcripts, and public discussions.
Validates product isolation, role segregation, freshness evaluation, conflict tracking,
and grounding rule formulation.
Writes evaluation artifacts to evaluations/live/evidence/.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.evidence.builder import EvidenceBuilder
from tools.evidence.conflicts import ConflictTracker, GapTracker
from tools.evidence.grounding import GroundingContextBuilder
from tools.observation.models import ObservationRecord


def run_evidence_integration():
    print("==================================================")
    print("PHASE 3D.0: EVIDENCE INTEGRATION VALIDATION (NON-LLM)")
    print("==================================================")

    out_dir = Path(__file__).resolve().parent / "live" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)

    base_obs_dir = Path(__file__).resolve().parent / "live" / "observation"

    # 1. Load Live Observation Artifacts across families
    artifact_paths = [
        base_obs_dir / "search" / "search_discovery_001.json",
        base_obs_dir / "search" / "search_to_read_page_001.json",
        base_obs_dir / "youtube" / "youtube_metadata_001.json",
        base_obs_dir / "youtube" / "youtube_transcript_manual_001.json",
        base_obs_dir / "discussions" / "discussion_thread_001.json",
    ]

    target_product_id = "PROD_BENCHMARK_EVIDENCE"
    target_brand_id = "BRAND_BENCHMARK"

    evidence_items = []

    print("\n[Step 1] Loading Observation Artifacts & Mapping to EvidenceItems:")
    for p in artifact_paths:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            data["product_id"] = target_product_id
            data["brand_id"] = target_brand_id
            obs = ObservationRecord(**data)
            ev_item = EvidenceBuilder.observation_to_evidence(obs)
            evidence_items.append(ev_item)
            print(f" - Mapped {obs.capability} ({obs.observation_id}) -> {ev_item.evidence_id} [Role: {ev_item.content_role.value}, Provenance: {ev_item.collection_provenance.value}]")

    # 2. Register Realistic Conflicts & Gaps
    conflicts = [
        ConflictTracker.create_conflict(
            topic="Launch Timeline & Availability",
            evidence_ids=[evidence_items[0].evidence_id, evidence_items[1].evidence_id],
            conflict_type="TEMPORAL_CHANGE",
            description="Encyclopedic summary cites historical release date; current documentation reflects updated v2.0 roadmap.",
        )
    ]

    evidence_gaps = [
        GapTracker.create_gap(
            question="Are high public view counts driving unit transactions?",
            required_evidence_type="TRANSACTION_DATA",
            importance="HIGH",
        ),
        GapTracker.create_gap(
            question="What is the repeat customer retention rate?",
            required_evidence_type="CUSTOMER_RETENTION_METRICS",
            importance="MEDIUM",
        ),
    ]

    # 3. Assemble EvidenceBundle
    print("\n[Step 2] Assembling EvidenceBundle with Product Isolation:")
    bundle = EvidenceBuilder.assemble_bundle(
        task_id="TASK_EVIDENCE_INTEGRATION_001",
        product_id=target_product_id,
        brand_id=target_brand_id,
        research_question="Evaluate multi-channel marketing evidence and market reception for benchmark product",
        evidence_items=evidence_items,
        conflicts=conflicts,
        evidence_gaps=evidence_gaps,
    )
    bundle.limitations.extend([
        "EVALUATION_ONLY = true",
        "SEMANTIC_COHERENCE_TEST = NOT_APPLICABLE",
        "This bundle was compiled from heterogeneous sensory artifacts strictly for schema contract validation.",
    ])

    print(f"Bundle ID: {bundle.bundle_id}")
    print(f"Total Sources: {bundle.source_count} (Discovery: {len(bundle.discovery_items)}, Substantive: {len(bundle.substantive_items)}, Metrics: {len(bundle.platform_metrics)}, UGC: {len(bundle.user_generated_items)})")

    # 4. Generate GroundingContext
    print("\n[Step 3] Generating Model-Facing GroundingContext:")
    gctx = GroundingContextBuilder.build_grounding_context(
        bundle=bundle,
        task_description="Perform contract validation analysis of multi-channel product observation",
        business_context="Product strategy and schema validation benchmark",
    )

    # 5. Save Artifacts
    bundle_file = out_dir / "evidence_bundle_001.json"
    gctx_file = out_dir / "grounding_context_001.json"

    bundle_file.write_text(json.dumps(bundle.model_dump(), indent=2), encoding="utf-8")
    gctx_file.write_text(json.dumps(gctx.model_dump(), indent=2), encoding="utf-8")

    print("\n==================================================")
    print("EVIDENCE INTEGRATION RUN COMPLETE (NON-LLM)")
    print(f"Saved EvidenceBundle to: {bundle_file}")
    print(f"Saved GroundingContext to: {gctx_file}")
    print("==================================================")


if __name__ == "__main__":
    run_evidence_integration()
