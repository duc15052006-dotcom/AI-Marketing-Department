import unittest
from types import SimpleNamespace

import app_api.server as server
from integrations.models.registry import ProviderDefinition


class _SecretStore:
    def __init__(self, present=False):
        self.present = present

    def has_secret(self, credential_ref):
        return self.present


class _Registry:
    def __init__(self, providers):
        self.providers = providers

    def get_provider(self, provider_id):
        return self.providers.get(provider_id)


class LocalNoAuthDiagnostics05BTests(unittest.TestCase):
    def _report_for(self, pdef, has_credential=False):
        original = server.APP_BACKEND
        fake_mgr = SimpleNamespace(
            get_settings=lambda: SimpleNamespace(providers={pdef.provider_id: pdef}),
            _secret_store=_SecretStore(has_credential),
        )
        fake_registry = _Registry({pdef.provider_id: pdef})
        server.APP_BACKEND = SimpleNamespace(
            settings_manager=fake_mgr,
            runtime=SimpleNamespace(
                model_gateway=SimpleNamespace(provider_registry=fake_registry)
            ),
        )
        try:
            handler = object.__new__(server.DepartmentAPIHandler)
            return handler._authoritative_provider_report()[0]
        finally:
            server.APP_BACKEND = original

    def test_loopback_openai_compatible_is_configured_without_key(self):
        pdef = ProviderDefinition(
            provider_id="localtest",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="http://127.0.0.1:11434/v1",
            default_model="local-model",
            enabled=True,
        )
        row = self._report_for(pdef, has_credential=False)
        self.assertFalse(row["credential_present"])
        self.assertFalse(row["requires_api_key"])
        self.assertTrue(row["configured"])
        self.assertEqual(row["health"], "AVAILABLE")

    def test_remote_openai_compatible_without_key_is_not_configured(self):
        pdef = ProviderDefinition(
            provider_id="remotetest",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://example.com/v1",
            default_model="remote-model",
            enabled=True,
        )
        row = self._report_for(pdef, has_credential=False)
        self.assertFalse(row["credential_present"])
        self.assertTrue(row["requires_api_key"])
        self.assertFalse(row["configured"])
        self.assertEqual(row["health"], "NO_CREDENTIAL")

    def test_disabled_loopback_remains_disabled(self):
        pdef = ProviderDefinition(
            provider_id="localoff",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="http://localhost:11434/v1",
            default_model="local-model",
            enabled=False,
        )
        row = self._report_for(pdef, has_credential=False)
        self.assertFalse(row["requires_api_key"])
        self.assertFalse(row["configured"])
        self.assertEqual(row["health"], "DISABLED")


if __name__ == "__main__":
    unittest.main()
