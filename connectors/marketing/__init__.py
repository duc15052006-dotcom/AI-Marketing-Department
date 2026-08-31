"""External marketing connector foundation exports."""

from connectors.marketing.models import (
    ExternalMarketingContractError,
    ExternalMarketingRequest,
    MarketingCapabilityPolicy,
    MarketingConnectorSpec,
    MarketingEffect,
    MarketingExecutionMode,
    UnsafeMarketingPayloadError,
    UnsupportedMarketingCapabilityError,
    policy_for,
)
from connectors.marketing.preflight import (
    ProviderPreflightArtifact,
    ProviderPreflightConflictError,
    ProviderPreflightError,
    ProviderPreflightIntegrityError,
    ProviderPreflightRepository,
    ProviderPreflightState,
)
from connectors.marketing.registry import (
    MarketingConnectionNotReadyError,
    MarketingConnectorNotFoundError,
    MarketingConnectorRegistrationError,
    MarketingConnectorRegistry,
    MarketingConnectorRegistryError,
    MarketingLiveExecutionDisabledError,
    PreparedMarketingAction,
)

__all__ = [
    "ExternalMarketingContractError",
    "ExternalMarketingRequest",
    "MarketingCapabilityPolicy",
    "MarketingConnectorSpec",
    "MarketingEffect",
    "MarketingExecutionMode",
    "UnsafeMarketingPayloadError",
    "UnsupportedMarketingCapabilityError",
    "policy_for",
    "ProviderPreflightArtifact",
    "ProviderPreflightConflictError",
    "ProviderPreflightError",
    "ProviderPreflightIntegrityError",
    "ProviderPreflightRepository",
    "ProviderPreflightState",
    "MarketingConnectionNotReadyError",
    "MarketingConnectorNotFoundError",
    "MarketingConnectorRegistrationError",
    "MarketingConnectorRegistry",
    "MarketingConnectorRegistryError",
    "MarketingLiveExecutionDisabledError",
    "PreparedMarketingAction",
]
