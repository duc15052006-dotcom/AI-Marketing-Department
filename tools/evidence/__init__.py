"""Evidence Integration Package (Phase 3D.0 / 3D.1 / 3D.1.3).

Provides deterministic mapping from raw ObservationRecords into structured EvidenceItems,
compiles isolated EvidenceBundles, tracks empirical conflicts and gaps, audits source family coverage
and research dimensions, enforces structured relevance traces, and validates semantic coherence.
"""

from __future__ import annotations

from tools.evidence.builder import EvidenceBuilder, ProductIsolationViolationError
from tools.evidence.conflicts import ConflictTracker, GapTracker
from tools.evidence.freshness import FreshnessEvaluator
from tools.evidence.grounding import GroundingContextBuilder
from tools.evidence.models import (
    AliasVerificationStatus,
    CollectionProvenance,
    ConflictRelationType,
    ContentRole,
    DimensionCoverageStatus,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceGap,
    EvidenceItem,
    FreshnessPolicy,
    FreshnessPolicySource,
    FreshnessState,
    GroundingContext,
    GroundingMetadata,
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
    ResearchSubject,
    SemanticCoherenceStatus,
    SourceFamily,
    SourceProvenance,
    SourceRelationship,
    SubjectAlias,
    SubjectAliasType,
    SubjectIdentity,
    VideoSubstantiveCoverage,
)
from tools.evidence.relevance import (
    EvidenceBundleSemanticValidator,
    EvidenceRelevanceGate,
    ResearchDimensionEvaluator,
)

__all__ = [
    "ContentRole",
    "CollectionProvenance",
    "SourceProvenance",
    "SourceRelationship",
    "SourceFamily",
    "ResearchSourceCoverage",
    "VideoSubstantiveCoverage",
    "DimensionCoverageStatus",
    "SemanticCoherenceStatus",
    "RelevanceStatus",
    "ConflictRelationType",
    "FreshnessState",
    "FreshnessPolicy",
    "FreshnessPolicySource",
    "AliasVerificationStatus",
    "SubjectAliasType",
    "SubjectAlias",
    "RelevanceAnchorType",
    "RelevanceMatchField",
    "RelevanceMatchMethod",
    "RelevanceTraceItem",
    "SubjectIdentity",
    "ResearchSubject",
    "ResearchDimension",
    "ResearchCoverageReport",
    "RelevanceAssessment",
    "RejectedEvidenceRecord",
    "EvidenceItem",
    "EvidenceConflict",
    "EvidenceGap",
    "EvidenceBundle",
    "GroundingMetadata",
    "GroundingContext",
    "FreshnessEvaluator",
    "ConflictTracker",
    "GapTracker",
    "EvidenceBuilder",
    "ProductIsolationViolationError",
    "GroundingContextBuilder",
    "EvidenceRelevanceGate",
    "ResearchDimensionEvaluator",
    "EvidenceBundleSemanticValidator",
]
