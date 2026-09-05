from __future__ import annotations

import json
import unittest

from connections.manager import ConnectionManager, ConnectionScopeDeniedError
from connections.models import ConnectionProfile
from connections.secrets import SecretNotFoundError, SecretValue
from connectors.control_plane import (
    ConnectorAmbiguousBindingError,
    ConnectorAuthorityState,
    ConnectorControlPlane,
    ConnectorNotFoundError,
    ConnectorProviderMismatchError,
)
from connectors.registry import ConnectorRegistry
from tools.receipts import ExecutionMode
from connectors.publishing_connector import SandboxPublishingConnector


class _SpySecretProvider:
    def __init__(self, values=None) -> None:
        self.values = dict(values or {})
        self.get_calls = []

    def can_resolve(self, secret_ref: str) -> bool:
        return isinstance(secret_ref, str) and secret_ref.startswith("memory:")

    def get(self, secret_ref: str) -> SecretValue:
        self.get_calls.append(secret_ref)
        value = self.values.get(secret_ref)
        if value is None:
            raise SecretNotFoundError("Secret unavailable.")
        return SecretValue(value)


class ConnectorConnectionAuthorityV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = _SpySecretProvider(
            {
                "memory:xkiro-a": "xkiro-secret-A-123456789",
                "memory:xkiro-global": "xkiro-global-secret-123456789",
                "memory:xkiro-second": "xkiro-second-secret-123456789",
            }
        )
        self.manager = ConnectionManager(self.provider)
        self.registry = ConnectorRegistry()
        self.control = ConnectorControlPlane(self.registry, self.manager)

    def _register_xkiro(
        self,
        connection_id: str,
        secret_ref: str,
        *,
        business_id=None,
        project_ids=(),
        brand_ids=(),
        enabled=True,
    ) -> ConnectionProfile:
        profile = ConnectionProfile(
            connection_id=connection_id,
            provider="xkiro",
            display_name=connection_id,
            secret_ref=secret_ref,
            business_id=business_id,
            project_ids=tuple(project_ids),
            brand_ids=tuple(brand_ids),
            enabled=enabled,
        )
        self.manager.register(profile)
        self.control.bind("conn_model_xkiro", connection_id)
        return profile

    def test_status_is_metadata_only_and_execution_resolves_after_scope(self) -> None:
        self._register_xkiro(
            "xkiro-business-a",
            "memory:xkiro-a",
            business_id="BUSINESS-A",
            project_ids=("PROJECT-1",),
            brand_ids=("BRAND-1",),
        )

        status = self.control.get_status(
            "conn_model_xkiro",
            business_id="BUSINESS-A",
            project_id="PROJECT-1",
            brand_id="BRAND-1",
        )
        self.assertEqual(status.state, ConnectorAuthorityState.CONFIGURED_UNVERIFIED)
        self.assertEqual(status.connection_id, "xkiro-business-a")
        self.assertFalse(status.credential_resolved)
        self.assertEqual(self.provider.get_calls, [])

        denied = self.control.get_status(
            "conn_model_xkiro",
            business_id="BUSINESS-B",
            project_id="PROJECT-1",
            brand_id="BRAND-1",
        )
        self.assertEqual(denied.state, ConnectorAuthorityState.SCOPE_DENIED)
        self.assertEqual(self.provider.get_calls, [])

        access = self.control.resolve_for_execution(
            "conn_model_xkiro",
            business_id="BUSINESS-A",
            project_id="PROJECT-1",
            brand_id="BRAND-1",
        )
        self.assertFalse(access.local_no_auth)
        self.assertEqual(access.connection.profile.connection_id, "xkiro-business-a")
        self.assertEqual(access.connection.secret.reveal(), "xkiro-secret-A-123456789")
        self.assertEqual(self.provider.get_calls, ["memory:xkiro-a"])

    def test_wrong_project_or_brand_fails_before_secret_lookup(self) -> None:
        self._register_xkiro(
            "xkiro-scoped",
            "memory:xkiro-a",
            business_id="BUSINESS-A",
            project_ids=("PROJECT-1",),
            brand_ids=("BRAND-1",),
        )
        with self.assertRaises(ConnectionScopeDeniedError):
            self.control.resolve_for_execution(
                "conn_model_xkiro",
                business_id="BUSINESS-A",
                project_id="PROJECT-OTHER",
                brand_id="BRAND-1",
            )
        self.assertEqual(self.provider.get_calls, [])

        with self.assertRaises(ConnectionScopeDeniedError):
            self.control.resolve_for_execution(
                "conn_model_xkiro",
                business_id="BUSINESS-A",
                project_id="PROJECT-1",
                brand_id="BRAND-OTHER",
            )
        self.assertEqual(self.provider.get_calls, [])

    def test_disabled_profile_is_not_resolved(self) -> None:
        self._register_xkiro(
            "xkiro-disabled",
            "memory:xkiro-a",
            business_id="BUSINESS-A",
            enabled=False,
        )
        status = self.control.get_status("conn_model_xkiro", business_id="BUSINESS-A")
        self.assertEqual(status.state, ConnectorAuthorityState.CONNECTION_DISABLED)
        self.assertEqual(self.provider.get_calls, [])

    def test_scope_specific_profile_wins_over_global_profile(self) -> None:
        self._register_xkiro("xkiro-global", "memory:xkiro-global")
        self._register_xkiro(
            "xkiro-business-a",
            "memory:xkiro-a",
            business_id="BUSINESS-A",
        )

        business_a = self.control.get_status("conn_model_xkiro", business_id="BUSINESS-A")
        other_business = self.control.get_status("conn_model_xkiro", business_id="BUSINESS-B")
        self.assertEqual(business_a.connection_id, "xkiro-business-a")
        self.assertEqual(other_business.connection_id, "xkiro-global")
        self.assertEqual(self.provider.get_calls, [])

    def test_equally_specific_accounts_fail_closed_until_explicit_selection(self) -> None:
        self._register_xkiro("xkiro-global", "memory:xkiro-global")
        self._register_xkiro("xkiro-second", "memory:xkiro-second")

        status = self.control.get_status("conn_model_xkiro", business_id="BUSINESS-A")
        self.assertEqual(status.state, ConnectorAuthorityState.AMBIGUOUS_BINDING)
        self.assertEqual(self.provider.get_calls, [])

        with self.assertRaises(ConnectorAmbiguousBindingError):
            self.control.resolve_for_execution("conn_model_xkiro", business_id="BUSINESS-A")
        self.assertEqual(self.provider.get_calls, [])

        access = self.control.resolve_for_execution(
            "conn_model_xkiro",
            business_id="BUSINESS-A",
            connection_id="xkiro-second",
        )
        self.assertEqual(access.connection.profile.connection_id, "xkiro-second")
        self.assertEqual(self.provider.get_calls, ["memory:xkiro-second"])

    def test_provider_mismatch_is_rejected_at_binding(self) -> None:
        self.manager.register(
            ConnectionProfile(
                connection_id="wrong-provider",
                provider="gemini",
                display_name="Wrong Provider",
                secret_ref="memory:xkiro-a",
            )
        )
        with self.assertRaises(ConnectorProviderMismatchError):
            self.control.bind("conn_model_xkiro", "wrong-provider")
        self.assertEqual(self.provider.get_calls, [])

    def test_local_and_sandbox_connectors_need_no_secret_binding(self) -> None:
        web_status = self.control.get_status("conn_web_reader", business_id="BUSINESS-A")
        publishing_status = self.control.get_status("conn_publishing_sandbox", business_id="BUSINESS-A")
        self.assertEqual(web_status.state, ConnectorAuthorityState.LOCAL_AVAILABLE)
        self.assertEqual(publishing_status.state, ConnectorAuthorityState.LOCAL_AVAILABLE)

        web_access = self.control.resolve_for_execution("conn_web_reader", business_id="BUSINESS-A")
        publish_access = self.control.resolve_for_execution("conn_publishing_sandbox", business_id="BUSINESS-A")
        self.assertTrue(web_access.local_no_auth)
        self.assertTrue(publish_access.local_no_auth)
        self.assertIsNone(publish_access.connection)
        self.assertTrue(publish_access.descriptor.configuration_metadata["real_publishing_disabled"])

        sandbox = SandboxPublishingConnector()
        self.assertEqual(sandbox.execution_mode_for("social_publishing"), ExecutionMode.SANDBOX)
        self.assertEqual(self.provider.get_calls, [])

    def test_control_plane_ignores_legacy_env_credential_health_as_authority(self) -> None:
        # ConnectorRegistry may mark this descriptor from legacy env discovery.
        # The new bridge must use ConnectionManager metadata instead of treating
        # credential_env_names or that cached legacy credential state as authority.
        self._register_xkiro(
            "xkiro-business-a",
            "memory:xkiro-a",
            business_id="BUSINESS-A",
        )
        status = self.control.get_status("conn_model_xkiro", business_id="BUSINESS-A")
        self.assertEqual(status.state, ConnectorAuthorityState.CONFIGURED_UNVERIFIED)
        self.assertEqual(self.provider.get_calls, [])

    def test_safe_status_and_errors_never_expose_secret_or_secret_ref(self) -> None:
        self._register_xkiro(
            "xkiro-business-a",
            "memory:xkiro-a",
            business_id="BUSINESS-A",
        )
        status = self.control.get_status("conn_model_xkiro", business_id="BUSINESS-A")
        serialized = json.dumps(status.to_safe_dict(), sort_keys=True)
        self.assertNotIn("xkiro-secret-A-123456789", serialized)
        self.assertNotIn("memory:xkiro-a", serialized)
        self.assertNotIn("secret_ref", serialized)

        with self.assertRaises(ConnectorNotFoundError) as ctx:
            self.control.get_status("conn_missing", business_id="BUSINESS-A")
        self.assertNotIn("xkiro-secret-A-123456789", str(ctx.exception))
        self.assertNotIn("memory:xkiro-a", str(ctx.exception))
        self.assertEqual(self.provider.get_calls, [])

    def test_connection_manager_authorize_profile_does_not_resolve_secret(self) -> None:
        profile = ConnectionProfile(
            connection_id="metadata-only",
            provider="xkiro",
            display_name="Metadata Only",
            secret_ref="memory:xkiro-a",
            business_id="BUSINESS-A",
        )
        self.manager.register(profile)
        authorized = self.manager.authorize_profile("metadata-only", business_id="BUSINESS-A")
        self.assertEqual(authorized.connection_id, "metadata-only")
        self.assertEqual(self.provider.get_calls, [])


if __name__ == "__main__":
    unittest.main()
