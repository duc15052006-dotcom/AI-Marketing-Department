from __future__ import annotations

import unittest

from connections.manager import ConnectionManager
from connections.models import ConnectionProfile
from connections.secrets import SecretValue
from connectors.control_plane import ConnectorControlPlane
from connectors.marketing import (
    ExternalMarketingContractError,
    ExternalMarketingRequest,
    MarketingConnectionNotReadyError,
    MarketingConnectorRegistrationError,
    MarketingConnectorRegistry,
    MarketingConnectorSpec,
    MarketingExecutionMode,
    MarketingLiveExecutionDisabledError,
    UnsafeMarketingPayloadError,
)
from connectors.models import AuthenticationType, ConnectorDescriptor, ReadWriteMode
from connectors.registry import ConnectorRegistry
from tools.capabilities import RiskLevel


class CountingSecretProvider:
    def __init__(self) -> None:
        self.get_calls = 0

    def can_resolve(self, secret_ref: str) -> bool:
        return str(secret_ref).startswith("env:")

    def get(self, secret_ref: str) -> SecretValue:
        self.get_calls += 1
        return SecretValue("META-LIVE-SECRET-NEVER-LOG")


class ExternalMarketingConnectorFoundationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret_provider = CountingSecretProvider()
        self.connection_manager = ConnectionManager(self.secret_provider)
        self.connection_manager.register(
            ConnectionProfile(
                connection_id="meta-brand-main",
                provider="meta",
                display_name="Meta Brand Main",
                secret_ref="env:META_TEST_TOKEN",
                business_id="biz-1",
                project_ids=("proj-1",),
                brand_ids=("brand-1",),
            )
        )

        self.connector_registry = ConnectorRegistry()
        self.connector_registry.register_connector(
            ConnectorDescriptor(
                connector_id="conn_meta_marketing",
                provider="meta",
                capability_ids=[
                    "analytics_retrieval",
                    "social_publishing",
                    "content_scheduling",
                    "platform_operations",
                ],
                authentication_type=AuthenticationType.BEARER_TOKEN,
                credential_env_names=["LEGACY_META_TOKEN"],
                read_write_mode=ReadWriteMode.READ_WRITE,
                risk_level=RiskLevel.CRITICAL,
                supported_operations=["read_metrics", "publish", "schedule", "campaign_mutation"],
            )
        )
        self.control_plane = ConnectorControlPlane(self.connector_registry, self.connection_manager)
        self.control_plane.bind("conn_meta_marketing", "meta-brand-main")
        self.registry = MarketingConnectorRegistry(self.control_plane)
        self.registry.register(
            MarketingConnectorSpec(
                connector_id="conn_meta_marketing",
                provider="meta",
                supported_capabilities=(
                    "analytics_retrieval",
                    "social_publishing",
                    "content_scheduling",
                    "platform_operations",
                ),
            )
        )

    def _request(self, **overrides) -> ExternalMarketingRequest:
        values = {
            "request_id": "req-12345678",
            "run_id": "run-12345678",
            "connector_id": "conn_meta_marketing",
            "connection_id": "meta-brand-main",
            "capability_id": "analytics_retrieval",
            "action": "read_metrics",
            "resource_type": "campaign",
            "resource_id": "campaign-1",
            "business_id": "biz-1",
            "project_id": "proj-1",
            "brand_id": "brand-1",
            "payload": {"date_window": "last_30_days"},
        }
        values.update(overrides)
        return ExternalMarketingRequest(**values)

    def test_prepare_is_metadata_only_and_never_resolves_secret(self) -> None:
        prepared = self.registry.prepare(self._request())
        safe = prepared.to_safe_dict()
        self.assertEqual(0, self.secret_provider.get_calls)
        self.assertFalse(safe["credential_resolved"])
        self.assertFalse(safe["network_called"])
        self.assertFalse(safe["approval_required"])
        self.assertEqual("READ", safe["effect"])

    def test_external_write_requires_idempotency_key(self) -> None:
        with self.assertRaisesRegex(ExternalMarketingContractError, "IDEMPOTENCY_KEY_REQUIRED"):
            self._request(
                capability_id="social_publishing",
                action="publish_post",
                resource_type="post",
            )

    def test_publish_plan_is_critical_and_requires_approval(self) -> None:
        prepared = self.registry.prepare(
            self._request(
                capability_id="social_publishing",
                action="publish_post",
                resource_type="post",
                resource_id=None,
                idempotency_key="idem-publish-0001",
                payload={"caption": "safe campaign caption"},
            )
        )
        safe = prepared.to_safe_dict()
        self.assertTrue(safe["approval_required"])
        self.assertEqual("CRITICAL", safe["risk_level"])
        self.assertEqual("PUBLISH", safe["effect"])
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_nested_credential_shaped_payload_is_rejected(self) -> None:
        with self.assertRaises(UnsafeMarketingPayloadError):
            self._request(payload={"post": {"caption": "hello", "access_token": "do-not-store"}})

    def test_scope_denial_happens_without_secret_resolution(self) -> None:
        with self.assertRaisesRegex(MarketingConnectionNotReadyError, "SCOPE_DENIED"):
            self.registry.prepare(self._request(business_id="biz-other"))
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_connection_selection_is_mandatory(self) -> None:
        with self.assertRaises(ExternalMarketingContractError):
            self._request(connection_id="")

    def test_live_registration_is_disabled_by_default(self) -> None:
        live_spec = MarketingConnectorSpec(
            connector_id="conn_meta_marketing",
            provider="meta",
            supported_capabilities=("analytics_retrieval",),
            execution_mode=MarketingExecutionMode.LIVE,
        )
        with self.assertRaisesRegex(MarketingLiveExecutionDisabledError, "LIVE_MARKETING_REGISTRATION_DISABLED"):
            MarketingConnectorRegistry(self.control_plane).register(live_spec)

        opted_in = MarketingConnectorRegistry(self.control_plane, allow_live_registration=True)
        self.assertEqual(live_spec, opted_in.register(live_spec))
        self.assertFalse(hasattr(opted_in, "execute"))

    def test_provider_mismatch_is_rejected_at_registration(self) -> None:
        with self.assertRaisesRegex(MarketingConnectorRegistrationError, "provider does not match"):
            MarketingConnectorRegistry(self.control_plane).register(
                MarketingConnectorSpec(
                    connector_id="conn_meta_marketing",
                    provider="tiktok",
                    supported_capabilities=("analytics_retrieval",),
                )
            )

    def test_capability_must_be_declared_by_connector_descriptor(self) -> None:
        self.connector_registry.register_connector(
            ConnectorDescriptor(
                connector_id="conn_meta_readonly",
                provider="meta",
                capability_ids=["analytics_retrieval"],
                authentication_type=AuthenticationType.BEARER_TOKEN,
                read_write_mode=ReadWriteMode.READ_ONLY,
                risk_level=RiskLevel.LOW,
            )
        )
        with self.assertRaisesRegex(MarketingConnectorRegistrationError, "does not declare capabilities"):
            MarketingConnectorRegistry(self.control_plane).register(
                MarketingConnectorSpec(
                    connector_id="conn_meta_readonly",
                    provider="meta",
                    supported_capabilities=("analytics_retrieval", "social_publishing"),
                )
            )

    def test_unbound_account_fails_closed_without_reading_secret(self) -> None:
        self.connection_manager.register(
            ConnectionProfile(
                connection_id="meta-unbound",
                provider="meta",
                display_name="Meta Unbound",
                secret_ref="env:META_UNBOUND_TOKEN",
                business_id="biz-1",
                project_ids=("proj-1",),
                brand_ids=("brand-1",),
            )
        )
        with self.assertRaisesRegex(MarketingConnectionNotReadyError, "MISSING_BINDING"):
            self.registry.prepare(self._request(connection_id="meta-unbound"))
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_safe_request_projection_redacts_token_like_text(self) -> None:
        request = self._request(payload={"note": "Authorization: Bearer abcdefghijklmnop"})
        safe_text = repr(request.to_safe_dict())
        self.assertNotIn("abcdefghijklmnop", safe_text)
        self.assertIn("REDACTED", safe_text)

    def test_fingerprint_is_deterministic_and_payload_bound(self) -> None:
        first = self._request(payload={"date_window": "last_30_days", "limit": 10})
        second = self._request(payload={"limit": 10, "date_window": "last_30_days"})
        changed = self._request(payload={"date_window": "last_7_days", "limit": 10})
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertNotEqual(first.fingerprint(), changed.fingerprint())

    def test_registry_has_no_execution_or_secret_resolution_surface(self) -> None:
        self.assertFalse(hasattr(self.registry, "execute"))
        self.assertFalse(hasattr(self.registry, "resolve_for_execution"))
        self.assertEqual(0, self.secret_provider.get_calls)


if __name__ == "__main__":
    unittest.main()
