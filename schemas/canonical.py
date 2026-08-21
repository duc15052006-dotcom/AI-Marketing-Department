"""Phase 4.3C.6: Canonical Candidate Proposal and Deterministic Normalizer.

Defines:
1. CanonicalProposal: Provider-independent candidate contract supporting all 28 deliverables and learning-ready provenance.
2. CandidateNormalizer: Deterministic JSON extractor, root wrapper unwrapper, and canonical key mapper with 0 content patching.
3. audit_canonical_completeness: Strict fail-closed 7-category completeness gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from schemas.base import BaseModel, Field

logger = logging.getLogger("schemas.canonical")


# Documented neutral root wrappers that can be safely unwrapped
NEUTRAL_ROOT_WRAPPERS = {
    "go_to_market_strategy",
    "gtm_strategy",
    "proposal",
    "candidate",
    "output",
    "strategy",
    "campaign_proposal",
}

# Canonical key mappings (from lowercase/snake_case/common aliases to canonical uppercase keys)
CANONICAL_KEY_MAP = {
    "executive_summary": "EXECUTIVE_SUMMARY",
    "summary": "EXECUTIVE_SUMMARY",
    "research_findings": "RESEARCH_FINDINGS",
    "known_facts": "KNOWN_FACTS",
    "observations": "OBSERVATIONS",
    "inferences": "INFERENCES",
    "hypotheses": "HYPOTHESES",
    "unknowns": "UNKNOWNS",
    "customer_segments": "CUSTOMER_SEGMENTS",
    "top_priority_segment": "TOP_PRIORITY_SEGMENT",
    "positioning": "POSITIONING",
    "value_proposition": "VALUE_PROPOSITION",
    "channel_priorities": "CHANNEL_PRIORITIES",
    "deferred_channels": "DEFERRED_CHANNELS",
    "what_not_to_do": "WHAT_NOT_TO_DO",
    "creative_territories": "CREATIVE_TERRITORIES",
    "selected_creative_territory": "SELECTED_CREATIVE_TERRITORY",
    "angles": "ANGLES",
    "hooks": "HOOKS",
    "short_form_copy": "SHORT_FORM_COPY",
    "video_script": "VIDEO_SCRIPT",
    "measurement_framework": "MEASUREMENT_FRAMEWORK",
    "experiments": "EXPERIMENTS",
    "attribution_approach": "ATTRIBUTION_APPROACH",
    "risks": "RISKS",
    "top_3_priorities": "TOP_3_PRIORITIES",
    "go_test_hold_defer_decisions": "GO_TEST_HOLD_DEFER_DECISIONS",
    "human_approval_requirements": "HUMAN_APPROVAL_REQUIREMENTS",
    "next_actions": "NEXT_ACTIONS",
}


class CanonicalProposal(BaseModel):
    """Authoritative provider-independent candidate proposal contract across all 28 deliverables."""

    # 1. Executive Summary
    EXECUTIVE_SUMMARY: Union[str, Dict[str, Any]] = ""

    # 2. Research Findings & Evidence Discipline
    RESEARCH_FINDINGS: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    KNOWN_FACTS: List[str] = Field(default_factory=list)
    OBSERVATIONS: List[str] = Field(default_factory=list)
    INFERENCES: List[str] = Field(default_factory=list)
    HYPOTHESES: List[str] = Field(default_factory=list)
    UNKNOWNS: List[str] = Field(default_factory=list)

    # 3. Customer Segments
    CUSTOMER_SEGMENTS: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    TOP_PRIORITY_SEGMENT: Union[str, Dict[str, Any]] = ""

    # 4. Strategy & Positioning
    POSITIONING: Union[str, Dict[str, Any]] = ""
    VALUE_PROPOSITION: Union[str, Dict[str, Any]] = ""
    CHANNEL_PRIORITIES: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    DEFERRED_CHANNELS: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    WHAT_NOT_TO_DO: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)

    # 5. Creative Production & Copy
    CREATIVE_TERRITORIES: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    SELECTED_CREATIVE_TERRITORY: Union[str, Dict[str, Any]] = ""
    ANGLES: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    HOOKS: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    SHORT_FORM_COPY: Union[str, List[Any], Dict[str, Any]] = ""
    VIDEO_SCRIPT: Union[str, Dict[str, Any]] = ""

    # 6. Measurement Framework & Experiments
    MEASUREMENT_FRAMEWORK: Union[str, Dict[str, Any]] = Field(default_factory=dict)
    EXPERIMENTS: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    ATTRIBUTION_APPROACH: Union[str, Dict[str, Any]] = ""

    # 7. Governance, Risks & Next Actions
    RISKS: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    TOP_3_PRIORITIES: Union[str, List[Any], Dict[str, Any]] = Field(default_factory=list)
    GO_TEST_HOLD_DEFER_DECISIONS: Union[str, Dict[str, Any]] = Field(default_factory=dict)
    HUMAN_APPROVAL_REQUIREMENTS: Union[str, Dict[str, Any]] = Field(default_factory=dict)
    NEXT_ACTIONS: Union[str, List[Any], Dict[str, Any]] = ""

    # Learning-Ready Provenance Metadata
    benchmark_id: str = "BENCHMARK-PHASE4-3-UNSEEN-AI-SPEAKING"
    run_id: str = "DEFAULT"
    run_fingerprint: str = ""
    condition_id: str = ""
    source_raw_hash: str = ""
    canonical_hash: str = ""
    provider_requested: str = ""
    provider_resolved: str = ""
    model_requested: str = ""
    model_resolved: str = ""
    execution_generation: str = "phase4_3_v2"
    candidate_schema_version: str = "v2"
    content_patch_count: int = 0
    semantic_rewrite_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_canonical_hash(self) -> str:
        """Compute SHA-256 hash of the canonical deliverable contents (excluding runtime metadata)."""
        content_dict = {k: getattr(self, k) for k in CANONICAL_KEY_MAP.values()}
        canon_str = json.dumps(content_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canon_str.encode("utf-8")).hexdigest()


class NormalizationResult(BaseModel):
    """Result of deterministic candidate parsing and canonicalization."""
    status: str  # SUCCESS | NORMALIZATION_FAILED
    raw_hash: str
    parsed_hash: Optional[str] = None
    canonical_hash: Optional[str] = None
    parsed_structure: Optional[Dict[str, Any]] = None
    canonical_proposal: Optional[CanonicalProposal] = None
    error: Optional[str] = None
    content_patch_count: int = 0
    semantic_rewrite_count: int = 0


class CandidateNormalizer:
    """Deterministic, provider-independent candidate parser with zero semantic patching."""

    @classmethod
    def extract_json_object(cls, raw_text: Union[str, Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Extract a valid JSON dictionary from raw text (pure JSON, markdown fenced, prose before/after)."""
        if isinstance(raw_text, dict):
            return raw_text, None

        if not raw_text or not isinstance(raw_text, str):
            return None, "Raw text is empty or not a string."

        cleaned = raw_text.strip()

        # Pattern 1: Try direct JSON parse
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed, None
        except Exception:
            pass

        # Pattern 2: Markdown code fence ```json ... ```
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if fence_match:
            try:
                parsed = json.loads(fence_match.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed, None
            except Exception:
                pass

        # Pattern 3: Find outermost balanced or regex JSON object
        # Find first '{' and try expanding
        start_idx = cleaned.find("{")
        if start_idx != -1:
            # Try from first '{' to last '}'
            end_idx = cleaned.rfind("}")
            if end_idx != -1 and end_idx > start_idx:
                candidate_substr = cleaned[start_idx : end_idx + 1]
                try:
                    parsed = json.loads(candidate_substr)
                    if isinstance(parsed, dict):
                        return parsed, None
                except Exception:
                    pass

        return None, "Deterministic extraction could not find complete, valid JSON syntax."

    @classmethod
    def unwrap_root_wrapper(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Unwrap known neutral root wrappers (e.g. go_to_market_strategy) if present."""
        if not isinstance(data, dict):
            return data

        # Check if single top-level key matches a neutral wrapper
        if len(data) == 1:
            k = list(data.keys())[0]
            if k.lower() in NEUTRAL_ROOT_WRAPPERS and isinstance(data[k], dict):
                return data[k]

        # Check if any top-level key matches a neutral wrapper
        for wrapper in NEUTRAL_ROOT_WRAPPERS:
            for k in list(data.keys()):
                if k.lower() == wrapper and isinstance(data[k], dict):
                    # If this wrapper contains deliverable-like keys, unwrap it
                    inner = data[k]
                    if any(ik.lower() in CANONICAL_KEY_MAP for ik in inner.keys()):
                        return inner

        return data

    @classmethod
    def canonicalize_keys(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Map snake_case/lowercase dictionary keys to canonical uppercase keys without changing content."""
        if not isinstance(data, dict):
            return {}

        canonical: Dict[str, Any] = {}
        for k, v in data.items():
            norm_k = k.lower().strip().replace(" ", "_")
            if norm_k in CANONICAL_KEY_MAP:
                canon_k = CANONICAL_KEY_MAP[norm_k]
                canonical[canon_k] = v
            else:
                canonical[k.upper()] = v
        return canonical

    @classmethod
    def normalize_candidate(
        cls,
        raw_text: Union[str, Dict[str, Any]],
        condition_id: str,
        benchmark_id: str = "BENCHMARK-PHASE4-3-UNSEEN-AI-SPEAKING",
        run_id: str = "DEFAULT",
        run_fingerprint: str = "",
        provider_requested: str = "",
        provider_resolved: str = "",
        model_requested: str = "",
        model_resolved: str = "",
        execution_generation: str = "phase4_3_v2",
    ) -> NormalizationResult:
        """Execute full deterministic normalization pipeline with fail-closed semantics."""
        raw_str = json.dumps(raw_text, ensure_ascii=False) if isinstance(raw_text, dict) else str(raw_text or "")
        raw_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

        # Step 1: Deterministic JSON extraction
        parsed_dict, err = cls.extract_json_object(raw_text)
        if parsed_dict is None or not isinstance(parsed_dict, dict):
            return NormalizationResult(
                status="NORMALIZATION_FAILED",
                raw_hash=raw_hash,
                error=f"JSON extraction failed: {err}",
                content_patch_count=0,
                semantic_rewrite_count=0,
            )

        parsed_hash = hashlib.sha256(json.dumps(parsed_dict, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

        # Step 2: Unwrap neutral root wrappers
        unwrapped = cls.unwrap_root_wrapper(parsed_dict)

        # Step 3: Canonical key normalization
        canonical_dict = cls.canonicalize_keys(unwrapped)

        # Step 4: Construct CanonicalProposal
        try:
            # Map canonical fields
            proposal_kwargs: Dict[str, Any] = {
                "benchmark_id": benchmark_id,
                "run_id": run_id,
                "run_fingerprint": run_fingerprint,
                "condition_id": condition_id,
                "source_raw_hash": raw_hash,
                "provider_requested": provider_requested,
                "provider_resolved": provider_resolved,
                "model_requested": model_requested,
                "model_resolved": model_resolved,
                "execution_generation": execution_generation,
                "candidate_schema_version": "v2",
                "content_patch_count": 0,
                "semantic_rewrite_count": 0,
            }

            for canon_key in CANONICAL_KEY_MAP.values():
                if canon_key in canonical_dict:
                    proposal_kwargs[canon_key] = canonical_dict[canon_key]

            proposal = CanonicalProposal(**proposal_kwargs)
            canon_hash = proposal.compute_canonical_hash()
            proposal.canonical_hash = canon_hash

            return NormalizationResult(
                status="SUCCESS",
                raw_hash=raw_hash,
                parsed_hash=parsed_hash,
                canonical_hash=canon_hash,
                parsed_structure=unwrapped,
                canonical_proposal=proposal,
                content_patch_count=0,
                semantic_rewrite_count=0,
            )
        except Exception as ex:
            return NormalizationResult(
                status="NORMALIZATION_FAILED",
                raw_hash=raw_hash,
                parsed_hash=parsed_hash,
                error=f"Canonical schema construction failed: {str(ex)}",
                content_patch_count=0,
                semantic_rewrite_count=0,
            )


def audit_canonical_completeness(proposal: Union[CanonicalProposal, Dict[str, Any]]) -> Tuple[bool, Dict[str, bool]]:
    """Strict fail-closed 7-category completeness audit for a CanonicalProposal."""
    if isinstance(proposal, CanonicalProposal):
        data = proposal.model_dump()
    elif isinstance(proposal, dict):
        data = proposal
    else:
        return False, {cat: False for cat in ["EXECUTIVE_SUMMARY", "RESEARCH", "SEGMENTATION", "STRATEGY", "CREATIVE", "MEASUREMENT", "GOVERNANCE"]}

    def has_content(val: Any) -> bool:
        if not val:
            return False
        if isinstance(val, str):
            return len(val.strip()) > 0
        if isinstance(val, (list, tuple)):
            return len(val) > 0 and any(has_content(v) for v in val)
        if isinstance(val, dict):
            return len(val) > 0 and any(has_content(v) for v in val.values())
        return True

    audit: Dict[str, bool] = {
        "EXECUTIVE_SUMMARY": has_content(data.get("EXECUTIVE_SUMMARY")),
        "RESEARCH": (
            has_content(data.get("RESEARCH_FINDINGS"))
            or has_content(data.get("KNOWN_FACTS"))
            or has_content(data.get("OBSERVATIONS"))
        ),
        "SEGMENTATION": (
            has_content(data.get("CUSTOMER_SEGMENTS"))
            or has_content(data.get("TOP_PRIORITY_SEGMENT"))
        ),
        "STRATEGY": (
            has_content(data.get("POSITIONING"))
            or has_content(data.get("VALUE_PROPOSITION"))
            or has_content(data.get("CHANNEL_PRIORITIES"))
            or has_content(data.get("WHAT_NOT_TO_DO"))
        ),
        "CREATIVE": (
            has_content(data.get("CREATIVE_TERRITORIES"))
            or has_content(data.get("HOOKS"))
            or has_content(data.get("VIDEO_SCRIPT"))
        ),
        "MEASUREMENT": (
            has_content(data.get("MEASUREMENT_FRAMEWORK"))
            or has_content(data.get("EXPERIMENTS"))
        ),
        "GOVERNANCE": (
            has_content(data.get("RISKS"))
            or has_content(data.get("GO_TEST_HOLD_DEFER_DECISIONS"))
            or has_content(data.get("HUMAN_APPROVAL_REQUIREMENTS"))
            or has_content(data.get("NEXT_ACTIONS"))
        ),
    }

    is_complete = all(audit.values())
    return is_complete, audit
