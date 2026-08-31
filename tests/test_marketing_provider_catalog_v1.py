from __future__ import annotations

import unittest

from connections.manager import ConnectionManager
from connections.secrets import SecretNotFoundError, SecretValue
from connectors.control_plane import ConnectorControlPlane
from connectors.marketing.catalog import (
    GOOGLE_ADS_CONNECTOR_ID,
    GOOGLE_ANALYTICS_CONNECTOR_ID,
    META_CONNECTOR_ID,
    TIKTOK_CONNECTOR_ID,
    MarketingProviderCatalog,
    MarketingProviderCatalogBindingError,
    MarketingProviderCatalogLiveRegistrationDisabledError,
    default_live_executors,
)
from connectors.marketing.operations import ProviderOperationRepository
from connectors.marketing.preflight import ProviderPreflightRepository
from connectors.marketing.providers import MetaMarketingExecutor, TrackedTikTokMarketingExecutor
from connectors.marketing.registry import MarketingConnectorRegistry
from connectors.models import ConnectorHealthStatus, CredentialState, ReadWriteMode
from connectors.registry import ConnectorRegistry
from tools.dynamic_gateway.marketing_live import MarketingLiveExecutorRegistry


class _CountingSecretProvider:
    def __init__(self) -> None:
        self.get_calls = 0

    def can_resolve(self, secret_ref: str) -> bool:
        return str(secret_ref).startswith("test:")

    def get(self, secret_ref: str) -> SecretValue:
        self.get_calls += 1
        raise SecretNotFoundError("test provider intentionally has no plaintext secret")


class MarketingProviderCatalogV1Tests(unittest.TestCase):
    def _stack(self, *, allow_live_registration: bool):
        secrets = _CountingSecretProvider()
        connection_manager = ConnectionManager(secrets)
        connector_registry = ConnectorRegistry()
        control_plane = ConnectorControlPlane(connector_registry, connection_manager)
        marketing_registry = MarketingConnectorRegistry(
            control_plane,
            allow_live_registration=allow_live_registration,
        )
        executor_registry = MarketingLiveExecutorRegistry(marketing_registry)
        catalog = MarketingProviderCatalog(
            connector_registry=connector_registry,
            marketing_registry=marketing_registry,
            executor_registry=executor_registry,
        )
        preflights = ProviderPreflightRepository()
        operations = ProviderOperationRepository()
        executors = default_live_executors(
            preflight_repository=preflights,
            operation_repository=operations,
        )
        return {
            "secrets": secrets,
            "connection_manager": connection_manager,
            "connector_registry": connector_registry,
            "control_plane": control_plane,
            "marketing_registry": marketing_registry,
            "executor_registry": executor_registry,
            "catalog": catalog,
            "preflights": preflights,
            "operations": operations,
            "executors": executors,
        }

    def test_live_registration_must_be_explicit_before_any_catalog_mutation(self):
        stack = self._stack(allow_live_registration=False)
        with self.assertRaises(MarketingProviderCatalogLiveRegistrationDisabledError):
            stack["catalog"].install(executors=stack["executors"])
        self.assertIsNone(stack["connector_registry"].get_connector(META_CONNECTOR_ID))
        self.assertEqual(stack["executor_registry"].list_bindings(), {})
        self.assertEqual(stack["secrets"].get_calls, 0)

    def test_successful_install_registers_four_specs_and_bindings_without_accounts_or_secrets(self):
        stack = self._stack(allow_live_registration=True)
        report = stack["catalog"].install(executors=stack["executors"])
        expected = {
            META_CONNECTOR_ID,
            TIKTOK_CONNECTOR_ID,
            GOOGLE_ADS_CONNECTOR_ID,
            GOOGLE_ANALYTICS_CONNECTOR_ID,
        }
        self.assertEqual(set(report.connector_ids), expected)
        self.assertEqual(set(report.executor_bindings), expected)
        self.assertFalse(report.live_runtime_enabled)
        self.assertEqual(report.connection_profiles_created, 0)
        self.assertEqual(report.secrets_resolved, 0)
        self.assertEqual(stack["connection_manager"].list_profiles(), [])
        self.assertEqual(stack["control_plane"].list_bindings(), [])
        self.assertEqual(stack["secrets"].get_calls, 0)
        self.assertEqual(
            {spec.connector_id for spec in stack["marketing_registry"].list_specs()},
            expected,
        )

    def test_normalized_executor_keys_bind_using_canonical_ids(self):
        stack = self._stack(allow_live_registration=True)
        normalized_input = {
            f"  {connector_id.upper()}  ": executor
            for connector_id, executor in stack["executors"].items()
        }
        report = stack["catalog"].install(executors=normalized_input)
        self.assertEqual(
            set(report.executor_bindings),
            {
                META_CONNECTOR_ID,
                TIKTOK_CONNECTOR_ID,
                GOOGLE_ADS_CONNECTOR_ID,
                GOOGLE_ANALYTICS_CONNECTOR_ID,
            },
        )

    def test_duplicate_normalized_executor_key_fails_before_any_mutation(self):
        stack = self._stack(allow_live_registration=True)
        duplicate = dict(stack["executors"])
        duplicate[f"  {META_CONNECTOR_ID.upper()}  "] = stack["executors"][META_CONNECTOR_ID]
        with self.assertRaises(MarketingProviderCatalogBindingError):
            stack["catalog"].install(executors=duplicate)
        self.assertIsNone(stack["connector_registry"].get_connector(META_CONNECTOR_ID))
        self.assertEqual(stack["marketing_registry"].list_specs(), [])
        self.assertEqual(stack["executor_registry"].list_bindings(), {})
        self.assertEqual(stack["secrets"].get_calls, 0)

    def test_managed_connector_health_delegates_credential_readiness(self):
        stack = self._stack(allow_live_registration=True)
        stack["catalog"].install(executors=stack["executors"])
        health = stack["connector_registry"].list_connector_health()
        for connector_id in (
            META_CONNECTOR_ID,
            TIKTOK_CONNECTOR_ID,
            GOOGLE_ADS_CONNECTOR_ID,
            GOOGLE_ANALYTICS_CONNECTOR_ID,
        ):
            self.assertEqual(health[connector_id]["health_status"], ConnectorHealthStatus.AVAILABLE.value)
            self.assertEqual(health[connector_id]["credential_state"], CredentialState.UNKNOWN.value)
        self.assertEqual(stack["secrets"].get_calls, 0)

    def test_descriptor_modes_and_providers_are_exact(self):
        stack = self._stack(allow_live_registration=True)
        stack["catalog"].install(executors=stack["executors"])
        meta = stack["connector_registry"].get_connector(META_CONNECTOR_ID)
        tiktok = stack["connector_registry"].get_connector(TIKTOK_CONNECTOR_ID)
        ads = stack["connector_registry"].get_connector(GOOGLE_ADS_CONNECTOR_ID)
        ga4 = stack["connector_registry"].get_connector(GOOGLE_ANALYTICS_CONNECTOR_ID)
        self.assertEqual(meta.provider, "meta")
        self.assertEqual(tiktok.provider, "tiktok")
        self.assertEqual(ads.provider, "google_ads")
        self.assertEqual(ga4.provider, "google_analytics")
        self.assertEqual(meta.read_write_mode, ReadWriteMode.READ_WRITE)
        self.assertEqual(tiktok.read_write_mode, ReadWriteMode.READ_WRITE)
        self.assertEqual(ads.read_write_mode, ReadWriteMode.READ_ONLY)
        self.assertEqual(ga4.read_write_mode, ReadWriteMode.READ_ONLY)
        for descriptor in (meta, tiktok, ads, ga4):
            self.assertEqual(
                descriptor.configuration_metadata.get("credential_authority"),
                "connection_manager",
            )

    def test_default_executors_use_tracked_tiktok(self):
        stack = self._stack(allow_live_registration=True)
        self.assertIsInstance(stack["executors"][META_CONNECTOR_ID], MetaMarketingExecutor)
        self.assertIsInstance(stack["executors"][TIKTOK_CONNECTOR_ID], TrackedTikTokMarketingExecutor)

    def test_provider_mismatch_fails_before_mutating_registries(self):
        stack = self._stack(allow_live_registration=True)
        bad = dict(stack["executors"])
        bad[TIKTOK_CONNECTOR_ID] = MetaMarketingExecutor()
        with self.assertRaises(MarketingProviderCatalogBindingError):
            stack["catalog"].install(executors=bad)
        self.assertIsNone(stack["connector_registry"].get_connector(META_CONNECTOR_ID))
        self.assertEqual(stack["marketing_registry"].list_specs(), [])
        self.assertEqual(stack["executor_registry"].list_bindings(), {})

    def test_missing_executor_fails_before_mutation(self):
        stack = self._stack(allow_live_registration=True)
        missing = dict(stack["executors"])
        missing.pop(GOOGLE_ANALYTICS_CONNECTOR_ID)
        with self.assertRaises(MarketingProviderCatalogBindingError):
            stack["catalog"].install(executors=missing)
        self.assertIsNone(stack["connector_registry"].get_connector(META_CONNECTOR_ID))

    def test_duplicate_install_requires_explicit_replace(self):
        stack = self._stack(allow_live_registration=True)
        stack["catalog"].install(executors=stack["executors"])
        with self.assertRaises(MarketingProviderCatalogBindingError):
            stack["catalog"].install(executors=stack["executors"])
        replaced = stack["catalog"].install(executors=stack["executors"], replace=True)
        self.assertEqual(len(replaced.executor_bindings), 4)

    def test_catalog_never_configures_cross_provider_fallback_for_writes(self):
        stack = self._stack(allow_live_registration=True)
        stack["catalog"].install(executors=stack["executors"])
        self.assertEqual(stack["connector_registry"].get_fallback_chain("social_publishing"), [])
        self.assertEqual(stack["connector_registry"].get_fallback_chain("platform_operations"), [])


if __name__ == "__main__":
    unittest.main()
