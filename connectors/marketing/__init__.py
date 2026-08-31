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
    "MarketingConnectionNotReadyError",
    "MarketingConnectorNotFoundError",
    "MarketingConnectorRegistrationError",
    "MarketingConnectorRegistry",
    "MarketingConnectorRegistryError",
    "MarketingLiveExecutionDisabledError",
    "PreparedMarketingAction",
]
