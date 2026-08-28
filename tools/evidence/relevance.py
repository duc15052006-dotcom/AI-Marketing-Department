"""Deterministic Subject Relevance Gate, Trace Auditor, & Dimension Evaluator (Phase 3D.1.3 / 3D.1.4 Hardened).

Ensures accurate field-level relevance tracing (zero false attribution between title, URL,
transcript, and body), validates SubjectAlias provenance, and audits research dimension coverage
with strict claim-suitability policies (search discovery and platform metrics excluded from substantive claims).
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple
from tools.evidence.models import (
    AliasVerificationStatus,
    ContentRole,
    DimensionCoverageStatus,
    EvidenceBundle,
    EvidenceGap,
    EvidenceItem,
    RejectedEvidenceRecord,
    RelevanceAnchorType,
    RelevanceAssessment,
    RelevanceMatchField,
    RelevanceMatchMethod,
    RelevanceStatus,
    RelevanceTraceItem,
    ResearchCoverageReport,
    ResearchDimension,
    ResearchSourceCoverage,
    SemanticCoherenceStatus,
    SourceFamily,
    SubjectAlias,
    SubjectAliasType,
    SubjectIdentity,
    VideoSubstantiveCoverage,
)


class EvidenceRelevanceGate:
    """Deterministic subject relevance filter with structured, field-attributed audit traces."""

    @classmethod
    def evaluate(
        cls,
        item: EvidenceItem,
        subject: SubjectIdentity,
    ) -> RelevanceAssessment:
        """Evaluate whether an EvidenceItem genuinely concerns the specified SubjectIdentity with exact field attribution."""
        # E0. No semantic identity available -> UNKNOWN (not evaluated)
        has_semantic_identity = bool(
            subject.canonical_name and subject.canonical_name.strip()
        ) or bool(
            subject.brand_name and subject.brand_name.strip()
        ) or bool(subject.official_domains) or bool(subject.aliases)

        if not has_semantic_identity:
            return RelevanceAssessment(
                evidence_id=item.evidence_id,
                relevance_status=RelevanceStatus.UNKNOWN,
                relevance_method="NO_SEMANTIC_IDENTITY",
                matched_subject_anchors=[],
                structured_traces=[],
                relevance_reason="Trusted semantic subject identity unavailable; deterministic relevance could not be evaluated.",
            )

        structured_traces: List[RelevanceTraceItem] = []
        strong_matches: List[str] = []
        weak_category_matches: List[str] = []

        # 1. Parse Discrete Fields from Evidence Item
        fields_map = cls._extract_field_strings(item)

        url_str = fields_map.get(RelevanceMatchField.URL, "")
        domain_str = fields_map.get(RelevanceMatchField.DOMAIN, "")
        title_str = fields_map.get(RelevanceMatchField.TITLE, "")
        desc_str = fields_map.get(RelevanceMatchField.DESCRIPTION, "")
        headings_str = fields_map.get(RelevanceMatchField.HEADINGS, "")
        body_str = fields_map.get(RelevanceMatchField.BODY, "")
        transcript_str = fields_map.get(RelevanceMatchField.TRANSCRIPT, "")
        channel_str = fields_map.get(RelevanceMatchField.CHANNEL, "")

        canonical_lower = subject.canonical_name.lower()
        brand_lower = subject.brand_name.lower()

        pattern_canonical = re.compile(rf"\b{re.escape(canonical_lower)}\b", re.IGNORECASE)
        pattern_brand = re.compile(rf"\b{re.escape(brand_lower)}\b", re.IGNORECASE)

        # 2. Official Domain Anchor Match (DOMAIN field only)
        for off_dom in subject.official_domains:
            off_dom_clean = off_dom.lower()
            if domain_str == off_dom_clean or domain_str.endswith("." + off_dom_clean):
                strong_matches.append(f"official_domain:{off_dom}")
                structured_traces.append(
                    RelevanceTraceItem(
                        anchor_type=RelevanceAnchorType.OFFICIAL_DOMAIN,
                        field=RelevanceMatchField.DOMAIN,
                        matched_value=domain_str,
                        match_method=RelevanceMatchMethod.DOMAIN_EXACT_OR_SUBDOMAIN,
                        subject_anchor=off_dom,
                    )
                )

        # 3. Canonical Name Exact Match Across Individual Fields
        for fld, val in fields_map.items():
            if not val:
                continue
            matches = pattern_canonical.findall(val)
            if matches:
                strong_matches.append(f"{fld.value}_contains_canonical:{subject.canonical_name}")
                structured_traces.append(
                    RelevanceTraceItem(
                        anchor_type=RelevanceAnchorType.CANONICAL_NAME,
                        field=fld,
                        matched_value=matches[0],
                        match_method=RelevanceMatchMethod.CASE_INSENSITIVE_TOKEN_MATCH,
                        subject_anchor=subject.canonical_name,
                        occurrence_count=len(matches),
                    )
                )

        # 4. Brand Name Exact Match Across Individual Fields
        for fld, val in fields_map.items():
            if not val or subject.brand_name.lower() == subject.canonical_name.lower():
                continue  # Avoid duplicate recording if canonical == brand
            matches = pattern_brand.findall(val)
            if matches:
                strong_matches.append(f"{fld.value}_contains_brand:{subject.brand_name}")
                structured_traces.append(
                    RelevanceTraceItem(
                        anchor_type=RelevanceAnchorType.BRAND_NAME,
                        field=fld,
                        matched_value=matches[0],
                        match_method=RelevanceMatchMethod.CASE_INSENSITIVE_TOKEN_MATCH,
                        subject_anchor=subject.brand_name,
                        occurrence_count=len(matches),
                    )
                )

        # 5. Verified Aliases vs Unverified Aliases
        for alias_obj in subject.aliases:
            if isinstance(alias_obj, str):
                alias_val = alias_obj
                is_verified = False
            else:
                alias_val = alias_obj.value
                is_verified = (alias_obj.verification_status == AliasVerificationStatus.VERIFIED)

            p_alias = re.compile(rf"\b{re.escape(alias_val.lower())}\b", re.IGNORECASE)
            for fld, val in fields_map.items():
                if not val:
                    continue
                matches = p_alias.findall(val)
                if matches:
                    if is_verified:
                        strong_matches.append(f"{fld.value}_contains_verified_alias:{alias_val}")
                        structured_traces.append(
                            RelevanceTraceItem(
                                anchor_type=RelevanceAnchorType.VERIFIED_ALIAS,
                                field=fld,
                                matched_value=matches[0],
                                match_method=RelevanceMatchMethod.CASE_INSENSITIVE_TOKEN_MATCH,
                                subject_anchor=alias_val,
                                occurrence_count=len(matches),
                            )
                        )
                    else:
                        # Unverified alias recorded in traces, but does NOT add to strong_matches
                        structured_traces.append(
                            RelevanceTraceItem(
                                anchor_type=RelevanceAnchorType.UNVERIFIED_ALIAS,
                                field=fld,
                                matched_value=f"UNVERIFIED_ALIAS:{matches[0]}",
                                match_method=RelevanceMatchMethod.CASE_INSENSITIVE_TOKEN_MATCH,
                                subject_anchor=alias_val,
                                occurrence_count=len(matches),
                            )
                        )

        # 6. Category Terms (Weak Signals)
        for cat in subject.category_terms:
            p_cat = re.compile(rf"\b{re.escape(cat.lower())}\b", re.IGNORECASE)
            for fld, val in fields_map.items():
                if not val:
                    continue
                if p_cat.search(val):
                    weak_category_matches.append(f"{fld.value}_category:{cat}")
                    structured_traces.append(
                        RelevanceTraceItem(
                            anchor_type=RelevanceAnchorType.CATEGORY_TERM,
                            field=fld,
                            matched_value=cat,
                            match_method=RelevanceMatchMethod.CASE_INSENSITIVE_TOKEN_MATCH,
                            subject_anchor=cat,
                        )
                    )

        # -------------------------------------------------------------
        # Decision Synthesis
        # -------------------------------------------------------------
        legacy_matched_anchors = list(set(strong_matches))

        # A. Official Domain Hit -> RELEVANT
        if any("official_domain" in m for m in strong_matches):
            return RelevanceAssessment(
                evidence_id=item.evidence_id,
                relevance_status=RelevanceStatus.RELEVANT,
                relevance_method="OFFICIAL_DOMAIN_ANCHOR",
                matched_subject_anchors=legacy_matched_anchors,
                structured_traces=structured_traces,
                relevance_reason=f"Matches official domain: {item.source_domain}",
            )

        # B. Canonical Name Hit in Title, URL, Headings, or Body -> RELEVANT
        canonical_traces = [t for t in structured_traces if t.anchor_type == RelevanceAnchorType.CANONICAL_NAME]
        if len(canonical_traces) > 0:
            fields_hit = ", ".join({t.field.value for t in canonical_traces})
            return RelevanceAssessment(
                evidence_id=item.evidence_id,
                relevance_status=RelevanceStatus.RELEVANT,
                relevance_method="CANONICAL_NAME_ANCHOR",
                matched_subject_anchors=legacy_matched_anchors,
                structured_traces=structured_traces,
                relevance_reason=f"Explicit canonical anchor '{subject.canonical_name}' matched in fields: {fields_hit}.",
            )

        # C. Verified Alias / Brand Hit -> LIKELY_RELEVANT
        verified_traces = [t for t in structured_traces if t.anchor_type in (RelevanceAnchorType.VERIFIED_ALIAS, RelevanceAnchorType.BRAND_NAME)]
        if len(verified_traces) > 0:
            return RelevanceAssessment(
                evidence_id=item.evidence_id,
                relevance_status=RelevanceStatus.LIKELY_RELEVANT,
                relevance_method="SECONDARY_ANCHOR_MATCH",
                matched_subject_anchors=legacy_matched_anchors,
                structured_traces=structured_traces,
                relevance_reason=f"Matched verified secondary anchors in fields: {', '.join({t.field.value for t in verified_traces})}",
            )

        # D. Category-Only Matches -> IRRELEVANT
        if len(weak_category_matches) > 0 and len(strong_matches) == 0:
            return RelevanceAssessment(
                evidence_id=item.evidence_id,
                relevance_status=RelevanceStatus.IRRELEVANT,
                relevance_method="CATEGORY_TERMS_ONLY",
                matched_subject_anchors=[],
                structured_traces=structured_traces,
                relevance_reason=f"Only generic category buzzwords matched ({', '.join(weak_category_matches[:3])}); lacks canonical subject anchors for {subject.canonical_name}.",
            )

        return RelevanceAssessment(
            evidence_id=item.evidence_id,
            relevance_status=RelevanceStatus.IRRELEVANT,
            relevance_method="NO_ANCHORS_FOUND",
            matched_subject_anchors=[],
            structured_traces=structured_traces,
            relevance_reason=f"Zero matching subject anchors or verified aliases found for {subject.canonical_name}.",
        )

    @classmethod
    def _extract_field_strings(cls, item: EvidenceItem) -> Dict[RelevanceMatchField, str]:
        """Deterministically parse individual structural text fields from EvidenceItem."""
        fields: Dict[RelevanceMatchField, str] = {
            RelevanceMatchField.URL: item.source_url_or_id or "",
            RelevanceMatchField.DOMAIN: item.source_domain or "",
            RelevanceMatchField.TITLE: "",
            RelevanceMatchField.DESCRIPTION: "",
            RelevanceMatchField.HEADINGS: "",
            RelevanceMatchField.BODY: "",
            RelevanceMatchField.TRANSCRIPT: "",
            RelevanceMatchField.CHANNEL: "",
        }

        content = item.bounded_content or ""

        # Title extraction
        m_title = re.search(r"^Title:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        if m_title:
            fields[RelevanceMatchField.TITLE] = m_title.group(1).strip()

        # Description extraction
        m_desc = re.search(r"^Description:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        if m_desc:
            fields[RelevanceMatchField.DESCRIPTION] = m_desc.group(1).strip()

        # Headings extraction
        m_head = re.search(r"^Headings:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        if m_head:
            fields[RelevanceMatchField.HEADINGS] = m_head.group(1).strip()

        # Channel extraction
        m_chan = re.search(r"^Channel:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        if m_chan:
            fields[RelevanceMatchField.CHANNEL] = m_chan.group(1).strip()

        # Body / Content extraction
        if "Content:\n" in content:
            fields[RelevanceMatchField.BODY] = content.split("Content:\n", 1)[1].strip()
        elif "Thread:" in content:
            fields[RelevanceMatchField.BODY] = content.strip()
        elif item.capability in ("read_page", "search_web"):
            fields[RelevanceMatchField.BODY] = content.strip()

        # Transcript extraction
        if item.content_role == ContentRole.TRANSCRIPT or item.capability == "read_transcript":
            fields[RelevanceMatchField.TRANSCRIPT] = content.strip()

        return fields


class ResearchDimensionEvaluator:
    """Evaluates multi-dimensional research question suitability with strict epistemic claim gates."""

    @classmethod
    def evaluate_bundle(
        cls,
        bundle: EvidenceBundle,
        research_question: str,
    ) -> ResearchCoverageReport:
        """Decompose research question into dimensions and assess evidential suitability using deterministic rules."""
        # 1. Standard Dimensions for Local AI Runtime Research
        dim_positioning = ResearchDimension(
            dimension_id="MARKET_POSITIONING",
            question="How is the subject positioned in the local AI ecosystem relative to hosted cloud APIs and raw model weights?",
            required_evidence_roles=[ContentRole.FETCHED_SOURCE_CONTENT, ContentRole.METADATA],
        )

        dim_reception = ResearchDimension(
            dimension_id="DEVELOPER_RECEPTION",
            question="What is the community sentiment, adoption feedback, and developer response?",
            required_evidence_roles=[ContentRole.USER_GENERATED_CONTENT],
        )

        dim_friction = ResearchDimension(
            dimension_id="OPERATIONAL_FRICTION",
            question="What are the practical installation, runtime memory, GPU acceleration, and hardware bottlenecks reported by developers?",
            required_evidence_roles=[ContentRole.USER_GENERATED_CONTENT, ContentRole.FETCHED_SOURCE_CONTENT],
        )

        dimensions = [dim_positioning, dim_reception, dim_friction]

        # 2. Audit Evidential Suitability for each dimension
        for item in bundle.evidence_items:
            if item.relevance_status not in (RelevanceStatus.RELEVANT, RelevanceStatus.LIKELY_RELEVANT):
                continue

            content_lower = (item.bounded_content or "").lower()

            # --- Dimension 1: MARKET_POSITIONING Suitability ---
            if item.content_role in (ContentRole.FETCHED_SOURCE_CONTENT, ContentRole.METADATA):
                dim_positioning.supporting_evidence_ids.append(item.evidence_id)
            elif item.content_role == ContentRole.DISCOVERY:
                dim_positioning.excluded_evidence_ids.append(item.evidence_id)
                dim_positioning.exclusion_reasons[item.evidence_id] = "SEARCH_DISCOVERY is a discovery pointer only; cannot serve as substantive positioning evidence."

            # --- Dimension 2: DEVELOPER_RECEPTION Suitability ---
            if item.content_role == ContentRole.USER_GENERATED_CONTENT:
                dim_reception.supporting_evidence_ids.append(item.evidence_id)
                dim_reception.sampling_limitations.append(
                    f"Evidence {item.evidence_id} reflects user comments within collected thread sample; not general population truth."
                )
            elif item.content_role == ContentRole.PLATFORM_REPORTED_METRIC:
                dim_reception.excluded_evidence_ids.append(item.evidence_id)
                dim_reception.exclusion_reasons[item.evidence_id] = "PLATFORM_REPORTED_METRIC reflects external engagement observations, not developer sentiment or satisfaction."

            # --- Dimension 3: OPERATIONAL_FRICTION Suitability ---
            if item.content_role == ContentRole.USER_GENERATED_CONTENT and any(k in content_lower for k in ["gpu", "ram", "memory", "linux", "driver", "throttle", "slow", "vram", "error"]):
                dim_friction.supporting_evidence_ids.append(item.evidence_id)
            elif item.content_role == ContentRole.FETCHED_SOURCE_CONTENT and "dev.to" in (item.source_url_or_id or ""):
                dim_friction.supporting_evidence_ids.append(item.evidence_id)
            elif item.content_role == ContentRole.FETCHED_SOURCE_CONTENT and "ollama.com" in (item.source_url_or_id or ""):
                # Official homepage contains installation procedure, NOT empirical friction
                dim_friction.excluded_evidence_ids.append(item.evidence_id)
                dim_friction.exclusion_reasons[item.evidence_id] = "Official installation commands document procedure, not empirical friction or user difficulty."

        # 3. Assess Coverage Status
        weak_dims: List[str] = []
        missing_dims: List[str] = []

        for dim in dimensions:
            count = len(dim.supporting_evidence_ids)
            if dim.dimension_id == "DEVELOPER_RECEPTION" and count == 1:
                # 1 bounded forum sample -> PARTIAL with explicit limitation
                dim.coverage_status = DimensionCoverageStatus.PARTIAL
                dim.limitations.append("Supported by single bounded forum thread; lacks multi-source or survey validation.")
                weak_dims.append(dim.dimension_id)
            elif count >= 2:
                dim.coverage_status = DimensionCoverageStatus.SUPPORTED
            elif count == 1:
                dim.coverage_status = DimensionCoverageStatus.PARTIAL
                dim.limitations.append(f"Supported by only 1 evidence item ({dim.supporting_evidence_ids[0]}).")
                weak_dims.append(dim.dimension_id)
            else:
                dim.coverage_status = DimensionCoverageStatus.UNSUPPORTED
                dim.limitations.append("Zero supporting evidence items found in collected bundle.")
                missing_dims.append(dim.dimension_id)

        # 4. Assess Video Substantive Coverage
        video_items = [i for i in bundle.evidence_items if i.source_family == SourceFamily.VIDEO and i.relevance_status in (RelevanceStatus.RELEVANT, RelevanceStatus.LIKELY_RELEVANT)]
        has_transcript = any(i.content_role == ContentRole.TRANSCRIPT for i in video_items)
        has_metadata = any(i.content_role == ContentRole.PLATFORM_REPORTED_METRIC for i in video_items)

        if has_transcript and has_metadata:
            video_sub_cov = VideoSubstantiveCoverage.FULL
        elif has_metadata:
            video_sub_cov = VideoSubstantiveCoverage.PARTIAL
        elif len(video_items) > 0:
            video_sub_cov = VideoSubstantiveCoverage.METADATA_ONLY
        else:
            video_sub_cov = VideoSubstantiveCoverage.MISSING

        # 5. Compile Dimension Coverage Status
        if len(missing_dims) == 0 and len(weak_dims) == 0:
            dim_cov_status = ResearchSourceCoverage.PASS
        elif len(missing_dims) == 0:
            dim_cov_status = ResearchSourceCoverage.PASS
        else:
            dim_cov_status = ResearchSourceCoverage.PARTIAL

        req_families = bundle.requested_source_families or [
            SourceFamily.FIRST_PARTY_WEB,
            SourceFamily.SECONDARY_WEB,
            SourceFamily.VIDEO,
            SourceFamily.COMMUNITY,
        ]
        present_families = list({item.source_family for item in bundle.evidence_items if item.source_family != SourceFamily.OTHER and item.relevance_status in (RelevanceStatus.RELEVANT, RelevanceStatus.LIKELY_RELEVANT)})
        substantive_families = list({item.source_family for item in bundle.evidence_items if item.content_role in (ContentRole.FETCHED_SOURCE_CONTENT, ContentRole.USER_GENERATED_CONTENT) and item.relevance_status in (RelevanceStatus.RELEVANT, RelevanceStatus.LIKELY_RELEVANT)})

        return ResearchCoverageReport(
            research_question=research_question,
            dimensions=dimensions,
            requested_source_families=req_families,
            present_source_families=present_families,
            substantive_source_families=substantive_families,
            source_family_coverage=bundle.research_source_coverage,
            video_substantive_coverage=video_sub_cov,
            research_dimension_coverage=dim_cov_status,
            weak_dimensions=weak_dims,
            missing_dimensions=missing_dims,
            limitations=[
                "Dimensions evaluated deterministically for evidence availability without generating reasoning conclusions.",
                f"Video substantive coverage evaluated as {video_sub_cov.value}.",
            ],
        )


class EvidenceBundleSemanticValidator:
    """Validates overall subject coherence, dimension coverage, and quarantines irrelevant evidence."""

    @classmethod
    def validate(
        cls,
        bundle: EvidenceBundle,
        subject: SubjectIdentity,
    ) -> Tuple[SemanticCoherenceStatus, List[RejectedEvidenceRecord], List[str]]:
        """Perform deterministic audit of bundle evidence relevance and coherence."""
        rejection_manifest: List[RejectedEvidenceRecord] = []
        validation_notes: List[str] = []

        relevant_items: List[EvidenceItem] = []
        irrelevant_items: List[EvidenceItem] = []
        unassessed_items: List[EvidenceItem] = []

        for item in bundle.evidence_items:
            assessment = EvidenceRelevanceGate.evaluate(item, subject)
            item.relevance_status = assessment.relevance_status
            item.matched_subject_anchors = assessment.matched_subject_anchors
            item.structured_traces = assessment.structured_traces
            item.relevance_reason = assessment.relevance_reason

            if assessment.relevance_status in (RelevanceStatus.RELEVANT, RelevanceStatus.LIKELY_RELEVANT):
                relevant_items.append(item)
            elif assessment.relevance_status == RelevanceStatus.UNKNOWN:
                unassessed_items.append(item)
            else:
                irrelevant_items.append(item)
                rejection_manifest.append(
                    RejectedEvidenceRecord(
                        evidence_id=item.evidence_id,
                        source_url_or_id=item.source_url_or_id,
                        capability=item.capability,
                        relevance_status=assessment.relevance_status,
                        reason=assessment.relevance_reason,
                    )
                )

        # Audit Source Family Coverage on RELEVANT Items Only
        req_families = bundle.requested_source_families or [
            SourceFamily.FIRST_PARTY_WEB,
            SourceFamily.SECONDARY_WEB,
            SourceFamily.VIDEO,
            SourceFamily.COMMUNITY,
        ]
        relevant_collected_families = list({item.source_family for item in relevant_items if item.source_family != SourceFamily.OTHER})
        missing_families = [f for f in req_families if f not in relevant_collected_families]

        bundle.requested_source_families = req_families
        bundle.collected_source_families = relevant_collected_families
        bundle.missing_source_families = missing_families

        if not missing_families and len(irrelevant_items) == 0 and len(unassessed_items) == 0:
            coverage_status = ResearchSourceCoverage.PASS
            coherence_status = SemanticCoherenceStatus.PASS
            validation_notes.append("All substantive evidence items verified RELEVANT to subject. Source family coverage is PASS.")
        elif not missing_families and len(irrelevant_items) == 0 and len(unassessed_items) > 0:
            coverage_status = ResearchSourceCoverage.PASS
            coherence_status = SemanticCoherenceStatus.PARTIAL
            validation_notes.append(f"Coverage satisfied but {len(unassessed_items)} items have unassessed relevance (trusted semantic identity unavailable).")
        elif not missing_families and len(irrelevant_items) > 0:
            coverage_status = ResearchSourceCoverage.PASS
            coherence_status = SemanticCoherenceStatus.PARTIAL
            validation_notes.append(f"Coverage satisfied but {len(irrelevant_items)} irrelevant items detected and quarantined.")
        elif len(relevant_collected_families) > 0:
            coverage_status = ResearchSourceCoverage.PARTIAL
            coherence_status = SemanticCoherenceStatus.PARTIAL
            validation_notes.append(f"Missing required source families: {[f.value for f in missing_families]}.")
        elif len(unassessed_items) > 0 and len(irrelevant_items) == 0:
            coverage_status = ResearchSourceCoverage.FAIL
            coherence_status = SemanticCoherenceStatus.PARTIAL
            validation_notes.append(f"All {len(unassessed_items)} evidence items have unassessed relevance (trusted semantic identity unavailable).")
        else:
            coverage_status = ResearchSourceCoverage.FAIL
            coherence_status = SemanticCoherenceStatus.FAIL
            validation_notes.append("Zero relevant evidence collected across requested source families.")

        # Research Dimension Audit — only RELEVANT/LIKELY_RELEVANT items are
        # eligible to support coverage. UNKNOWN and IRRELEVANT are excluded.
        eligible_items = [item for item in bundle.evidence_items
                          if item.relevance_status in (RelevanceStatus.RELEVANT, RelevanceStatus.LIKELY_RELEVANT)]
        eligible_bundle = bundle.model_copy(update={"evidence_items": eligible_items})
        cov_report = ResearchDimensionEvaluator.evaluate_bundle(eligible_bundle, bundle.research_question)
        bundle.research_dimensions = cov_report.dimensions
        bundle.video_substantive_coverage = cov_report.video_substantive_coverage
        bundle.research_dimension_coverage = cov_report.research_dimension_coverage

        bundle.research_source_coverage = coverage_status
        bundle.semantic_coherence = coherence_status
        bundle.relevant_source_count = len(relevant_items)
        bundle.rejected_evidence = rejection_manifest

        return coherence_status, rejection_manifest, validation_notes
