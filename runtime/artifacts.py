"""Run Artifact and Memory Write Candidate Models (Phase 5.2).

Defines serializable, hashable DepartmentRunArtifact and MemoryWriteCandidate
guaranteeing no raw model output is auto-promoted into trusted learning.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from memory.models import MemoryItem, MemoryType, PromotionState
from runtime.context import RuntimeStatus
from schemas.base import BaseModel, Field
from tools.receipts import ExecutionReceipt


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
    errors: List[str] = Field(default_factory=list)
    final_artifact_hash: str = Field(default="")

    def compute_artifact_hash(self) -> str:
        """Compute authoritative SHA-256 fingerprint of the complete run artifact."""
        raw = (
            f"{self.run_id}:{self.objective}:{self.status.value}:"
            f"{json.dumps(self.agent_outputs, sort_keys=True, ensure_ascii=False)}:"
            f"{json.dumps([r.execution_id for r in self.execution_receipts])}:"
            f"{json.dumps(self.final_cmo_output, sort_keys=True, ensure_ascii=False)}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
