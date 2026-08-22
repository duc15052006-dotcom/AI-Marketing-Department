"""Run Artifact and Memory Write Candidate Models (Phase 5.2).

Defines serializable, hashable DepartmentRunArtifact and MemoryWriteCandidate
guaranteeing no raw model output is auto-promoted into trusted learning.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from memory.models import MemoryItem, MemoryType, PromotionState
from runtime.context import RuntimeStatus
from schemas.base import BaseModel, Field
from tools.receipts import ExecutionReceipt


def _normalize_for_hashing(obj: Any) -> Any:
    """Recursively normalize enums, pydantic models, dataclasses, dicts, lists for deterministic hashing."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        return _normalize_for_hashing(obj.model_dump())
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return _normalize_for_hashing(obj.to_dict())
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return _normalize_for_hashing(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _normalize_for_hashing(v) for k, v in sorted(obj.items(), key=lambda item: str(item[0]))}
    if isinstance(obj, (list, tuple)):
        return [_normalize_for_hashing(item) for item in obj]
    if isinstance(obj, set):
        return sorted([_normalize_for_hashing(item) for item in obj], key=lambda x: str(x))
    return str(obj)


class MemoryWriteCandidate(BaseModel):
    """Candidate memory entry proposed at the conclusion of a supervised run."""
    memory_type: MemoryType
    agent_source: str
    content: str
    context: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    target_initial_state: PromotionState = Field(
        default=PromotionState.RAW_OBSERVATION,
        description="Must be RAW_OBSERVATION or CANDIDATE_MEMORY; automatic PROMOTED_LEARNING is strictly prohibited.",
    )

    def to_memory_item(self, run_id: str) -> MemoryItem:
        """Convert write candidate into a formal MemoryItem."""
        # Enforce non-automatic promotion rule
        initial_state = (
            self.target_initial_state
            if self.target_initial_state in (PromotionState.RAW_OBSERVATION, PromotionState.CANDIDATE_MEMORY)
            else PromotionState.CANDIDATE_MEMORY
        )
        return MemoryItem(
            memory_type=self.memory_type,
            agent_source=self.agent_source,
            run_id=run_id,
            content=self.content,
            context=self.context,
            evidence_refs=self.evidence_refs,
            confidence=self.confidence,
            promotion_level=initial_state,
        )


class DepartmentRunArtifact(BaseModel):
    """Complete, immutable audit artifact produced at the conclusion of a department run."""
    run_id: str
    objective: str
    started_at: datetime
    completed_at: datetime
    status: RuntimeStatus
    agent_outputs: Dict[str, Any] = Field(default_factory=dict)
    knowledge_used: List[str] = Field(default_factory=list)
    memory_used: List[str] = Field(default_factory=list)
    capabilities_used: List[str] = Field(default_factory=list)
    execution_receipts: List[ExecutionReceipt] = Field(default_factory=list)
    approvals: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)
    learning_candidates: List[MemoryWriteCandidate] = Field(default_factory=list)
    final_cmo_output: Dict[str, Any] = Field(default_factory=dict)
    lineage_summary: Dict[str, Any] = Field(default_factory=dict)
    binding_constraints: List[str] = Field(default_factory=list, description="Structural user/business restrictions in force for this run (COLLAB-03)")
    epistemic_handoffs: Dict[str, Any] = Field(default_factory=dict, description="Per-stage structured epistemic handoffs (COLLAB-05)")
    claim_verification_ledger: List[Any] = Field(default_factory=list, description="Authoritative sealed claim verification audit records (CLAIM-04)")
    errors: List[str] = Field(default_factory=list)
    final_artifact_hash: str = Field(default="")

    def _receipt_integrity_representation(self, r: Any) -> Dict[str, Any]:
        """Extract canonical immutable integrity fields for an ExecutionReceipt."""
        if hasattr(r, "model_dump") and callable(r.model_dump):
            dump = r.model_dump()
            return {
                "execution_id": str(dump.get("execution_id", "")),
                "run_id": str(dump.get("run_id", "")),
                "agent_id": str(dump.get("agent_id", "")),
                "capability_id": str(dump.get("capability_id", "")),
                "provider": str(dump.get("provider", "")),
                "request_hash": str(dump.get("request_hash", "")),
                "execution_mode": _normalize_for_hashing(dump.get("execution_mode", "")),
                "status": _normalize_for_hashing(dump.get("status", "")),
                "error_class": dump.get("error_class"),
                "result_hash": str(dump.get("result_hash", "")),
            }
        elif isinstance(r, dict):
            return {
                "execution_id": str(r.get("execution_id", "")),
                "run_id": str(r.get("run_id", "")),
                "agent_id": str(r.get("agent_id", "")),
                "capability_id": str(r.get("capability_id", "")),
                "provider": str(r.get("provider", "")),
                "request_hash": str(r.get("request_hash", "")),
                "execution_mode": _normalize_for_hashing(r.get("execution_mode", "")),
                "status": _normalize_for_hashing(r.get("status", "")),
                "error_class": r.get("error_class"),
                "result_hash": str(r.get("result_hash", "")),
            }
        return {
            "execution_id": str(getattr(r, "execution_id", str(r))),
            "execution_mode": _normalize_for_hashing(getattr(r, "execution_mode", "")),
            "status": _normalize_for_hashing(getattr(r, "status", "")),
            "capability_id": str(getattr(r, "capability_id", "")),
            "provider": str(getattr(r, "provider", "")),
            "request_hash": str(getattr(r, "request_hash", "")),
            "result_hash": str(getattr(r, "result_hash", "")),
        }

    def _claim_verification_integrity_representation(self, c: Any) -> Dict[str, Any]:
        """Extract canonical bounded immutable integrity fields for a claim verification record."""
        if hasattr(c, "model_dump") and callable(c.model_dump):
            d = c.model_dump()
        elif hasattr(c, "dict") and callable(c.dict):
            d = c.dict()
        elif isinstance(c, dict):
            d = c
        else:
            d = {}

        df = d.get("deterministic_findings")
        df_dict = None
        if isinstance(df, dict):
            df_dict = {
                "guard_name": str(df.get("guard_name") or ""),
                "passed": bool(df.get("passed", True)),
                "reason": str(df.get("reason") or ""),
                "extracted_claim_values": _normalize_for_hashing(df.get("extracted_claim_values") or {}),
                "extracted_evidence_values": _normalize_for_hashing(df.get("extracted_evidence_values") or {}),
            }
        elif hasattr(df, "guard_name"):
            df_dict = {
                "guard_name": str(getattr(df, "guard_name", "") or ""),
                "passed": bool(getattr(df, "passed", True)),
                "reason": str(getattr(df, "reason", "") or ""),
                "extracted_claim_values": _normalize_for_hashing(getattr(df, "extracted_claim_values", {})),
                "extracted_evidence_values": _normalize_for_hashing(getattr(df, "extracted_evidence_values", {})),
            }

        ss = d.get("semantic_scores")
        ss_dict = None
        if isinstance(ss, dict):
            ss_dict = {
                "p_entailment": round(float(ss.get("p_entailment", 0.0)), 6),
                "p_neutral": round(float(ss.get("p_neutral", 0.0)), 6),
                "p_contradiction": round(float(ss.get("p_contradiction", 0.0)), 6),
                "argmax_label": str(ss.get("argmax_label") or ""),
            }
        elif hasattr(ss, "p_entailment"):
            ss_dict = {
                "p_entailment": round(float(getattr(ss, "p_entailment", 0.0)), 6),
                "p_neutral": round(float(getattr(ss, "p_neutral", 0.0)), 6),
                "p_contradiction": round(float(getattr(ss, "p_contradiction", 0.0)), 6),
                "argmax_label": str(getattr(ss, "argmax_label", "") or ""),
            }

        return {
            "claim_text": str(d.get("claim_text", "")),
            "source_id": str(d.get("source_id", "")),
            "evidence_refs": _normalize_for_hashing(d.get("evidence_refs") or []),
            "evidence_content_hash": str(d.get("evidence_content_hash") or ""),
            "verdict": _normalize_for_hashing(d.get("verdict", "")),
            "reason": str(d.get("reason", "")),
            "model_id": str(d.get("model_id", "")),
            "model_revision": str(d.get("model_revision", "")),
            "backend": str(d.get("backend", "")),
            "deterministic_findings": df_dict,
            "semantic_scores": ss_dict,
            "provenance_context_hash": str(d.get("provenance_context_hash") or ""),
        }

    def _integrity_payload(self) -> Dict[str, Any]:
        """Construct the authoritative integrity payload representing all business, epistemic, and governance state."""
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "agent_outputs": _normalize_for_hashing(self.agent_outputs),
            "final_cmo_output": _normalize_for_hashing(self.final_cmo_output),
            "binding_constraints": _normalize_for_hashing(self.binding_constraints),
            "epistemic_handoffs": _normalize_for_hashing(self.epistemic_handoffs),
            "claim_verification_ledger": [
                self._claim_verification_integrity_representation(c)
                for c in self.claim_verification_ledger
            ],
            "execution_receipts": [
                self._receipt_integrity_representation(r)
                for r in self.execution_receipts
            ],
            "errors": _normalize_for_hashing(self.errors),
        }

    def compute_artifact_hash(self) -> str:
        """Compute authoritative SHA-256 fingerprint of the complete run artifact."""
        payload = self._integrity_payload()
        canonical_raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical_raw.encode("utf-8")).hexdigest()
