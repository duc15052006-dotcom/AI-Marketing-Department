"""Claim Governance and Safety Protocol.

Export core validators, audit gates, claim registers, and the runtime pipeline
orchestrator without eagerly importing the runtime/model stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from governance.claim_register import ClaimRegister, ClaimRegisterVersion
from governance.claim_safety import (
    ClaimStatusInvarianceValidator,
    CreativeClaimSafetyValidator,
    FinalClaimAuditGate,
    FinalClaimAuditGateResult,
    NumericAuthorityValidator,
    PerformancePlanningSafetyValidator,
    ProductClaimFirewall,
    ValidationDecision,
    validate_claim_lineage,
)

if TYPE_CHECKING:
    from governance.runtime_engine import (
        GovernedExecutionPipeline,
        PreHandoffAuditReport,
    )

_RUNTIME_EXPORTS = {
    "GovernedExecutionPipeline",
    "PreHandoffAuditReport",
}


def __getattr__(name: str) -> Any:
    """Lazily expose runtime exports to avoid model/governance import cycles.

    ``integrations.models.base`` depends on ``governance.redaction``. Importing a
    submodule first executes this package initializer, so eagerly importing
    ``governance.runtime_engine`` here would recurse back into the partially
    initialized model module. Runtime exports remain API-compatible but are
    loaded only when actually requested.
    """
    if name in _RUNTIME_EXPORTS:
        from governance.runtime_engine import (
            GovernedExecutionPipeline,
            PreHandoffAuditReport,
        )

        exports = {
            "GovernedExecutionPipeline": GovernedExecutionPipeline,
            "PreHandoffAuditReport": PreHandoffAuditReport,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ClaimRegister",
    "ClaimRegisterVersion",
    "ClaimStatusInvarianceValidator",
    "NumericAuthorityValidator",
    "ProductClaimFirewall",
    "CreativeClaimSafetyValidator",
    "PerformancePlanningSafetyValidator",
    "FinalClaimAuditGate",
    "FinalClaimAuditGateResult",
    "ValidationDecision",
    "validate_claim_lineage",
    "GovernedExecutionPipeline",
    "PreHandoffAuditReport",
]
