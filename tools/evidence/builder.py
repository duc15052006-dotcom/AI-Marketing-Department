"""Deterministic Evidence Builder & Bundle Assembler (Phase 3D.0 / 3D.1 / 3D.1.1 Hardened).

Transforms raw ObservationRecords into typed, bounded EvidenceItems and compiles
comprehensive EvidenceBundles with strict product isolation, content role segregation,
source family coverage auditing, structural bounded excerpts, and sampling preservation.
"""

from __future__ import annotations

import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from tools.evidence.conflicts import ConflictTracker, GapTracker
from tools.evidence.freshness import FreshnessEvaluator
from tools.evidence.models import (
    CollectionProvenance,
    ContentRole,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceGap,
    EvidenceItem,
    FreshnessPolicy,
    FreshnessPolicySource,
    FreshnessState,
    ResearchSourceCoverage,
    SourceFamily,
    SourceRelationship,
)
from tools.observation.models import ObservationRecord


class ProductIsolationViolationError(ValueError):
    """Raised when an EvidenceItem belonging to another product is added to a bundle."""
    pass


class ScopeViolationError(ValueError):
    """Raised when EvidenceItems with mismatched trusted scope are added to a bundle."""
    pass


class EvidenceBuilder:
    """Deterministic converter and compiler for observational evidence."""

    DEFAULT_MAX_CONTENT_CHARS = 4000

    @classmethod
    def observation_to_evidence(
        cls,
        obs: ObservationRecord,
        max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
        target_subject_domain: Optional[str] = None,
        custom_freshness_policy: Optional[FreshnessPolicy] = None,
    ) -> EvidenceItem:
        """Convert a raw ObservationRecord into a typed, bounded EvidenceItem."""
        # 1. Determine Stable ID Prefix
        cap = obs.capability
        if "youtube" in cap or "transcript" in cap:
            prefix = "EVID-YT"
        elif "forum" in cap or "discussion" in cap:
            prefix = "EVID-FORUM"
        elif "search" in cap:
            prefix = "EVID-SRCH"
        else:
            prefix = "EVID-WEB"
        evidence_id = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

        # 2. Extract Source Domain
        domain = ""
        if obs.source_url_or_id.startswith("http"):
            try:
                parsed = urllib.parse.urlparse(obs.source_url_or_id)
                domain = (parsed.hostname or "").lower()
            except Exception:
                domain = ""

        # 3. Parse and normalize dates
        col_at = obs.collected_at
        if isinstance(col_at, str):
            try:
                col_at = datetime.fromisoformat(col_at.replace("Z", "+00:00"))
            except Exception:
                col_at = datetime.now(timezone.utc)

        obs_at = obs.observed_at
        if isinstance(obs_at, str):
            try:
                obs_at = datetime.fromisoformat(obs_at.replace("Z", "+00:00"))
            except Exception:
                obs_at = None

        # 4. Determine Content Role & Source Family
        role = cls._infer_content_role(obs)
        col_prov = cls._infer_collection_provenance(obs)
        src_rel = cls._infer_source_relationship(obs, domain, target_subject_domain)
        src_fam = cls._infer_source_family(obs, domain, target_subject_domain)

        # 5. Evaluate Freshness
        fresh_state, fresh_days, fresh_policy_src = FreshnessEvaluator.evaluate(
            capability=obs.capability,
            collected_at=col_at,
            observed_at=obs_at,
            custom_policy=custom_freshness_policy,
        )

        # 6. Extract Structural Bounded Content
        bounded_text, original_len, included_len, truncated = cls._extract_structural_bounded_content(
            obs, max_content_chars
        )

        # 7. Extract Sampling Context
        norm = obs.normalized_data or {}
        sampling = norm.get("sampling_context", {})

        return EvidenceItem(
            evidence_id=evidence_id,
            observation_id=obs.observation_id,
            capability=obs.capability,
            product_id=obs.product_id,
            brand_id=obs.brand_id,
            run_id=obs.run_id,
            business_id=obs.business_id,
            project_id=obs.project_id,
            source_platform=obs.source_platform,
            source_type=obs.source_type,
            source_url_or_id=obs.source_url_or_id,
            source_domain=domain,
            collection_provenance=col_prov,
            source_relationship=src_rel,
            source_family=src_fam,
            source_provenance=col_prov,
            collection_method=obs.collection_method,
            backend_used=obs.backend_used,
            evidence_class=obs.evidence_class,
            content_trust=obs.content_trust,
            source_credibility=obs.source_credibility,
            content_truth_status=obs.content_truth_status,
            extraction_confidence=obs.extraction_confidence,
            collected_at=col_at,
            observed_at=obs_at,
            freshness_state=fresh_state,
            freshness_days=fresh_days,
            freshness_policy_source=fresh_policy_src,
            content_role=role,
            content_reference=obs.raw_reference,
            bounded_content=bounded_text,
            content_truncated=truncated,
            original_length=original_len,
            included_length=included_len,
            sampling_context=sampling,
            limitations=list(obs.limitations),
        )

    @classmethod
    def assemble_bundle(
        cls,
        task_id: str,
        product_id: str,
        brand_id: str,
        research_question: str,
        evidence_items: List[EvidenceItem],
        conflicts: Optional[List[EvidenceConflict]] = None,
        evidence_gaps: Optional[List[EvidenceGap]] = None,
        requested_source_families: Optional[List[SourceFamily]] = None,
        allow_cross_product: bool = False,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> EvidenceBundle:
        """Compile an EvidenceBundle with strict product isolation, coverage auditing, and segmented indices."""
        bundle_id = f"BNDL-{uuid.uuid4().hex[:8].upper()}"

        # 1. Product Isolation Check
        for item in evidence_items:
            if not allow_cross_product:
                if item.product_id != product_id:
                    raise ProductIsolationViolationError(
                        f"Product isolation violation: EvidenceItem '{item.evidence_id}' belongs to product '{item.product_id}', expected '{product_id}'."
                    )

        # 1b. Trusted Scope Isolation Check
        if evidence_items and (run_id or business_id or project_id):
            for item in evidence_items:
                if item.run_id != run_id:
                    raise ScopeViolationError(
                        f"Scope violation: EvidenceItem '{item.evidence_id}' has run_id '{item.run_id}', expected '{run_id}'."
                    )
                if item.business_id != business_id:
                    raise ScopeViolationError(
                        f"Scope violation: EvidenceItem '{item.evidence_id}' has business_id '{item.business_id}', expected '{business_id}'."
                    )
                if item.project_id != project_id:
                    raise ScopeViolationError(
                        f"Scope violation: EvidenceItem '{item.evidence_id}' has project_id '{item.project_id}', expected '{project_id}'."
                    )

        # 2. Deduplication Check (Exact URL / ID)
        seen_sources: Dict[str, str] = {}
        for item in evidence_items:
            source_key = item.source_url_or_id
            if source_key in seen_sources:
                item.duplicate_of = seen_sources[source_key]
            else:
                seen_sources[source_key] = item.evidence_id

        # 3. Segment by ContentRole
        discovery_ids: List[str] = []
        substantive_ids: List[str] = []
        metrics_ids: List[str] = []
        user_gen_ids: List[str] = []

        for item in evidence_items:
            if item.content_role == ContentRole.DISCOVERY:
                discovery_ids.append(item.evidence_id)
            elif item.content_role in (ContentRole.FETCHED_SOURCE_CONTENT, ContentRole.PRIMARY_CONTENT):
                substantive_ids.append(item.evidence_id)
            elif item.content_role == ContentRole.PLATFORM_REPORTED_METRIC:
                metrics_ids.append(item.evidence_id)
            elif item.content_role in (ContentRole.USER_GENERATED_CONTENT, ContentRole.TRANSCRIPT):
                user_gen_ids.append(item.evidence_id)

        # 4. Multi-Channel Source Family Coverage Audit
        req_families = requested_source_families or [
            SourceFamily.FIRST_PARTY_WEB,
            SourceFamily.SECONDARY_WEB,
            SourceFamily.VIDEO,
            SourceFamily.COMMUNITY,
        ]
        collected_families = list({item.source_family for item in evidence_items if item.source_family != SourceFamily.OTHER})
        missing_families = [f for f in req_families if f not in collected_families]

        if not missing_families:
            coverage_status = ResearchSourceCoverage.PASS
        elif len(collected_families) > 0:
            coverage_status = ResearchSourceCoverage.PARTIAL
        else:
            coverage_status = ResearchSourceCoverage.FAIL

        # 5. Compute Diversity & Summary Metadata
        unique_domains = {item.source_domain for item in evidence_items if item.source_domain}
        unique_platforms = {item.source_platform for item in evidence_items}

        first_party = sum(1 for i in evidence_items if i.source_relationship == SourceRelationship.FIRST_PARTY_TO_SUBJECT)
        secondary_sources = sum(1 for i in evidence_items if i.source_relationship == SourceRelationship.SECONDARY_SOURCE)
        user_gen = sum(1 for i in evidence_items if i.source_relationship == SourceRelationship.USER_GENERATED or i.content_role == ContentRole.USER_GENERATED_CONTENT)

        fresh_summary: Dict[str, int] = {}
        for i in evidence_items:
            fresh_summary[i.freshness_state.value] = fresh_summary.get(i.freshness_state.value, 0) + 1

        prov_summary: Dict[str, int] = {}
        for i in evidence_items:
            prov_summary[i.collection_provenance.value] = prov_summary.get(i.collection_provenance.value, 0) + 1

        sampling_summary: Dict[str, Any] = {
            "total_evidence_count": len(evidence_items),
            "discovery_count": len(discovery_ids),
            "substantive_count": len(substantive_ids),
            "metrics_count": len(metrics_ids),
            "user_generated_count": len(user_gen_ids),
            "unique_domain_count": len(unique_domains),
            "unique_platform_count": len(unique_platforms),
            "source_family_coverage": coverage_status.value,
        }

        return EvidenceBundle(
            bundle_id=bundle_id,
            task_id=task_id,
            product_id=product_id,
            brand_id=brand_id,
            run_id=run_id,
            business_id=business_id,
            project_id=project_id,
            research_question=research_question,
            evidence_items=evidence_items,
            discovery_items=discovery_ids,
            substantive_items=substantive_ids,
            platform_metrics=metrics_ids,
            user_generated_items=user_gen_ids,
            requested_source_families=req_families,
            collected_source_families=collected_families,
            missing_source_families=missing_families,
            research_source_coverage=coverage_status,
            conflicts=conflicts or [],
            evidence_gaps=evidence_gaps or [],
            source_count=len(evidence_items),
            unique_domain_count=len(unique_domains),
            platform_count=len(unique_platforms),
            first_party_count=first_party,
            secondary_source_count=secondary_sources,
            user_generated_count=user_gen,
            freshness_summary=fresh_summary,
            sampling_summary=sampling_summary,
            provenance_summary=prov_summary,
            limitations=[
                "Evidence integration compiled deterministically without LLM synthesis or claim creation.",
                "Search snippets represent discovery pointers and are segregated from substantive fetched page evidence.",
                "Platform metrics and user comments remain unverified empirical observations.",
            ],
        )

    # -------------------------------------------------------------
    # Helper Inferences
    # -------------------------------------------------------------
    @classmethod
    def _infer_content_role(cls, obs: ObservationRecord) -> ContentRole:
        cap = obs.capability
        if cap == "search_web":
            return ContentRole.DISCOVERY
        elif cap == "read_page":
            return ContentRole.FETCHED_SOURCE_CONTENT
        elif cap == "analyze_url":
            return ContentRole.METADATA
        elif cap == "youtube_metadata":
            return ContentRole.PLATFORM_REPORTED_METRIC
        elif cap == "read_transcript":
            return ContentRole.TRANSCRIPT
        elif cap in ("read_forum_thread", "search_public_discussions"):
            return ContentRole.USER_GENERATED_CONTENT
        return ContentRole.OTHER

    @classmethod
    def _infer_collection_provenance(cls, obs: ObservationRecord) -> CollectionProvenance:
        norm = obs.normalized_data or {}
        backend = obs.backend_used

        if backend == "search_wikipedia_opensearch" or norm.get("thread", {}).get("upstream_provenance") == "FIRST_PARTY_OFFICIAL_API":
            return CollectionProvenance.FIRST_PARTY_OFFICIAL_API
        elif backend == "http_static":
            return CollectionProvenance.DIRECT_PUBLISHER_PAGE
        elif backend == "search_duckduckgo_html":
            return CollectionProvenance.UNOFFICIAL_HTML_PARSE
        elif backend == "search_searxng":
            return CollectionProvenance.SELF_HOSTED_META_SEARCH
        elif "algolia" in backend or norm.get("upstream_provenance") == "THIRD_PARTY_SEARCH_INDEX":
            return CollectionProvenance.THIRD_PARTY_SEARCH_INDEX
        elif backend == "youtube_ytdlp":
            return CollectionProvenance.PLATFORM_PUBLIC_EXTRACTION
        elif "discussion" in backend or "forum" in backend:
            return CollectionProvenance.PLATFORM_PUBLIC_EXTRACTION
        return CollectionProvenance.OTHER

    @classmethod
    def _infer_source_relationship(
        cls, obs: ObservationRecord, domain: str, target_subject_domain: Optional[str]
    ) -> SourceRelationship:
        if target_subject_domain and domain and (domain == target_subject_domain.lower() or domain.endswith("." + target_subject_domain.lower())):
            return SourceRelationship.FIRST_PARTY_TO_SUBJECT
        if obs.capability in ("read_forum_thread", "search_public_discussions"):
            return SourceRelationship.USER_GENERATED
        if obs.capability in ("youtube_metadata", "read_transcript"):
            return SourceRelationship.SECONDARY_SOURCE
        if "wikipedia.org" in domain or "news" in domain or "blog" in domain or "github.com" in domain:
            return SourceRelationship.SECONDARY_SOURCE
        return SourceRelationship.UNKNOWN

    @classmethod
    def _infer_source_family(
        cls, obs: ObservationRecord, domain: str, target_subject_domain: Optional[str]
    ) -> SourceFamily:
        cap = obs.capability
        if cap == "search_web":
            return SourceFamily.SEARCH_DISCOVERY
        if cap in ("youtube_metadata", "read_transcript"):
            return SourceFamily.VIDEO
        if cap in ("read_forum_thread", "search_public_discussions"):
            return SourceFamily.COMMUNITY
        if target_subject_domain and domain and (domain == target_subject_domain.lower() or domain.endswith("." + target_subject_domain.lower())):
            return SourceFamily.FIRST_PARTY_WEB
        if cap in ("read_page", "analyze_url"):
            return SourceFamily.SECONDARY_WEB
        return SourceFamily.OTHER

    @classmethod
    def _extract_structural_bounded_content(
        cls, obs: ObservationRecord, max_chars: int
    ) -> Tuple[str, int, int, bool]:
        """Deterministically format and bound observational payload using structural heuristics."""
        norm = obs.normalized_data or {}
        raw_text = ""

        if obs.capability == "read_page":
            title = norm.get("title") or ""
            headings = norm.get("headings") or []
            main_text = norm.get("main_text") or ""
            h_texts = []
            for h in headings[:8]:
                if isinstance(h, dict):
                    h_texts.append(h.get("text") or str(h))
                else:
                    h_texts.append(str(h))
            headings_str = " | ".join(h_texts) if h_texts else ""
            raw_text = f"Title: {title}\nHeadings: {headings_str}\n\nContent:\n{main_text}"
        elif obs.capability == "search_web":
            results = norm.get("search_results", {}).get("results", [])
            lines = [f"Rank {r.get('rank')}: {r.get('title')} ({r.get('url')})\nSnippet: {r.get('snippet')}" for r in results]
            raw_text = "\n\n".join(lines)
        elif obs.capability == "youtube_metadata":
            raw_text = f"Title: {norm.get('title')}\nChannel: {norm.get('channel_name')}\nDuration: {norm.get('duration_seconds')}s\nViews: {norm.get('reported_view_count')}\nLikes: {norm.get('reported_like_count')}\nDescription: {norm.get('description', '')[:500]}"
        elif obs.capability == "read_transcript":
            segments = norm.get("segments", [])
            lines = [f"[{s.get('start_seconds')}s] {s.get('text')}" for s in segments]
            raw_text = "\n".join(lines)
        elif obs.capability == "read_forum_thread":
            thread = norm.get("thread", {})
            title = thread.get("title", "")
            body = thread.get("body") or ""
            comments = thread.get("comments", [])
            c_lines = [f"Comment by {c.get('author_display_name')}: {c.get('body')}" for c in comments[:20]]
            raw_text = f"Thread: {title}\nBody: {body}\n\n" + "\n".join(c_lines)
        elif obs.capability == "search_public_discussions":
            summary = norm.get("search_summary", {})
            threads = summary.get("threads", [])
            lines = [f"Hit: {t.get('title')} ({t.get('thread_url')}) - Score: {t.get('reported_score')}" for t in threads]
            raw_text = "\n".join(lines)
        else:
            raw_text = str(norm)

        original_len = len(raw_text)
        if original_len > max_chars:
            bounded = raw_text[:max_chars]
            return bounded, original_len, len(bounded), True
        return raw_text, original_len, original_len, False
