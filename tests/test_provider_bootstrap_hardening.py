"""Acceptance Tests for Provider Bootstrap Hardening & Single Source of Truth.

Validates:
1. Deterministic config root resolution without cwd dependency
2. ProviderConfigService as the single source of truth
3. Sanitized health reporting (zero secret / token exposure)
4. Stale backend version & build ID contract
5. Error classification into standardized ProviderErrorCode
6. UniversalModelGateway fallback chain with config service
"""

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus
from integrations.models.config_service import GLOBAL_PROVIDER_CONFIG, ProviderConfigService, ProviderErrorCode
from integrations.models.gateway import UniversalModelGateway, classify_error


class TestProviderBootstrapHardening(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_deterministic_config_root_and_no_cwd_dependency(self) -> None:
        """Config service resolves deterministic path regardless of current working directory."""
        service = ProviderConfigService(config_dir=str(self.config_dir))
        self.assertEqual(service._config_dir, self.config_dir.resolve())

        # Test fallback resolution when not provided
        service_auto = ProviderConfigService()
        self.assertTrue(service_auto._config_dir.exists())

    def test_provider_config_single_source(self) -> None:
        """ProviderConfigService resolves all provider configurations and credentials."""
        mock_env = {
            "XKIRO_API_KEY": "test-xkiro-key-12345",
            "GEMINI_API_KEY": "test-gemini-key-67890",
            "THESPARK_API_KEY": "test-spark-key-11223",
        }
        service = ProviderConfigService(config_dir=str(self.config_dir), override_env=mock_env)

        self.assertTrue(service.is_provider_enabled("xkiro"))
        self.assertTrue(service.has_credential("xkiro"))
        self.assertEqual(service.get_default_model("xkiro"), "mistralai/mistral-large-2512")

        self.assertTrue(service.is_provider_enabled("gemini"))
        self.assertTrue(service.has_credential("gemini"))
        self.assertEqual(service.get_default_model("gemini"), "gemini-flash-latest")

        self.assertTrue(service.is_provider_enabled("thespark"))
        self.assertTrue(service.has_credential("thespark"))

    def test_sanitized_health_endpoint_zero_secret_exposure(self) -> None:
        """Sanitized health report exposes status and model without leaking API keys or secrets."""
        mock_env = {
            "XKIRO_API_KEY": "secret-xkiro-private-token",
            "GEMINI_API_KEY": "secret-gemini-private-token",
        }
        service = ProviderConfigService(config_dir=str(self.config_dir), override_env=mock_env)
        report = service.get_sanitized_health_report()

        self.assertIsInstance(report, list)
        self.assertTrue(len(report) >= 3)

        report_json = str(report)
        self.assertNotIn("secret-xkiro-private-token", report_json)
        self.assertNotIn("secret-gemini-private-token", report_json)
        self.assertNotIn("api_key", report_json.lower())
        self.assertNotIn("authorization", report_json.lower())

        # Verify structure
        for item in report:
            self.assertIn("provider", item)
            self.assertIn("enabled", item)
            self.assertIn("credential_present", item)
            self.assertIn("configured", item)
            self.assertIn("health", item)
            self.assertIn("model", item)

    def test_stale_backend_detection(self) -> None:
        """Diagnostics expose backend version and build id for stale detection."""
        service = ProviderConfigService(config_dir=str(self.config_dir))
        diag = service.get_boot_diagnostics()

        self.assertEqual(diag["app_backend_version"], "1.0.0")
        self.assertTrue(bool(diag["build_id"]))
        self.assertIn("providers", diag)

    def test_error_classification(self) -> None:
        """Raw provider error strings are classified into standardized error codes."""
        self.assertEqual(classify_error("HTTP 401 Unauthorized: Invalid API key"), ProviderErrorCode.AUTH_401)
        self.assertEqual(classify_error("HTTP 403 Forbidden: Permission denied"), ProviderErrorCode.PERMISSION_403)
        self.assertEqual(classify_error("HTTP 429 Rate limit exceeded / Quota exceeded"), ProviderErrorCode.RATE_LIMIT_429)
        self.assertEqual(classify_error("Request timed out after 60s"), ProviderErrorCode.TIMEOUT)
        self.assertEqual(classify_error("MISSING_API_KEY: Key not configured"), ProviderErrorCode.NO_CREDENTIAL)
        self.assertEqual(classify_error("HTTP 404 Model not found: gpt-fake"), ProviderErrorCode.MODEL_NOT_FOUND)
        self.assertEqual(classify_error("Connection refused / Network unreachable"), ProviderErrorCode.NETWORK_ERROR)

    def test_provider_fallback_chain(self) -> None:
        """UniversalModelGateway resolves fallback candidates with config service."""
        gateway = UniversalModelGateway(free_only_mode=True)
        candidates = gateway.resolve_candidate_chain()

        self.assertIsInstance(candidates, list)
        self.assertTrue(len(candidates) >= 2)
        self.assertEqual(candidates[0][0], "xkiro")
        self.assertEqual(candidates[1][0], "gemini")


if __name__ == "__main__":
    unittest.main()
