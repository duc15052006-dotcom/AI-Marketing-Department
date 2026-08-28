"""Deterministic Evidence Conflict & Gap Tracker (Phase 3D.0 / 3D.1.1 / B4 Hardened).

Manages explicit conflict and tension representations between evidence items
with refined epistemic relation types (CONTRADICTION, TENSION, DIFFERENT_CONDITION)
and registers known empirical gaps without manufacturing false data.

B4: Adds deterministic gap detection from ResearchDimension coverage status.
Automatic conflict detection is NOT implemented — the existing EvidenceItem model
lacks the structured claim/metric/value fields needed for deterministic comparison.
Explicit canonical EvidenceConflict records are preserved and enforced.
"""

from __future__ import annotations

from typing import List, Optional, Union
from tools.evidence.models import (
    ConflictRelationType,
    DimensionCoverageStatus,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceGap,
    RelevanceStatus,
    ResearchDimension,
)


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

    @classmethod
    def detect_conflicts(
        cls,
        bundle: EvidenceBundle,
    ) -> List[EvidenceConflict]:
        """Detect structurally provable conflicts between evidence items.

        AUTOMATIC_CONFLICT_DETECTION = NO

        The existing EvidenceItem model does not contain structured fields for
        same claim / same entity / same metric / same time window / incompatible
        values. bounded_content is free text; semantic contradiction detection
        requires structured claim values not yet in the data model.

        Scope differences (different product_id, run_id, business_id, project_id)
        are isolation/authorization concerns handled by canonical scope authority
        (ScopeViolationError, ProductIsolationViolationError). They are NOT
        epistemic contradictions and must NOT produce EvidenceConflict records.

        Same capability + same domain with different independent claims is NOT
        a conflict — it is normal multi-source evidence collection.

        This method always returns an empty list. Explicit canonical EvidenceConflict
        records attached to the bundle by upstream callers are preserved and enforced.
        """
        return []


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

    @classmethod
    def detect_gaps(
        cls,
        bundle: EvidenceBundle,
    ) -> List[EvidenceGap]:
        """Detect evidence gaps from ResearchDimension coverage status.

        Creates a gap for each ResearchDimension with UNSUPPORTED coverage status.
        This is deterministic: gaps are derived directly from the dimension evaluator's
        structured output, not from LLM reasoning or semantic guessing.

        A gap means: the system has an explicit deterministic expected information
        need for which sufficient eligible evidence is missing.

        Does NOT create gaps for:
        - SUPPORTED dimensions (evidence exists)
        - PARTIAL dimensions (some evidence exists, limitations noted)
        - IRRELEVANT evidence (does not close gaps)
        - UNKNOWN relevance evidence (does not deterministically close gaps)
        """
        gaps: List[EvidenceGap] = []

        for dim in bundle.research_dimensions:
            if dim.coverage_status == DimensionCoverageStatus.UNSUPPORTED:
                gaps.append(cls.create_gap(
                    question=dim.question,
                    required_evidence_type=", ".join(
                        r.value for r in dim.required_evidence_roles
                    ) if dim.required_evidence_roles else "ANY",
                    importance="HIGH",
                ))
                # Also attach dimension_id to the gap for traceability
                if gaps and gaps[-1].dimension_id is None:
                    gaps[-1].dimension_id = dim.dimension_id

        return gaps
