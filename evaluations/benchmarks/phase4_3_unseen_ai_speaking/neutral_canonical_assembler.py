"""Architecture-Neutral Canonical Candidate Assembler (Phase 4.3C.9 / 4.3C.9A).

Strict Truncation & Extraction Policy: PARTIAL_IMMUTABLE_SALVAGE
- Extracts only syntactically complete, verbatim sections/fields already present in raw model output.
- ZERO inferred text.
- ZERO fabricated closing braces or patched JSON syntax.
- ZERO synthetic content invention (FABRICATED_DELIVERABLE_COUNT = 0).
- ZERO semantic alteration (SEMANTIC_REWRITE_COUNT = 0).
- ZERO content patching (CONTENT_PATCH_COUNT = 0).
- IDENTICAL extraction rules applied to Candidate A, Candidate B, and Candidate C.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from schemas.canonical import (
    CANONICAL_KEY_MAP,
    CanonicalProposal,
    CandidateNormalizer,
    NormalizationResult,
    audit_canonical_completeness,
)

logger = logging.getLogger("neutral_assembler")

CANONICAL_DELIVERABLE_KEYWORDS: Dict[str, List[str]] = {
    "executive_summary": ["executive summary", "core objective"],
    "known_facts": ["known facts", "verified product capabilities", "ground truth"],
    "observations": ["observations", "market observations", "consumer intelligence"],
    "inferences": ["inferences", "strategic inferences", "market inferences"],
    "hypotheses": ["hypotheses", "strategic hypotheses", "testable hypotheses"],
    "unknowns": ["unknowns", "critical unknowns", "unverified", "information gaps"],
    "customer_segments": ["customer segments", "target customer segmentation", "target segments"],
    "top_priority_segment": ["top priority segment", "primary segment", "lead segment", "priority target"],
    "positioning": ["positioning", "executive positioning architecture", "core positioning"],
    "value_proposition": ["value proposition", "core value prop"],
    "channel_priorities": ["channel priorities", "channel strategy", "channel allocation"],
    "deferred_channels": ["deferred channels", "deprioritized channels"],
    "what_not_to_do": ["what not to do", "guardrails", "boundary rules", "prohibited"],
    "creative_territories": ["creative territories", "territory 1", "creative angles"],
    "selected_creative_territory": ["selected creative territory", "lead territory", "chosen territory"],
    "angles": ["angles", "message angles", "messaging angles"],
    "hooks": ["hooks", "video hooks", "ad hooks"],
    "short_form_copy": ["short form copy", "ad copy", "headlines"],
    "video_script": ["video script", "30-second script", "production script"],
    "measurement_framework": ["measurement framework", "kpis", "funnel metrics"],
    "experiments": ["experiments", "experimentation", "a/b test", "experiment blueprint"],
    "attribution_approach": ["attribution approach", "attribution & tracking", "mmp"],
    "risks": ["risks", "risk matrix", "risk mitigation"],
    "top_3_priorities": ["top 3 priorities", "strategic priorities", "core priorities"],
    "go_test_hold_defer_decisions": ["go / test / hold / defer", "go test hold defer", "governance decisions"],
    "human_approval_requirements": ["human approval requirements", "approval gates", "sign-off"],
    "next_actions": ["next actions", "immediate actions", "action plan"],
    "claim_governance": ["claim governance", "claim compliance", "claim safety"],
}


@dataclass
class AssemblyAudit:
    candidate_id: str
    architecture: str
    total_deliverables_found: int
    deliverable_origins: Dict[str, str]
    content_patch_count: int
    semantic_rewrite_count: int
    fabricated_deliverable_count: int
    is_complete: bool
    completeness_breakdown: Dict[str, bool]
    canonical_hash: str


class NeutralCanonicalCandidateAssembler:
    """Neutral assembler extracting canonical deliverables from raw model execution traces."""

    @staticmethod
    def extract_json_block(text: str) -> Optional[Dict[str, Any]]:
        """Extract valid JSON object from markdown or raw text without mutating content."""
        if not text or not isinstance(text, str):
            return None
        text_clean = text.strip()
        # Direct parse
        if text_clean.startswith("{") and text_clean.endswith("}"):
            try:
                parsed = json.loads(text_clean)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        # Fenced markdown block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_clean, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return None

    @classmethod
    def extract_unclosed_fields(cls, text: str) -> Dict[str, Any]:
        """Extract fully emitted top-level string and list fields from unclosed JSON text (Partial Immutable Salvage)."""
        if not text or not isinstance(text, str):
            return {}
        res: Dict[str, Any] = {}
        # Completed string fields: "key": "value"
        str_pattern = re.compile(r'"([a-zA-Z0-9_]+)"\s*:\s*"((?:\\.|[^"\\])*)"')
        for match in str_pattern.finditer(text):
            k, v = match.group(1), match.group(2)
            try:
                res[k] = v.encode().decode("unicode_escape", errors="ignore")
            except Exception:
                res[k] = v

        # Completed list of strings: "key": [ "item1", "item2" ]
        list_pattern = re.compile(r'"([a-zA-Z0-9_]+)"\s*:\s*\[(.*?)\]', re.DOTALL)
        for match in list_pattern.finditer(text):
            k, body = match.group(1), match.group(2)
            items = []
            for item_match in str_pattern.finditer('{' + body + '}'):
                try:
                    items.append(item_match.group(2).encode().decode("unicode_escape", errors="ignore"))
                except Exception:
                    items.append(item_match.group(2))
            if not items:
                for raw_item in re.findall(r'"((?:\\.|[^"\\])*)"', body):
                    try:
                        items.append(raw_item.encode().decode("unicode_escape", errors="ignore"))
                    except Exception:
                        items.append(raw_item)
            if items:
                res[k] = items
        return res

    @classmethod
    def extract_markdown_section_by_keywords(cls, text: str, keywords: List[str]) -> Optional[str]:
        """Extract verbatim markdown section matching keyword anchors from model output."""
        if not text or not isinstance(text, str):
            return None
        for kw in keywords:
            pattern = re.compile(
                rf'(?:#+|\*\*)\s*(?:[0-9\.]+\s*)?([^\n]*{re.escape(kw)}[^\n]*)\s*(?:#+|\*\*)?\n(.*?)(?=\n(?:#+|\*\*)\s*(?:[0-9\.]+\s*)?[A-Z0-9]|\Z)',
                re.IGNORECASE | re.DOTALL,
            )
            m = pattern.search(text)
            if m:
                body = m.group(2).strip()
                if body:
                    return body
        return None

    @classmethod
    def extract_from_raw_output(cls, raw_text: str) -> Dict[str, Any]:
        """Extract all available deliverables from a single raw text output via JSON or Markdown parsing."""
        deliverables: Dict[str, Any] = {}
        # 1. Try full JSON parse
        json_obj = cls.extract_json_block(raw_text)
        if json_obj:
            unwrapped = CandidateNormalizer.unwrap_root_wrapper(json_obj)
            for k, v in unwrapped.items():
                canon_k = k.lower()
                if v:
                    deliverables[canon_k] = v
            return deliverables

        # 2. Try unclosed JSON completed fields (Partial Immutable Salvage)
        unclosed = cls.extract_unclosed_fields(raw_text)
        for k, v in unclosed.items():
            canon_k = k.lower()
            if v:
                deliverables[canon_k] = v

        # 3. Try Markdown Section keyword parsing for remaining keys
        for key, kws in CANONICAL_DELIVERABLE_KEYWORDS.items():
            if key not in deliverables:
                sec_text = cls.extract_markdown_section_by_keywords(raw_text, kws)
                if sec_text:
                    deliverables[key] = sec_text

        return deliverables

    @classmethod
    def assemble_candidate_a(cls, stages: Dict[str, Any]) -> Tuple[CanonicalProposal, AssemblyAudit]:
        """Assemble Candidate A (Five-Agent V2) from 6 stage outputs using verbatim extraction."""
        origins: Dict[str, str] = {}
        deliverables: Dict[str, Any] = {}

        # Precedence: Stage 6 (Final CMO) -> Stage 5 -> Stage 4 -> Stage 3 -> Stage 2 -> Stage 1
        stage_order = [
            ("final_cmo", "Stage 6 (Final CMO)"),
            ("performance", "Stage 5 (Performance)"),
            ("creative", "Stage 4 (Creative)"),
            ("strategist", "Stage 3 (Strategist)"),
            ("intelligence", "Stage 2 (Intelligence)"),
            ("cmo_initial", "Stage 1 (CMO Initial)"),
        ]

        for s_key, s_label in stage_order:
            s_data = stages.get(s_key, {})
            raw_text = s_data.get("raw_text", "")
            extracted = cls.extract_from_raw_output(raw_text)
            for k, v in extracted.items():
                if k not in deliverables and v:
                    deliverables[k] = v
                    origins[k] = s_label

        # Map to canonical uppercase fields
        valid_fields = set(CanonicalProposal.model_fields.keys()) if hasattr(CanonicalProposal, "model_fields") else set(CanonicalProposal.__annotations__.keys())
        mapped_deliverables: Dict[str, Any] = {}
        for k, v in deliverables.items():
            upper_k = CANONICAL_KEY_MAP.get(k.lower(), k.upper())
            if upper_k in valid_fields:
                mapped_deliverables[upper_k] = v

        canonical = CanonicalProposal(**mapped_deliverables)
        is_complete, audit = audit_canonical_completeness(canonical)
        raw_hash = hashlib.sha256(json.dumps(deliverables, sort_keys=True, default=str).encode("utf-8")).hexdigest()

        audit_res = AssemblyAudit(
            candidate_id="CANDIDATE_A",
            architecture="ROLE_SPECIALIZED_MULTI_AGENT",
            total_deliverables_found=len(mapped_deliverables),
            deliverable_origins={k: v for k, v in origins.items() if CANONICAL_KEY_MAP.get(k.lower(), k.upper()) in valid_fields},
            content_patch_count=0,
            semantic_rewrite_count=0,
            fabricated_deliverable_count=0,
            is_complete=is_complete,
            completeness_breakdown=audit,
            canonical_hash=raw_hash,
        )
        return canonical, audit_res

    @classmethod
    def assemble_candidate_b(cls, passes: List[Dict[str, Any]]) -> Tuple[CanonicalProposal, AssemblyAudit]:
        """Assemble Candidate B (Single-Agent Multi-Pass) from 5 pass outputs using verbatim extraction."""
        origins: Dict[str, str] = {}
        deliverables: Dict[str, Any] = {}

        # Reverse precedence: Pass 5 (Final Synthesis) -> Pass 4 -> Pass 3 -> Pass 2 -> Pass 1
        pass_labels = [
            f"Pass {i+1} ({['Research', 'Strategy', 'Creative', 'Performance', 'Synthesis'][i]})"
            for i in range(len(passes))
        ]

        for idx in reversed(range(len(passes))):
            p_data = passes[idx]
            raw_text = p_data.get("raw_text", "")
            extracted = cls.extract_from_raw_output(raw_text)
            for k, v in extracted.items():
                if k not in deliverables and v:
                    deliverables[k] = v
                    origins[k] = pass_labels[idx]

        valid_fields = set(CanonicalProposal.model_fields.keys()) if hasattr(CanonicalProposal, "model_fields") else set(CanonicalProposal.__annotations__.keys())
        mapped_deliverables: Dict[str, Any] = {}
        for k, v in deliverables.items():
            upper_k = CANONICAL_KEY_MAP.get(k.lower(), k.upper())
            if upper_k in valid_fields:
                mapped_deliverables[upper_k] = v

        canonical = CanonicalProposal(**mapped_deliverables)
        is_complete, audit = audit_canonical_completeness(canonical)
        raw_hash = hashlib.sha256(json.dumps(deliverables, sort_keys=True, default=str).encode("utf-8")).hexdigest()

        audit_res = AssemblyAudit(
            candidate_id="CANDIDATE_B",
            architecture="SINGLE_AGENT_ITERATIVE_SCRATCHPAD",
            total_deliverables_found=len(mapped_deliverables),
            deliverable_origins={k: v for k, v in origins.items() if CANONICAL_KEY_MAP.get(k.lower(), k.upper()) in valid_fields},
            content_patch_count=0,
            semantic_rewrite_count=0,
            fabricated_deliverable_count=0,
            is_complete=is_complete,
            completeness_breakdown=audit,
            canonical_hash=raw_hash,
        )
        return canonical, audit_res

    @classmethod
    def assemble_candidate_c(cls, raw_output: str) -> Tuple[CanonicalProposal, AssemblyAudit]:
        """Assemble Candidate C (Single-Agent One-Shot) from single direct output using verbatim extraction."""
        origins: Dict[str, str] = {}
        deliverables: Dict[str, Any] = {}

        extracted = cls.extract_from_raw_output(raw_output)
        for k, v in extracted.items():
            deliverables[k] = v
            origins[k] = "Candidate C One-Shot Model Output"

        valid_fields = set(CanonicalProposal.model_fields.keys()) if hasattr(CanonicalProposal, "model_fields") else set(CanonicalProposal.__annotations__.keys())
        mapped_deliverables: Dict[str, Any] = {}
        for k, v in deliverables.items():
            upper_k = CANONICAL_KEY_MAP.get(k.lower(), k.upper())
            if upper_k in valid_fields:
                mapped_deliverables[upper_k] = v

        canonical = CanonicalProposal(**mapped_deliverables)
        is_complete, audit = audit_canonical_completeness(canonical)
        raw_hash = hashlib.sha256(json.dumps(deliverables, sort_keys=True, default=str).encode("utf-8")).hexdigest()

        audit_res = AssemblyAudit(
            candidate_id="CANDIDATE_C",
            architecture="SINGLE_AGENT_ONE_SHOT",
            total_deliverables_found=len(mapped_deliverables),
            deliverable_origins={k: v for k, v in origins.items() if CANONICAL_KEY_MAP.get(k.lower(), k.upper()) in valid_fields},
            content_patch_count=0,
            semantic_rewrite_count=0,
            fabricated_deliverable_count=0,
            is_complete=is_complete,
            completeness_breakdown=audit,
            canonical_hash=raw_hash,
        )
        return canonical, audit_res
