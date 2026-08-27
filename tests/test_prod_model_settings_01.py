"""Targeted Deterministic Test Suite for Secure Provider & Model Settings (Phase PROD-MODEL-SETTINGS-01).

Guarantees:
- Safe settings read without secret exposure (zero plaintext key returned).
- Masked/encrypted secret persistence via SecureSecretStore (Windows DPAPI / safe vault).
- Full custom OpenAI-compatible and Gemini Native provider management.
- Exactly 5 permanent logical agent identities (CMO, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE).
- Strict rejection of FINAL_CMO or unknown agent overrides.
- Deterministic fallback chain editing without duplicates.
- Safe base URL validation (HTTPS remote, HTTP loopback only).
- Non-mutating transient connection testing (test does not save, does not enable, discards transient keys).
- API-key rotation V1 -> V2 invalidating adapter cache without restart.
- Active run immutability: RUN-1 remains on initial snapshot; RUN-2 uses updated settings.
- Security & authorization boundary: unauthenticated mutation blocked (401), invalid host rejected (400), untrusted origin rejected (403).
- Optimistic concurrency control: stale revision rejected (409 CONFLICT).
- Atomic failure rollback on invalid data or storage failure.
- Zero internet dependency: hermetic, deterministic, real local HTTP loopback server.
"""

from __future__ import annotations

import copy
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from app_api.server import DepartmentAPIHandler, DepartmentAppBackend, GLOBAL_API_SESSION_TOKEN
from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.registry import (
    AgentId,
    ModelPolicy,
    ModelTarget,
    ProviderDefinition,
    ProviderRegistry,
    ProviderRegistrySnapshot,
    normalize_agent_id,
    validate_base_url,
)
from integrations.models import secret_store as secret_store_module
from integrations.models.secret_store import (
    InMemorySecretStore,
    SecureSecretStore,
    SecureSecretStoreUnavailableError,
    VaultCorruptionError,
)
from integrations.models.settings_manager import (
    ModelSettings,
    ModelSettingsManager,
    ModelSettingsValidationError,
    StaleSettingsRevisionError,
)
from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class MockOpenAIHttpServer(http.server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, received_requests, response_queue):
        super().__init__(server_address, RequestHandlerClass)
        self.received_requests = received_requests
        self.response_queue = response_queue


class MockOpenAIHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        auth_header = self.headers.get("Authorization", "")

        self.server.received_requests.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": json.loads(body) if body else {},
            "auth": auth_header,
        })

        resp_tuple = self.server.response_queue.pop(0) if self.server.response_queue else (200, {
            "id": "chatcmpl-mock",
            "choices": [{"message": {"role": "assistant", "content": '{"content": "Mock Local Response"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

        status_code, resp_payload = resp_tuple
        body_bytes = json.dumps(resp_payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def log_message(self, format, *args):
        pass


class TaggedMockOpenAIHandler(http.server.BaseHTTPRequestHandler):
    """Records which physical server received each request."""
    tag = "?"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if hasattr(self.server, "received_requests"):
            self.server.received_requests.append({
                "path": self.path,
                "tag": self.tag,
                "auth": self.headers.get("Authorization", ""),
            })
        body = json.dumps({"id": "chatcmpl-tag", "choices": [{"message": {"role": "assistant", "content": "{}"}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class TestProdModelSettings01(unittest.TestCase):
    """Deterministic, comprehensive test suite for Model & Provider Settings."""

    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp(prefix="ai_mktg_settings_test_")
        self.vault_path = Path(self.test_dir) / "secrets.vault"
        self.settings_path = Path(self.test_dir) / "model_settings.json"

        self.secret_store = SecureSecretStore(vault_path=self.vault_path)
        self.registry = ProviderRegistry()
        self.gateway = UniversalModelGateway(provider_registry=self.registry, free_only_mode=True)
        self.settings_manager = ModelSettingsManager(
            settings_file_path=self.settings_path,
            secret_store=self.secret_store,
            provider_registry=self.registry,
            gateway=self.gateway,
        )

        # Setup test server for API endpoint testing
        self.server_port = 0
        self.http_server = None
        self.server_thread = None

    def tearDown(self) -> None:
        DepartmentAPIHandler.allow_testserver_for_testing = False
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()
        if self.server_thread:
            self.server_thread.join(timeout=1.0)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _start_test_api_server(self):
        """Start local HTTP server with DepartmentAPIHandler."""
        DepartmentAPIHandler.allow_testserver_for_testing = False
        handler = DepartmentAPIHandler
        self.http_server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self.server_port = self.http_server.server_port
        self.server_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.server_thread.start()

    def _api_request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = GLOBAL_API_SESSION_TOKEN,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Send HTTP request to test server."""
        url = f"http://127.0.0.1:{self.server_port}{path}"
        req_headers = {"Host": "127.0.0.1", "Content-Type": "application/json"}
        if auth_token:
            req_headers["Authorization"] = f"Bearer {auth_token}"
        if headers:
            req_headers.update(headers)

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())

        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                resp_body = resp.read().decode("utf-8")
                return resp.status, json.loads(resp_body) if resp_body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            return e.code, json.loads(err_body) if err_body else {}

    # =========================================================================
    # 1. SAFE SETTINGS READ & ZERO SECRET LEAKAGE
    # =========================================================================

    def test_01_safe_settings_read_contains_zero_plaintext_secrets(self):
        """Verify get_safe_settings_dict returns metadata and has_credential without secret leakage."""
        self.settings_manager.upsert_provider({"provider_id": "openai"}, secret="sk-super-secret-key-12345")
        safe_dict = self.settings_manager.get_safe_settings_dict()

        self.assertIn("settings_revision", safe_dict)
        self.assertIn("global_target", safe_dict)
        self.assertIn("providers", safe_dict)

        # Check all providers
        serialized_str = json.dumps(safe_dict)
        self.assertNotIn("sk-super-secret-key-12345", serialized_str)
        self.assertNotIn("api_key", safe_dict)

        openai_prov = next((p for p in safe_dict["providers"] if p["provider_id"] == "openai"), None)
        self.assertIsNotNone(openai_prov)
        self.assertTrue(openai_prov["has_credential"])
        self.assertNotIn("sk-super-secret-key-12345", json.dumps(openai_prov))

    def test_02_persisted_file_contains_zero_plaintext_secrets(self):
        """Verify model_settings.json on disk retains only credential_ref, never plaintext secrets."""
        self.secret_store.set_secret("custom_cloud", "sk-my-private-api-key-999")
        self.settings_manager.upsert_provider({
            "provider_id": "custom_cloud",
            "display_name": "Custom Cloud",
            "base_url": "https://api.custom.com/v1",
            "default_model": "custom-v1",
            "credential_ref": "STORE:custom_cloud",
        })

        raw_file_content = self.settings_path.read_text(encoding="utf-8")
        self.assertNotIn("sk-my-private-api-key-999", raw_file_content)
        self.assertIn("STORE:custom_cloud", raw_file_content)

    def test_03_allowed_agents_list_has_exactly_five_identities(self):
        """Verify allowed_agents returns exactly the 5 permanent logical agents without FINAL_CMO."""
        safe_dict = self.settings_manager.get_safe_settings_dict()
        agents = safe_dict["allowed_agents"]
        self.assertEqual(len(agents), 5)
        self.assertEqual(set(agents), {"CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"})
        self.assertNotIn("FINAL_CMO", agents)

    # =========================================================================
    # 2. PROVIDER CREATION, EDITING, ENABLING & DISABLING
    # =========================================================================

    def test_04_create_custom_openai_compatible_provider(self):
        """Verify creating a custom OpenAI-compatible provider with URL validation and secret storage."""
        pdef = self.settings_manager.upsert_provider(
            provider_data={
                "provider_id": "vllm_local",
                "display_name": "Local vLLM Server",
                "adapter_type": "OPENAI_COMPATIBLE",
                "base_url": "http://127.0.0.1:8000/v1",
                "default_model": "mistral-7b-instruct",
                "cost_policy": "FREE_TIER_ALLOWED",
                "enabled": True,
            },
            secret="vllm-token-12345",
        )

        self.assertEqual(pdef.provider_id, "vllm_local")
        self.assertEqual(pdef.base_url, "http://127.0.0.1:8000/v1")
        # Versioned opaque credential reference: STORE:<provider_id>:<version>
        self.assertTrue(pdef.credential_ref.startswith("STORE:vllm_local:"))
        self.assertNotEqual(pdef.credential_ref, "STORE:vllm_local")
        self.assertEqual(self.secret_store.get_secret(pdef.credential_ref), "vllm-token-12345")

        # Live registry updated
        reg_p = self.registry.get_provider("vllm_local")
        self.assertIsNotNone(reg_p)
        self.assertEqual(reg_p.default_model, "mistral-7b-instruct")

    def test_05_edit_provider_preserves_existing_credential_if_omitted(self):
        """Verify editing provider metadata without supplying a new API key preserves the existing secret."""
        self.settings_manager.upsert_provider(
            provider_data={"provider_id": "prov_edit", "default_model": "m1"},
            secret="secret_v1",
        )
        ref_v1 = self.settings_manager.get_settings().providers["prov_edit"].credential_ref
        self.assertTrue(ref_v1.startswith("STORE:prov_edit:"))
        self.assertEqual(self.secret_store.get_secret(ref_v1), "secret_v1")

        # Edit display name and model without passing secret
        updated = self.settings_manager.upsert_provider(
            provider_data={
                "provider_id": "prov_edit",
                "display_name": "Updated Provider",
                "default_model": "m2",
            }
        )
        self.assertEqual(updated.default_model, "m2")
        self.assertEqual(updated.display_name, "Updated Provider")
        # credential_ref (and its version) is preserved when no new key is given
        self.assertEqual(updated.credential_ref, ref_v1)
        self.assertEqual(self.secret_store.get_secret(ref_v1), "secret_v1")

    def test_06_enable_and_disable_provider_semantics(self):
        """Verify enabling and disabling provider updates state and applies to settings."""
        self.settings_manager.upsert_provider({"provider_id": "prov_toggle", "default_model": "m1"})
        self.assertTrue(self.settings_manager.get_settings().providers["prov_toggle"].enabled)

        # Disable
        disabled = self.settings_manager.disable_provider("prov_toggle")
        self.assertFalse(disabled.enabled)
        self.assertFalse(self.registry.get_provider("prov_toggle").enabled)

        # Enable
        enabled = self.settings_manager.enable_provider("prov_toggle")
        self.assertTrue(enabled.enabled)
        self.assertTrue(self.registry.get_provider("prov_toggle").enabled)

    def test_07_delete_provider_succeeds_when_unreferenced(self):
        """Verify deleting unreferenced custom provider removes it from settings, registry, and vault."""
        self.settings_manager.upsert_provider(
            {"provider_id": "temp_prov", "default_model": "m1"},
            secret="temp_secret",
        )
        temp_ref = self.settings_manager.get_settings().providers["temp_prov"].credential_ref
        self.assertIn("temp_prov", self.settings_manager.get_settings().providers)

        res = self.settings_manager.delete_provider("temp_prov")
        self.assertTrue(res)
        self.assertNotIn("temp_prov", self.settings_manager.get_settings().providers)
        self.assertIsNone(self.secret_store.get_secret(temp_ref))

    def test_08_delete_provider_blocked_when_referenced_in_global_target(self):
        """Verify deleting provider referenced in global_target fails closed."""
        self.settings_manager.upsert_provider({"provider_id": "active_global", "default_model": "m1"})
        self.settings_manager.update_settings({"global_target": {"provider_id": "active_global", "model_id": "m1"}})

        with self.assertRaises(ModelSettingsValidationError):
            self.settings_manager.delete_provider("active_global")

    def test_09_delete_provider_blocked_when_referenced_in_agent_override(self):
        """Verify deleting provider referenced in agent_overrides fails closed."""
        self.settings_manager.upsert_provider({"provider_id": "agent_prov", "default_model": "m1"})
        self.settings_manager.update_settings({
            "agent_overrides": {"CREATIVE": {"provider_id": "agent_prov", "model_id": "m1"}},
        })

        with self.assertRaises(ModelSettingsValidationError):
            self.settings_manager.delete_provider("agent_prov")

    def test_10_delete_provider_blocked_when_referenced_in_fallback_chain(self):
        """Verify deleting provider referenced in fallback_chain fails closed."""
        self.settings_manager.upsert_provider({"provider_id": "fb_prov", "default_model": "m1"})
        self.settings_manager.update_settings({
            "fallback_chain": [{"provider_id": "fb_prov", "model_id": "m1"}],
        })

        with self.assertRaises(ModelSettingsValidationError):
            self.settings_manager.delete_provider("fb_prov")

    # =========================================================================
    # 3. BASE URL SECURITY VALIDATION
    # =========================================================================

    def test_11_base_url_https_remote_accepted(self):
        """Verify valid HTTPS remote base URLs are accepted and canonicalized."""
        valid_url = "https://api.together.xyz/v1/chat/completions/"
        canonical = validate_base_url(valid_url)
        self.assertEqual(canonical, "https://api.together.xyz/v1")

    def test_12_base_url_http_loopback_accepted(self):
        """Verify plain HTTP on loopback (127.0.0.1, localhost, ::1) is accepted."""
        for loopback in ("http://127.0.0.1:11434/v1", "http://localhost:8080/v1", "http://[::1]:8000/v1"):
            self.assertIsNotNone(validate_base_url(loopback))

    def test_13_base_url_insecure_remote_http_rejected(self):
        """Verify plain HTTP on remote non-loopback hosts is strictly rejected."""
        with self.assertRaises(ValueError) as ctx:
            validate_base_url("http://api.remote-insecure.com/v1")
        self.assertIn("INSECURE_HTTP_URL", str(ctx.exception))

    def test_14_base_url_invalid_schemes_rejected(self):
        """Verify file://, ftp://, javascript:, data: schemes are rejected."""
        for bad_scheme in ("file:///etc/passwd", "ftp://server.com/api", "javascript:alert(1)", "data:text/html,abc"):
            with self.assertRaises(ValueError) as ctx:
                validate_base_url(bad_scheme)
            self.assertIn("INVALID_URL_SCHEME", str(ctx.exception))

    def test_15_base_url_embedded_credentials_rejected(self):
        """Verify URLs with embedded user:password are rejected."""
        with self.assertRaises(ValueError) as ctx:
            validate_base_url("https://user:pass@api.openai.com/v1")
        self.assertIn("INVALID_URL_CREDENTIALS", str(ctx.exception))

    # =========================================================================
    # 4. GLOBAL TARGET & FIVE LOGICAL AGENT OVERRIDES
    # =========================================================================

    def test_16_global_target_updates_gateway_policy(self):
        """Verify updating global_target immediately updates gateway.model_policy.global_target."""
        self.settings_manager.update_settings({
            "global_target": {"provider_id": "xkiro", "model_id": "mistralai/mistral-large-2512"},
        })
        self.assertEqual(self.gateway.model_policy.global_target.provider_id, "xkiro")
        self.assertEqual(self.gateway.model_policy.global_target.model_id, "mistralai/mistral-large-2512")

    def test_17_all_five_logical_agents_support_overrides(self):
        """Verify CMO, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE can be overridden independently."""
        overrides = {
            "CMO": {"provider_id": "prov_cmo", "model_id": "m-cmo"},
            "INTELLIGENCE": {"provider_id": "prov_intel", "model_id": "m-intel"},
            "STRATEGIST": {"provider_id": "prov_strat", "model_id": "m-strat"},
            "CREATIVE": {"provider_id": "prov_crtv", "model_id": "m-crtv"},
            "PERFORMANCE": {"provider_id": "prov_perf", "model_id": "m-perf"},
        }
        self.settings_manager.update_settings({"agent_overrides": overrides})

        policy = self.gateway.model_policy
        self.assertEqual(policy.get_target_for_agent("cmo").provider_id, "prov_cmo")
        self.assertEqual(policy.get_target_for_agent("intelligence").provider_id, "prov_intel")
        self.assertEqual(policy.get_target_for_agent("strategist").provider_id, "prov_strat")
        self.assertEqual(policy.get_target_for_agent("creative").provider_id, "prov_crtv")
        self.assertEqual(policy.get_target_for_agent("performance").provider_id, "prov_perf")

    def test_18_final_cmo_override_rejected(self):
        """Verify attempting to configure FINAL_CMO as a separate agent override is rejected."""
        with self.assertRaises(ModelSettingsValidationError) as ctx:
            self.settings_manager.update_settings({
                "agent_overrides": {"FINAL_CMO": {"provider_id": "prov_bad", "model_id": "m1"}},
            })
        self.assertIn("INVALID_AGENT_OVERRIDE", str(ctx.exception))

    def test_19_unknown_agent_override_rejected(self):
        """Verify attempting to configure an unknown agent (e.g. agent_6) is rejected."""
        with self.assertRaises(ModelSettingsValidationError) as ctx:
            self.settings_manager.update_settings({
                "agent_overrides": {"AGENT_6": {"provider_id": "prov_bad", "model_id": "m1"}},
            })
        self.assertIn("INVALID_AGENT_OVERRIDE", str(ctx.exception))

    def test_20_final_cmo_resolves_to_cmo_policy(self):
        """Verify candidate resolution for Final CMO resolves to the CMO target."""
        self.settings_manager.update_settings({
            "agent_overrides": {"CMO": {"provider_id": "cmo_exclusive", "model_id": "cmo-model"}},
        })
        targets = self.gateway.resolve_candidate_chain(agent_id="final_cmo")
        self.assertEqual(targets[0], ("cmo_exclusive", "cmo-model"))

    # =========================================================================
    # 5. FALLBACK CHAIN ORDERING & VALIDATION
    # =========================================================================

    def test_21_fallback_chain_ordered_evaluation(self):
        """Verify fallback chain retains strict user-defined ordering."""
        fallbacks = [
            {"provider_id": "thespark", "model_id": "spark-default"},
            {"provider_id": "xkiro", "model_id": "mistralai/mistral-large-2512"},
            {"provider_id": "gemini", "model_id": "gemini-flash-latest"},
        ]
        self.settings_manager.update_settings({"fallback_chain": fallbacks})

        policy_fbs = self.gateway.model_policy.fallback_chain
        self.assertEqual(len(policy_fbs), 3)
        self.assertEqual(policy_fbs[0].provider_id, "thespark")
        self.assertEqual(policy_fbs[1].provider_id, "xkiro")
        self.assertEqual(policy_fbs[2].provider_id, "gemini")

    def test_22_duplicate_fallback_targets_rejected(self):
        """Verify duplicate (provider_id, model_id) entries in fallback_chain are rejected."""
        dup_fallbacks = [
            {"provider_id": "xkiro", "model_id": "m1"},
            {"provider_id": "xkiro", "model_id": "m1"},
        ]
        with self.assertRaises(ModelSettingsValidationError) as ctx:
            self.settings_manager.update_settings({"fallback_chain": dup_fallbacks})
        self.assertIn("DUPLICATE_FALLBACK_TARGET", str(ctx.exception))

    # =========================================================================
    # 6. TRANSIENT TEST CONNECTION (NON-MUTATING)
    # =========================================================================

    def test_23_transient_test_connection_success(self):
        """Verify Test Connection executes against target without persisting or modifying policy."""
        # Mock adapter generate response
        with patch.object(OpenAICompatibleProviderAdapter, "generate") as mock_gen:
            mock_gen.return_value = ModelResponse(
                request_id="REQ-TEST",
                provider="custom_test",
                model_name="test-model",
                status=ModelResponseStatus.SUCCESS,
                content="Ping response",
            )

            res = self.settings_manager.test_connection({
                "provider_id": "custom_test",
                "adapter_type": "OPENAI_COMPATIBLE",
                "base_url": "https://api.test.com/v1",
                "model_id": "test-model",
                "api_key": "sk-transient-test-key",
            })

            self.assertEqual(res["status"], "CONNECTED")
            self.assertIn("latency_ms", res)

            # Test connection must NOT have persisted the provider or secret
            self.assertNotIn("custom_test", self.settings_manager.get_settings().providers)
            self.assertIsNone(self.secret_store.get_secret("STORE:custom_test"))
            self.assertEqual(self.gateway.model_policy.global_target.provider_id, "gemini")

    def test_24_transient_test_connection_auth_failure_classified(self):
        """Verify Test Connection classifies 401 / unauthorized as AUTH_FAILED."""
        with patch.object(OpenAICompatibleProviderAdapter, "generate") as mock_gen:
            mock_gen.return_value = ModelResponse(
                request_id="REQ-TEST",
                provider="custom_test",
                model_name="test-model",
                status=ModelResponseStatus.ERROR,
                error="AUTHENTICATION_FAILED: HTTP 401 Unauthorized: Invalid API key",
            )

            res = self.settings_manager.test_connection({
                "provider_id": "custom_test",
                "base_url": "https://api.test.com/v1",
                "model_id": "test-model",
                "api_key": "sk-bad-key",
            })
            self.assertEqual(res["status"], "AUTH_FAILED")

    def test_25_transient_test_connection_timeout_classified(self):
        """Verify Test Connection classifies timeout as TIMEOUT."""
        with patch.object(OpenAICompatibleProviderAdapter, "generate") as mock_gen:
            mock_gen.return_value = ModelResponse(
                request_id="REQ-TEST",
                provider="custom_test",
                model_name="test-model",
                status=ModelResponseStatus.TIMEOUT,
                error="TIMEOUT: Request timed out after 10.0s",
            )

            res = self.settings_manager.test_connection({
                "provider_id": "custom_test",
                "base_url": "https://api.test.com/v1",
                "model_id": "test-model",
                "api_key": "sk-key",
            })
            self.assertEqual(res["status"], "TIMEOUT")

    def test_26_transient_test_connection_missing_credential(self):
        """Verify Test Connection without stored or transient secret returns AUTH_FAILED."""
        res = self.settings_manager.test_connection({
            "provider_id": "unconfigured_prov",
            "base_url": "https://api.test.com/v1",
            "model_id": "m1",
        })
        self.assertEqual(res["status"], "AUTH_FAILED")
        self.assertIn("MISSING_CREDENTIAL", res["error"])

    # =========================================================================
    # 7. API KEY ROTATION & ADAPTER CACHE INVALIDATION
    # =========================================================================

    def test_27_api_key_rotation_evicts_cached_adapter(self):
        """Verify updating a provider's API key evicts the cached adapter so the next call uses the new key."""
        self.settings_manager.upsert_provider(
            provider_data={
                "provider_id": "openai_rot",
                "base_url": "https://api.openai.com/v1",
                "default_model": "gpt-4o-mini",
            },
            secret="KEY_V1",
        )

        adapter1 = self.registry.get_adapter("openai_rot")
        self.assertIsNotNone(adapter1)
        self.assertEqual(adapter1._api_key, "KEY_V1")

        # Rotate secret to KEY_V2
        self.settings_manager.upsert_provider(
            provider_data={
                "provider_id": "openai_rot",
                "base_url": "https://api.openai.com/v1",
                "default_model": "gpt-4o-mini",
            },
            secret="KEY_V2",
        )

        adapter2 = self.registry.get_adapter("openai_rot")
        self.assertIsNotNone(adapter2)
        self.assertEqual(adapter2._api_key, "KEY_V2")
        self.assertNotEqual(id(adapter1), id(adapter2))

    # =========================================================================
    # 8. ACTIVE RUN IMMUTABILITY VS NEW RUN SETTINGS
    # =========================================================================

    def test_28_active_run_remains_pinned_across_settings_save(self):
        """Verify RUN-1 remains pinned to initial routing even if settings are modified mid-run."""
        # Register Provider A & B
        self.settings_manager.upsert_provider({"provider_id": "prov_a", "default_model": "m-a", "cost_policy": "FREE_TIER_ALLOWED"}, secret="key_a")
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="m-a",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "Dir A", "market_findings": "Intel A", "positioning": "Strat A", "creative_synthesis": "Ad A", "funnel_kpi": "Perf A", "final_synthesis": "Report A"}',
        )
        self.registry.register_custom_adapter(mock_a)

        self.settings_manager.upsert_provider({"provider_id": "prov_b", "default_model": "m-b", "cost_policy": "FREE_TIER_ALLOWED"}, secret="key_b")
        mock_b = MagicMock()
        mock_b.provider_name = "prov_b"
        mock_b.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_b.generate.return_value = ModelResponse(
            request_id="REQ-B",
            provider="prov_b",
            model_name="m-b",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "Dir B", "market_findings": "Intel B"}',
        )
        self.registry.register_custom_adapter(mock_b)

        self.settings_manager.update_settings({
            "global_target": {"provider_id": "prov_a", "model_id": "m-a"},
        })

        runtime = FiveAgentDepartmentRuntime(model_gateway=self.gateway, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        # Start RUN-1 with Provider A
        ctx1 = runtime.start_run(objective="Active Run Immutability Test")
        out1 = runtime.execute_stage_cmo_initial(ctx1)
        self.assertEqual(out1["status"], "COMPLETED")
        self.assertEqual(mock_a.generate.call_count, 1)

        # WHILE RUN-1 IS ACTIVE: Mutate settings to Provider B
        self.settings_manager.update_settings({
            "global_target": {"provider_id": "prov_b", "model_id": "m-b"},
        })

        # Continue RUN-1 through stages 2-6: must continue using Provider A from snapshot!
        runtime.execute_stage_intelligence(ctx1)
        runtime.execute_stage_strategist(ctx1)
        runtime.execute_stage_creative(ctx1)
        runtime.execute_stage_performance(ctx1)
        runtime.execute_stage_final_cmo(ctx1)

        self.assertEqual(mock_a.generate.call_count, 6)
        mock_b.generate.assert_not_called()

        # Start RUN-2: captures new settings (Provider B)
        ctx2 = runtime.start_run(objective="New Run on Mutated Settings")
        out_r2 = runtime.execute_stage_cmo_initial(ctx2)
        self.assertEqual(out_r2["status"], "COMPLETED")
        self.assertEqual(mock_b.generate.call_count, 1)

    # =========================================================================
    # 9. CONCURRENCY & OPTIMISTIC LOCKING
    # =========================================================================

    def test_29_stale_settings_revision_rejected_with_409(self):
        """Verify update_settings rejects stale expected_revision with StaleSettingsRevisionError."""
        current_rev = self.settings_manager.get_settings().settings_revision

        # First update increments revision to current_rev + 1
        self.settings_manager.update_settings(
            {"free_only_mode": False},
            expected_revision=current_rev,
        )

        # Second update with original stale revision is rejected
        with self.assertRaises(StaleSettingsRevisionError) as ctx:
            self.settings_manager.update_settings(
                {"free_only_mode": True},
                expected_revision=current_rev,
            )
        self.assertEqual(ctx.exception.current_revision, current_rev + 1)
        self.assertEqual(ctx.exception.expected_revision, current_rev)

    # =========================================================================
    # 10. ATOMIC TRANSACTION & FAIL-CLOSED ROLLBACK
    # =========================================================================

    def test_30_atomic_update_failure_rolls_back_entire_transaction(self):
        """Verify validation failure in multi-field update rolls back without partial mutations."""
        initial_settings = self.settings_manager.get_settings()
        initial_rev = initial_settings.settings_revision

        with self.assertRaises(ModelSettingsValidationError):
            self.settings_manager.update_settings({
                "free_only_mode": not initial_settings.free_only_mode,
                "agent_overrides": {"INVALID_AGENT_X": {"provider_id": "gemini", "model_id": "flash"}},
            })

        # Verify nothing changed
        current = self.settings_manager.get_settings()
        self.assertEqual(current.settings_revision, initial_rev)
        self.assertEqual(current.free_only_mode, initial_settings.free_only_mode)
        self.assertEqual(current.agent_overrides, initial_settings.agent_overrides)

    def test_31_settings_manager_reload_restores_persisted_state(self):
        """Verify reconstructing ModelSettingsManager restores exact persisted state and credential refs."""
        self.settings_manager.upsert_provider(
            provider_data={
                "provider_id": "persisted_custom",
                "display_name": "Persisted Custom",
                "base_url": "https://api.persisted.com/v1",
                "default_model": "p-model",
            },
            secret="persisted_key_123",
        )
        self.settings_manager.update_settings({
            "global_target": {"provider_id": "persisted_custom", "model_id": "p-model"},
            "agent_overrides": {"CREATIVE": {"provider_id": "persisted_custom", "model_id": "p-model"}},
        })

        # Reconstruct new manager pointing to same disk path
        new_manager = ModelSettingsManager(
            settings_file_path=self.settings_path,
            secret_store=self.secret_store,
        )
        restored = new_manager.get_settings()

        self.assertEqual(restored.global_target.provider_id, "persisted_custom")
        self.assertIn("CREATIVE", restored.agent_overrides)
        self.assertTrue(restored.providers["persisted_custom"].credential_ref.startswith("STORE:persisted_custom:"))
        self.assertEqual(self.secret_store.get_secret(restored.providers["persisted_custom"].credential_ref), "persisted_key_123")

    # =========================================================================
    # 11. AUTHENTICATED API ENDPOINTS & CSRF SECURITY
    # =========================================================================

    def test_32_api_get_settings_requires_auth(self):
        """Verify GET /api/settings/model requires valid session bearer token (401 without auth)."""
        self._start_test_api_server()
        code, body = self._api_request("GET", "/api/settings/model", auth_token=None)
        self.assertEqual(code, 401)
        self.assertEqual(body.get("error"), "UNAUTHORIZED")

    def test_33_api_get_settings_authorized_returns_safe_data(self):
        """Verify GET /api/settings/model with valid auth returns safe settings dictionary."""
        self._start_test_api_server()
        code, body = self._api_request("GET", "/api/settings/model")
        self.assertEqual(code, 200)
        self.assertIn("settings_revision", body)
        self.assertIn("global_target", body)
        self.assertIn("providers", body)
        self.assertNotIn("api_key", json.dumps(body))

    def test_34_api_post_settings_requires_auth(self):
        """Verify POST /api/settings/model requires auth (401 without auth)."""
        self._start_test_api_server()
        code, body = self._api_request("POST", "/api/settings/model", body={"free_only_mode": False}, auth_token=None)
        self.assertEqual(code, 401)

    def test_35_api_post_settings_rejects_untrusted_origin_csrf(self):
        """Verify POST /api/settings/model rejects untrusted browser Origin with 403."""
        self._start_test_api_server()
        code, body = self._api_request(
            "POST",
            "/api/settings/model",
            body={"free_only_mode": False},
            headers={"Origin": "https://evil-attacker.com"},
        )
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error"), "FORBIDDEN_ORIGIN")

    def test_36_api_post_settings_stale_revision_returns_409(self):
        """Verify POST /api/settings/model returns 409 when expected_revision is stale."""
        self._start_test_api_server()
        # Fetch current revision
        _, current = self._api_request("GET", "/api/settings/model")
        curr_rev = current["settings_revision"]

        # Mutate to advance revision
        self._api_request("POST", "/api/settings/model", body={"free_only_mode": False, "expected_revision": curr_rev})

        # Try stale update
        code, body = self._api_request("POST", "/api/settings/model", body={"free_only_mode": True, "expected_revision": curr_rev})
        self.assertEqual(code, 409)
        self.assertEqual(body.get("error"), "STALE_SETTINGS_REVISION")

    def test_37_api_upsert_provider_stores_secret_and_returns_safe_object(self):
        """Verify POST /api/settings/providers/upsert stores secret and returns safe definition."""
        self._start_test_api_server()
        _, current = self._api_request("GET", "/api/settings/model")
        payload = {
            "expected_revision": current["settings_revision"],
            "provider_id": "api_custom_prov",
            "display_name": "API Custom Provider",
            "adapter_type": "OPENAI_COMPATIBLE",
            "base_url": "https://api.custom-ai.com/v1",
            "default_model": "custom-fast-v1",
            "api_key": "sk-real-secret-12345",
        }
        code, body = self._api_request("POST", "/api/settings/providers/upsert", body=payload)
        self.assertEqual(code, 200)
        self.assertEqual(body["provider_id"], "api_custom_prov")
        self.assertTrue(body["has_credential"])
        self.assertNotIn("sk-real-secret-12345", json.dumps(body))

    def test_38_api_delete_provider_endpoint(self):
        """Verify POST /api/settings/providers/{pid}/delete deletes unreferenced provider."""
        self._start_test_api_server()
        _, current = self._api_request("GET", "/api/settings/model")
        code, _ = self._api_request("POST", "/api/settings/providers/upsert", body={
            "expected_revision": current["settings_revision"],
            "provider_id": "del_api_prov",
            "default_model": "m1",
        })
        self.assertEqual(code, 200)

        _, current = self._api_request("GET", "/api/settings/model")
        code, body = self._api_request("POST", "/api/settings/providers/del_api_prov/delete", body={
            "expected_revision": current["settings_revision"],
        })
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "DELETED")

    def test_39_api_test_connection_endpoint_non_mutating(self):
        """Verify POST /api/settings/models/test returns connection result without mutating settings."""
        self._start_test_api_server()
        with patch.object(OpenAICompatibleProviderAdapter, "generate") as mock_gen:
            mock_gen.return_value = ModelResponse(
                request_id="REQ-TEST",
                provider="test_prov",
                model_name="m1",
                status=ModelResponseStatus.SUCCESS,
                content="Success",
            )

            code, body = self._api_request("POST", "/api/settings/models/test", body={
                "provider_id": "test_prov",
                "base_url": "https://api.test.com/v1",
                "model_id": "m1",
                "api_key": "sk-transient-test",
            })
            self.assertEqual(code, 200)
            self.assertEqual(body["status"], "CONNECTED")

    # =========================================================================
    # 12. REAL LOCAL HTTP CONTRACT & FULL PIPELINE EXECUTION
    # =========================================================================

    def test_40_real_local_http_server_contract_end_to_end(self):
        """Verify configuring a local OpenAI-compatible provider via Settings executes real HTTP requests."""
        received_reqs = []
        resp_queue = [
            (200, {
                "id": "chatcmpl-test",
                "choices": [{"message": {"role": "assistant", "content": '{"strategic_directives": "Local Directives", "market_findings": "Local Findings", "positioning": "Local Positioning", "creative_synthesis": "Local Ad", "funnel_kpi": "Local KPI", "final_synthesis": "Local Plan"}'}}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 15, "total_tokens": 30},
            })
        ]

        # Ephemeral local mock server
        mock_server = MockOpenAIHttpServer(("127.0.0.1", 0), MockOpenAIHandler, received_reqs, resp_queue)
        local_port = mock_server.server_address[1]
        server_th = threading.Thread(target=mock_server.serve_forever, daemon=True)
        server_th.start()

        try:
            # Configure local provider via settings manager
            local_url = f"http://127.0.0.1:{local_port}/v1"
            self.settings_manager.upsert_provider(
                provider_data={
                    "provider_id": "local_mock_llm",
                    "display_name": "Local Mock LLM",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": local_url,
                    "default_model": "local-model-v1",
                    "cost_policy": "FREE_TIER_ALLOWED",
                },
                secret="Bearer-Local-Token-12345",
            )
            self.settings_manager.update_settings({
                "global_target": {"provider_id": "local_mock_llm", "model_id": "local-model-v1"},
            })

            # Run FiveAgentDepartmentRuntime stage
            runtime = FiveAgentDepartmentRuntime(model_gateway=self.gateway, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
            ctx = runtime.start_run(objective="Local HTTP Server Contract Test")
            out = runtime.execute_stage_cmo_initial(ctx)

            self.assertEqual(out["status"], "COMPLETED")
            self.assertEqual(len(received_reqs), 1)
            self.assertEqual(received_reqs[0]["auth"], "Bearer Bearer-Local-Token-12345")
            self.assertEqual(received_reqs[0]["body"]["model"], "local-model-v1")
        finally:
            mock_server.shutdown()
            mock_server.server_close()
            server_th.join(timeout=1.0)


    # =========================================================================
    # 13. SECRET STORE HARDENING (PROD-MODEL-SETTINGS-01R1)
    # =========================================================================

    SENTINEL = "SETTINGS_SECRET_SENTINEL_7E91F4"
    ROTATION_V1 = "ACTIVE_RUN_KEY_V1"
    ROTATION_V2 = "ACTIVE_RUN_KEY_V2"

    def test_41_windows_dpapi_failure_fails_closed(self):
        """Verify a Windows DPAPI encryption failure fails closed: set_secret raises
        and NO vault file is persisted through any weaker fallback."""
        with patch.object(
            secret_store_module, "_win_dpapi_encrypt",
            side_effect=OSError("CryptProtectData failed with error code 2"),
        ):
            with self.assertRaises(SecureSecretStoreUnavailableError) as ctx:
                self.secret_store.set_secret("prov_dpapi_fail", self.SENTINEL)
        self.assertIn("SECRET_STORE_WRITE_FAILED", str(ctx.exception))
        self.assertIn("fail-closed", str(ctx.exception))
        # No plaintext, XOR, base64 or any other artifact may exist on disk.
        self.assertFalse(self.vault_path.exists())

    def test_42_no_xor_or_static_fallback_in_production(self):
        """Verify production secret storage never uses XOR/static-key obfuscation:
        non-Windows persistent storage fails closed and no fallback codec exists."""
        # The legacy insecure fallback codec must no longer exist at all.
        self.assertFalse(hasattr(secret_store_module, "_xor_fallback_crypto"))

        store = SecureSecretStore(vault_path=self.vault_path)
        with patch.object(secret_store_module, "_IS_WINDOWS", False):
            with self.assertRaises(SecureSecretStoreUnavailableError) as ctx:
                store.set_secret("prov_nonwin", self.SENTINEL)
            self.assertIn("SECURE_SECRET_STORE_UNAVAILABLE", str(ctx.exception))
            with self.assertRaises(SecureSecretStoreUnavailableError):
                store.get_secret("STORE:prov_nonwin")
            with self.assertRaises(SecureSecretStoreUnavailableError):
                store.delete_secret("prov_nonwin")
        # Nothing was written by any fallback path.
        self.assertFalse(self.vault_path.exists())

        # Explicit DI test double remains available for deterministic tests only.
        mem = InMemorySecretStore()
        ref = mem.set_secret("di_test", "v")
        self.assertEqual(mem.get_secret(ref), "v")

    def test_43_vault_corruption_fails_closed(self):
        """Tampered ciphertext / truncated vault / invalid structure must raise
        VaultCorruptionError; never empty-string success or fallback recovery."""
        ref = self.secret_store.set_secret("prov_corrupt", "corrupt-check-value")
        self.assertTrue(self.vault_path.exists())
        pristine_raw = self.vault_path.read_bytes()
        self.assertTrue(len(pristine_raw) > 16)

        # 1. Tampered ciphertext
        tampered = bytearray(pristine_raw)
        mid = len(tampered) // 2
        tampered[mid] ^= 0xFF
        self.vault_path.write_bytes(bytes(tampered))
        with self.assertRaises(VaultCorruptionError):
            self.secret_store.get_secret(ref)

        # 2. Truncated vault
        self.vault_path.write_bytes(pristine_raw[: len(pristine_raw) // 3])
        with self.assertRaises(VaultCorruptionError):
            self.secret_store.get_secret(ref)

        # 3. Valid encryption but invalid JSON structure (list instead of object)
        encrypted_invalid = secret_store_module._win_dpapi_encrypt(
            b"[1, 2, 3]",
            SecureSecretStore._get_application_entropy(),
        )
        self.vault_path.write_bytes(encrypted_invalid)
        with self.assertRaises(VaultCorruptionError):
            self.secret_store.get_secret(ref)

    def test_44_plaintext_sentinel_absent_from_persisted_files(self):
        """Inspect ACTUAL files written by the test: the sentinel must appear
        exactly 0 times in model_settings.json and secrets.vault bytes."""
        self.settings_manager.upsert_provider(
            provider_data={
                "provider_id": "sentinel_prov",
                "display_name": "Sentinel Provider",
                "base_url": "https://api.sentinel.test/v1",
                "default_model": "sentinel-model",
            },
            secret=self.SENTINEL,
        )
        self.settings_manager.update_settings({
            "global_target": {"provider_id": "sentinel_prov", "model_id": "sentinel-model"},
        })

        settings_bytes = self.settings_path.read_bytes()
        vault_exists = self.vault_path.exists()
        total = (
            settings_bytes.count(self.SENTINEL.encode())
            + (self.vault_path.read_bytes().count(self.SENTINEL.encode()) if vault_exists else 0)
        )
        self.assertEqual(total, 0)
        self.assertTrue(vault_exists)

    # =========================================================================
    # 14. ACTIVE-RUN KEY ROTATION TRUTH (REAL LOOPBACK EXECUTION)
    # =========================================================================

    def _run_active_run_rotation_scenario(self):
        """Full deterministic rotation scenario against a real loopback HTTP
        provider that records the Authorization credential of every request.

        RUN-1 starts on V1 -> key rotated through ModelSettingsManager ->
        RUN-1 continues -> RUN-2 starts.
        """
        full_content = json.dumps({
            "strategic_directives": "D", "market_findings": "F", "positioning": "P",
            "creative_synthesis": "C", "funnel_kpi": "K", "final_synthesis": "S",
        })
        mock_response = (200, {
            "id": "chatcmpl-rot",
            "choices": [{"message": {"role": "assistant", "content": full_content}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        })
        received: List[Dict[str, Any]] = []
        server = MockOpenAIHttpServer(
            ("127.0.0.1", 0), MockOpenAIHandler, received, [mock_response, mock_response, mock_response],
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
            self.settings_manager.upsert_provider(
                provider_data={
                    "provider_id": "prov_rot",
                    "display_name": "Rotation Provider",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": base_url,
                    "default_model": "m-rot",
                    "cost_policy": "FREE_TIER_ALLOWED",
                },
                secret=self.ROTATION_V1,
            )
            ref_v1 = self.settings_manager.get_settings().providers["prov_rot"].credential_ref

            self.settings_manager.update_settings({
                "global_target": {"provider_id": "prov_rot", "model_id": "m-rot"},
            })

            runtime = FiveAgentDepartmentRuntime(model_gateway=self.gateway, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
            ctx1 = runtime.start_run(objective="Active Run Rotation Truth RUN-1")

            # RUN-1 first actual model call
            out1 = runtime.execute_stage_cmo_initial(ctx1)
            self.assertEqual(out1["status"], "COMPLETED")

            # Rotate key THROUGH the real Settings pathway while RUN-1 is active
            self.settings_manager.upsert_provider(
                provider_data={
                    "provider_id": "prov_rot",
                    "base_url": base_url,
                    "default_model": "m-rot",
                },
                secret=self.ROTATION_V2,
            )
            ref_v2 = self.settings_manager.get_settings().providers["prov_rot"].credential_ref

            # Same RUN-1, another actual model call after rotation
            out1b = runtime.execute_stage_intelligence(ctx1)
            self.assertEqual(out1b["status"], "COMPLETED")

            # New RUN-2 after rotation
            ctx2 = runtime.start_run(objective="Active Run Rotation Truth RUN-2")
            out2 = runtime.execute_stage_cmo_initial(ctx2)
            self.assertEqual(out2["status"], "COMPLETED")

            snapshot_json = json.dumps(ctx1.model_policy, default=str)
            return {
                "auths": [e["auth"] for e in received],
                "ref_v1": ref_v1,
                "ref_v2": ref_v2,
                "snapshot_json": snapshot_json,
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    @staticmethod
    def _classify(auth_header: Optional[str]) -> str:
        if auth_header is None:
            return "MISSING"
        if TestProdModelSettings01.ROTATION_V1 in auth_header:
            return "V1"
        if TestProdModelSettings01.ROTATION_V2 in auth_header:
            return "V2"
        return "OTHER"

    def test_45_active_run1_key_before_rotation_is_v1(self):
        """RUN-1's first real model call must authenticate with KEY_V1."""
        result = self._run_active_run_rotation_scenario()
        self.assertGreaterEqual(len(result["auths"]), 3)
        self.assertEqual(result["auths"][0], f"Bearer {self.ROTATION_V1}")
        self.assertEqual(self._classify(result["auths"][0]), "V1")

    def test_46_active_run1_key_after_rotation_still_v1(self):
        """RUN-1 continuation AFTER key rotation must still authenticate with
        KEY_V1 (no active-run credential drift)."""
        result = self._run_active_run_rotation_scenario()
        self.assertEqual(result["auths"][1], f"Bearer {self.ROTATION_V1}")
        self.assertEqual(self._classify(result["auths"][1]), "V1")
        self.assertNotEqual(result["ref_v1"], result["ref_v2"])
        self.assertTrue(result["ref_v1"].startswith("STORE:prov_rot:"))
        self.assertTrue(result["ref_v2"].startswith("STORE:prov_rot:"))
        # Old credential version retained so RUN-1 can keep resolving it.
        self.assertTrue(self.secret_store.has_secret(result["ref_v1"]))
        self.assertTrue(self.secret_store.has_secret(result["ref_v2"]))

    def test_47_new_run2_key_after_rotation_is_v2(self):
        """RUN-2 started after rotation must authenticate with KEY_V2."""
        result = self._run_active_run_rotation_scenario()
        self.assertEqual(result["auths"][2], f"Bearer {self.ROTATION_V2}")
        self.assertEqual(self._classify(result["auths"][2]), "V2")

    def test_48_run_snapshot_contains_no_plaintext_key(self):
        """The run-pinned context snapshot (policy + provider definitions) must
        contain zero plaintext credential material — only opaque refs."""
        result = self._run_active_run_rotation_scenario()
        snap = result["snapshot_json"]
        self.assertNotIn(self.ROTATION_V1, snap)
        self.assertNotIn(self.ROTATION_V2, snap)
        self.assertNotIn(self.SENTINEL, snap)
        # Opaque versioned references ARE expected in the snapshot.
        self.assertIn(result["ref_v1"], snap)

    def test_49_credential_version_refs_are_opaque_and_non_secret(self):
        """Versioned credential refs never embed secret material; refs are stable
        resolvable handles while referenced and safely reclaimed when not."""
        self.settings_manager.upsert_provider(
            {"provider_id": "opaque_prov", "default_model": "m1"},
            secret=self.ROTATION_V1,
        )
        ref_a = self.settings_manager.get_settings().providers["opaque_prov"].credential_ref
        self.settings_manager.upsert_provider(
            {"provider_id": "opaque_prov", "default_model": "m1"},
            secret=self.ROTATION_V2,
        )
        ref_b = self.settings_manager.get_settings().providers["opaque_prov"].credential_ref

        for ref in (ref_a, ref_b):
            self.assertTrue(ref.startswith("STORE:opaque_prov:"))
            version = ref.split(":")[-1]
            self.assertTrue(version and all(c in "0123456789abcdef" for c in version))
            self.assertNotIn(self.ROTATION_V1, ref)
            self.assertNotIn(self.ROTATION_V2, ref)
            self.assertNotIn(self.SENTINEL, ref)

        self.assertNotEqual(ref_a, ref_b)
        # New committed version resolves exactly.
        self.assertEqual(self.secret_store.get_secret(ref_b), self.ROTATION_V2)
        # Old UNREFERENCED version was reclaimed by the lifetime authority
        # (no active run pins it) — never left as an indefinitely usable orphan.
        self.assertIsNone(self.secret_store.get_secret(ref_a))

    def test_49b_active_reference_defers_reclamation_of_old_version(self):
        """While a registered usage authority reports an old version in use,
        rotation must retain it; after the reference clears it is reclaimable."""
        held = {"ref": None}

        def authority(ref: str) -> bool:
            return ref == held["ref"]

        self.registry.set_credential_usage_authority(authority)
        try:
            self.settings_manager.upsert_provider(
                {"provider_id": "lease_prov", "default_model": "m1"},
                secret=self.ROTATION_V1,
            )
            ref_v1 = self.settings_manager.get_settings().providers["lease_prov"].credential_ref

            # Active run acquires its reference (run pins V1)
            held["ref"] = ref_v1
            self.settings_manager.upsert_provider(
                {"provider_id": "lease_prov", "default_model": "m1"},
                secret=self.ROTATION_V2,
            )
            # V1 still resolvable while actively referenced
            self.assertEqual(self.secret_store.get_secret(ref_v1), self.ROTATION_V1)

            # Run terminates: reference released -> reclaimable
            held["ref"] = None
            self.settings_manager.reclaim_obsolete_credential_versions(provider_ids=["lease_prov"])
            self.assertIsNone(self.secret_store.get_secret(ref_v1))
        finally:
            self.registry.set_credential_usage_authority(None)

    def test_50_adapter_cache_distinguishes_credential_versions(self):
        """Adapter cache identity must not collapse credential versions:
        with V1 actively referenced, live adapter uses V2 while the pinned V1
        adapter stays distinct and keeps authenticating with its version."""
        self.settings_manager.upsert_provider(
            {
                "provider_id": "cache_ver",
                "adapter_type": "OPENAI_COMPATIBLE",
                "base_url": "https://api.cache-ver.test/v1",
                "default_model": "m-cv",
                "cost_policy": "FREE_TIER_ALLOWED",
            },
            secret=self.ROTATION_V1,
        )
        cfg_v1 = self.registry.get_provider("cache_ver").model_dump()
        ref_v1 = cfg_v1["credential_ref"]
        adapter_v1 = self.registry.get_adapter("cache_ver")
        self.assertIsNotNone(adapter_v1)
        self.assertEqual(adapter_v1._api_key, self.ROTATION_V1)

        # Simulate an active run pinning V1 before rotation.
        self.registry.set_credential_usage_authority(lambda ref: ref == ref_v1)
        try:
            # Rotate V1 -> V2 through Settings (real pathway).
            self.settings_manager.upsert_provider(
                {
                    "provider_id": "cache_ver",
                    "base_url": "https://api.cache-ver.test/v1",
                    "default_model": "m-cv",
                },
                secret=self.ROTATION_V2,
            )

            adapter_v2_live = self.registry.get_adapter("cache_ver")
            self.assertIsNot(adapter_v1, adapter_v2_live)
            self.assertEqual(adapter_v2_live._api_key, self.ROTATION_V2)

            # Pinned resolution of the OLD definition must yield the V1-bound
            # adapter, never collapse onto the stale/live V2 instance.
            from integrations.models.registry import ProviderDefinition as _PD
            pinned_def = _PD(**{**cfg_v1, "credential_ref": ref_v1})
            adapter_pinned_v1 = self.registry.get_pinned_adapter(pinned_def)
            self.assertIsNot(adapter_pinned_v1, adapter_v2_live)
            self.assertEqual(adapter_pinned_v1._api_key, self.ROTATION_V1)

            # Cache keys: provider_id + 64-hex SHA-256 execution fingerprint.
            # Opaque refs only — never secret values, never raw config dumps.
            import re as _re
            cache_keys = [k for k in self.registry._adapters.keys() if k.startswith("cache_ver")]
            self.assertIn("cache_ver", cache_keys)
            pinned_keys = [k for k in cache_keys if k != "cache_ver"]
            self.assertTrue(pinned_keys)
            for key in pinned_keys:
                suffix = key.split("@", 1)[1]
                self.assertTrue(_re.fullmatch(r"[0-9a-f]{64}", suffix), key)
                self.assertNotIn(self.ROTATION_V1, key)
                self.assertNotIn(self.ROTATION_V2, key)
                self.assertNotIn(ref_v1, key)
            # The two credential versions produced DISTINCT fingerprints/keys.
            self.assertEqual(len(set(pinned_keys)), len(pinned_keys))
        finally:
            self.registry.set_credential_usage_authority(None)


    # =========================================================================
    # 15. CREDENTIAL LIFETIME, TRANSACTION ATOMICITY & REVISION AUTHORITY
    #     (PROD-MODEL-SETTINGS-01R2)
    # =========================================================================

    def _run_multi_rotation_scenario(self, rotations: int = 6):
        """RUN-1 pins V1 on a real loopback provider; the key is rotated through
        N subsequent versions via the actual Settings pathway while RUN-1 stays
        active; RUN-1 makes a late call; RUN-2 starts on the newest key.
        No adapter for the provider is constructed by the test itself."""
        full_content = json.dumps({
            "strategic_directives": "D", "market_findings": "F", "positioning": "P",
            "creative_synthesis": "C", "funnel_kpi": "K", "final_synthesis": "S",
        })
        mock_response = (200, {
            "id": "chatcmpl-mrot",
            "choices": [{"message": {"role": "assistant", "content": full_content}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        })
        received: List[Dict[str, Any]] = []
        server = MockOpenAIHttpServer(
            ("127.0.0.1", 0), MockOpenAIHandler, received,
            [mock_response for _ in range(rotations + 3)],
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
            self.settings_manager.upsert_provider(
                provider_data={
                    "provider_id": "prov_mrot",
                    "display_name": "Multi Rotation Provider",
                    "adapter_type": "OPENAI_COMPATIBLE",
                    "base_url": base_url,
                    "default_model": "m-mrot",
                    "cost_policy": "FREE_TIER_ALLOWED",
                },
                secret=f"MULTI_ROT_V1",
            )
            ref_v1 = self.settings_manager.get_settings().providers["prov_mrot"].credential_ref

            self.settings_manager.update_settings({
                "global_target": {"provider_id": "prov_mrot", "model_id": "m-mrot"},
            })

            runtime = FiveAgentDepartmentRuntime(model_gateway=self.gateway, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
            ctx1 = runtime.start_run(objective="Multi Rotation RUN-1")
            out1 = runtime.execute_stage_cmo_initial(ctx1)
            self.assertEqual(out1["status"], "COMPLETED")

            newest_key = "MULTI_ROT_V1"
            for i in range(2, rotations + 2):
                newest_key = f"MULTI_ROT_V{i}"
                self.settings_manager.upsert_provider(
                    provider_data={
                        "provider_id": "prov_mrot",
                        "base_url": base_url,
                        "default_model": "m-mrot",
                    },
                    secret=newest_key,
                )

            # LATE actual model call for RUN-1 after all rotations
            out_late = runtime.execute_stage_intelligence(ctx1)
            self.assertEqual(out_late["status"], "COMPLETED")

            ctx2 = runtime.start_run(objective="Multi Rotation RUN-2")
            out2 = runtime.execute_stage_cmo_initial(ctx2)
            self.assertEqual(out2["status"], "COMPLETED")

            return {
                "ref_v1": ref_v1,
                "newest_key": newest_key,
                "auths": [e["auth"] for e in received],
                "runtime": runtime,
                "ctx1": ctx1,
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    def test_51_more_than_five_rotations_keep_active_run1_v1(self):
        """>5 rotations must NOT invalidate an active RUN-1's pinned V1 credential.
        The fixed-cap pruning race is prohibited: retention is reference-based."""
        result = self._run_multi_rotation_scenario(rotations=6)
        # V7 total versions created while RUN-1 was active
        self.assertTrue(self.secret_store.has_secret(result["ref_v1"]))
        self.assertEqual(self.secret_store.get_secret(result["ref_v1"]), "MULTI_ROT_V1")
        # RUN-1's late real call still authenticated with V1
        self.assertEqual(result["auths"][0], "Bearer MULTI_ROT_V1")   # first call
        self.assertEqual(result["auths"][1], "Bearer MULTI_ROT_V1")   # post-rotation call

    def test_52_late_adapter_construction_after_many_rotations_resolves_v1(self):
        """Adversarial: RUN-1 pins V1 but NO adapter is ever built; after >5
        rotations a fresh pinned-adapter construction must resolve V1 from the
        vault — not from any cached in-memory plaintext."""
        self.settings_manager.upsert_provider(
            {
                "provider_id": "late_prov",
                "adapter_type": "OPENAI_COMPATIBLE",
                "base_url": "https://api.late.test/v1",
                "default_model": "m-late",
                "cost_policy": "FREE_TIER_ALLOWED",
            },
            secret="LATE_V1",
        )
        ref_v1 = self.settings_manager.get_settings().providers["late_prov"].credential_ref
        cfg_v1 = self.settings_manager.get_settings().providers["late_prov"].model_dump()

        # Simulate run-start pinning of the V1 definition BEFORE any rotation.
        from integrations.models.registry import ProviderDefinition as _PD
        pinned_def = _PD(**{**cfg_v1, "credential_ref": ref_v1})

        # Register the pin as an active-run reference, then rotate 6 times.
        # No adapter for this provider is constructed until AFTER all rotations.
        self.registry.set_credential_usage_authority(lambda ref: ref == ref_v1)
        try:
            for i in range(2, 8):
                self.settings_manager.upsert_provider(
                    {"provider_id": "late_prov", "default_model": f"m-late-v{i}"},
                    secret=f"LATE_V{i}",
                )
            self.assertEqual(self.secret_store.get_secret(ref_v1), "LATE_V1")

            # FIRST adapter construction for V1 happens only now.
            late_adapter = self.registry.get_pinned_adapter(pinned_def)
            self.assertIsNotNone(late_adapter)
            self.assertEqual(late_adapter._api_key, "LATE_V1")
        finally:
            self.registry.set_credential_usage_authority(None)

    def test_53_new_run_after_many_rotations_uses_newest_credential(self):
        """RUN-2 started after many rotations resolves the NEWEST committed version."""
        result = self._run_multi_rotation_scenario(rotations=6)
        self.assertEqual(result["auths"][-1], f"Bearer {result['newest_key']}")
        current_ref = self.settings_manager.get_settings().providers["prov_mrot"].credential_ref
        self.assertEqual(self.secret_store.get_secret(current_ref), result["newest_key"])

    def test_54_active_run_referenced_provider_delete_is_active_run_safe(self):
        """Deleting a provider no longer referenced by committed routing must not
        destroy credentials/config still required by an active run: new runs lose
        access immediately, RUN-1 keeps resolving its pinned V1."""
        # Isolated manager/registry/gateway stack for this scenario.
        td_vault = Path(self.test_dir) / "del_probe.vault"
        probe_store = SecureSecretStore(vault_path=td_vault)
        from integrations.models.registry import ProviderRegistry as _PR
        registry = _PR(secret_store=probe_store)
        gateway = UniversalModelGateway(provider_registry=registry, free_only_mode=True)
        manager = ModelSettingsManager(
            settings_file_path=Path(self.test_dir) / "del_settings.json",
            secret_store=probe_store,
            provider_registry=registry,
            gateway=gateway,
        )

        full_content = json.dumps({
            "strategic_directives": "D", "market_findings": "F", "positioning": "P",
            "creative_synthesis": "C", "funnel_kpi": "K", "final_synthesis": "S",
        })
        resp = (200, {"id": "c", "choices": [{"message": {"role": "assistant", "content": full_content}}],
                      "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}})
        received: List[Dict[str, Any]] = []
        server = MockOpenAIHttpServer(("127.0.0.1", 0), MockOpenAIHandler, received, [resp, resp])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
            manager.upsert_provider(
                {"provider_id": "del_prov", "base_url": base_url, "default_model": "m-d",
                 "cost_policy": "FREE_TIER_ALLOWED"},
                secret="DELETE_PROBE_V1",
            )
            ref_v1 = manager.get_settings().providers["del_prov"].credential_ref
            manager.update_settings({"global_target": {"provider_id": "del_prov", "model_id": "m-d"}})

            runtime = FiveAgentDepartmentRuntime(model_gateway=gateway, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
            ctx1 = runtime.start_run(objective="Delete vs Active Run RUN-1")
            out1 = runtime.execute_stage_cmo_initial(ctx1)
            self.assertEqual(out1["status"], "COMPLETED")

            # Unreference from committed routing, then delete while RUN-1 active.
            manager.update_settings({"global_target": {"provider_id": "gemini", "model_id": "gemini-flash-latest"}})
            self.assertTrue(manager.delete_provider("del_prov"))

            # New-run authority: provider gone from settings + registry.
            self.assertNotIn("del_prov", manager.get_settings().providers)
            self.assertIsNone(registry.get_provider("del_prov"))
            self.assertIsNone(registry.get_adapter("del_prov"))

            # Active-run safety: pinned credential/config state survives.
            self.assertEqual(probe_store.get_secret(ref_v1), "DELETE_PROBE_V1")

            # RUN-1 continues to authenticate with V1 after deletion.
            out_late = runtime.execute_stage_intelligence(ctx1)
            self.assertEqual(out_late["status"], "COMPLETED")
            self.assertEqual(received[-1]["auth"], "Bearer DELETE_PROBE_V1")

            # After RUN-1 terminates, physical reclamation becomes possible.
            ctx1.status = RuntimeStatus.CANCELLED
            reclaimed = manager.reclaim_obsolete_credential_versions(provider_ids=["del_prov"])
            self.assertIn(ref_v1, reclaimed)
            self.assertIsNone(probe_store.get_secret(ref_v1))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    def test_55_delete_after_run_terminal_reclaims_everything(self):
        """After the referencing run reached a terminal state, delete/reclaim
        fully removes config, cached adapters, and obsolete credential versions;
        new runs cannot select the deleted provider."""
        self.settings_manager.upsert_provider(
            {"provider_id": "term_prov", "adapter_type": "OPENAI_COMPATIBLE",
             "base_url": "https://api.term.test/v1", "default_model": "m-t",
             "cost_policy": "FREE_TIER_ALLOWED"},
            secret="TERM_V1",
        )
        ref = self.settings_manager.get_settings().providers["term_prov"].credential_ref
        adapter = self.registry.get_adapter("term_prov")
        self.assertIsNotNone(adapter)

        self.assertTrue(self.settings_manager.delete_provider("term_prov"))
        self.assertNotIn("term_prov", self.settings_manager.get_settings().providers)
        self.assertIsNone(self.registry.get_provider("term_prov"))
        self.assertIsNone(self.registry.get_adapter("term_prov"))
        self.assertIsNone(self.secret_store.get_secret(ref))
        # New runs cannot select it even directly through the registry.
        from integrations.models.registry import ProviderDefinition as _PD
        self.assertIsNone(self.registry.get_pinned_adapter(_PD(
            provider_id="term_prov", adapter_type="OPENAI_COMPATIBLE",
            default_model="m-t", credential_ref=ref,
        )))

    def _revision_snapshot(self) -> Dict[str, Any]:
        s = self.settings_manager.get_settings()
        return {
            "revision": s.settings_revision,
            "file_bytes": self.settings_path.read_bytes(),
            "vault_refs": {
                pid: self.secret_store.list_provider_version_refs(pid)
                for pid in ("txa", "txb")
            },
            "in_memory": s.model_dump(),
        }

    def test_56_secret_store_write_failure_leaves_coherent_state(self):
        """A failing vault write during a MULTI-PROVIDER single save must abort
        the whole transaction truthfully: revision/file/in-memory unchanged,
        zero orphan staged credentials in the vault."""
        self.settings_manager.upsert_provider({"provider_id": "txa", "default_model": "m"}, secret="TX_A_V1")
        before = self._revision_snapshot()
        real_set = self.secret_store.set_secret

        def failing_set(key_id, value):
            if str(key_id) == "txb":
                raise SecureSecretStoreUnavailableError("INJECTED_VAULT_FAILURE")
            return real_set(key_id, value)

        # ONE transaction staging two provider credentials; second write fails.
        with patch.object(self.secret_store, "set_secret", side_effect=failing_set):
            with self.assertRaises(SecureSecretStoreUnavailableError):
                self.settings_manager.update_settings({"providers": [
                    {"provider_id": "txa", "default_model": "m", "api_key": "TX_A_V2"},
                    {"provider_id": "txb", "default_model": "m", "api_key": "TX_B_V1"},
                ]})

        after = self._revision_snapshot()
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["file_bytes"], before["file_bytes"])
        self.assertNotIn("txb", after["in_memory"]["providers"])
        # No usable orphan: txa keeps exactly its original committed version;
        # the staged TX_A_V2 was rolled back; txb has nothing.
        self.assertEqual(after["vault_refs"]["txa"], before["vault_refs"]["txa"])
        self.assertEqual(self.secret_store.get_secret(before["vault_refs"]["txa"][0]), "TX_A_V1")
        self.assertEqual(after["vault_refs"]["txb"], [])

    def test_57_settings_persistence_failure_rolls_back_candidate(self):
        """Disk publish failure during key rotation rolls back staged secrets and
        leaves the previously persisted payload and memory authoritative."""
        self.settings_manager.upsert_provider(
            {"provider_id": "persist_fail", "default_model": "m"}, secret="PF_V1"
        )
        before = self._revision_snapshot_for("persist_fail")

        with patch.object(
            ModelSettingsManager, "_save_to_disk",
            side_effect=OSError("INJECTED_DISK_FAILURE"),
        ):
            with self.assertRaises(OSError):
                self.settings_manager.upsert_provider(
                    {"provider_id": "persist_fail", "default_model": "m"}, secret="PF_V2"
                )

        after = self._revision_snapshot_for("persist_fail")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["file_bytes"], before["file_bytes"])
        self.assertEqual(after["committed_ref"], before["committed_ref"])
        self.assertEqual(self.secret_store.get_secret(before["committed_ref"]), "PF_V1")
        # Exactly one version retained: the staged V2 was rolled back.
        self.assertEqual(len(after["all_refs"]), 1)

    def _revision_snapshot_for(self, pid: str) -> Dict[str, Any]:
        s = self.settings_manager.get_settings()
        return {
            "revision": s.settings_revision,
            "file_bytes": self.settings_path.read_bytes(),
            "committed_ref": s.providers[pid].credential_ref,
            "all_refs": self.secret_store.list_provider_version_refs(pid),
        }

    def test_58_registry_apply_failure_leaves_coherent_state(self):
        """Registry application failure after disk publish triggers full rollback:
        previous file payload restored, staged secrets removed, memory untouched."""
        self.settings_manager.upsert_provider(
            {"provider_id": "reg_fail", "default_model": "m"}, secret="RF_V1"
        )
        before = self._revision_snapshot_for("reg_fail")

        with patch.object(
            ProviderRegistry, "register_provider",
            side_effect=RuntimeError("INJECTED_REGISTRY_FAILURE"),
        ):
            with self.assertRaises(RuntimeError):
                self.settings_manager.upsert_provider(
                    {"provider_id": "reg_fail", "default_model": "m"}, secret="RF_V2"
                )

        after = self._revision_snapshot_for("reg_fail")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["file_bytes"], before["file_bytes"])
        self.assertEqual(after["committed_ref"], before["committed_ref"])
        self.assertEqual(self.secret_store.get_secret(before["committed_ref"]), "RF_V1")
        self.assertEqual(len(after["all_refs"]), 1)

    def test_59_policy_apply_failure_leaves_coherent_state(self):
        """Gateway policy application failure triggers identical full rollback."""

        class FailingPolicyProperty:
            def __set__(self, obj, value):
                raise RuntimeError("INJECTED_POLICY_FAILURE")

            def __get__(self, obj, objtype=None):
                return obj._model_policy

        self.settings_manager.upsert_provider(
            {"provider_id": "pol_fail", "default_model": "m"}, secret="PO_V1"
        )
        before = self._revision_snapshot_for("pol_fail")

        with patch.object(UniversalModelGateway, "model_policy", FailingPolicyProperty()):
            with self.assertRaises(RuntimeError):
                self.settings_manager.upsert_provider(
                    {"provider_id": "pol_fail", "default_model": "m"}, secret="PO_V2"
                )

        after = self._revision_snapshot_for("pol_fail")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["file_bytes"], before["file_bytes"])
        self.assertEqual(self.secret_store.get_secret(before["committed_ref"]), "PO_V1")
        self.assertEqual(len(after["all_refs"]), 1)

    def test_60_failed_update_leaves_no_usable_orphan_credential(self):
        """Validation failure AFTER secret staging (stage 4 of the transaction)
        must delete the staged credential: no reachable orphan remains."""
        self.settings_manager.upsert_provider(
            {"provider_id": "orphan_prov", "default_model": "m"}, secret="OK_V1"
        )
        ok_ref = self.settings_manager.get_settings().providers["orphan_prov"].credential_ref
        rev_before = self.settings_manager.get_settings().settings_revision

        # Single transaction: stage a new key AND introduce a candidate-level
        # validation failure (duplicate fallback target) in the same update.
        with self.assertRaises(ModelSettingsValidationError) as ctx:
            self.settings_manager.update_settings({
                "providers": [
                    {"provider_id": "orphan_prov", "default_model": "m", "api_key": "ORPHAN_STAGED_V2"},
                ],
                "fallback_chain": [
                    {"provider_id": "gemini", "model_id": "g1"},
                    {"provider_id": "gemini", "model_id": "g1"},
                ],
            })
        self.assertIn("DUPLICATE_FALLBACK_TARGET", str(ctx.exception))

        # Staged ORPHAN_STAGED_V2 was rolled back; only OK_V1 remains reachable.
        self.assertEqual(self.secret_store.list_provider_version_refs("orphan_prov"), [ok_ref])
        self.assertEqual(self.secret_store.get_secret(ok_ref), "OK_V1")
        self.assertIsNone(self.secret_store.get_secret("STORE:orphan_prov"))
        self.assertEqual(self.settings_manager.get_settings().settings_revision, rev_before)

    def test_61_stale_provider_delete_rejected_and_provider_remains(self):
        """DELETE honors the authoritative revision: stale expected_revision is
        rejected (manager + HTTP route) and the provider remains."""
        self.settings_manager.upsert_provider({"provider_id": "stale_del", "default_model": "m"})
        stale_rev = self.settings_manager.get_settings().settings_revision
        self.settings_manager.update_settings({"free_only_mode": False})  # revision advances

        with self.assertRaises(StaleSettingsRevisionError):
            self.settings_manager.delete_provider("stale_del", expected_revision=stale_rev)
        self.assertIn("stale_del", self.settings_manager.get_settings().providers)

        # HTTP contract: 409 through the DELETE route query parameter.
        from app_api.server import APP_BACKEND
        self._start_test_api_server()
        # Seed a provider through the real API so the SERVING backend owns it.
        _, current = self._api_request("GET", "/api/settings/model")
        code, _ = self._api_request(
            "POST", "/api/settings/providers/upsert",
            body={"expected_revision": current["settings_revision"],
                  "provider_id": "stale_del_http", "default_model": "m"},
        )
        self.assertEqual(code, 200)

        backend_rev = APP_BACKEND.settings_manager.get_settings().settings_revision
        code, body = self._api_request(
            "DELETE", f"/api/settings/providers/stale_del_http?expected_revision={backend_rev - 1}"
        )
        self.assertEqual(code, 409)
        self.assertEqual(body.get("error"), "STALE_SETTINGS_REVISION")
        self.assertIn("stale_del_http", APP_BACKEND.settings_manager.get_settings().providers)

        code, body = self._api_request(
            "DELETE", f"/api/settings/providers/stale_del_http?expected_revision={backend_rev}"
        )
        self.assertEqual(code, 200)
        self.assertNotIn("stale_del_http", APP_BACKEND.settings_manager.get_settings().providers)

    def test_62_stale_api_key_replacement_rejected(self):
        """A stale tab cannot replace an API key over a newer committed revision."""
        self.settings_manager.upsert_provider({"provider_id": "stale_key", "default_model": "m"}, secret="SK_V1")
        stale_rev = self.settings_manager.get_settings().settings_revision
        self.settings_manager.update_settings({"free_only_mode": False})

        with self.assertRaises(StaleSettingsRevisionError):
            self.settings_manager.upsert_provider(
                {"provider_id": "stale_key", "default_model": "m"}, secret="SK_EVIL",
                expected_revision=stale_rev,
            )
        ref = self.settings_manager.get_settings().providers["stale_key"].credential_ref
        self.assertEqual(self.secret_store.get_secret(ref), "SK_V1")

    def test_63_stale_enable_rejected(self):
        self.settings_manager.upsert_provider({"provider_id": "stale_en", "default_model": "m"})
        self.settings_manager.disable_provider("stale_en")
        stale_rev = self.settings_manager.get_settings().settings_revision
        self.settings_manager.update_settings({"free_only_mode": True})

        with self.assertRaises(StaleSettingsRevisionError):
            self.settings_manager.enable_provider("stale_en", expected_revision=stale_rev)
        self.assertFalse(self.settings_manager.get_settings().providers["stale_en"].enabled)

    def test_64_stale_disable_rejected(self):
        self.settings_manager.upsert_provider({"provider_id": "stale_dis", "default_model": "m"})
        stale_rev = self.settings_manager.get_settings().settings_revision
        self.settings_manager.update_settings({"free_only_mode": True})

        with self.assertRaises(StaleSettingsRevisionError):
            self.settings_manager.disable_provider("stale_dis", expected_revision=stale_rev)
        self.assertTrue(self.settings_manager.get_settings().providers["stale_dis"].enabled)

    def test_65_all_successful_mutations_monotonically_increment_revision(self):
        """update / upsert / enable / disable / delete each advance THE single
        authoritative revision by exactly one — no silent last-write-wins forks."""
        rev = self.settings_manager.get_settings().settings_revision

        self.settings_manager.update_settings({"free_only_mode": False})
        rev += 1
        self.assertEqual(self.settings_manager.get_settings().settings_revision, rev)

        self.settings_manager.upsert_provider({"provider_id": "mono_prov", "default_model": "m"})
        rev += 1
        self.assertEqual(self.settings_manager.get_settings().settings_revision, rev)

        self.settings_manager.disable_provider("mono_prov")
        rev += 1
        self.assertEqual(self.settings_manager.get_settings().settings_revision, rev)

        self.settings_manager.enable_provider("mono_prov")
        rev += 1
        self.assertEqual(self.settings_manager.get_settings().settings_revision, rev)

        self.settings_manager.delete_provider("mono_prov")
        rev += 1
        self.assertEqual(self.settings_manager.get_settings().settings_revision, rev)


    # =========================================================================
    # 16. PRODUCTION REGISTRY WIRING & RUN SNAPSHOT FIDELITY
    #     (PROD-MODEL-SETTINGS-01R3)
    # =========================================================================

    def _pin_generate(self, gateway, registry, snapshot_dump, policy_dump, request_id, model_id):
        """Execute through the exact production pathway used by the runtime:
        pinned ModelPolicy + ProviderRegistrySnapshot passed to generate()."""
        from integrations.models.base import ModelMessage, ModelRequest, ModelRole
        req = ModelRequest(
            request_id=request_id,
            messages=[ModelMessage(role=ModelRole.USER, content="ping")],
            model_name=model_id,
        )
        return gateway.generate(
            req,
            agent_id="cmo",
            model_policy=ModelPolicy(**policy_dump),
            provider_snapshot=ProviderRegistrySnapshot(
                providers={k: ProviderDefinition(**v) for k, v in snapshot_dump["providers"].items()}
            ),
        )

    def test_67_production_bootstrap_keeps_one_registry_instance(self):
        """Production construction order (runtime first, then
        ModelSettingsManager(gateway=...) exactly as DepartmentAppBackend does)
        must keep ONE authoritative ProviderRegistry on the Gateway."""
        from app_api.server import APP_BACKEND
        runtime_registry = APP_BACKEND.runtime.model_gateway.provider_registry
        settings_registry = APP_BACKEND.settings_manager._provider_registry
        self.assertIs(runtime_registry, settings_registry)

    def test_68_credential_usage_authority_survives_settings_manager(self):
        """The credential usage authority installed by the runtime must remain
        installed on the final Gateway registry after Settings bootstrap."""
        from app_api.server import APP_BACKEND
        registry = APP_BACKEND.runtime.model_gateway.provider_registry
        authority = getattr(registry, "_credential_usage_authority", None)
        self.assertIsNotNone(authority)
        # And it answers truthfully through the runtime's active contexts.
        self.assertIsInstance(authority("STORE:definitely_not_used_anywhere"), bool)

    def test_69_production_wired_run1_v1_survives_credential_gc(self):
        """Through REAL DepartmentAppBackend wiring: RUN-1 pins V1, key rotates
        (post-commit GC fires), RUN-1's late call must still authenticate V1."""
        from app_api.server import APP_BACKEND
        full_content = json.dumps({
            "strategic_directives": "D", "market_findings": "F", "positioning": "P",
            "creative_synthesis": "C", "funnel_kpi": "K", "final_synthesis": "S",
        })
        resp = (200, {"id": "c", "choices": [{"message": {"role": "assistant", "content": full_content}}],
                      "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}})
        received: List[Dict[str, Any]] = []
        server = MockOpenAIHttpServer(("127.0.0.1", 0), MockOpenAIHandler, received, [resp, resp])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            mgr = APP_BACKEND.settings_manager
            base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
            original_target = mgr.get_settings().global_target.model_dump()
            try:
                mgr.upsert_provider(
                    {"provider_id": "prodwire_prov", "adapter_type": "OPENAI_COMPATIBLE",
                     "base_url": base_url, "default_model": "m-pw",
                     "cost_policy": "FREE_TIER_ALLOWED"},
                    secret="PRODWIRE_V1",
                )
                ref_v1 = mgr.get_settings().providers["prodwire_prov"].credential_ref
                mgr.update_settings({"fallback_chain": []})
                mgr.update_settings({"global_target": {"provider_id": "prodwire_prov", "model_id": "m-pw"}})

                runtime = APP_BACKEND.runtime
                ctx1 = runtime.start_run(objective="Prod wiring rotation truth")
                out1 = runtime.execute_stage_cmo_initial(ctx1)
                self.assertEqual(out1["status"], "COMPLETED")

                # Rotate through real Settings pathway -> GC fires post-commit.
                mgr.upsert_provider(
                    {"provider_id": "prodwire_prov", "base_url": base_url, "default_model": "m-pw"},
                    secret="PRODWIRE_V2",
                )
                out_late = runtime.execute_stage_intelligence(ctx1)
                self.assertEqual(out_late["status"], "COMPLETED")

                self.assertEqual(received[0]["auth"], "Bearer PRODWIRE_V1")
                self.assertEqual(received[1]["auth"], "Bearer PRODWIRE_V1")
                self.assertTrue(mgr._secret_store.has_secret(ref_v1))
            finally:
                mgr.update_settings({"global_target": original_target})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    def _aliasing_stack(self, url_a, url_b, order_run1_first):
        """Shared scenario: same credential_ref, ONLY base_url changes mid-flight."""
        store = SecureSecretStore(vault_path=Path(self.test_dir) / f"alias_{order_run1_first}.vault")
        registry = ProviderRegistry(secret_store=store)
        gateway = UniversalModelGateway(provider_registry=registry, free_only_mode=True)
        manager = ModelSettingsManager(
            settings_file_path=Path(self.test_dir) / f"alias_{order_run1_first}.json",
            secret_store=store, provider_registry=registry, gateway=gateway,
        )
        manager.upsert_provider(
            {"provider_id": "prov_alias", "adapter_type": "OPENAI_COMPATIBLE",
             "base_url": url_a, "default_model": "m-a", "cost_policy": "FREE_TIER_ALLOWED"},
            secret="ALIAS_V1",
        )
        manager.update_settings({"global_target": {"provider_id": "prov_alias", "model_id": "m-a"}})

        snap_a = registry.snapshot().model_dump()
        pol_a = gateway.model_policy.model_dump()

        # Settings changes ONLY base_url; credential_ref unchanged.
        manager.update_settings({"providers": [{"provider_id": "prov_alias", "base_url": url_b}]})
        snap_b = registry.snapshot().model_dump()

        if order_run1_first:
            r1 = self._pin_generate(gateway, registry, snap_a, pol_a, "AL1", "m-a")
            pol_b = gateway.model_policy.model_dump()
            r2 = self._pin_generate(gateway, registry, snap_b, pol_b, "AL2", "m-a")
        else:
            pol_b = gateway.model_policy.model_dump()
            r2 = self._pin_generate(gateway, registry, snap_b, pol_b, "AL2", "m-a")
            r1 = self._pin_generate(gateway, registry, snap_a, pol_a, "AL1", "m-a")
        return r1, r2

    def test_70_same_key_base_url_mutation_run1_first_order(self):
        """CASE 1: RUN-1 constructs first. RUN-1 must reach SERVER_A (pinned),
        RUN-2 must reach SERVER_B (its own committed config) despite identical
        credential version."""
        full_content = json.dumps({"strategic_directives": "D"})
        received: List[Dict[str, Any]] = []
        resp = (200, {"id": "c", "choices": [{"message": {"role": "assistant", "content": full_content}}],
                      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        def make_server(tag):
            handler_cls = type(f"TaggedHandler{tag}", (TaggedMockOpenAIHandler,), {"tag": tag})
            srv = MockOpenAIHttpServer(("127.0.0.1", 0), handler_cls, received, [resp, resp, resp])
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"

        srv_a, url_a = make_server("A")
        srv_b, url_b = make_server("B")
        try:
            r1, r2 = self._aliasing_stack(url_a, url_b, order_run1_first=True)
            self.assertEqual(r1.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(r2.status, ModelResponseStatus.SUCCESS)
            tags = [e["tag"] for e in received]
            self.assertEqual(tags, ["A", "B"])  # RUN-1 -> A, RUN-2 -> B
        finally:
            for s in (srv_a, srv_b):
                s.shutdown(); s.server_close()
        threading.enumerate()

    def test_71_same_key_base_url_mutation_run2_first_order(self):
        """CASE 2: RUN-2 constructs first. RUN-2 -> SERVER_B, and RUN-1's later
        pinned construction must STILL resolve SERVER_A."""
        full_content = json.dumps({"strategic_directives": "D"})
        received: List[Dict[str, Any]] = []
        resp = (200, {"id": "c", "choices": [{"message": {"role": "assistant", "content": full_content}}],
                      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        def make_server(tag):
            handler_cls = type(f"TaggedHandler{tag}", (TaggedMockOpenAIHandler,), {"tag": tag})
            srv = MockOpenAIHttpServer(("127.0.0.1", 0), handler_cls, received, [resp, resp, resp])
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"

        srv_a, url_a = make_server("A")
        srv_b, url_b = make_server("B")
        try:
            r1, r2 = self._aliasing_stack(url_a, url_b, order_run1_first=False)
            self.assertEqual(r1.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(r2.status, ModelResponseStatus.SUCCESS)
            tags = [e["tag"] for e in received]
            self.assertEqual(tags, ["B", "A"])  # construction order reversed
        finally:
            for s in (srv_a, srv_b):
                s.shutdown(); s.server_close()

    def test_72_pinned_execution_fingerprint_is_safe_and_config_sensitive(self):
        """Fingerprint: 64-hex SHA-256 over safe execution fields; excludes
        plaintext secrets AND non-execution metadata like display_name;
        sensitive to endpoint/model/timeout/credential-version changes."""
        base_def = ProviderDefinition(
            provider_id="fp_prov", adapter_type="OPENAI_COMPATIBLE",
            base_url="https://api.fp.test/v1", default_model="m-fp",
            timeout_seconds=12.5, cost_policy="FREE_TIER_ALLOWED",
            credential_ref="STORE:fp_prov:abc123",
            supported_capabilities={"supports_json": True},
        )
        fp1 = ProviderRegistry._execution_fingerprint(base_def)
        self.assertRegex(fp1, r"^[0-9a-f]{64}$")

        # Same config -> identical fingerprint (deterministic canonical form).
        self.assertEqual(fp1, ProviderRegistry._execution_fingerprint(
            ProviderDefinition(**base_def.model_dump())))

        # display_name is NOT execution identity.
        renamed = ProviderDefinition(**{**base_def.model_dump(), "display_name": "Totally Different"})
        self.assertEqual(fp1, ProviderRegistry._execution_fingerprint(renamed))

        # Every execution-relevant field changes the fingerprint.
        # NOTE: adapter_type is schema-normalized (protocol-coerced) and cannot
        # be mutated independently, so it is covered by construction equality.
        mutations = {
            "base_url": "https://other.test/v1",
            "credential_ref": "STORE:fp_prov:def456",
            "default_model": "m-other",
            "chat_completions_path": "/custom/path",
            "timeout_seconds": 99.0,
            "cost_policy": "PAID",
            "supported_capabilities": {"supports_json": False},
        }
        for field, value in mutations.items():
            mutated = ProviderDefinition(**{**base_def.model_dump(), field: value})
            self.assertNotEqual(fp1, ProviderRegistry._execution_fingerprint(mutated), field)

        # No plaintext material in fingerprints even with secret-like inputs.
        secretish = ProviderDefinition(**{**base_def.model_dump(), "credential_ref": "STORE:x:SECRETVALUE"})
        self.assertNotIn("SECRETVALUE", ProviderRegistry._execution_fingerprint(secretish))

    def test_73_pinned_cache_cleanup_by_credential_ref_still_works(self):
        """Reclamation eviction works with fingerprint keys: every adapter built
        on a reclaimed credential_ref is evicted; others survive."""
        d1 = ProviderDefinition(provider_id="evict_prov", adapter_type="OPENAI_COMPATIBLE",
                                base_url="https://api.e1.test/v1", default_model="m1",
                                credential_ref="PLACEHOLDER_V1")
        vault = SecureSecretStore(vault_path=Path(self.test_dir) / "evict.vault")
        ref_v1 = vault.set_secret("evict_prov", "k-v1")
        ref_v2 = vault.set_secret("evict_prov", "k-v2")
        d1 = ProviderDefinition(provider_id="evict_prov", adapter_type="OPENAI_COMPATIBLE",
                                base_url="https://api.e1.test/v1", default_model="m1",
                                credential_ref=ref_v1)
        d2 = ProviderDefinition(**{**d1.model_dump(),
                                   "base_url": "https://api.e1.test/v2",
                                   "credential_ref": ref_v2})
        # Dedicated registry BOUND to this vault so pinned resolution works.
        evict_registry = ProviderRegistry(secret_store=vault)

        a1 = evict_registry.get_pinned_adapter(d1)
        a2 = evict_registry.get_pinned_adapter(d2)
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)
        self.assertIsNot(a1, a2)

        evict_registry.evict_pinned_adapter(ref_v1)
        remaining = [k for k in evict_registry._adapters if k.startswith("evict_prov@")]
        self.assertEqual(len(remaining), 1)
        self.assertIs(evict_registry.get_pinned_adapter(d2), a2)      # untouched, cached
        self.assertIsNotNone(evict_registry.get_pinned_adapter(d1))   # rebuildable while secret exists
        # After actual reclamation of the secret, pinned resolution fails closed.
        vault.delete_secret_ref(ref_v1)
        evict_registry.evict_pinned_adapter(ref_v1)
        self.assertIsNone(evict_registry.get_pinned_adapter(d1))

    def _free_only_stack(self):
        self.settings_manager.update_settings({"fallback_chain": []})
        self.settings_manager.upsert_provider(
            {"provider_id": "fo_paid", "adapter_type": "OPENAI_COMPATIBLE",
             "base_url": "https://api.fo-paid.test/v1", "default_model": "m-fo",
             "cost_policy": "PAID"},
            secret="FO_KEY",
        )
        self.settings_manager.update_settings({"global_target": {"provider_id": "fo_paid", "model_id": "m-fo"}})

    def test_74_free_only_true_to_false_active_run_pinning(self):
        """RUN-1 pinned free_only=True stays BLOCKED on a PAID provider even
        after Settings flips free_only=False; RUN-2 observes False."""
        from unittest.mock import patch as _patch
        self._free_only_stack()
        snap_true = self.registry.snapshot().model_dump()
        pol_true = self.gateway.model_policy.model_dump()   # free_only True pinned

        calls = {"n": 0}

        def counting_gen(self_adapter, request):
            calls["n"] += 1
            return ModelResponse(request_id=request.request_id, provider=self_adapter.provider_name,
                                 model_name=request.model_name,
                                 status=ModelResponseStatus.SUCCESS, content="ok")

        with patch.object(OpenAICompatibleProviderAdapter, "generate", counting_gen):
            r_first = self._pin_generate(self.gateway, self.registry, snap_true, pol_true, "FO-A", "m-fo")
            self.assertEqual(r_first.status, ModelResponseStatus.ERROR)
            self.assertIn("FREE_ONLY_POLICY_VIOLATION", str(r_first.error))

            # Mid-run flip through real Settings pathway.
            self.settings_manager.update_settings({"free_only_mode": False})
            hits_after_flip = calls["n"]

            r_run1 = self._pin_generate(self.gateway, self.registry, snap_true, pol_true, "FO-B", "m-fo")
            self.assertEqual(r_run1.status, ModelResponseStatus.ERROR)
            self.assertIn("FREE_ONLY_POLICY_VIOLATION", str(r_run1.error))
            self.assertEqual(calls["n"], hits_after_flip)  # RUN-1 never executed

            pol_new = self.gateway.model_policy.model_dump()
            snap_new = self.registry.snapshot().model_dump()
            r_run2 = self._pin_generate(self.gateway, self.registry, snap_new, pol_new, "FO-C", "m-fo")
            self.assertEqual(calls["n"], hits_after_flip + 1)  # RUN-2 executed
            self.assertEqual(r_run2.status, ModelResponseStatus.SUCCESS)

    def test_75_free_only_false_to_true_active_run_pinning(self):
        """Inverse: RUN-1 pinned free_only=False stays ALLOWED after Settings
        flips True; RUN-2 becomes blocked."""
        from unittest.mock import patch as _patch
        self._free_only_stack()
        self.settings_manager.update_settings({"free_only_mode": False})
        snap_false = self.registry.snapshot().model_dump()
        pol_false = self.gateway.model_policy.model_dump()

        calls = {"n": 0}

        def counting_gen(self_adapter, request):
            calls["n"] += 1
            return ModelResponse(request_id=request.request_id, provider=self_adapter.provider_name,
                                 model_name=request.model_name,
                                 status=ModelResponseStatus.SUCCESS, content="ok")

        with _patch.object(OpenAICompatibleProviderAdapter, "generate", counting_gen):
            r_first = self._pin_generate(self.gateway, self.registry, snap_false, pol_false, "FI-A", "m-fo")
            self.assertEqual(r_first.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(calls["n"], 1)

            self.settings_manager.update_settings({"free_only_mode": True})

            r_run1 = self._pin_generate(self.gateway, self.registry, snap_false, pol_false, "FI-B", "m-fo")
            self.assertEqual(r_run1.status, ModelResponseStatus.SUCCESS)   # still allowed
            self.assertEqual(calls["n"], 2)

            pol_new = self.gateway.model_policy.model_dump()
            snap_new = self.registry.snapshot().model_dump()
            r_run2 = self._pin_generate(self.gateway, self.registry, snap_new, pol_new, "FI-C", "m-fo")
            self.assertIn("FREE_ONLY_POLICY_VIOLATION", str(r_run2.error or ""))
            self.assertEqual(calls["n"], 2)  # RUN-2 never reached an adapter

    def test_76_unknown_cost_follows_generic_free_only_semantics(self):
        """UNKNOWN cost is unverified: blocked under strict free-only for ANY
        provider name (no hardcoded exceptions); FREE_TIER_ALLOWED executes."""
        self.settings_manager.update_settings({"fallback_chain": []})
        self.settings_manager.upsert_provider(
            {"provider_id": "gemini", "adapter_type": "OPENAI_COMPATIBLE",  # deliberately ambiguous name
             "base_url": "https://api.ambiguous.test/v1", "default_model": "m-u",
             "cost_policy": "UNKNOWN"},
            secret="U_KEY",
        )
        self.settings_manager.update_settings({"global_target": {"provider_id": "gemini", "model_id": "m-u"}})
        snap = self.registry.snapshot().model_dump()
        pol = self.gateway.model_policy.model_dump()

        executed = {"n": 0}
        def no_exec(self, request):
            executed["n"] += 1
            raise AssertionError("UNKNOWN-cost provider must not execute under FREE_ONLY_MODE")

        from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter as _Ad
        with patch.object(_Ad, "generate", no_exec):
            r = self._pin_generate(self.gateway, self.registry, snap, pol, "UNK-1", "m-u")
        self.assertEqual(r.status, ModelResponseStatus.ERROR)
        self.assertIn("FREE_ONLY_POLICY_VIOLATION", str(r.error))
        self.assertEqual(executed["n"], 0)

        # Generic allow path for declared-free providers (any name).
        self.settings_manager.upsert_provider(
            {"provider_id": "thespark", "adapter_type": "OPENAI_COMPATIBLE",
             "base_url": "https://api.free-named.test/v1", "default_model": "m-f",
             "cost_policy": "FREE_TIER_ALLOWED"},
            secret="F_KEY",
        )
        self.settings_manager.update_settings({"global_target": {"provider_id": "thespark", "model_id": "m-f"}})
        snap2 = self.registry.snapshot().model_dump()
        pol2 = self.gateway.model_policy.model_dump()
        with patch.object(_Ad, "generate", lambda self_, rq: ModelResponse(
                request_id=rq.request_id, provider="thespark", model_name=rq.model_name,
                status=ModelResponseStatus.SUCCESS, content="ok")):
            r_ok = self._pin_generate(self.gateway, self.registry, snap2, pol2, "UNK-2", "m-f")
        self.assertEqual(r_ok.status, ModelResponseStatus.SUCCESS)

    def _timeout_capture_stack(self):
        captured = {}
        real_gen = OpenAICompatibleProviderAdapter.generate

        def spy(self, request):
            captured[request.request_id] = request.timeout_seconds
            return ModelResponse(request_id=request.request_id, provider=self.provider_name,
                                 model_name=request.model_name,
                                 status=ModelResponseStatus.SUCCESS, content="ok")

        return captured, spy

    def test_77_provider_timeout_comes_from_definition_not_legacy_config(self):
        """Execution timeout derives from ProviderDefinition.timeout_seconds even
        when GLOBAL_PROVIDER_CONFIG holds a different value."""
        captured, spy = self._timeout_capture_stack()
        self.settings_manager.upsert_provider(
            {"provider_id": "tmo_prov", "adapter_type": "OPENAI_COMPATIBLE",
             "base_url": "https://api.tmo.test/v1", "default_model": "m-t",
             "timeout_seconds": 5.55, "cost_policy": "FREE_TIER_ALLOWED"},
            secret="T_KEY",
        )
        self.settings_manager.update_settings({"global_target": {"provider_id": "tmo_prov", "model_id": "m-t"}})
        legacy_value = None
        if getattr(self.gateway, "config_service", None):
            try:
                legacy_value = self.gateway.config_service.get_timeout("tmo_prov")
            except Exception:
                legacy_value = None
        snap = self.registry.snapshot().model_dump()
        pol = self.gateway.model_policy.model_dump()

        with patch.object(OpenAICompatibleProviderAdapter, "generate", spy):
            self._pin_generate(self.gateway, self.registry, snap, pol, "TO-1", "m-t")

        self.assertEqual(captured["TO-1"], 5.55)
        if legacy_value is not None:
            self.assertNotEqual(legacy_value, 5.55)  # split brain source documented

    def test_78_active_run_timeout_remains_pinned(self):
        """Settings timeout change without key rotation must NOT drift RUN-1."""
        captured, spy = self._timeout_capture_stack()
        self.settings_manager.upsert_provider(
            {"provider_id": "tmo_pin", "adapter_type": "OPENAI_COMPATIBLE",
             "base_url": "https://api.tmop.test/v1", "default_model": "m-tp",
             "timeout_seconds": 4.25, "cost_policy": "FREE_TIER_ALLOWED"},
            secret="TP_KEY",
        )
        self.settings_manager.update_settings({"global_target": {"provider_id": "tmo_pin", "model_id": "m-tp"}})
        snap_old = self.registry.snapshot().model_dump()
        pol_old = self.gateway.model_policy.model_dump()

        self.settings_manager.update_settings({
            "providers": [{"provider_id": "tmo_pin", "timeout_seconds": 44.0}],
        })

        with patch.object(OpenAICompatibleProviderAdapter, "generate", spy):
            self._pin_generate(self.gateway, self.registry, snap_old, pol_old, "TO-R1", "m-tp")
            self.assertEqual(captured["TO-R1"], 4.25)

    def test_79_new_run_observes_new_timeout(self):
        captured, spy = self._timeout_capture_stack()
        self.settings_manager.upsert_provider(
            {"provider_id": "tmo_new", "adapter_type": "OPENAI_COMPATIBLE",
             "base_url": "https://api.tmon.test/v1", "default_model": "m-tn",
             "timeout_seconds": 4.25, "cost_policy": "FREE_TIER_ALLOWED"},
            secret="TN_KEY",
        )
        self.settings_manager.update_settings({"global_target": {"provider_id": "tmo_new", "model_id": "m-tn"}})
        self.settings_manager.update_settings({
            "providers": [{"provider_id": "tmo_new", "timeout_seconds": 33.0}],
        })
        snap_new = self.registry.snapshot().model_dump()
        pol_new = self.gateway.model_policy.model_dump()
        with patch.object(OpenAICompatibleProviderAdapter, "generate", spy):
            self._pin_generate(self.gateway, self.registry, snap_new, pol_new, "TO-R2", "m-tn")
        self.assertEqual(captured["TO-R2"], 33.0)

    def test_80_deleted_builtin_does_not_resurrect_after_reload(self):
        """Registry reconciliation: a deleted provider (even a builtin) stays
        deleted across a full Settings+Registry reconstruction (restart)."""
        # Isolated persistent stack.
        td = Path(tempfile.mkdtemp(prefix="resurrect_"))
        vault = SecureSecretStore(vault_path=td / "s.vault")
        reg1 = ProviderRegistry(secret_store=vault)
        gw1 = UniversalModelGateway(provider_registry=reg1, free_only_mode=True)
        mgr1 = ModelSettingsManager(settings_file_path=td / "m.json",
                                    secret_store=vault, provider_registry=reg1, gateway=gw1)
        self.assertIn("openai", reg1.list_providers())  # builtin present initially

        mgr1.delete_provider("openai")                  # remove routing refs unnecessary: not referenced
        self.assertNotIn("openai", mgr1.get_settings().providers)
        self.assertNotIn("openai", reg1.list_providers())

        # Full restart simulation: brand-new Registry bootstrap + Manager reload.
        reg2 = ProviderRegistry(secret_store=vault)     # bootstraps built-ins incl. openai
        gw2 = UniversalModelGateway(provider_registry=reg2, free_only_mode=True)
        mgr2 = ModelSettingsManager(settings_file_path=td / "m.json",
                                    secret_store=vault, provider_registry=reg2, gateway=gw2)
        self.assertNotIn("openai", mgr2.get_settings().providers)
        self.assertNotIn("openai", reg2.list_providers())
        self.assertNotIn("openai", gw2.provider_registry.list_providers())


    # =========================================================================
    # 17. PERSISTENCE INTEGRITY, REVISION AUTHORITY & SAFE SERIALIZATION
    #     (PROD-MODEL-SETTINGS-01R4A)
    # =========================================================================

    def _committed_ab_stack(self):
        """Committed state: providers A+B, global A, fallback B."""
        store = SecureSecretStore(vault_path=Path(self.test_dir) / f"rb_{id(self)}.vault")
        registry = ProviderRegistry(secret_store=store)
        gateway = UniversalModelGateway(provider_registry=registry, free_only_mode=True)
        manager = ModelSettingsManager(
            settings_file_path=Path(self.test_dir) / f"rb_{id(self)}.json",
            secret_store=store, provider_registry=registry, gateway=gateway,
        )
        manager.upsert_provider({"provider_id": "pa", "adapter_type": "OPENAI_COMPATIBLE",
                                 "base_url": "https://api.pa.test/v1", "default_model": "m-a",
                                 "cost_policy": "FREE_TIER_ALLOWED"}, secret="KA1")
        manager.upsert_provider({"provider_id": "pb", "adapter_type": "OPENAI_COMPATIBLE",
                                 "base_url": "https://api.pb.test/v1", "default_model": "m-b",
                                 "cost_policy": "FREE_TIER_ALLOWED"}, secret="KB1")
        manager.update_settings({"global_target": {"provider_id": "pa", "model_id": "m-a"}})
        return store, registry, gateway, manager

    def test_81_mid_registry_apply_failure_restores_previous_registry(self):
        """Failure injected mid-compile (after pa mutated, during pb apply AND
        during reconciliation) must restore the complete previous live registry."""
        _, registry, _, manager = self._committed_ab_stack()
        real_register = ProviderRegistry.register_provider

        def half_apply(self_reg, pdef):
            if pdef.provider_id == "pb" and pdef.default_model == "m-b2":
                raise RuntimeError("INJECTED_MID_APPLY")
            return real_register(self_reg, pdef)

        with patch.object(ProviderRegistry, "register_provider", half_apply):
            with self.assertRaises(RuntimeError):
                manager.update_settings({"providers": [
                    {"provider_id": "pa", "default_model": "m-a2"},
                    {"provider_id": "pb", "default_model": "m-b2"},
                ]})

        self.assertEqual(registry.get_provider("pa").default_model, "m-a")
        self.assertEqual(manager.get_settings().providers["pa"].default_model, "m-a")

        # Reconciliation-phase injection: one removal happens, then boom.
        def failing_reconcile(self_reg, valid_ids):
            self_reg._configs.pop("pb", None)
            raise RuntimeError("INJECTED_RECONCILE_FAILURE")

        with patch.object(ProviderRegistry, "reconcile_provider_configs", failing_reconcile):
            with self.assertRaises(RuntimeError):
                manager.update_settings({"free_only_mode": True})
        self.assertIsNotNone(registry.get_provider("pb"))
        self.assertIsNotNone(registry.get_provider("pa"))

    def test_82_policy_publication_failure_restores_registry_and_policy(self):
        """Registry applies, then gateway policy publication fails: BOTH must be
        restored to prior committed state."""
        _, registry, gateway, manager = self._committed_ab_stack()
        old_policy_dump = gateway.model_policy.model_dump()

        class FailingPolicyProperty:
            def __set__(self, obj, value):
                raise RuntimeError("INJECTED_POLICY_PUBLICATION_FAILURE")

            def __get__(self, obj, objtype=None):
                return obj._model_policy

        with patch.object(UniversalModelGateway, "model_policy", FailingPolicyProperty()):
            with self.assertRaises(RuntimeError):
                manager.update_settings({
                    "global_target": {"provider_id": "pb", "model_id": "m-b"},
                })

        self.assertEqual(gateway.model_policy.global_target.provider_id,
                         old_policy_dump["global_target"]["provider_id"])
        self.assertEqual(registry.get_provider("pa").enabled, True)
        self.assertEqual(manager.get_settings().global_target.provider_id, "pa")

    def test_83_failed_transaction_executes_old_committed_provider(self):
        """After a rolled-back save, a REAL request must execute using the OLD
        committed endpoint/credential — proven by actual loopback traffic."""
        full_content = json.dumps({"strategic_directives": "D"})
        received: List[Dict[str, Any]] = []
        resp = (200, {"id": "c", "choices": [{"message": {"role": "assistant", "content": full_content}}],
                      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        server = MockOpenAIHttpServer(("127.0.0.1", 0), MockOpenAIHandler, received, [resp])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/v1"
            store, registry, gateway, manager = self._committed_ab_stack()
            manager.upsert_provider({"provider_id": "pa", "base_url": url}, secret="KA_LIVE_V1")
            manager.update_settings({"global_target": {"provider_id": "pa", "model_id": "m-a"}})
            snap = registry.snapshot().model_dump()
            pol = gateway.model_policy.model_dump()

            # Failed transaction: rotate key AND break candidate (duplicate fallback).
            with self.assertRaises(ModelSettingsValidationError):
                manager.update_settings({
                    "providers": [{"provider_id": "pa", "api_key": "KA_SHOULD_NEVER_APPLY"}],
                    "fallback_chain": [
                        {"provider_id": "gemini", "model_id": "g"},
                        {"provider_id": "gemini", "model_id": "g"},
                    ],
                })
            ref = manager.get_settings().providers["pa"].credential_ref
            self.assertEqual(store.get_secret(ref), "KA_LIVE_V1")

            r = self._pin_generate(gateway, registry, registry.snapshot().model_dump(), pol, "RB-1", "m-a")
            self.assertEqual(r.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["auth"], "Bearer KA_LIVE_V1")  # OLD credential executed
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    # ---- Corrupt persisted configuration ------------------------------

    def _write_settings_file(self, td: Path, content: str) -> None:
        td.mkdir(parents=True, exist_ok=True)
        (td / "m.json").write_text(content, encoding="utf-8")

    def test_84_corrupt_truncated_settings_file_fails_closed(self):
        from integrations.models.settings_manager import PersistedSettingsCorruptionError
        td = Path(tempfile.mkdtemp(prefix="corrupt_"))
        good = SecureSecretStore(vault_path=td / "s.vault")
        reg0 = ProviderRegistry(secret_store=good)
        mgr0 = ModelSettingsManager(settings_file_path=td / "m.json",
                                    secret_store=good, provider_registry=reg0)
        original_bytes = (td / "m.json").read_bytes()

        truncated = original_bytes[: len(original_bytes) // 2]
        (td / "m.json").write_bytes(truncated)

        reg1 = ProviderRegistry(secret_store=good)
        with self.assertRaises(PersistedSettingsCorruptionError):
            ModelSettingsManager(settings_file_path=td / "m.json",
                                 secret_store=good, provider_registry=reg1)
        # File preserved exactly; not overwritten with defaults.
        self.assertEqual((td / "m.json").read_bytes(), truncated)

    def test_85_corrupt_schema_settings_file_fails_closed(self):
        from integrations.models.settings_manager import PersistedSettingsCorruptionError
        td = Path(tempfile.mkdtemp(prefix="corrupt2_"))
        variants = [
            '{"providers": "not-a-dict", "settings_revision": 1}',
            '{"agent_overrides": {"FINAL_CMO": {"provider_id": "x", "model_id": "y"}}, "settings_revision": 3}',
            '[]',
            '{"providers": {"bad": {"provider_id": "../evil", "default_model": "m"}}}',
            '{"providers": {"badto": {"provider_id": "x", "default_model": "m", "timeout_seconds": 99999}}}',
        ]
        for i, content in enumerate(variants):
            target = td / f"case_{i}.json"
            target.write_text(content, encoding="utf-8")
            vault = SecureSecretStore(vault_path=td / f"s{i}.vault")
            reg = ProviderRegistry(secret_store=vault)
            with self.assertRaises(PersistedSettingsCorruptionError, msg=content):
                ModelSettingsManager(settings_file_path=target, secret_store=vault, provider_registry=reg)
            self.assertEqual(target.read_text(encoding="utf-8"), content)  # preserved

    def test_86_missing_settings_file_initialization_distinct_from_corruption(self):
        from integrations.models.settings_manager import PersistedSettingsCorruptionError
        td = Path(tempfile.mkdtemp(prefix="fresh_"))
        vault = SecureSecretStore(vault_path=td / "s.vault")
        reg = ProviderRegistry(secret_store=vault)
        mgr = ModelSettingsManager(settings_file_path=td / "m.json",
                                   secret_store=vault, provider_registry=reg)
        self.assertEqual(mgr.get_settings().settings_revision, 1)
        self.assertIn("gemini", mgr.get_settings().providers)  # defaults initialized
        # And the initialized file reloads cleanly (not corruption).
        mgr2 = ModelSettingsManager(settings_file_path=td / "m.json",
                                    secret_store=vault, provider_registry=reg)
        self.assertEqual(mgr2.get_settings().settings_revision, 1)

    # ---- Vault integrity -------------------------------------------------

    def test_87_zero_byte_existing_vault_fails_closed(self):
        vault_path = Path(self.test_dir) / "zero.vault"
        vault_path.write_bytes(b"")
        store = SecureSecretStore(vault_path=vault_path)
        with self.assertRaises(VaultCorruptionError):
            store.set_secret("any", "value")
        with self.assertRaises(VaultCorruptionError):
            store.has_secret("STORE:any")
        # The corrupt file was NOT silently reset or expanded into a valid vault.
        self.assertEqual(vault_path.read_bytes(), b"")

    def test_88_malformed_encrypted_vault_fails_closed(self):
        import os as _os
        vault_path = Path(self.test_dir) / "random.vault"
        vault_path.write_bytes(_os.urandom(128))
        store = SecureSecretStore(vault_path=vault_path)
        with self.assertRaises(VaultCorruptionError):
            store.get_secret("STORE:whatever")

    def test_89_corrupt_vault_preserved_after_failed_operation(self):
        vault_path = self.vault_path
        ref = self.secret_store.set_secret("preserve_prov", "keep-me")
        raw = vault_path.read_bytes()
        tampered = bytearray(raw)
        tampered[len(tampered) // 2] ^= 0xFF
        vault_path.write_bytes(bytes(tampered))

        with self.assertRaises(VaultCorruptionError):
            self.secret_store.set_secret("other_prov", "never-persisted")
        with self.assertRaises(VaultCorruptionError):
            self.secret_store.get_secret(ref)
        self.assertEqual(vault_path.read_bytes(), bytes(tampered))  # untouched

    # ---- Mandatory expected_revision at the API boundary ------------------

    def _backend_rev(self):
        _, current = self._api_request("GET", "/api/settings/model")
        return current["settings_revision"]

    def test_90_missing_expected_revision_settings_update_rejected(self):
        self._start_test_api_server()
        code, body = self._api_request("POST", "/api/settings/model", body={"free_only_mode": False})
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "MISSING_SETTINGS_REVISION")

    def test_91_missing_expected_revision_provider_upsert_rejected(self):
        self._start_test_api_server()
        code, body = self._api_request("POST", "/api/settings/providers/upsert", body={
            "provider_id": "norev_prov", "default_model": "m",
        })
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "MISSING_SETTINGS_REVISION")

    def _seed_backend_provider(self, pid):
        rev = self._backend_rev()
        code, _ = self._api_request("POST", "/api/settings/providers/upsert", body={
            "expected_revision": rev, "provider_id": pid, "default_model": "m",
        })
        self.assertEqual(code, 200)

    def test_92_missing_expected_revision_enable_rejected(self):
        self._start_test_api_server()
        self._seed_backend_provider("norev_enable")
        code, body = self._api_request("POST", "/api/settings/providers/norev_enable/enable", body={})
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "MISSING_SETTINGS_REVISION")

    def test_93_missing_expected_revision_disable_rejected(self):
        self._start_test_api_server()
        self._seed_backend_provider("norev_disable")
        code, body = self._api_request("POST", "/api/settings/providers/norev_disable/disable", body={})
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "MISSING_SETTINGS_REVISION")

    def test_94_missing_expected_revision_delete_rejected_both_routes(self):
        self._start_test_api_server()
        self._seed_backend_provider("norev_delete")
        code, body = self._api_request("POST", "/api/settings/providers/norev_delete/delete", body={})
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "MISSING_SETTINGS_REVISION")
        code, body = self._api_request("DELETE", "/api/settings/providers/norev_delete")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "MISSING_SETTINGS_REVISION")

    def test_95_stale_revision_matrix_all_routes(self):
        self._start_test_api_server()
        self._seed_backend_provider("stale_matrix")
        stale = self._backend_rev() - 10  # guaranteed stale
        cases = [
            ("POST", "/api/settings/model", {"expected_revision": stale, "free_only_mode": False}),
            ("POST", "/api/settings/providers/upsert", {
                "expected_revision": stale, "provider_id": "stale_matrix", "default_model": "m2"}),
            ("POST", "/api/settings/providers/stale_matrix/enable", {"expected_revision": stale}),
            ("POST", "/api/settings/providers/stale_matrix/disable", {"expected_revision": stale}),
            ("POST", "/api/settings/providers/stale_matrix/delete", {"expected_revision": stale}),
            ("DELETE", f"/api/settings/providers/stale_matrix?expected_revision={stale}", None),
        ]
        for method, path, body in cases:
            code, resp_body = self._api_request(method, path, body=body)
            self.assertEqual(code, 409, f"{method} {path}")
            self.assertEqual(resp_body.get("error"), "STALE_SETTINGS_REVISION", f"{method} {path}")

    # ---- Safe serialization -----------------------------------------------

    def test_96_settings_get_contains_no_credential_ref(self):
        self._start_test_api_server()
        rev = self._backend_rev()
        self._api_request("POST", "/api/settings/providers/upsert", body={
            "expected_revision": rev, "provider_id": "ser_prov",
            "default_model": "m", "api_key": "SER_KEY_VALUE",
        })
        code, body = self._api_request("GET", "/api/settings/model")
        self.assertEqual(code, 200)
        serialized = json.dumps(body)
        self.assertNotIn("credential_ref", serialized)
        self.assertNotIn("SER_KEY_VALUE", serialized)

    def test_97_mutation_responses_contain_no_credential_ref(self):
        self._start_test_api_server()
        rev = self._backend_rev()
        code, body = self._api_request("POST", "/api/settings/providers/upsert", body={
            "expected_revision": rev, "provider_id": "mut_ser",
            "default_model": "m", "api_key": "MUT_SER_KEY",
        })
        self.assertEqual(code, 200)
        self.assertNotIn("credential_ref", json.dumps(body))
        self.assertNotIn("MUT_SER_KEY", json.dumps(body))
        self.assertNotIn("api_key_env", json.dumps(body))

        rev = self._backend_rev()
        code, body = self._api_request("POST", "/api/settings/providers/mut_ser/disable", body={
            "expected_revision": rev})
        self.assertEqual(code, 200)
        self.assertNotIn("credential_ref", json.dumps(body))

        rev = self._backend_rev()
        code, body = self._api_request("POST", "/api/settings/providers/mut_ser/enable", body={
            "expected_revision": rev})
        self.assertEqual(code, 200)
        self.assertNotIn("credential_ref", json.dumps(body))

    def test_98_test_connection_response_contains_no_secrets_or_refs(self):
        self._start_test_api_server()
        with patch.object(OpenAICompatibleProviderAdapter, "generate") as mock_gen:
            mock_gen.return_value = ModelResponse(
                request_id="RQ", provider="tp", model_name="m",
                status=ModelResponseStatus.SUCCESS, content="ok")
            code, body = self._api_request("POST", "/api/settings/models/test", body={
                "provider_id": "conn_tp", "adapter_type": "OPENAI_COMPATIBLE",
                "base_url": "https://api.conn.test/v1", "model_id": "m",
                "api_key": "CONN_SECRET_KEY",
            })
        self.assertEqual(code, 200)
        serialized = json.dumps(body)
        for forbidden in ("credential_ref", "CONN_SECRET_KEY", "Authorization", "authorization", "api_key"):
            self.assertNotIn(forbidden, serialized)

    # ---- Provider field validation -----------------------------------------

    def test_99_invalid_provider_id_matrix_rejected(self):
        bad_ids = ["", "   ", "../evil", "a/b", "a\\b", "a:b", "a:b:c",
                   "has space", "ctrl\x01char", "x" * 65, ".hidden", "-lead"]
        for bad in bad_ids:
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.settings_manager.update_settings({"providers": [
                    {"provider_id": bad, "default_model": "m"}
                ]})

    def test_100_invalid_adapter_type_rejected(self):
        with self.assertRaises(ValueError):
            self.settings_manager.update_settings({"providers": [
                {"provider_id": "badadapt", "adapter_type": "MAGIC_ADAPTER", "default_model": "m"}
            ]})
        with patch.object(OpenAICompatibleProviderAdapter, "generate", lambda s, rq: None):
            pass  # no-op guard: rejection above is schema-level, pre-network

    def test_101_timeout_validation_matrix(self):
        import math
        bad_values = [float("nan"), float("inf"), float("-inf"), -1.0, 0, 601.0]
        for bad in bad_values:
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.settings_manager.update_settings({"providers": [
                    {"provider_id": "tmobad", "default_model": "m", "timeout_seconds": bad}
                ]})
        # Upper bound itself is accepted.
        self.settings_manager.update_settings({"providers": [
            {"provider_id": "tmo_ok", "default_model": "m", "timeout_seconds": 600.0}
        ]})
        self.assertEqual(
            self.settings_manager.get_settings().providers["tmo_ok"].timeout_seconds, 600.0)

    def test_102_invalid_model_id_rejected(self):
        for bad in ["", "   ", "bad\x01id", "x" * 201]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.settings_manager.update_settings({"providers": [
                    {"provider_id": "midbad", "default_model": bad}
                ]})
        # Manual custom ids remain supported.
        ok = self.settings_manager.update_settings({"providers": [
            {"provider_id": "midok", "default_model": "my-org/my-custom-model:7b"}
        ]})
        self.assertEqual(ok.providers["midok"].default_model, "my-org/my-custom-model:7b")

    def test_103_chat_completions_path_alternate_origin_rejected(self):
        for bad in ["https://evil.test/v1/chat/completions", "//evil.test/x",
                    "http://evil.test/x", "relative/path", "path\x00"]:
            with self.assertRaises(ValueError, msg=bad):
                self.settings_manager.update_settings({"providers": [
                    {"provider_id": "ccpbad", "default_model": "m",
                     "chat_completions_path": bad}
                ]})
        ok = self.settings_manager.update_settings({"providers": [
            {"provider_id": "ccpok", "default_model": "m",
             "chat_completions_path": "/api/v2/chat/completions"}
        ]})
        self.assertEqual(ok.providers["ccpok"].chat_completions_path, "/api/v2/chat/completions")

    def test_104_strict_loopback_url_security_matrix(self):
        allowed = [
            "https://example.com",
            "https://api.example.com/v1",
            "http://127.0.0.1:8000/v1",
            "http://localhost:11434/v1",
            "http://[::1]:8000/v1",
        ]
        for url in allowed:
            self.assertIsNotNone(validate_base_url(url), url)

        rejected = [
            "http://example.com",
            "http://127.0.0.2",
            "http://0.0.0.0",
            "http://[::]",
            "file:///etc/passwd",
            "ftp://server.com/api",
            "data:text/html,hi",
            "javascript:alert(1)",
            "https://user:pass@example.com/v1",
            "//example.com/v1",
            "http://[::1:broken]:8000",
            "http://exa%6Dple.com",
            "https://exa mple.com",
        ]
        for url in rejected:
            with self.assertRaises(ValueError, msg=url):
                validate_base_url(url)

    def test_105_diagnostics_match_committed_settings_authority(self):
        self._start_test_api_server()
        rev = self._backend_rev()
        try:
            code, _ = self._api_request("POST", "/api/settings/providers/upsert", body={
                "expected_revision": rev, "provider_id": "diag_prov",
                "adapter_type": "OPENAI_COMPATIBLE",
                "base_url": "https://api.diag.test/v1",
                "default_model": "diag-model-v9",
                "timeout_seconds": 123.0,
                "api_key": "DIAG_KEY",
            })
            self.assertEqual(code, 200)
            rev = self._backend_rev()
            code, _ = self._api_request("POST", "/api/settings/providers/diag_prov/disable", body={
                "expected_revision": rev})
            self.assertEqual(code, 200)

            code, report = self._api_request("GET", "/api/system/providers/health")
            self.assertEqual(code, 200)
            entry = next(p for p in report if p["provider"] == "diag_prov")
            self.assertFalse(entry["enabled"])
            self.assertEqual(entry["model"], "diag-model-v9")
            self.assertEqual(entry["timeout_seconds"], 123.0)
            self.assertTrue(entry["credential_present"])
        finally:
            try:
                rev = self._backend_rev()
                self._api_request("POST", "/api/settings/providers/diag_prov/delete", body={
                    "expected_revision": rev})
            except Exception:
                pass

    def test_106_paid_primary_free_tier_fallback_executes_fallback(self):
        """Certified fallback semantics: policy-blocked PAID primary falls through
        to an allowed FREE_TIER_ALLOWED fallback which actually executes."""
        full_content = json.dumps({"strategic_directives": "D"})
        received: List[Dict[str, Any]] = []
        resp = (200, {"id": "c", "choices": [{"message": {"role": "assistant", "content": full_content}}],
                      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        server = MockOpenAIHttpServer(("127.0.0.1", 0), MockOpenAIHandler, received, [resp])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/v1"
            store = SecureSecretStore(vault_path=Path(self.test_dir) / "fb.vault")
            registry = ProviderRegistry(secret_store=store)
            gateway = UniversalModelGateway(provider_registry=registry, free_only_mode=True)
            manager = ModelSettingsManager(settings_file_path=Path(self.test_dir) / "fb.json",
                                           secret_store=store, provider_registry=registry, gateway=gateway)
            manager.upsert_provider({"provider_id": "paidp", "adapter_type": "OPENAI_COMPATIBLE",
                                     "base_url": url, "default_model": "m-paid",
                                     "cost_policy": "PAID"}, secret="K1")
            manager.upsert_provider({"provider_id": "freep", "adapter_type": "OPENAI_COMPATIBLE",
                                     "base_url": url, "default_model": "m-free",
                                     "cost_policy": "FREE_TIER_ALLOWED"}, secret="K2")
            manager.update_settings({"fallback_chain": []})
            manager.update_settings({"global_target": {"provider_id": "paidp", "model_id": "m-paid"}})
            manager.update_settings({"fallback_chain": [
                {"provider_id": "freep", "model_id": "m-free"},
            ]})
            snap = registry.snapshot().model_dump()
            pol = gateway.model_policy.model_dump()

            r = self._pin_generate(gateway, registry, snap, pol, "FB-1", "m-paid")
            self.assertEqual(r.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(len(received), 1)
            self.assertEqual(r.metadata.get("resolved_provider"), "freep")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2.0)

    def test_107_all_candidates_policy_blocked_means_no_execution(self):
        """If EVERY candidate violates cost policy, the final result must be a
        policy violation and NO model execution may occur."""
        store = SecureSecretStore(vault_path=Path(self.test_dir) / "allblock.vault")
        registry = ProviderRegistry(secret_store=store)
        gateway = UniversalModelGateway(provider_registry=registry, free_only_mode=True)
        manager = ModelSettingsManager(settings_file_path=Path(self.test_dir) / "allblock.json",
                                       secret_store=store, provider_registry=registry, gateway=gateway)
        manager.upsert_provider({"provider_id": "paidone", "adapter_type": "OPENAI_COMPATIBLE",
                                 "base_url": "https://api.p1.test/v1", "default_model": "m1",
                                 "cost_policy": "PAID"}, secret="K1")
        manager.upsert_provider({"provider_id": "unknownp", "adapter_type": "OPENAI_COMPATIBLE",
                                 "base_url": "https://api.u1.test/v1", "default_model": "m2",
                                 "cost_policy": "UNKNOWN"}, secret="K2")
        manager.update_settings({"fallback_chain": []})
        manager.update_settings({"global_target": {"provider_id": "paidone", "model_id": "m1"}})
        manager.update_settings({"fallback_chain": [{"provider_id": "unknownp", "model_id": "m2"}]})
        snap = registry.snapshot().model_dump()
        pol = gateway.model_policy.model_dump()

        executed = {"n": 0}

        def no_exec(self_adapter, request):
            executed["n"] += 1
            raise AssertionError("No candidate may execute when all are policy-blocked")

        with patch.object(OpenAICompatibleProviderAdapter, "generate", no_exec):
            r = self._pin_generate(gateway, registry, snap, pol, "AB-1", "m1")
        self.assertEqual(r.status, ModelResponseStatus.ERROR)
        self.assertIn("FREE_ONLY_POLICY_VIOLATION", str(r.error))
        self.assertEqual(executed["n"], 0)


    # =========================================================================
    # 18. FRONTEND/SETTINGS CONTRACT (PROD-MODEL-SETTINGS-01R4B)
    # =========================================================================

    def test_108_settings_rejects_custom_injected_persistence(self):
        """CUSTOM_INJECTED is an internal DI harness type; Model Settings must
        refuse to persist it as a user-configurable provider."""
        with self.assertRaises(ModelSettingsValidationError) as ctx:
            self.settings_manager.update_settings({"providers": [
                {"provider_id": "sneaky_di", "adapter_type": "CUSTOM_INJECTED",
                 "default_model": "m"},
            ]})
        self.assertIn("INVALID_ADAPTER_TYPE", str(ctx.exception))
        self.assertIn("CUSTOM_INJECTED", str(ctx.exception))
        # Unknown types remain rejected too.
        with self.assertRaises(ValueError):
            self.settings_manager.update_settings({"providers": [
                {"provider_id": "unknown_ad", "adapter_type": "WARP_DRIVE", "default_model": "m"},
            ]})

    def test_109_direct_registry_custom_injected_di_remains_functional(self):
        """Internal DI capability is untouched: register_custom_adapter still
        works at the Registry level for deterministic harnesses."""
        mock = MagicMock()
        mock.provider_name = "di_harness"
        mock.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock.generate.return_value = ModelResponse(
            request_id="REQ-DI", provider="di_harness", model_name="m-di",
            status=ModelResponseStatus.SUCCESS, content='{"strategic_directives": "D"}')
        self.registry.register_custom_adapter(mock)
        adapter = self.registry.get_adapter("di_harness")
        self.assertIs(adapter, mock)
        self.assertEqual(self.registry.get_provider("di_harness").adapter_type, "CUSTOM_INJECTED")

    def test_110_mutation_responses_include_new_safe_settings_revision(self):
        """upsert / enable / disable / POST delete responses each carry the NEW
        authoritative settings_revision so clients can adopt it without a refetch."""
        self._start_test_api_server()
        rev = self._backend_rev()
        code, body = self._api_request("POST", "/api/settings/providers/upsert", body={
            "expected_revision": rev, "provider_id": "revecho", "default_model": "m",
        })
        self.assertEqual(code, 200)
        self.assertEqual(body["settings_revision"], rev + 1)

        code, body = self._api_request("POST", "/api/settings/providers/revecho/disable", body={
            "expected_revision": body["settings_revision"]})
        self.assertEqual(code, 200)
        self.assertEqual(body["settings_revision"], rev + 2)

        code, body = self._api_request("POST", "/api/settings/providers/revecho/enable", body={
            "expected_revision": body["settings_revision"]})
        self.assertEqual(code, 200)
        self.assertEqual(body["settings_revision"], rev + 3)

        code, body = self._api_request("POST", "/api/settings/providers/revecho/delete", body={
            "expected_revision": body["settings_revision"]})
        self.assertEqual(code, 200)
        self.assertEqual(body["settings_revision"], rev + 4)

        # DELETE route variant echoes the revision as well.
        rev = self._backend_rev()
        self._seed_backend_provider("revecho2")
        code, body = self._api_request(
            "DELETE", f"/api/settings/providers/revecho2?expected_revision={self._backend_rev()}")
        self.assertEqual(code, 200)
        self.assertIn("settings_revision", body)

    def test_111_settings_get_and_mutation_responses_still_contain_no_credential_ref(self):
        """Serialization boundary holds after the revision-contract additions."""
        self._start_test_api_server()
        rev = self._backend_rev()
        code, body = self._api_request("POST", "/api/settings/providers/upsert", body={
            "expected_revision": rev, "provider_id": "sercheck",
            "default_model": "m", "api_key": "FINAL_SER_KEY",
        })
        self.assertEqual(code, 200)
        serialized = json.dumps(body)
        self.assertNotIn("credential_ref", serialized)
        self.assertNotIn("FINAL_SER_KEY", serialized)

        code, get_body = self._api_request("GET", "/api/settings/model")
        self.assertEqual(code, 200)
        self.assertNotIn("credential_ref", json.dumps(get_body))


if __name__ == "__main__":
    unittest.main()
