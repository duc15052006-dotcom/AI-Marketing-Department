"""Metadata-only registry and preparation gate for external marketing connectors.

The registry validates connector/provider/capability/account scope before a
future execution adapter is allowed to proceed. It never resolves credentials,
performs network I/O, consumes approvals, or executes platform side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from connectors.control_plane import ConnectorAuthorityState, ConnectorControlPlane
from connectors.marketing.models import (
    ExternalMarketingContractError,
    ExternalMarketingRequest,
    MarketingConnectorSpec,
    MarketingExecutionMode,
)


class MarketingConnectorRegistryError(RuntimeError):
    """Base registry/preparation error."""


class MarketingConnectorNotFoundError(MarketingConnectorRegistryError):
    pass


class MarketingConnectorRegistrationError(MarketingConnectorRegistryError):
    pass


class MarketingLiveExecutionDisabledError(MarketingConnectorRegistrationError):
    pass


class MarketingConnectionNotReadyError(MarketingConnectorRegistryError):
    pass


@dataclass(frozen=True)
class PreparedMarketingAction:
    """Secret-free preparation result for trusted gateway integration."""

    request_fingerprint: str
    request_id: str
    run_id: str
    connector_id: str
    provider: str
    connection_id: str
    capability_id: str
    effect: str
    risk_level: str
    approval_required: bool
    execution_mode: MarketingExecutionMode
    business_id: str
    project_id: str | None
    brand_id: str | None

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "request_fingerprint": self.request_fingerprint,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "connector_id": self.connector_id,
            "provider": self.provider,
            "connection_id": self.connection_id,
            "capability_id": self.capability_id,
            "effect": self.effect,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "execution_mode": self.execution_mode.value,
            "business_id": self.business_id,
            "project_id": self.project_id,
            "brand_id": self.brand_id,
            "credential_resolved": False,
            "network_called": False,
        }


class MarketingConnectorRegistry:
    """Fail-closed metadata registry for external marketing providers.

    ``allow_live_registration`` is intentionally false by default. Even when it
    is explicitly enabled, this class still has no execute method and cannot
    resolve secrets; LIVE only means the spec is eligible for a later trusted
    gateway adapter that must independently enforce approval/receipt semantics.
    """

    def __init__(
        self,
        control_plane: ConnectorControlPlane,
        *,
        allow_live_registration: bool = False,
    ) -> None:
        self.control_plane = control_plane
        self.allow_live_registration = bool(allow_live_registration)
        self._specs: Dict[str, MarketingConnectorSpec] = {}

    @staticmethod
    def _key(connector_id: str) -> str:
        return str(connector_id or "").strip().lower()

    def register(self, spec: MarketingConnectorSpec, *, replace: bool = False) -> MarketingConnectorSpec:
        key = self._key(spec.connector_id)
        if key in self._specs and not replace:
            raise MarketingConnectorRegistrationError(
                f"Marketing connector '{spec.connector_id}' is already registered; use replace=True explicitly."
            )
        if spec.execution_mode is MarketingExecutionMode.LIVE and not self.allow_live_registration:
            raise MarketingLiveExecutionDisabledError(
                "LIVE_MARKETING_REGISTRATION_DISABLED: explicit trusted opt-in is required."
            )

        descriptor = self.control_plane.connector_registry.get_connector(spec.connector_id)
        if descriptor is None:
            raise MarketingConnectorRegistrationError(
                f"Connector descriptor '{spec.connector_id}' must exist before marketing registration."
            )
        if descriptor.provider.strip().lower() != spec.provider:
            raise MarketingConnectorRegistrationError(
                f"Connector '{spec.connector_id}' provider does not match marketing spec provider."
            )

        descriptor_capabilities = {str(item).strip().lower() for item in descriptor.capability_ids}
        missing = sorted(set(spec.supported_capabilities) - descriptor_capabilities)
        if missing:
            raise MarketingConnectorRegistrationError(
                f"Connector '{spec.connector_id}' descriptor does not declare capabilities: {', '.join(missing)}."
            )

        self._specs[key] = spec
        return spec

    def get(self, connector_id: str) -> MarketingConnectorSpec:
        key = self._key(connector_id)
        try:
            return self._specs[key]
        except KeyError as exc:
            raise MarketingConnectorNotFoundError(
                f"Marketing connector '{connector_id}' is not registered."
            ) from exc

    def list_specs(self) -> List[MarketingConnectorSpec]:
        return [self._specs[key] for key in sorted(self._specs)]

    def prepare(self, request: ExternalMarketingRequest) -> PreparedMarketingAction:
        """Validate routing/account scope without reading a credential.

        Preparation is deliberately not execution. Approval artifacts remain a
        DynamicToolGateway concern, and plaintext credentials remain inaccessible
        from this registry.
        """
        if not isinstance(request, ExternalMarketingRequest):
            raise ExternalMarketingContractError("request must be an ExternalMarketingRequest instance.")

        spec = self.get(request.connector_id)
        if request.capability_id not in spec.supported_capabilities:
            raise MarketingConnectorRegistryError(
                f"Capability '{request.capability_id}' is not supported by connector '{spec.connector_id}'."
            )

        status = self.control_plane.get_status(
            spec.connector_id,
            business_id=request.business_id,
            project_id=request.project_id,
            brand_id=request.brand_id,
            connection_id=request.connection_id,
        )
        if status.state is not ConnectorAuthorityState.CONFIGURED_UNVERIFIED:
            raise MarketingConnectionNotReadyError(
                f"MARKETING_CONNECTION_NOT_READY: connector '{spec.connector_id}' account selection is {status.state.value}."
            )
        if status.connection_id != request.connection_id:
            raise MarketingConnectionNotReadyError(
                "MARKETING_CONNECTION_SELECTION_MISMATCH: exact connection_id authorization could not be proven."
            )

        policy = request.policy
        return PreparedMarketingAction(
            request_fingerprint=request.fingerprint(),
            request_id=request.request_id,
            run_id=request.run_id,
            connector_id=spec.connector_id,
            provider=spec.provider,
            connection_id=request.connection_id,
            capability_id=request.capability_id,
            effect=policy.effect.value,
            risk_level=policy.risk_level.value,
            approval_required=policy.approval_required,
            execution_mode=spec.execution_mode,
            business_id=request.business_id,
            project_id=request.project_id,
            brand_id=request.brand_id,
        )
