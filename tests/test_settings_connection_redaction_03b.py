"""Regression tests for ModelSettingsManager connection-test redaction.

FIX-SETTINGS-CONNECTION-REDACTION-03B
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from integrations.models.base import ModelResponse, ModelResponseStatus
from integrations.models.settings_manager import ModelSettingsManager


class TestSettingsConnectionRedaction03B(unittest.TestCase):
    def _manager_without_persisted_settings(self) -> ModelSettingsManager:
        manager = object.__new__(ModelSettingsManager)
        manager._settings = SimpleNamespace(providers={})
        return manager

    def test_adapter_constructor_exception_cannot_echo_transient_secret(self) -> None:
        secret = "opaque-provider-credential-03b-123456"
        manager = self._manager_without_persisted_settings()

        with patch(
            "integrations.models.settings_manager.OpenAICompatibleProviderAdapter",
            side_effect=RuntimeError(
                f"connection failed with Authorization: Bearer {secret} api_key={secret}"
            ),
        ):
            result = manager.test_connection(
                {
                    "provider_id": "custom-provider",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": "https://example.com/v1",
                    "default_model": "model-1",
                    "api_key": secret,
                }
            )

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertNotIn(secret, result.get("error", ""))
        self.assertIn("[REDACTED", result.get("error", ""))

    def test_provider_error_cannot_echo_opaque_transient_secret(self) -> None:
        secret = "opaque-provider-credential-03b-abcdef"
        manager = self._manager_without_persisted_settings()
        adapter = MagicMock()
        adapter.generate.return_value = ModelResponse(
            request_id="REQ-03B-1",
            provider="custom-provider",
            model_name="model-1",
            status=ModelResponseStatus.ERROR,
            error=f"upstream echoed credential value {secret}",
        )

        with patch(
            "integrations.models.settings_manager.OpenAICompatibleProviderAdapter",
            return_value=adapter,
        ):
            result = manager.test_connection(
                {
                    "provider_id": "custom-provider",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": "https://example.com/v1",
                    "default_model": "model-1",
                    "api_key": secret,
                }
            )

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertNotIn(secret, result.get("error", ""))
        self.assertIn("[REDACTED_SECRET]", result.get("error", ""))

    def test_timeout_error_is_also_exact_secret_sanitized(self) -> None:
        secret = "opaque-provider-credential-03b-timeout"
        manager = self._manager_without_persisted_settings()
        adapter = MagicMock()
        adapter.generate.return_value = ModelResponse(
            request_id="REQ-03B-2",
            provider="custom-provider",
            model_name="model-1",
            status=ModelResponseStatus.TIMEOUT,
            error=f"timeout after provider echoed {secret}",
        )

        with patch(
            "integrations.models.settings_manager.OpenAICompatibleProviderAdapter",
            return_value=adapter,
        ):
            result = manager.test_connection(
                {
                    "provider_id": "custom-provider",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": "https://example.com/v1",
                    "default_model": "model-1",
                    "api_key": secret,
                }
            )

        self.assertEqual(result["status"], "TIMEOUT")
        self.assertNotIn(secret, result.get("error", ""))
        self.assertIn("[REDACTED_SECRET]", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
