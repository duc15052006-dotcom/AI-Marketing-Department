"""Deterministic Grounding Context Generator (Phase 3D.0 / 3D.1 / 3D.1.3 Hardened).

Formats EvidenceBundles into model-facing GroundingContext structures containing
bounded evidence items, structured relevance traces, research dimension suitability mappings,
unresolved conflicts, explicit empirical gaps, grounding metadata, and strict grounding constraints.
Zero chain-of-thought, zero marketing hallucinations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from tools.evidence.models import EvidenceBundle, GroundingContext, GroundingMetadata


class GroundingContextBuilder:
    """Constructs model-facing GroundingContext contracts from EvidenceBundles."""

    @classmethod
    def build_grounding_context(
        cls,
        bundle: EvidenceBundle,
        task_description: str,
        business_context: str,
        known_facts: Optional[List[str]] = None,
    ) -> GroundingContext:
        """Compile a GroundingContext contract from an EvidenceBundle."""
        # 1. Build Grounding Metadata with Coverage & Dimension Audit
        grounding_meta = GroundingMetadata(
            bundle_id=bundle.bundle_id,
            task_id=bundle.task_id,
            collected_at=bundle.created_at,
            total_sources=bundle.source_count,
            relevant_sources=bundle.relevant_source_count,
            rejected_sources=len(bundle.rejected_evidence),
            unique_domains=bundle.unique_domain_count,
            unique_platforms=bundle.platform_count,
            discovery_sources=len(bundle.discovery_items),
            substantive_sources=len(bundle.substantive_items),
            platform_metric_sources=len(bundle.platform_metrics),
            user_generated_sources=len(bundle.user_generated_items),
            requested_source_families=[f.value for f in bundle.requested_source_families],
            collected_source_families=[f.value for f in bundle.collected_source_families],
            missing_source_families=[f.value for f in bundle.missing_source_families],
            source_family_coverage=bundle.research_source_coverage.value,
            video_substantive_coverage=bundle.video_substantive_coverage.value,
            research_dimension_coverage=bundle.research_dimension_coverage.value,
            semantic_coherence=bundle.semantic_coherence.value,
        )

        # 2. Format Evidence Items with Structured Traces
        items_payload: List[Dict[str, Any]] = []
        for item in bundle.evidence_items:
            items_payload.append({
                "evidence_id": item.evidence_id,
                "capability": item.capability,
                "content_role": getattr(item.content_role, "value", str(item.content_role)),
                "source_platform": item.source_platform,
                "source_domain": item.source_domain,
                "source_family": getattr(item.source_family, "value", str(item.source_family)),
                "collection_provenance": getattr(item.collection_provenance, "value", str(item.collection_provenance)),
                "source_relationship": getattr(item.source_relationship, "value", str(item.source_relationship)),
                "relevance_status": getattr(item.relevance_status, "value", str(item.relevance_status)),
                "relevance_reason": item.relevance_reason,
                "structured_traces": [t.model_dump() for t in item.structured_traces],
                "evidence_class": getattr(item.evidence_class, "value", str(item.evidence_class)),
                "content_trust": getattr(item.content_trust, "value", str(item.content_trust)),
                "source_credibility": getattr(item.source_credibility, "value", str(item.source_credibility)),
                "content_truth_status": getattr(item.content_truth_status, "value", str(item.content_truth_status)),
                "freshness_state": getattr(item.freshness_state, "value", str(item.freshness_state)),
                "freshness_days": item.freshness_days,
                "freshness_policy_source": getattr(item.freshness_policy_source, "value", str(item.freshness_policy_source)),
                "bounded_content": item.bounded_content,
                "content_truncated": item.content_truncated,
                "duplicate_of": item.duplicate_of,
                "limitations": item.limitations,
            })

        # 3. Format Research Dimensions
        dimensions_payload = [d.model_dump() for d in bundle.research_dimensions]

        # 4. Format Conflicts
        conflicts_payload = [c.model_dump() for c in bundle.conflicts]

        # 5. Format Gaps & Unknown Facts
        gaps_payload = [g.model_dump() for g in bundle.evidence_gaps]
        unknown_facts = [
            f"Missing {g.required_evidence_type}: {g.question}"
            for g in bundle.evidence_gaps
        ]

        # 6. Formulate Notes & Limitations
        sampling_notes = [
            f"Total evidence items: {bundle.source_count} ({bundle.relevant_source_count} admitted, {len(bundle.rejected_evidence)} rejected).",
            f"Source Family Coverage: {bundle.research_source_coverage.value} | Video Content Depth: {bundle.video_substantive_coverage.value}.",
            f"Research Dimension Coverage: {bundle.research_dimension_coverage.value} ({len(bundle.research_dimensions)} dimensions evaluated).",
            f"Discovery items: {len(bundle.discovery_items)}, Substantive items: {len(bundle.substantive_items)}, Metrics: {len(bundle.platform_metrics)}, UGC items: {len(bundle.user_generated_items)}.",
        ]

        freshness_notes = [
            f"Freshness breakdown: {bundle.freshness_summary}",
        ]

        source_limitations = list(bundle.limitations)

        return GroundingContext(
            task=task_description,
            business_context=business_context,
            product_id=bundle.product_id,
            brand_id=bundle.brand_id,
            run_id=bundle.run_id,
            business_id=bundle.business_id,
            project_id=bundle.project_id,
            grounding_metadata=grounding_meta,
            known_facts=known_facts or [
                f"Empirical evidence gathered for research question: '{bundle.research_question}'."
            ],
            unknown_facts=unknown_facts,
            evidence_bundle_reference=bundle.bundle_id,
            evidence_items=items_payload,
            research_dimensions=dimensions_payload,
            conflicts=conflicts_payload,
            evidence_gaps=gaps_payload,
            sampling_notes=sampling_notes,
            freshness_notes=freshness_notes,
            source_limitations=source_limitations,
        )
