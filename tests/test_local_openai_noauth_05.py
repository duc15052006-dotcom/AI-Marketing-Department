"""Regression tests for loopback-only no-auth OpenAI-compatible providers.

FIX-LOCAL-OPENAI-NOAUTH-05
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from integrations.models.base import CostPolicy, ModelResponse, ModelResponseStatus
from integrations.models.local_openai_compatible_adapter import (
    LocalNoAuthOpenAICompatibleProviderAdapter,
)
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.provider_auth import (
    is_loopback_base_url,
    provider_requires_api_key,
)
from integrations.models.registry import ProviderDefinition, ProviderRegistry, validate_base_url
from integrations.models.settings_manager import ModelSettings, ModelSettingsManager


class NoCredentialStore:
    def has_secret(self, credential_ref):
        return False


class TestLocalOpenAINoAuth05(unittest.TestCase):
    def test_auth_policy_allows_only_explicit_loopback_openai_compatible(self) -> None:
        for url in (
            "http://127.0.0.1:11434/v1",
            "http://localhost:8000/v1",
            "http://model.localhost:8000/v1",
            "http://[::1]:8000/v1",
            "https://localhost:8443/v1",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_loopback_base_url(url))
                self.assertFalse(provider_requires_api_key("OPENAI_COMPATIBLE", url))

        for url in (
            "https://api.example.com/v1",
            "https://127.0.0.1.example.com/v1",
            "https://localhost.example.com/v1",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_loopback_base_url(url))
                self.assertTrue(provider_requires_api_key("OPENAI_COMPATIBLE", url))

        self.assertTrue(provider_requires_api_key("GEMINI_NATIVE", "http://localhost:8000"))

    def test_no_auth_adapter_rejects_remote_endpoint_defense_in_depth(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            LocalNoAuthOpenAICompatibleProviderAdapter(
                provider_id="remote",
                base_url="https://api.example.com/v1",
                api_key_env="",
                default_model="model-1",
                api_key=None,
            )
        self.assertIn("LOCAL_NO_AUTH_REQUIRES_LOOPBACK", str(ctx.exception))

    def test_local_adapter_is_configured_without_key_and_sends_no_authorization_header(self) -> None:
        adapter = LocalNoAuthOpenAICompatibleProviderAdapter(
            provider_id="ollama-local",
            base_url="http://127.0.0.1:11434/v1",
            api_key_env="",
            default_model="llama3.2",
            api_key=None,
        )

        self.assertTrue(adapter.is_configured())
        headers = adapter.transport.build_headers()
        self.assertNotIn("Authorization", headers)

    def test_remote_adapter_without_key_remains_unconfigured(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="remote-provider",
            base_url="https://api.example.com/v1",
            api_key_env="REMOTE_PROVIDER_API_KEY_DOES_NOT_EXIST",
            default_model="model-1",
            api_key=None,
        )
        self.assertTrue(provider_requires_api_key("OPENAI_COMPATIBLE", adapter.base_url))
        self.assertFalse(adapter.is_configured())

    def test_registry_builds_local_noauth_adapter_but_remote_uses_credential_required_adapter(self) -> None:
        registry = ProviderRegistry()
        local_def = ProviderDefinition(
            provider_id="ollama-local",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="http://127.0.0.1:11434/v1",
            default_model="llama3.2",
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        remote_def = ProviderDefinition(
            provider_id="remote-custom",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://api.example.com/v1",
            default_model="model-1",
            cost_policy=CostPolicy.UNKNOWN,
        )

        local_adapter = registry._build_adapter(local_def, None)
        remote_adapter = registry._build_adapter(remote_def, None)

        self.assertIsInstance(local_adapter, LocalNoAuthOpenAICompatibleProviderAdapter)
        self.assertIsInstance(remote_adapter, OpenAICompatibleProviderAdapter)
        self.assertNotIsInstance(remote_adapter, LocalNoAuthOpenAICompatibleProviderAdapter)
        self.assertTrue(local_adapter.is_configured())
        self.assertFalse(remote_adapter.is_configured())

    def test_pinned_snapshot_allows_local_noauth_but_remote_no_key_fails_closed(self) -> None:
        registry = ProviderRegistry()
        local_def = ProviderDefinition(
            provider_id="vllm-local",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="http://localhost:8000/v1",
            default_model="local-model",
        )
        remote_def = ProviderDefinition(
            provider_id="remote-no-key",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://api.example.com/v1",
            default_model="remote-model",
            cost_policy=CostPolicy.UNKNOWN,
        )

        local_adapter = registry.get_pinned_adapter(local_def)
        remote_adapter = registry.get_pinned_adapter(remote_def)

        self.assertIsInstance(local_adapter, LocalNoAuthOpenAICompatibleProviderAdapter)
        self.assertIsNone(remote_adapter)

    def test_settings_connection_test_does_not_require_fake_key_for_loopback(self) -> None:
        manager = object.__new__(ModelSettingsManager)
        manager._settings = SimpleNamespace(providers={})
        successful_adapter = MagicMock()
        successful_adapter.generate.return_value = ModelResponse(
            request_id="REQ-LOCAL-05",
            provider="ollama-local",
            model_name="llama3.2",
            status=ModelResponseStatus.SUCCESS,
            content="pong",
        )

        with patch(
            "integrations.models.settings_manager.LocalNoAuthOpenAICompatibleProviderAdapter",
            return_value=successful_adapter,
        ) as adapter_cls:
            result = manager.test_connection(
                {
                    "provider_id": "ollama-local",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "default_model": "llama3.2",
                }
            )

        self.assertEqual(result["status"], "CONNECTED")
        adapter_cls.assert_called_once()
        self.assertIsNone(adapter_cls.call_args.kwargs["api_key"])

    def test_settings_connection_test_remote_without_key_still_auth_fails_before_dispatch(self) -> None:
        manager = object.__new__(ModelSettingsManager)
        manager._settings = SimpleNamespace(providers={})

        with patch("integrations.models.settings_manager.OpenAICompatibleProviderAdapter") as adapter_cls:
            result = manager.test_connection(
                {
                    "provider_id": "remote-custom",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": "https://api.example.com/v1",
                    "default_model": "model-1",
                }
            )

        self.assertEqual(result["status"], "AUTH_FAILED")
        self.assertIn("MISSING_CREDENTIAL", result.get("error", ""))
        adapter_cls.assert_not_called()

    def test_safe_settings_reports_local_noauth_as_configured_without_credential(self) -> None:
        local = ProviderDefinition(
            provider_id="ollama-local",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="http://127.0.0.1:11434/v1",
            default_model="llama3.2",
        )
        remote = ProviderDefinition(
            provider_id="remote-custom",
            adapter_type="OPENAI_COMPATIBLE",
            base_url="https://api.example.com/v1",
            default_model="model-1",
            cost_policy=CostPolicy.UNKNOWN,
        )
        settings = ModelSettings(providers={"ollama-local": local, "remote-custom": remote})
        manager = object.__new__(ModelSettingsManager)
        manager._lock = __import__("threading").RLock()
        manager._settings = settings
        manager._secret_store = NoCredentialStore()

        safe = manager.get_safe_settings_dict()
        by_id = {provider["provider_id"]: provider for provider in safe["providers"]}

        self.assertFalse(by_id["ollama-local"]["requires_api_key"])
        self.assertTrue(by_id["ollama-local"]["is_configured"])
        self.assertTrue(by_id["remote-custom"]["requires_api_key"])
        self.assertFalse(by_id["remote-custom"]["is_configured"])

    def test_plain_http_remote_remains_rejected_by_canonical_url_validator(self) -> None:
        self.assertEqual(
            validate_base_url("http://127.0.0.1:11434/v1"),
            "http://127.0.0.1:11434/v1",
        )
        with self.assertRaises(ValueError):
            validate_base_url("http://api.example.com/v1")

    def test_update_provider_cannot_downgrade_paid_builtin_cost_floor(self) -> None:
        registry = ProviderRegistry()
        updated_openai = registry.update_provider(
            "openai",
            {"cost_policy": CostPolicy.FREE_TIER_ALLOWED},
        )
        updated_thespark = registry.update_provider(
            "thespark",
            {"cost_policy": "FREE_TIER_ALLOWED"},
        )

        self.assertIs(updated_openai.cost_policy, CostPolicy.PAID)
        self.assertIs(updated_thespark.cost_policy, CostPolicy.PAID)


if __name__ == "__main__":
    unittest.main()
