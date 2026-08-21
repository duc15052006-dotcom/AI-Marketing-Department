"""Structured Claim Provenance and Status-Aware Types.

Defines:
1. MaterialClaim with explicit epistemic class, source type, and allowed usage
2. StatusAwareNumeric and StatusAwarePolicy to eliminate schema slot pressure
3. Status upgrade audit trail contracts
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from schemas.base import BaseModel, Field


class ClaimClass(str, Enum):
    """Epistemic class of a material claim."""
    VERIFIED_PRODUCT_FACT = "VERIFIED_PRODUCT_FACT"
    BUSINESS_FACT = "BUSINESS_FACT"
    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    CUSTOMER_OBSERVATION = "CUSTOMER_OBSERVATION"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    PROPOSED_TEST = "PROPOSED_TEST"
    PROPOSED_TARGET = "PROPOSED_TARGET"
    UNKNOWN = "UNKNOWN"


class SupportStatus(str, Enum):
    """Grounded support status of a claim."""
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    HUMAN_AUTHORIZED = "HUMAN_AUTHORIZED"


class AllowedUsage(str, Enum):
    """Permitted operational usage boundary for a claim."""
    PUBLIC_CLAIM = "PUBLIC_CLAIM"
    INTERNAL_PLANNING = "INTERNAL_PLANNING"
    EXPERIMENT_ONLY = "EXPERIMENT_ONLY"
    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"
    BLOCKED = "BLOCKED"


class SourceType(str, Enum):
    """Origin source category of a claim or value."""
    INPUT_SPEC = "INPUT_SPEC"
    VERIFIED_EVIDENCE = "VERIFIED_EVIDENCE"
    HUMAN_BUSINESS_INPUT = "HUMAN_BUSINESS_INPUT"
    DERIVED_CALCULATION = "DERIVED_CALCULATION"
    EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    AGENT_HYPOTHESIS = "AGENT_HYPOTHESIS"
    UNSUPPORTED_INVENTION = "UNSUPPORTED_INVENTION"


class ClaimStatusUpgradeRecord(BaseModel):
    """Audit record for any claim epistemic status transition."""
    previous_status: str
    new_status: str
    upgrade_source: SourceType
    upgrade_reason: str
    authorized_by: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MaterialClaim(BaseModel):
    """Structured material claim with full epistemic provenance."""
    claim_id: str
    claim_text: str
    claim_class: ClaimClass
    source_type: SourceType
    source_ids: List[str] = Field(default_factory=list)
    origin_agent: str
    support_status: SupportStatus = SupportStatus.SUPPORTED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    allowed_usage: AllowedUsage = AllowedUsage.INTERNAL_PLANNING
    requires_human_input: bool = False
    derived_from_claim_ids: List[str] = Field(default_factory=list)
    upgrade_history: List[ClaimStatusUpgradeRecord] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NumericStatus(str, Enum):
    """Status for numeric values avoiding schema fabrication pressure."""
    ESTABLISHED = "ESTABLISHED"
    TO_BE_ESTABLISHED = "TO_BE_ESTABLISHED"
    PROPOSED_FOR_TEST = "PROPOSED_FOR_TEST"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNKNOWN = "UNKNOWN"


class StatusAwareNumeric(BaseModel):
    """Nullable and status-aware numeric container for budgets, prices, KPIs, sample sizes."""
    value: Optional[Union[float, int]] = None
    unit: str = ""
    status: NumericStatus = NumericStatus.TO_BE_ESTABLISHED
    source_type: SourceType = SourceType.UNSUPPORTED_INVENTION
    source_ids: List[str] = Field(default_factory=list)
    derivation_formula: Optional[str] = None
    data_required: Optional[str] = None

    @classmethod
    def established(cls, value: Union[float, int], unit: str = "", source_type: SourceType = SourceType.INPUT_SPEC, source_ids: Optional[List[str]] = None) -> StatusAwareNumeric:
        return cls(
            value=value,
            unit=unit,
            status=NumericStatus.ESTABLISHED,
            source_type=source_type,
            source_ids=source_ids or [],
        )

    @classmethod
    def to_be_established(cls, unit: str = "", data_required: Optional[str] = None) -> StatusAwareNumeric:
        return cls(
            value=None,
            unit=unit,
            status=NumericStatus.TO_BE_ESTABLISHED,
            source_type=SourceType.UNSUPPORTED_INVENTION,
            data_required=data_required,
        )

    @classmethod
    def proposed_for_test(cls, proposed_value: Union[float, int], unit: str = "", rationale: Optional[str] = None) -> StatusAwareNumeric:
        return cls(
            value=proposed_value,
            unit=unit,
            status=NumericStatus.PROPOSED_FOR_TEST,
            source_type=SourceType.AGENT_HYPOTHESIS,
            derivation_formula=rationale,
        )


class StatusAwarePolicy(BaseModel):
    """Nullable status-aware container for warranties, return policies, trust badges."""
    policy_text: Optional[str] = None
    status: NumericStatus = NumericStatus.TO_BE_ESTABLISHED
    requires_human_authorization: bool = True
    source_type: SourceType = SourceType.UNSUPPORTED_INVENTION
    source_ids: List[str] = Field(default_factory=list)
    data_required: Optional[str] = None
