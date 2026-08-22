"""Phase CLAIM-REPAIR-03A: Structured Claim Verification Foundation.

Provides reusable claim verification interfaces and adapters:
1. VerificationVerdict & ClaimVerificationResult: Standard verification data contract.
2. Deterministic Claim Guards: Pure pre-NLI verification filters (numeric, currency,
   temporal, SKU/entity, scope, execution state, atomic invariant, hypothesis preservation).
3. BaseClaimVerifier: Abstract verifier contract.
4. MultilingualNLIClaimVerifier: Production NLI adapter with lazy loading, pinned revision,
   dynamic label resolution, fail-closed fault tolerance, and batching.
5. MockClaimVerifier: Deterministic mock verifier for unit testing.

Zero direct dependencies on external LLM calls or Agent 6.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from schemas.base import BaseModel, Field
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    SourceType,
    SupportStatus,
)

logger = logging.getLogger("runtime.claim_verification")

# ---------------------------------------------------------------------------
# Model Pinning Constants (Benchmark Calibrated & Validated)
# ---------------------------------------------------------------------------
DEFAULT_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
DEFAULT_MODEL_REVISION = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
DEFAULT_MODEL_LICENSE = "MIT"

# Provisional thresholds derived from CLAIM-BENCH-01 and verified on CLAIM-BENCH-02 holdout
PROVISIONAL_TAU_ENTAILMENT = 0.90
PROVISIONAL_TAU_CONTRADICTION = 0.70


# ---------------------------------------------------------------------------
# Data Contracts
# ---------------------------------------------------------------------------

class VerificationVerdict(str, Enum):
    """Standard verdict for a claim verification check."""
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED = "UNSUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"


class DeterministicFindings(BaseModel):
    """Details from pure deterministic pre-guard checks."""
    guard_name: Optional[str] = None
    passed: bool = True
    reason: Optional[str] = None
    extracted_claim_values: Dict[str, Any] = Field(default_factory=dict)
    extracted_evidence_values: Dict[str, Any] = Field(default_factory=dict)


class SemanticScores(BaseModel):
    """Raw probabilities and logits from semantic NLI backend."""
    p_entailment: float = 0.0
    p_neutral: float = 0.0
    p_contradiction: float = 0.0
    argmax_label: Optional[str] = None
    raw_latency_ms: float = 0.0


class ClaimVerificationResult(BaseModel):
    """Immutable result of a single claim verification attempt."""
    claim_text: str
    source_id: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    verdict: VerificationVerdict = VerificationVerdict.INCONCLUSIVE
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    model_id: Optional[str] = None
    backend: Optional[str] = None
    deterministic_findings: Optional[DeterministicFindings] = None
    semantic_scores: Optional[SemanticScores] = None
    epistemic_type_preserved: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Pure Deterministic Guards
# ---------------------------------------------------------------------------

def _normalize_unit(unit: str) -> str:
    """Normalize unit string to canonical singular lower-case form."""
    u = unit.lower().strip()
    mapping = {
        "months": "month", "month": "month", "tháng": "month",
        "days": "day", "day": "day", "ngày": "day",
        "hours": "hour", "hour": "hour", "giờ": "hour", "hrs": "hour", "hr": "hour",
        "mins": "min", "min": "min", "minutes": "min", "minute": "min", "phút": "min",
        "seconds": "sec", "second": "sec", "secs": "sec", "sec": "sec", "giây": "sec",
        "weeks": "week", "week": "week", "tuần": "week",
        "years": "year", "year": "year", "năm": "year",
        "lumens": "lumen", "lumen": "lumen",
        "liters": "liter", "liter": "liter", "litres": "liter", "litre": "liter", "lít": "liter",
        "miles": "mile", "mile": "mile",
    }
    return mapping.get(u, u)


def extract_numeric_tokens_with_units(text: str) -> List[Tuple[float, str]]:
    """Extract numeric values along with their trailing measurement units if present."""
    unit_pattern = (
        r'(?<!\w)(\d{1,3}(?:[,\.]\d{3})*(?:[,\.]\d+)?|\d+(?:[,\.]\d+)?)\s*[-]?\s*'
        r'(lumens?|hours?|hrs?|mins?|minutes?|seconds?|secs?|giây|giờ|phút|'
        r'months?|days?|years?|weeks?|tháng|ngày|năm|tuần|'
        r'mAh|Wh|kWh|kW|W|V|A|kg|g|mg|lb|oz|'
        r'km|m|cm|mm|miles?|ft|liters?|litres?|lít|ml|GB|MB|TB|Gbps|Mbps|%|USD|EUR|VND|GBP|đ)?(?!\w)'
    )
    matches = re.finditer(unit_pattern, text, re.IGNORECASE)
    results: List[Tuple[float, str]] = []
    for m in matches:
        num_str = m.group(1).replace(',', '')
        raw_unit = (m.group(2) or "").strip()
        unit = _normalize_unit(raw_unit) if raw_unit else ""
        try:
            val = float(num_str)
            results.append((val, unit))
        except ValueError:
            pass
    return results


def extract_numeric_tokens(text: str) -> List[float]:
    """Extract raw numeric values from text while ignoring punctuation commas."""
    pairs = extract_numeric_tokens_with_units(text)
    return [p[0] for p in pairs]


def extract_currency_codes(text: str) -> Set[str]:
    """Detect currency symbols and currency unit words."""
    currencies: Set[str] = set()
    patterns = [
        (r'(\$|USD|usd)\s*[\d,\.]+', 'USD'),
        (r'[\d,\.]+\s*(USD|usd)', 'USD'),
        (r'[\d,\.]+\s*(VND|vnd|đ|đồng|dong)', 'VND'),
        (r'(€|EUR|eur)\s*[\d,\.]+', 'EUR'),
        (r'[\d,\.]+\s*(EUR|eur)', 'EUR'),
        (r'(£|GBP|gbp)\s*[\d,\.]+', 'GBP'),
        (r'[\d,\.]+\s*(GBP|gbp)', 'GBP'),
    ]
    for pat, cur in patterns:
        if re.search(pat, text, re.IGNORECASE):
            currencies.add(cur)
    return currencies


def extract_explicit_skus(text: str) -> Set[str]:
    """Extract alphanumeric model numbers and SKU codes (e.g., VD-500, PRO-X9)."""
    sku_pattern = r'\b([A-Z]{2,}[-\s]?\d{2,}[A-Z]?\d*)\b'
    return set(re.findall(sku_pattern, text))


def extract_temporal_years(text: str) -> Set[int]:
    """Extract 4-digit calendar years between 1900 and 2099, avoiding units/SKUs."""
    pattern = (
        r'(?<![A-Za-z0-9\-])(19\d{2}|20\d{2})'
        r'(?!\s*[-]?\s*(?:mah|wh|kwh|kw|w|v|a|kg|g|mg|lb|oz|km|m|cm|mm|miles?|ft|liters?|litres?|lít|ml|gb|mb|tb|gbps|mbps|lumens?|%|usd|eur|vnd|gbp|đ|[a-zA-Z0-9]))'
    )
    return {int(m.group(1)) for m in re.finditer(pattern, text, re.IGNORECASE)}


def extract_scope_regions(text: str) -> Set[str]:
    """Extract geographical and commercial scope regions from prose."""
    regions: Set[str] = set()
    scope_keywords = [
        (r'\b(toàn cầu|worldwide|global)\b', 'global'),
        (r'\b(Việt Nam|Vietnam|VN)\b', 'vietnam'),
        (r'\b(châu Á|Asia|APAC)\b', 'asia'),
        (r'\b(châu Âu|Europe|EU)\b', 'europe'),
        (r'\b(Bắc Mỹ|North America|US|USA)\b', 'north_america'),
    ]
    for pat, label in scope_keywords:
        if re.search(pat, text, re.IGNORECASE):
            regions.add(label)
    return regions


def audit_deterministic_claim_guards(
    claim_text: str,
    evidence_text: str,
    claim_metadata: Optional[Dict[str, Any]] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
) -> DeterministicFindings:
    """Execute all pure deterministic guards.

    Returns a DeterministicFindings object indicating pass/fail and details.
    """
    claim_meta = claim_metadata or {}
    source_meta = source_metadata or {}

    # 1. Execution State Guard (MOCK, SANDBOX, ERROR, TIMEOUT, BLOCKED, APPROVAL_REQUIRED)
    exec_status = str(source_meta.get("status", "")).upper()
    exec_mode = str(source_meta.get("execution_mode", "")).upper()
    evidence_str = str(evidence_text)

    if exec_mode in ("MOCK", "SANDBOX") or "MOCK" in evidence_str or "SANDBOX" in evidence_str:
        return DeterministicFindings(
            guard_name="EXECUTION_STATE_MOCK_OR_SANDBOX",
            passed=False,
            reason="Evidence originates from MOCK or SANDBOX execution mode which cannot verify factual public claims.",
        )
    if exec_status in ("ERROR", "TIMEOUT", "BLOCKED", "APPROVAL_REQUIRED"):
        return DeterministicFindings(
            guard_name=f"EXECUTION_STATE_{exec_status}",
            passed=False,
            reason=f"Evidence source execution status is {exec_status}, invalidating support.",
        )

    # 2. Security / Provenance Scope Boundary Guard (Tenant, Run, Chat isolation)
    claim_tenant = claim_meta.get("tenant_id") or claim_meta.get("brand_id")
    source_tenant = source_meta.get("tenant_id") or source_meta.get("brand_id")
    if claim_tenant and source_tenant and str(claim_tenant).strip() != str(source_tenant).strip():
        return DeterministicFindings(
            guard_name="SECURITY_SCOPE_VIOLATION",
            passed=False,
            reason=f"Cross-tenant security violation: claim tenant '{claim_tenant}' != evidence source tenant '{source_tenant}'.",
            extracted_claim_values={"tenant_id": str(claim_tenant)},
            extracted_evidence_values={"tenant_id": str(source_tenant)},
        )

    claim_run = claim_meta.get("run_id")
    source_run = source_meta.get("run_id")
    if claim_run and source_run and str(claim_run).strip() != str(source_run).strip():
        return DeterministicFindings(
            guard_name="SECURITY_SCOPE_VIOLATION",
            passed=False,
            reason=f"Cross-run provenance violation: claim run '{claim_run}' != evidence source run '{source_run}'.",
            extracted_claim_values={"run_id": str(claim_run)},
            extracted_evidence_values={"run_id": str(source_run)},
        )

    claim_chat = claim_meta.get("chat_id")
    source_chat = source_meta.get("chat_id")
    if claim_chat and source_chat and str(claim_chat).strip() != str(source_chat).strip():
        return DeterministicFindings(
            guard_name="SECURITY_SCOPE_VIOLATION",
            passed=False,
            reason=f"Cross-chat session isolation violation: claim chat '{claim_chat}' != evidence source chat '{source_chat}'.",
            extracted_claim_values={"chat_id": str(claim_chat)},
            extracted_evidence_values={"chat_id": str(source_chat)},
        )

    # 3. Epistemic Hypothesis & Planning Preservation Guard
    claim_class_raw = claim_meta.get("claim_class")
    allowed_usage_raw = claim_meta.get("allowed_usage")
    if claim_class_raw in (
        ClaimClass.HYPOTHESIS,
        ClaimClass.PROPOSED_TEST,
        ClaimClass.PROPOSED_TARGET,
        ClaimClass.UNKNOWN,
        "HYPOTHESIS",
        "PROPOSED_TEST",
        "PROPOSED_TARGET",
        "UNKNOWN",
    ) or allowed_usage_raw in (
        AllowedUsage.HYPOTHESIS_ONLY,
        AllowedUsage.EXPERIMENT_ONLY,
        "HYPOTHESIS_ONLY",
        "EXPERIMENT_ONLY",
    ):
        return DeterministicFindings(
            guard_name="EPISTEMIC_HYPOTHESIS_PRESERVATION",
            passed=False,
            reason="Claim is classified as hypothesis, experiment proposal, or target and must preserve its non-factual epistemic type.",
            extracted_claim_values={"claim_class": str(claim_class_raw), "allowed_usage": str(allowed_usage_raw)},
        )

    # 4. Compound Claim Invariant Guard (Metadata contract only, no brittle and/or splitting)
    is_compound = claim_meta.get("is_compound", False)
    if is_compound:
        return DeterministicFindings(
            guard_name="COMPOUND_CLAIM_GUARD",
            passed=False,
            reason="Claim is marked as compound (multi-fact) and must be decomposed into atomic subclaims before verification.",
        )

    # 5. Explicit SKU / Entity Mismatch Guard (Metadata + Alphanumeric tokens)
    claim_sku_meta = claim_meta.get("sku") or claim_meta.get("product_id")
    source_sku_meta = source_meta.get("sku") or source_meta.get("product_id")
    if claim_sku_meta and source_sku_meta and str(claim_sku_meta).strip().upper() != str(source_sku_meta).strip().upper():
        return DeterministicFindings(
            guard_name="ENTITY_SKU_MISMATCH",
            passed=False,
            reason=f"Structured SKU mismatch: claim specifies '{claim_sku_meta}' but evidence is for '{source_sku_meta}'.",
            extracted_claim_values={"sku": str(claim_sku_meta)},
            extracted_evidence_values={"sku": str(source_sku_meta)},
        )

    claim_skus = extract_explicit_skus(claim_text)
    evidence_skus = extract_explicit_skus(evidence_text)
    if claim_skus and evidence_skus and not claim_skus.intersection(evidence_skus):
        return DeterministicFindings(
            guard_name="ENTITY_SKU_MISMATCH",
            passed=False,
            reason=f"SKU mismatch: claim specifies {claim_skus} but evidence refers to {evidence_skus}.",
            extracted_claim_values={"skus": list(claim_skus)},
            extracted_evidence_values={"skus": list(evidence_skus)},
        )

    # 6. Currency Mismatch Guard
    claim_currencies = extract_currency_codes(claim_text)
    evidence_currencies = extract_currency_codes(evidence_text)
    if claim_currencies and evidence_currencies and not claim_currencies.intersection(evidence_currencies):
        return DeterministicFindings(
            guard_name="CURRENCY_MISMATCH",
            passed=False,
            reason=f"Currency mismatch: claim uses {claim_currencies} while evidence specifies {evidence_currencies}.",
            extracted_claim_values={"currencies": list(claim_currencies)},
            extracted_evidence_values={"currencies": list(evidence_currencies)},
        )

    # 7. Temporal / Year Mismatch Guard (Passes when shared year or no year asserted)
    claim_years = extract_temporal_years(claim_text)
    evidence_years = extract_temporal_years(evidence_text)
    if claim_years and evidence_years and not claim_years.intersection(evidence_years):
        return DeterministicFindings(
            guard_name="TEMPORAL_YEAR_MISMATCH",
            passed=False,
            reason=f"Temporal mismatch: claim cites year {claim_years} but evidence is from {evidence_years}.",
            extracted_claim_values={"years": list(claim_years)},
            extracted_evidence_values={"years": list(evidence_years)},
        )

    # 8. Content Geographic Scope Mismatch Guard (Factual comparison, not security boundary)
    claim_scopes = extract_scope_regions(claim_text)
    evidence_scopes = extract_scope_regions(evidence_text)
    if claim_scopes and evidence_scopes and not claim_scopes.intersection(evidence_scopes):
        if "global" not in evidence_scopes:
            return DeterministicFindings(
                guard_name="GEOGRAPHIC_SCOPE_MISMATCH",
                passed=False,
                reason=f"Geographic scope mismatch: claim asserts scope {claim_scopes} but evidence only covers {evidence_scopes}.",
                extracted_claim_values={"scopes": list(claim_scopes)},
                extracted_evidence_values={"scopes": list(evidence_scopes)},
            )

    # 9. Numeric Conflict Guard (Unit-aligned quantitative comparison)
    claim_num_units = extract_numeric_tokens_with_units(claim_text)
    evidence_num_units = extract_numeric_tokens_with_units(evidence_text)

    claim_nums = [p[0] for p in claim_num_units]
    evidence_nums = [p[0] for p in evidence_num_units]

    if claim_num_units and evidence_num_units:
        for cn, c_unit in claim_num_units:
            if cn > 0 and cn not in evidence_nums:
                matching_unit_ev = [
                    en for en, e_unit in evidence_num_units
                    if (c_unit and e_unit and c_unit == e_unit) or (not c_unit and not e_unit and len(claim_nums) == 1 and len(evidence_nums) == 1)
                ]
                for en in matching_unit_ev:
                    if abs(cn - en) / max(cn, en) > 0.05:
                        return DeterministicFindings(
                            guard_name="NUMERIC_VALUE_MISMATCH",
                            passed=False,
                            reason=f"Numeric mismatch: claim asserts {cn} ({c_unit or 'unitless'}) but evidence specifies {en} ({c_unit or 'unitless'}).",
                            extracted_claim_values={"numbers": claim_nums, "units": [c_unit]},
                            extracted_evidence_values={"numbers": evidence_nums, "units": [c_unit]},
                        )

    return DeterministicFindings(
        guard_name="ALL_GUARDS_PASSED",
        passed=True,
        reason="Passed all pure deterministic guards.",
        extracted_claim_values={"numbers": claim_nums, "currencies": list(claim_currencies)},
        extracted_evidence_values={"numbers": evidence_nums, "currencies": list(evidence_currencies)},
    )


# ---------------------------------------------------------------------------
# Base Claim Verifier Interface
# ---------------------------------------------------------------------------

class BaseClaimVerifier(ABC):
    """Abstract interface for factual claim verification."""

    @abstractmethod
    def verify_claim(
        self,
        claim_text: str,
        evidence_text: str,
        claim_metadata: Optional[Dict[str, Any]] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
    ) -> ClaimVerificationResult:
        """Verify a single atomic claim against an evidence chunk."""
        raise NotImplementedError

    def verify_batch(
        self,
        requests: Sequence[Tuple[str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]],
    ) -> List[ClaimVerificationResult]:
        """Verify a batch of (claim_text, evidence_text, claim_metadata, source_metadata) tuples.

        Default implementation iterates verify_claim sequentially. Subclasses may override
        for batched neural tensor acceleration.
        """
        results = []
        for claim_text, evidence_text, claim_meta, source_meta in requests:
            results.append(self.verify_claim(claim_text, evidence_text, claim_meta, source_meta))
        return results


# ---------------------------------------------------------------------------
# Production Multilingual NLI Claim Verifier
# ---------------------------------------------------------------------------

class MultilingualNLIClaimVerifier(BaseClaimVerifier):
    """Production NLI claim verifier adapter backed by HuggingFace Transformers.

    Features:
    - Lazy model loading (weights loaded on first inference or explicit load_model)
    - Pinned model ID and revision commit
    - Dynamic label resolution via config (never hardcoded indices)
    - Deterministic pre-guard execution
    - Fail-closed fault tolerance (OOM, missing model, invalid labels return INCONCLUSIVE)
    - Device auto-detection (CUDA preferred when available, CPU fallback)
    - Batched inference API preserving sequence ordering
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        model_revision: str = DEFAULT_MODEL_REVISION,
        tau_entailment: float = PROVISIONAL_TAU_ENTAILMENT,
        tau_contradiction: float = PROVISIONAL_TAU_CONTRADICTION,
        device: str = "auto",
        max_length: int = 512,
    ) -> None:
        self.model_id = model_id
        self.model_revision = model_revision
        self.tau_entailment = tau_entailment
        self.tau_contradiction = tau_contradiction
        self.max_length = max_length

        self._requested_device = device
        self._active_device = "cpu"
        self._model = None
        self._tokenizer = None
        self._label_map: Dict[str, int] = {}
        self._is_loaded = False

    def load_model(self) -> bool:
        """Load tokenizer and model with strict pinning and error handling."""
        if self._is_loaded and self._model is not None:
            return True

        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            # 1. Resolve Device
            if self._requested_device == "auto":
                self._active_device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._active_device = self._requested_device

            logger.info(f"Loading NLI verifier: {self.model_id} (rev: {self.model_revision}) on {self._active_device}")

            # 2. Load Tokenizer & Model (trust_remote_code=False strictly enforced)
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                revision=self.model_revision,
                use_fast=True,
                trust_remote_code=False,
            )
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_id,
                revision=self.model_revision,
                trust_remote_code=False,
            )
            self._model.to(self._active_device)
            self._model.eval()

            # 3. Dynamic Label Resolution
            config = self._model.config
            raw_label2id = {k.lower(): int(v) for k, v in config.label2id.items()} if hasattr(config, "label2id") else {}
            raw_id2label = {int(k): v.lower() for k, v in config.id2label.items()} if hasattr(config, "id2label") else {}

            ent_idx = raw_label2id.get("entailment")
            neu_idx = raw_label2id.get("neutral")
            con_idx = raw_label2id.get("contradiction")

            if ent_idx is None or neu_idx is None or con_idx is None:
                # Fallback: scan id2label
                for idx, name in raw_id2label.items():
                    name_l = name.lower()
                    if "entail" in name_l:
                        ent_idx = idx
                    elif "contra" in name_l:
                        con_idx = idx
                    elif "neut" in name_l:
                        neu_idx = idx

            if ent_idx is None or neu_idx is None or con_idx is None:
                logger.error(f"Cannot resolve 3-way NLI labels from model config: {config}")
                self._is_loaded = False
                return False

            self._label_map = {
                "entailment": ent_idx,
                "neutral": neu_idx,
                "contradiction": con_idx,
            }

            self._is_loaded = True
            logger.info(f"NLI verifier loaded successfully. Label map: {self._label_map}")
            return True

        except Exception as e:
            logger.error(f"Failed to load NLI verifier ({self.model_id}): {e}", exc_info=True)
            self._model = None
            self._tokenizer = None
            self._is_loaded = False
            return False

    def verify_claim(
        self,
        claim_text: str,
        evidence_text: str,
        claim_metadata: Optional[Dict[str, Any]] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
    ) -> ClaimVerificationResult:
        """Verify an atomic claim using deterministic pre-guards + NLI inference."""
        claim_meta = claim_metadata or {}
        source_meta = source_metadata or {}
        source_id = source_meta.get("source_id") or source_meta.get("execution_id")
        evidence_refs = [str(source_id)] if source_id else []

        # 1. Deterministic Guard Layer
        guard_findings = audit_deterministic_claim_guards(
            claim_text=claim_text,
            evidence_text=evidence_text,
            claim_metadata=claim_meta,
            source_metadata=source_meta,
        )

        if not guard_findings.passed:
            g_name = str(guard_findings.guard_name)
            verdict = VerificationVerdict.INCONCLUSIVE
            if "SECURITY_SCOPE" in g_name or "PROVENANCE_SCOPE" in g_name:
                verdict = VerificationVerdict.SCOPE_VIOLATION
            elif "GEOGRAPHIC_SCOPE" in g_name or "MISMATCH" in g_name:
                verdict = VerificationVerdict.CONTRADICTED
            elif "MOCK" in g_name or "EXECUTION" in g_name:
                verdict = VerificationVerdict.UNSUPPORTED

            return ClaimVerificationResult(
                claim_text=claim_text,
                source_id=source_id,
                evidence_refs=evidence_refs,
                verdict=verdict,
                confidence=1.0,
                reason=f"Blocked by deterministic guard: {guard_findings.reason}",
                deterministic_findings=guard_findings,
                epistemic_type_preserved=guard_findings.extracted_claim_values.get("claim_class"),
            )

        # 2. Lazy Model Load
        if not self._is_loaded:
            loaded = self.load_model()
            if not loaded:
                return ClaimVerificationResult(
                    claim_text=claim_text,
                    source_id=source_id,
                    evidence_refs=evidence_refs,
                    verdict=VerificationVerdict.INCONCLUSIVE,
                    confidence=0.0,
                    reason="NLI verifier backend unavailable (model load failure). Fails closed.",
                    deterministic_findings=guard_findings,
                )

        # 3. Model Inference (Fail-closed)
        try:
            import numpy as np
            import torch

            t0 = time.perf_counter()
            inputs = self._tokenizer(
                evidence_text,
                claim_text,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            inputs = {k: v.to(self._active_device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits[0]
                probs = torch.softmax(logits, dim=-1).cpu().numpy()

            latency_ms = (time.perf_counter() - t0) * 1000.0

            p_ent = float(probs[self._label_map["entailment"]])
            p_neu = float(probs[self._label_map["neutral"]])
            p_con = float(probs[self._label_map["contradiction"]])

            # Determine Argmax
            scores_dict = {"ENTAILMENT": p_ent, "NEUTRAL": p_neu, "CONTRADICTION": p_con}
            argmax_label = max(scores_dict, key=scores_dict.get)

            semantic_scores = SemanticScores(
                p_entailment=round(p_ent, 6),
                p_neutral=round(p_neu, 6),
                p_contradiction=round(p_con, 6),
                argmax_label=argmax_label,
                raw_latency_ms=round(latency_ms, 2),
            )

            # 4. Apply Calibrated Provisional Thresholds
            if p_ent >= self.tau_entailment:
                verdict = VerificationVerdict.SUPPORTED
                confidence = p_ent
                reason = f"Verified with high entailment confidence (p_entailment={p_ent:.4f} >= {self.tau_entailment})."
            elif p_con >= self.tau_contradiction:
                verdict = VerificationVerdict.CONTRADICTED
                confidence = p_con
                reason = f"Contradiction detected (p_contradiction={p_con:.4f} >= {self.tau_contradiction})."
            else:
                verdict = VerificationVerdict.INCONCLUSIVE
                confidence = max(p_ent, p_con, p_neu)
                reason = (
                    f"Evidence is inconclusive for this claim (p_entailment={p_ent:.4f} < {self.tau_entailment}, "
                    f"p_contradiction={p_con:.4f} < {self.tau_contradiction})."
                )

            return ClaimVerificationResult(
                claim_text=claim_text,
                source_id=source_id,
                evidence_refs=evidence_refs,
                verdict=verdict,
                confidence=round(confidence, 4),
                reason=reason,
                model_id=self.model_id,
                backend=f"pytorch_{self._active_device}",
                deterministic_findings=guard_findings,
                semantic_scores=semantic_scores,
            )

        except Exception as e:
            logger.error(f"Inference exception during claim verification: {e}", exc_info=True)
            return ClaimVerificationResult(
                claim_text=claim_text,
                source_id=source_id,
                evidence_refs=evidence_refs,
                verdict=VerificationVerdict.INCONCLUSIVE,
                confidence=0.0,
                reason=f"Inference failure ({type(e).__name__}: {str(e)}). Fails closed.",
                deterministic_findings=guard_findings,
            )

    def verify_batch(
        self,
        requests: Sequence[Tuple[str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]],
    ) -> List[ClaimVerificationResult]:
        """Execute batched NLI inference with strict ordering preservation."""
        if not requests:
            return []

        # Check if all pass deterministic guards
        guard_results = []
        needs_nli_indices = []
        premises = []
        hypotheses = []

        for idx, (claim_text, evidence_text, claim_meta, source_meta) in enumerate(requests):
            findings = audit_deterministic_claim_guards(
                claim_text=claim_text,
                evidence_text=evidence_text,
                claim_metadata=claim_meta,
                source_metadata=source_meta,
            )
            guard_results.append(findings)
            if findings.passed:
                needs_nli_indices.append(idx)
                premises.append(evidence_text)
                hypotheses.append(claim_text)

        # If no items need NLI, return deterministic decisions directly
        results: List[Optional[ClaimVerificationResult]] = [None] * len(requests)
        for idx, (claim_text, evidence_text, claim_meta, source_meta) in enumerate(requests):
            findings = guard_results[idx]
            if not findings.passed:
                source_id = (source_meta or {}).get("source_id")
                g_name = str(findings.guard_name)
                verdict = VerificationVerdict.INCONCLUSIVE
                if "SECURITY_SCOPE" in g_name or "PROVENANCE_SCOPE" in g_name:
                    verdict = VerificationVerdict.SCOPE_VIOLATION
                elif "GEOGRAPHIC_SCOPE" in g_name or "MISMATCH" in g_name:
                    verdict = VerificationVerdict.CONTRADICTED
                elif "MOCK" in g_name or "EXECUTION" in g_name:
                    verdict = VerificationVerdict.UNSUPPORTED

                results[idx] = ClaimVerificationResult(
                    claim_text=claim_text,
                    source_id=source_id,
                    evidence_refs=[str(source_id)] if source_id else [],
                    verdict=verdict,
                    confidence=1.0,
                    reason=f"Blocked by deterministic guard: {findings.reason}",
                    deterministic_findings=findings,
                    epistemic_type_preserved=findings.extracted_claim_values.get("claim_class"),
                )

        if not needs_nli_indices:
            return [r for r in results if r is not None]

        # Load model for remaining items
        if not self._is_loaded:
            loaded = self.load_model()
            if not loaded:
                for idx in needs_nli_indices:
                    claim_text, evidence_text, claim_meta, source_meta = requests[idx]
                    source_id = (source_meta or {}).get("source_id")
                    results[idx] = ClaimVerificationResult(
                        claim_text=claim_text,
                        source_id=source_id,
                        evidence_refs=[str(source_id)] if source_id else [],
                        verdict=VerificationVerdict.INCONCLUSIVE,
                        confidence=0.0,
                        reason="NLI verifier backend unavailable. Fails closed.",
                        deterministic_findings=guard_results[idx],
                    )
                return [r for r in results if r is not None]

        # Execute batched inference
        try:
            import numpy as np
            import torch

            t0 = time.perf_counter()
            inputs = self._tokenizer(
                premises,
                hypotheses,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            inputs = {k: v.to(self._active_device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits
                probs_batch = torch.softmax(logits, dim=-1).cpu().numpy()

            batch_latency_ms = (time.perf_counter() - t0) * 1000.0
            per_item_latency_ms = batch_latency_ms / len(needs_nli_indices)

            for batch_pos, req_idx in enumerate(needs_nli_indices):
                claim_text, evidence_text, claim_meta, source_meta = requests[req_idx]
                source_id = (source_meta or {}).get("source_id")
                probs = probs_batch[batch_pos]

                p_ent = float(probs[self._label_map["entailment"]])
                p_neu = float(probs[self._label_map["neutral"]])
                p_con = float(probs[self._label_map["contradiction"]])

                scores_dict = {"ENTAILMENT": p_ent, "NEUTRAL": p_neu, "CONTRADICTION": p_con}
                argmax_label = max(scores_dict, key=scores_dict.get)

                semantic_scores = SemanticScores(
                    p_entailment=round(p_ent, 6),
                    p_neutral=round(p_neu, 6),
                    p_contradiction=round(p_con, 6),
                    argmax_label=argmax_label,
                    raw_latency_ms=round(per_item_latency_ms, 2),
                )

                if p_ent >= self.tau_entailment:
                    verdict = VerificationVerdict.SUPPORTED
                    confidence = p_ent
                    reason = f"Verified with high entailment confidence (p_entailment={p_ent:.4f} >= {self.tau_entailment})."
                elif p_con >= self.tau_contradiction:
                    verdict = VerificationVerdict.CONTRADICTED
                    confidence = p_con
                    reason = f"Contradiction detected (p_contradiction={p_con:.4f} >= {self.tau_contradiction})."
                else:
                    verdict = VerificationVerdict.INCONCLUSIVE
                    confidence = max(p_ent, p_con, p_neu)
                    reason = (
                        f"Evidence is inconclusive for this claim (p_entailment={p_ent:.4f} < {self.tau_entailment}, "
                        f"p_contradiction={p_con:.4f} < {self.tau_contradiction})."
                    )

                results[req_idx] = ClaimVerificationResult(
                    claim_text=claim_text,
                    source_id=source_id,
                    evidence_refs=[str(source_id)] if source_id else [],
                    verdict=verdict,
                    confidence=round(confidence, 4),
                    reason=reason,
                    model_id=self.model_id,
                    backend=f"pytorch_{self._active_device}",
                    deterministic_findings=guard_results[req_idx],
                    semantic_scores=semantic_scores,
                )

        except Exception as e:
            logger.error(f"Batch inference failure: {e}", exc_info=True)
            for req_idx in needs_nli_indices:
                claim_text, evidence_text, claim_meta, source_meta = requests[req_idx]
                source_id = (source_meta or {}).get("source_id")
                results[req_idx] = ClaimVerificationResult(
                    claim_text=claim_text,
                    source_id=source_id,
                    evidence_refs=[str(source_id)] if source_id else [],
                    verdict=VerificationVerdict.INCONCLUSIVE,
                    confidence=0.0,
                    reason=f"Batch inference failure ({type(e).__name__}: {str(e)}). Fails closed.",
                    deterministic_findings=guard_results[req_idx],
                )

        return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Deterministic Mock Verifier for Unit Testing
# ---------------------------------------------------------------------------

class MockClaimVerifier(BaseClaimVerifier):
    """Deterministic, configurable mock verifier for zero-download unit testing."""

    def __init__(
        self,
        forced_semantic_scores: Optional[Dict[Tuple[str, str], SemanticScores]] = None,
        default_semantic_scores: Optional[SemanticScores] = None,
        simulate_model_failure: bool = False,
        simulate_exception: bool = False,
        tau_entailment: float = PROVISIONAL_TAU_ENTAILMENT,
        tau_contradiction: float = PROVISIONAL_TAU_CONTRADICTION,
    ) -> None:
        self.forced_semantic_scores = forced_semantic_scores or {}
        self.default_semantic_scores = default_semantic_scores or SemanticScores(
            p_entailment=0.95, p_neutral=0.04, p_contradiction=0.01, argmax_label="ENTAILMENT"
        )
        self.simulate_model_failure = simulate_model_failure
        self.simulate_exception = simulate_exception
        self.tau_entailment = tau_entailment
        self.tau_contradiction = tau_contradiction

    def verify_claim(
        self,
        claim_text: str,
        evidence_text: str,
        claim_metadata: Optional[Dict[str, Any]] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
    ) -> ClaimVerificationResult:
        claim_meta = claim_metadata or {}
        source_meta = source_metadata or {}
        source_id = source_meta.get("source_id")

        if self.simulate_exception:
            return ClaimVerificationResult(
                claim_text=claim_text,
                source_id=source_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                reason="Simulated inference exception. Fails closed.",
            )

        # Deterministic Guard
        guard_findings = audit_deterministic_claim_guards(
            claim_text=claim_text,
            evidence_text=evidence_text,
            claim_metadata=claim_meta,
            source_metadata=source_meta,
        )

        if not guard_findings.passed:
            g_name = str(guard_findings.guard_name)
            verdict = VerificationVerdict.INCONCLUSIVE
            if "SECURITY_SCOPE" in g_name or "PROVENANCE_SCOPE" in g_name:
                verdict = VerificationVerdict.SCOPE_VIOLATION
            elif "GEOGRAPHIC_SCOPE" in g_name or "MISMATCH" in g_name:
                verdict = VerificationVerdict.CONTRADICTED
            elif "MOCK" in g_name or "EXECUTION" in g_name:
                verdict = VerificationVerdict.UNSUPPORTED

            return ClaimVerificationResult(
                claim_text=claim_text,
                source_id=source_id,
                evidence_refs=[str(source_id)] if source_id else [],
                verdict=verdict,
                confidence=1.0,
                reason=f"Blocked by deterministic guard: {guard_findings.reason}",
                deterministic_findings=guard_findings,
                epistemic_type_preserved=guard_findings.extracted_claim_values.get("claim_class"),
            )

        if self.simulate_model_failure:
            return ClaimVerificationResult(
                claim_text=claim_text,
                source_id=source_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                confidence=0.0,
                reason="Simulated model load failure. Fails closed.",
                deterministic_findings=guard_findings,
            )

        scores = self.forced_semantic_scores.get((evidence_text, claim_text), self.default_semantic_scores)

        if scores.p_entailment >= self.tau_entailment:
            verdict = VerificationVerdict.SUPPORTED
            conf = scores.p_entailment
            reason = f"Supported by mock semantic scoring (p_entailment={scores.p_entailment:.4f})."
        elif scores.p_contradiction >= self.tau_contradiction:
            verdict = VerificationVerdict.CONTRADICTED
            conf = scores.p_contradiction
            reason = f"Contradicted by mock semantic scoring (p_contradiction={scores.p_contradiction:.4f})."
        else:
            verdict = VerificationVerdict.INCONCLUSIVE
            conf = max(scores.p_entailment, scores.p_neutral, scores.p_contradiction)
            reason = f"Inconclusive mock semantic scoring."

        return ClaimVerificationResult(
            claim_text=claim_text,
            source_id=source_id,
            evidence_refs=[str(source_id)] if source_id else [],
            verdict=verdict,
            confidence=conf,
            reason=reason,
            model_id="mock-verifier-v1",
            backend="mock",
            deterministic_findings=guard_findings,
            semantic_scores=scores,
        )
