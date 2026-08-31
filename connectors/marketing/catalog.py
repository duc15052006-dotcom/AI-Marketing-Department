"""Governed provider catalog/wiring for external marketing v1.

This module centralizes descriptor/spec/executor registration for the provider
implementations that already exist in the platform. It deliberately does not
create ConnectionProfiles, resolve secrets, bind accounts, or enable LIVE runtime
execution. Those remain separate explicit authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from connectors.marketing.models import MarketingConnectorSpec, MarketingExecutionMode
from connectors.marketing.operations import ProviderOperationRepository
from connectors.marketing.preflight import ProviderPreflightRepository
from connectors.marketing.providers import (
    GoogleAdsReadExecutor,
    GoogleAnalyticsReadExecutor,
    MetaMarketingExecutor,
    TrackedTikTokMarketingExecutor,
)
from connectors.marketing.registry import MarketingConnectorRegistry
from connectors.models import AuthenticationType, ConnectorDescriptor, ReadWriteMode
from connectors.registry import ConnectorRegistry
from tools.capabilities import RiskLevel
from tools.dynamic_gateway.marketing_live import (
    MarketingLiveExecutor,
    MarketingLiveExecutorRegistry,
)


_CONNECTION_AUTHORITY = "connection_manager"

META_CONNECTOR_ID = "conn_meta_marketing"
TIKTOK_CONNECTOR_ID = "conn_tiktok_marketing"
GOOGLE_ADS_CONNECTOR_ID = "conn_google_ads"
GOOGLE_ANALYTICS_CONNECTOR_ID = "conn_google_analytics"


class MarketingProviderCatalogError(RuntimeError):
    """Base error for catalog installation failures."""


class MarketingProviderCatalogLiveRegistrationDisabledError(MarketingProviderCatalogError):
    pass


class MarketingProviderCatalogBindingError(MarketingProviderCatalogError):
    pass


@dataclass(frozen=True)
class MarketingProviderInstallReport:
    connector_ids: tuple[str, ...]
    executor_bindings: Mapping[str, str]
    live_runtime_enabled: bool = False
    connection_profiles_created: int = 0
    secrets_resolved: int = 0

    def to_safe_dict(self) -> Dict[str, object]:
        return {
            "connector_ids": list(self.connector_ids),
            "executor_bindings": dict(self.executor_bindings),
            "live_runtime_enabled": self.live_runtime_enabled,
            "connection_profiles_created": self.connection_profiles_created,
            "secrets_resolved": self.secrets_resolved,
        }


def _descriptor(
    *,
    connector_id: str,
    provider: str,
    capabilities: list[str],
    operations: list[str],
    mode: ReadWriteMode,
    risk: RiskLevel,
) -> ConnectorDescriptor:
    return ConnectorDescriptor(
        connector_id=connector_id,
        provider=provider,
        capability_ids=list(capabilities),
        authentication_type=AuthenticationType.OAUTH2,
        credential_env_names=[],
        read_write_mode=mode,
        risk_level=risk,
        supported_operations=list(operations),
        configuration_metadata={
            "credential_authority": _CONNECTION_AUTHORITY,
            "connection_profile_required": True,
            "legacy_env_health_disabled": True,
            "catalog": "marketing_provider_catalog_v1",
        },
    )


def default_connector_descriptors() -> tuple[ConnectorDescriptor, ...]:
    """Return fresh descriptor objects for the supported governed providers."""
    return (
        _descriptor(
            connector_id=META_CONNECTOR_ID,
            provider="meta",
            capabilities=["social_publishing", "analytics_retrieval"],
            operations=["publish_post", "read_metrics"],
            mode=ReadWriteMode.READ_WRITE,
            risk=RiskLevel.CRITICAL,
        ),
        _descriptor(
            connector_id=TIKTOK_CONNECTOR_ID,
            provider="tiktok",
            capabilities=["social_publishing", "analytics_retrieval"],
            operations=["query_creator_info", "publish_video", "fetch_publish_status"],
            mode=ReadWriteMode.READ_WRITE,
            risk=RiskLevel.CRITICAL,
        ),
        _descriptor(
            connector_id=GOOGLE_ADS_CONNECTOR_ID,
            provider="google_ads",
            capabilities=["analytics_retrieval"],
            operations=["campaign_performance"],
            mode=ReadWriteMode.READ_ONLY,
            risk=RiskLevel.LOW,
        ),
        _descriptor(
            connector_id=GOOGLE_ANALYTICS_CONNECTOR_ID,
            provider="google_analytics",
            capabilities=["analytics_retrieval"],
            operations=["run_report"],
            mode=ReadWriteMode.READ_ONLY,
            risk=RiskLevel.LOW,
        ),
    )


def default_marketing_specs() -> tuple[MarketingConnectorSpec, ...]:
    return (
        MarketingConnectorSpec(
            connector_id=META_CONNECTOR_ID,
            provider="meta",
            supported_capabilities=("social_publishing", "analytics_retrieval"),
            execution_mode=MarketingExecutionMode.LIVE,
        ),
        MarketingConnectorSpec(
            connector_id=TIKTOK_CONNECTOR_ID,
            provider="tiktok",
            supported_capabilities=("social_publishing", "analytics_retrieval"),
            execution_mode=MarketingExecutionMode.LIVE,
        ),
        MarketingConnectorSpec(
            connector_id=GOOGLE_ADS_CONNECTOR_ID,
            provider="google_ads",
            supported_capabilities=("analytics_retrieval",),
            execution_mode=MarketingExecutionMode.LIVE,
        ),
        MarketingConnectorSpec(
            connector_id=GOOGLE_ANALYTICS_CONNECTOR_ID,
            provider="google_analytics",
            supported_capabilities=("analytics_retrieval",),
            execution_mode=MarketingExecutionMode.LIVE,
        ),
    )


def default_live_executors(
    *,
    preflight_repository: ProviderPreflightRepository,
    operation_repository: ProviderOperationRepository,
) -> Dict[str, MarketingLiveExecutor]:
    """Build default provider executors without executing or resolving credentials."""
    if preflight_repository is None:
        raise MarketingProviderCatalogBindingError("TikTok requires ProviderPreflightRepository.")
    if operation_repository is None:
        raise MarketingProviderCatalogBindingError("TikTok requires ProviderOperationRepository.")
    return {
        META_CONNECTOR_ID: MetaMarketingExecutor(),
        TIKTOK_CONNECTOR_ID: TrackedTikTokMarketingExecutor(
            preflight_repository=preflight_repository,
            operation_repository=operation_repository,
        ),
        GOOGLE_ADS_CONNECTOR_ID: GoogleAdsReadExecutor(),
        GOOGLE_ANALYTICS_CONNECTOR_ID: GoogleAnalyticsReadExecutor(),
    }


class MarketingProviderCatalog:
    """Install known provider descriptors/specs/executors into existing authorities.

    Installation is configuration only. It never binds a connector to a
    ConnectionProfile and never toggles DynamicToolGateway LIVE execution.
    """

    def __init__(
        self,
        *,
        connector_registry: ConnectorRegistry,
        marketing_registry: MarketingConnectorRegistry,
        executor_registry: MarketingLiveExecutorRegistry,
    ) -> None:
        if executor_registry.marketing_registry is not marketing_registry:
            raise MarketingProviderCatalogBindingError(
                "executor_registry must use the same MarketingConnectorRegistry instance."
            )
        self.connector_registry = connector_registry
        self.marketing_registry = marketing_registry
        self.executor_registry = executor_registry

    def install(
        self,
        *,
        executors: Mapping[str, MarketingLiveExecutor],
        replace: bool = False,
    ) -> MarketingProviderInstallReport:
        """Register the standard catalog after explicit LIVE-registration opt-in."""
        if not self.marketing_registry.allow_live_registration:
            raise MarketingProviderCatalogLiveRegistrationDisabledError(
                "LIVE_MARKETING_REGISTRATION_DISABLED: enable the trusted marketing registry explicitly before catalog installation."
            )

        descriptors = default_connector_descriptors()
        specs = default_marketing_specs()
        expected_ids = {item.connector_id for item in specs}
        supplied_ids = {str(key).strip().lower() for key in executors}
        if supplied_ids != expected_ids:
            missing = sorted(expected_ids - supplied_ids)
            extra = sorted(supplied_ids - expected_ids)
            raise MarketingProviderCatalogBindingError(
                f"Executor catalog mismatch; missing={missing}, extra={extra}."
            )

        # Validate executor providers before mutating either registry.
        spec_by_id = {item.connector_id: item for item in specs}
        for connector_id, executor in executors.items():
            cid = str(connector_id).strip().lower()
            provider = str(getattr(executor, "provider", "") or "").strip().lower()
            executor_name = str(getattr(executor, "executor_name", "") or "").strip()
            if not executor_name or provider != spec_by_id[cid].provider:
                raise MarketingProviderCatalogBindingError(
                    f"Executor for '{cid}' does not match catalog provider '{spec_by_id[cid].provider}'."
                )

        # ConnectorRegistry descriptors are metadata only. Credential readiness
        # is delegated to ConnectorControlPlane/ConnectionManager by metadata.
        for descriptor in descriptors:
            existing = self.connector_registry.get_connector(descriptor.connector_id)
            if existing is not None and not replace:
                raise MarketingProviderCatalogBindingError(
                    f"Connector descriptor '{descriptor.connector_id}' already exists; use replace=True explicitly."
                )

        for spec in specs:
            try:
                self.marketing_registry.get(spec.connector_id)
            except Exception:
                pass
            else:
                if not replace:
                    raise MarketingProviderCatalogBindingError(
                        f"Marketing spec '{spec.connector_id}' already exists; use replace=True explicitly."
                    )

        for descriptor in descriptors:
            self.connector_registry.register_connector(descriptor)
        for spec in specs:
            self.marketing_registry.register(spec, replace=replace)
        for connector_id in sorted(expected_ids):
            self.executor_registry.bind(connector_id, executors[connector_id], replace=replace)

        return MarketingProviderInstallReport(
            connector_ids=tuple(sorted(expected_ids)),
            executor_bindings=self.executor_registry.list_bindings(),
            live_runtime_enabled=False,
            connection_profiles_created=0,
            secrets_resolved=0,
        )
