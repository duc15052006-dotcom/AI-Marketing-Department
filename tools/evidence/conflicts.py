"""Deterministic Evidence Conflict & Gap Tracker (Phase 3D.0 / 3D.1.1 Hardened).

Manages explicit conflict and tension representations between evidence items
with refined epistemic relation types (CONTRADICTION, TENSION, DIFFERENT_SCOPE, DIFFERENT_CONDITION)
and registers known empirical gaps without manufacturing false data.
"""

from __future__ import annotations

from typing import List, Optional, Union
from tools.evidence.models import ConflictRelationType, EvidenceConflict, EvidenceGap


class ConflictTracker:
    """Manages empirical conflicts and scope differences without premature resolution."""

    @staticmethod
    def create_conflict(
        topic: str,
        evidence_ids: List[str],
        relation_type: Union[ConflictRelationType, str] = ConflictRelationType.TENSION,
        claim_a: str = "",
        claim_b: str = "",
        shared_dimension: Optional[str] = None,
        condition_a: Optional[str] = None,
        condition_b: Optional[str] = None,
        description: str = "",
        limitations: Optional[List[str]] = None,
    ) -> EvidenceConflict:
        """Register a structured empirical conflict, tension, or scope difference."""
        rel_enum = (
            relation_type
            if isinstance(relation_type, ConflictRelationType)
            else ConflictRelationType(str(relation_type))
        )
        return EvidenceConflict(
            topic=topic,
            evidence_ids=evidence_ids,
            relation_type=rel_enum,
            claim_a=claim_a,
            claim_b=claim_b,
            shared_dimension=shared_dimension,
            condition_a=condition_a,
            condition_b=condition_b,
            resolution_status="UNRESOLVED",
            description=description,
            limitations=limitations
            or [
                f"Epistemic relation classified as {rel_enum.value}.",
                "Deterministic layer preserves unresolved tension without selecting a winner without explicit rules.",
            ],
        )


class GapTracker:
    """Registers known missing empirical evidence required for strategic reasoning."""

    @staticmethod
    def create_gap(
        question: str,
        required_evidence_type: str,
        importance: str = "HIGH",
    ) -> EvidenceGap:
        """Register an empirical evidence gap."""
        return EvidenceGap(
            question=question,
            required_evidence_type=required_evidence_type,
            importance=importance,
            status="MISSING",
        )
