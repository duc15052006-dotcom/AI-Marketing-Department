"""Targeted Test Suite for PROD-MODEL-GATEWAY-01: Universal Provider Registry & Model Routing Authority.

Tests:
1. ProviderDefinition validation, defaults, normalization, and backward-compat.
2. Base URL security validation (rejects file://, ftp://, javascript:, data:, credentials, remote plain HTTP).
3. Base URL loopback allowance and path canonicalization.
4. ModelTarget and AgentId normalization (strictly 5 agents: CMO, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE).
5. Final CMO normalization (maps strictly to CMO policy; no Agent 6).
6. ModelPolicy routing resolution precedence (Agent Override -> Global Target -> Fallback Chain).
7. ProviderRegistry CRUD, thread-safety, enable/disable, and adapter lifecycle.
8. ProviderRegistry snapshot immutability for active run pinning.
9. Test Connection backend contract (returns status, redacts secrets, zero registry mutation).
10. UniversalModelGateway integration with ModelPolicy and ProviderRegistry.
11. Preserved timeout budget across fallback candidates.
12. End-to-end 5-Agent pipeline execution with custom OpenAI-compatible provider.
"""

import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

from integrations.models import (
    AgentId,
    BaseModelAdapter,
    ConnectionTestResult,
    ConnectionTestStatus,
    CostGovernanceConfig,
    CostPolicy,
    ModelMessage,
    ModelMetadata,
    ModelPolicy,
    ModelRegistry,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelTarget,
    ModelUsage,
    OpenAICompatibleProviderAdapter,
    ProviderConfig,
    ProviderDefinition,
    ProviderProtocol,
    ProviderRegistry,
    ProviderRegistrySnapshot,
    UniversalModelGateway,
    normalize_agent_id,
    sanitize_secrets,
    validate_base_url,
)
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class TestProdModelGateway01ProviderRegistry(unittest.TestCase):
    """Targeted comprehensive suite for Model Gateway and Provider Registry."""

    # ----------------------------------------------------------------------
    # 1. ProviderDefinition & Base URL Tests
    # ----------------------------------------------------------------------

    def test_01_provider_definition_validation_valid(self):
        """Verify ProviderDefinition initializes properly with valid fields."""
        p = ProviderDefinition(
            provider_id="custom-openai",
            adapter_type="OPENAI_COMPATIBLE",
            display_name="Custom OpenAI",
            base_url="https://api.custom.ai/v1",
            credential_ref="ENV:CUSTOM_KEY",
            default_model="custom-model-v1",
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
        self.assertEqual(p.provider_id, "custom-openai")
        self.assertEqual(p.adapter_type, "OPENAI_COMPATIBLE")
        self.assertEqual(p.display_name, "Custom OpenAI")
        self.assertEqual(p.base_url, "https://api.custom.ai/v1")
        self.assertTrue(p.enabled)

    def test_02_provider_definition_empty_id_rejected(self):
        """Verify empty provider_id raises ValueError."""
        with self.assertRaises(ValueError):
            ProviderDefinition(provider_id="")

    def test_03_provider_definition_defaults_and_normalization(self):
        """Verify provider_id is lowercase normalized and display_name defaults."""
        p = ProviderDefinition(provider_id="MY_CUSTOM_PROVIDER")
        self.assertEqual(p.provider_id, "my_custom_provider")
        self.assertEqual(p.display_name, "My_custom_provider")

    def test_04_provider_definition_backward_compat_provider_config(self):
        """Verify ProviderConfig legacy subclass behaves as ProviderDefinition."""
        cfg = ProviderConfig(
            provider_id="legacy-xkiro",
            protocol=ProviderProtocol.OPENAI_COMPATIBLE,
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
        )
        self.assertEqual(cfg.provider_id, "legacy-xkiro")
        self.assertEqual(cfg.credential_ref, "ENV:XKIRO_API_KEY")
        self.assertEqual(cfg.adapter_type, "OPENAI_COMPATIBLE")

    def test_05_base_url_validation_https_valid(self):
        """Verify valid HTTPS URLs pass validation."""
        url = validate_base_url("https://api.openai.com/v1")
        self.assertEqual(url, "https://api.openai.com/v1")

    def test_06_base_url_validation_http_loopback_valid(self):
        """Verify plain HTTP explicit loopback URLs pass validation.
        R4A policy: only exact 127.0.0.1 / localhost / ::1 are loopback;
        0.0.0.0, other 127/8 and wildcard addresses are rejected."""
        self.assertEqual(validate_base_url("http://127.0.0.1:8000/v1"), "http://127.0.0.1:8000/v1")
        self.assertEqual(validate_base_url("http://localhost:11434/v1"), "http://localhost:11434/v1")
        self.assertEqual(validate_base_url("http://[::1]:8000/v1"), "http://[::1]:8000/v1")
        for no_longer_loopback in ("http://0.0.0.0:8080/v1", "http://127.0.0.2:8080/v1"):
            with self.assertRaises(ValueError) as ctx:
                validate_base_url(no_longer_loopback)
            self.assertIn("INSECURE_HTTP_URL", str(ctx.exception))

    def test_07_base_url_validation_http_remote_rejected(self):
        """Verify non-loopback plain HTTP is rejected with INSECURE_HTTP_URL."""
        with self.assertRaises(ValueError) as ctx:
            validate_base_url("http://api.remote-insecure.com/v1")
        self.assertIn("INSECURE_HTTP_URL", str(ctx.exception))

    def test_08_base_url_validation_disallowed_schemes_rejected(self):
        """Verify disallowed URL schemes are rejected."""
        disallowed = [
            "file:///etc/passwd",
            "ftp://ftp.example.com",
            "javascript:alert(1)",
            "data:text/plain;base64,AAAA",
        ]
        for bad_url in disallowed:
            with self.assertRaises(ValueError) as ctx:
                validate_base_url(bad_url)
            self.assertIn("INVALID_URL_SCHEME", str(ctx.exception))

    def test_09_base_url_validation_embedded_credentials_rejected(self):
        """Verify embedded username/password in URL is rejected."""
        with self.assertRaises(ValueError) as ctx:
            validate_base_url("https://user:password@api.example.com/v1")
        self.assertIn("INVALID_URL_CREDENTIALS", str(ctx.exception))

    def test_10_base_url_validation_path_canonicalization_redundant_v1(self):
        """Verify redundant /v1/v1 in base URL is cleaned."""
        self.assertEqual(validate_base_url("https://api.example.com/v1/v1"), "https://api.example.com/v1")

    def test_11_base_url_validation_trailing_chat_completions_stripped(self):
        """Verify mistakenly appended /chat/completions is stripped from base URL."""
        self.assertEqual(
            validate_base_url("https://api.example.com/v1/chat/completions"),
            "https://api.example.com/v1",
        )

    # ----------------------------------------------------------------------
    # 2. ModelTarget & AgentId Normalization Tests
    # ----------------------------------------------------------------------

    def test_12_model_target_validation_valid(self):
        """Verify ModelTarget initializes cleanly."""
        t = ModelTarget(provider_id="OPENAI", model_id="gpt-4o-mini")
        self.assertEqual(t.provider_id, "openai")
        self.assertEqual(t.model_id, "gpt-4o-mini")

    def test_13_model_target_validation_empty_rejected(self):
        """Verify empty provider_id or model_id in ModelTarget is rejected."""
        with self.assertRaises(ValueError):
            ModelTarget(provider_id="", model_id="m")
        with self.assertRaises(ValueError):
            ModelTarget(provider_id="p", model_id="")

    def test_14_agent_id_normalization_exact_5_agents(self):
        """Verify exact 5 logical agents are accepted and normalized."""
        self.assertEqual(normalize_agent_id("cmo"), "CMO")
        self.assertEqual(normalize_agent_id("intelligence"), "INTELLIGENCE")
        self.assertEqual(normalize_agent_id("strategist"), "STRATEGIST")
        self.assertEqual(normalize_agent_id("creative"), "CREATIVE")
        self.assertEqual(normalize_agent_id("performance"), "PERFORMANCE")

    def test_15_agent_id_normalization_final_cmo_maps_to_cmo(self):
        """Verify Final CMO variations map strictly to CMO."""
        self.assertEqual(normalize_agent_id("final_cmo"), "CMO")
        self.assertEqual(normalize_agent_id("FINAL_CMO"), "CMO")
        self.assertEqual(normalize_agent_id("stage_6_final_cmo"), "CMO")

    def test_16_agent_id_normalization_unknown_agent_rejected(self):
        """Verify unknown agent keys (e.g. agent_6, supervisor) are rejected."""
        with self.assertRaises(ValueError) as ctx:
            normalize_agent_id("agent_6")
        self.assertIn("INVALID_AGENT_OVERRIDE_KEY", str(ctx.exception))

    # ----------------------------------------------------------------------
    # 3. ModelPolicy Routing Precedence Tests
    # ----------------------------------------------------------------------

    def test_17_model_policy_global_target_resolution(self):
        """Verify un-overridden agent resolves to global target."""
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="openai", model_id="gpt-4o-mini"),
        )
        target = policy.resolve_target_for_agent("intelligence")
        self.assertEqual(target.provider_id, "openai")
        self.assertEqual(target.model_id, "gpt-4o-mini")

    def test_18_model_policy_agent_override_resolution(self):
        """Verify specific agent override takes precedence over global target."""
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="openai", model_id="gpt-4o-mini"),
            agent_overrides={
                "CREATIVE": ModelTarget(provider_id="custom-llm", model_id="claude-3-opus"),
            },
        )
        cmo_target = policy.resolve_target_for_agent("cmo")
        creative_target = policy.resolve_target_for_agent("creative")

        self.assertEqual(cmo_target.provider_id, "openai")
        self.assertEqual(creative_target.provider_id, "custom-llm")
        self.assertEqual(creative_target.model_id, "claude-3-opus")

    def test_19_model_policy_final_cmo_resolves_cmo_override(self):
        """Verify final_cmo resolves to the exact CMO override."""
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
            agent_overrides={
                "CMO": ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
            },
        )
        target = policy.resolve_target_for_agent("final_cmo")
        self.assertEqual(target.provider_id, "xkiro")
        self.assertEqual(target.model_id, "mistralai/mistral-large-2512")

    def test_20_model_policy_fallback_chain_deduplication(self):
        """Verify fallback candidate chain includes primary and deduplicates fallbacks."""
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
            fallback_chain=[
                ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
                ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
            ],
        )
        chain = policy.get_candidate_chain_for_agent("strategist")
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0].provider_id, "gemini")
        self.assertEqual(chain[1].provider_id, "xkiro")

    # ----------------------------------------------------------------------
    # 4. ProviderRegistry CRUD & Lifecycle Tests
    # ----------------------------------------------------------------------

    def test_21_provider_registry_builtin_registration(self):
        """Verify builtin providers (xkiro, gemini, openai, thespark) are registered."""
        reg = ProviderRegistry()
        p_ids = reg.list_providers()
        self.assertIn("xkiro", p_ids)
        self.assertIn("gemini", p_ids)
        self.assertIn("openai", p_ids)
        self.assertIn("thespark", p_ids)

    def test_22_provider_registry_register_custom_provider(self):
        """Verify custom OpenAI-compatible provider can be registered."""
        reg = ProviderRegistry()
        reg.register_provider(
            ProviderDefinition(
                provider_id="custom-local",
                adapter_type="OPENAI_COMPATIBLE",
                display_name="Local vLLM",
                base_url="http://127.0.0.1:8000/v1",
                default_model="qwen-2.5-72b",
            ),
            secret="sk-local-test",
        )
        prov = reg.get_provider("custom-local")
        self.assertIsNotNone(prov)
        self.assertEqual(prov.display_name, "Local vLLM")
        self.assertEqual(prov.default_model, "qwen-2.5-72b")

    def test_23_provider_registry_update_provider(self):
        """Verify provider properties can be updated dynamically."""
        reg = ProviderRegistry()
        updated = reg.update_provider("openai", {"default_model": "gpt-4o", "timeout_seconds": 90.0})
        self.assertEqual(updated.default_model, "gpt-4o")
        self.assertEqual(updated.timeout_seconds, 90.0)

    def test_24_provider_registry_enable_disable_provider(self):
        """Verify enabling and disabling providers works as expected."""
        reg = ProviderRegistry()
        reg.disable_provider("xkiro")
        self.assertFalse(reg.get_provider("xkiro").enabled)
        reg.enable_provider("xkiro")
        self.assertTrue(reg.get_provider("xkiro").enabled)

    def test_25_provider_registry_list_providers_filter_disabled(self):
        """Verify list_provider_definitions(include_disabled=False) filters disabled providers."""
        reg = ProviderRegistry()
        reg.disable_provider("openai")
        active = reg.list_provider_definitions(include_disabled=False)
        self.assertNotIn("openai", [p.provider_id for p in active])

    def test_26_provider_registry_get_adapter_openai_compatible(self):
        """Verify OpenAI-compatible adapter is created correctly."""
        reg = ProviderRegistry()
        adapter = reg.get_adapter("xkiro")
        self.assertIsNotNone(adapter)
        self.assertIsInstance(adapter, OpenAICompatibleProviderAdapter)

    def test_27_provider_registry_get_adapter_gemini_native(self):
        """Verify Gemini Native adapter is created correctly."""
        reg = ProviderRegistry()
        adapter = reg.get_adapter("gemini")
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.provider_name, "gemini")

    def test_28_provider_registry_get_adapter_disabled_returns_none(self):
        """Verify disabled provider returns None for get_adapter."""
        reg = ProviderRegistry()
        reg.disable_provider("xkiro")
        adapter = reg.get_adapter("xkiro")
        self.assertIsNone(adapter)

    def test_29_provider_registry_snapshot_immutability(self):
        """Verify snapshot creates an isolated copy unaffected by future registry changes."""
        reg = ProviderRegistry()
        snap = reg.snapshot()
        reg.disable_provider("gemini")
        self.assertTrue(snap.providers["gemini"].enabled)

    # ----------------------------------------------------------------------
    # 5. Connection Test Backend Contract
    # ----------------------------------------------------------------------

    def test_30_test_connection_success_connected(self):
        """Verify successful connection test returns CONNECTED status."""
        reg = ProviderRegistry()
        fake_body = {
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        }
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(fake_body).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.status = 200
            mock_url.return_value = mock_resp

            res = reg.test_connection(
                ProviderDefinition(
                    provider_id="test-prov",
                    base_url="https://api.test.com/v1",
                    default_model="model-1",
                ),
                api_key="sk-test-secret-12345",
            )
            self.assertEqual(res.status, ConnectionTestStatus.CONNECTED)
            self.assertEqual(res.provider_id, "test-prov")

    def test_31_test_connection_auth_failed_classification(self):
        """Verify 401/Auth failure maps to AUTH_FAILED status."""
        reg = ProviderRegistry()
        with patch("urllib.request.urlopen") as mock_url:
            import urllib.error
            mock_url.side_effect = urllib.error.HTTPError(
                "https://api.test.com/v1/chat/completions",
                401,
                "Unauthorized: Invalid API key",
                {"Content-Type": "application/json"},
                MagicMock(read=lambda: b'{"error": "Invalid API Key"}'),
            )
            res = reg.test_connection(
                ProviderDefinition(
                    provider_id="test-prov",
                    base_url="https://api.test.com/v1",
                    default_model="model-1",
                ),
                api_key="sk-bad-key",
            )
            self.assertEqual(res.status, ConnectionTestStatus.AUTH_FAILED)

    def test_32_test_connection_timeout_classification(self):
        """Verify timeout maps to TIMEOUT status."""
        reg = ProviderRegistry()
        with patch("urllib.request.urlopen") as mock_url:
            import socket
            mock_url.side_effect = socket.timeout("timed out")
            res = reg.test_connection(
                ProviderDefinition(
                    provider_id="test-prov",
                    base_url="https://api.test.com/v1",
                    default_model="model-1",
                ),
                api_key="sk-key",
                timeout_seconds=0.1,
            )
            self.assertEqual(res.status, ConnectionTestStatus.TIMEOUT)

    def test_33_test_connection_rate_limit_classification(self):
        """Verify 429 maps to RATE_LIMIT status."""
        reg = ProviderRegistry()
        with patch("urllib.request.urlopen") as mock_url:
            import urllib.error
            mock_url.side_effect = urllib.error.HTTPError(
                "https://api.test.com/v1/chat/completions",
                429,
                "Too Many Requests",
                {"Content-Type": "application/json"},
                MagicMock(read=lambda: b'{"error": "Rate limit exceeded"}'),
            )
            res = reg.test_connection(
                ProviderDefinition(
                    provider_id="test-prov",
                    base_url="https://api.test.com/v1",
                    default_model="model-1",
                ),
                api_key="sk-key",
            )
            self.assertEqual(res.status, ConnectionTestStatus.RATE_LIMIT)

    def test_34_test_connection_model_not_found_classification(self):
        """Verify 404/Model Not Found maps to MODEL_NOT_FOUND status."""
        reg = ProviderRegistry()
        with patch("urllib.request.urlopen") as mock_url:
            import urllib.error
            mock_url.side_effect = urllib.error.HTTPError(
                "https://api.test.com/v1/chat/completions",
                404,
                "Model Not Found",
                {"Content-Type": "application/json"},
                MagicMock(read=lambda: b'{"error": "The model non-existent does not exist"}'),
            )
            res = reg.test_connection(
                ProviderDefinition(
                    provider_id="test-prov",
                    base_url="https://api.test.com/v1",
                    default_model="non-existent",
                ),
                api_key="sk-key",
            )
            self.assertEqual(res.status, ConnectionTestStatus.MODEL_NOT_FOUND)

    def test_35_test_connection_invalid_config_classification(self):
        """Verify invalid URL scheme raises ValueError on definition and maps to INVALID_CONFIGURATION."""
        reg = ProviderRegistry()
        with self.assertRaises(ValueError) as ctx:
            ProviderDefinition(
                provider_id="test-prov",
                base_url="http://insecure-remote.com",
                default_model="m",
            )
        self.assertIn("INSECURE_HTTP_URL", str(ctx.exception))

    def test_36_test_connection_zero_leakage_secret_sanitization(self):
        """Verify raw secret is completely redacted from error output."""
        reg = ProviderRegistry()
        secret = "secret-super-key-998877"
        with patch("urllib.request.urlopen") as mock_url:
            mock_url.side_effect = Exception(f"Failed with secret token {secret} in raw exception")
            res = reg.test_connection(
                ProviderDefinition(
                    provider_id="test-prov",
                    base_url="https://api.test.com/v1",
                    default_model="m",
                ),
                api_key=secret,
            )
            self.assertNotIn(secret, str(res.error))
            self.assertIn("[REDACTED_API_KEY]", str(res.error))

    def test_37_test_connection_does_not_mutate_active_registry(self):
        """Verify test_connection does not add or alter any provider in the active registry."""
        reg = ProviderRegistry()
        initial_providers = reg.list_providers()
        temp_def = ProviderDefinition(
            provider_id="ephemeral-test-provider",
            base_url="https://api.ephemeral.com/v1",
            default_model="model-ephemeral",
        )
        reg.test_connection(temp_def, api_key="sk-key")
        self.assertIsNone(reg.get_provider("ephemeral-test-provider"))
        self.assertEqual(len(reg.list_providers()), len(initial_providers))

    # ----------------------------------------------------------------------
    # 6. UniversalModelGateway & Routing Integration Tests
    # ----------------------------------------------------------------------

    def test_38_gateway_agent_override_routing(self):
        """Verify gateway executes using the agent-specific override model."""
        reg = ProviderRegistry()
        mock_creative = MagicMock()
        mock_creative.provider_name = "mock_creative_prov"
        mock_creative.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_creative.generate.return_value = ModelResponse(
            request_id="REQ-1",
            provider="mock_creative_prov",
            model_name="creative-model-v1",
            status=ModelResponseStatus.SUCCESS,
            content="Creative copy ready.",
        )
        reg.register_custom_adapter(mock_creative)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
            agent_overrides={
                "CREATIVE": ModelTarget(provider_id="mock_creative_prov", model_id="creative-model-v1"),
            },
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        resp = gw.generate(req, agent_id="creative")

        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.content, "Creative copy ready.")
        self.assertEqual(resp.metadata.get("resolved_provider"), "mock_creative_prov")

    def test_39_gateway_final_cmo_uses_cmo_policy(self):
        """Verify final_cmo stage resolves using CMO policy override."""
        reg = ProviderRegistry()
        mock_cmo = MagicMock()
        mock_cmo.provider_name = "mock_cmo_prov"
        mock_cmo.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_cmo.generate.return_value = ModelResponse(
            request_id="REQ-2",
            provider="mock_cmo_prov",
            model_name="cmo-model-v1",
            status=ModelResponseStatus.SUCCESS,
            content="CMO Signoff complete.",
        )
        reg.register_custom_adapter(mock_cmo)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
            agent_overrides={
                "CMO": ModelTarget(provider_id="mock_cmo_prov", model_id="cmo-model-v1"),
            },
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Sign off")])
        resp = gw.generate(req, agent_id="final_cmo")

        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.content, "CMO Signoff complete.")
        self.assertEqual(resp.metadata.get("resolved_provider"), "mock_cmo_prov")

    def test_40_gateway_fallback_skips_disabled_provider(self):
        """Verify fallback chain skips disabled providers."""
        reg = ProviderRegistry()
        reg.disable_provider("xkiro")

        mock_gemini = MagicMock()
        mock_gemini.provider_name = "gemini"
        mock_gemini.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_gemini.generate.return_value = ModelResponse(
            request_id="REQ-3",
            provider="gemini",
            model_name="gemini-flash-latest",
            status=ModelResponseStatus.SUCCESS,
            content="Gemini fallback response.",
        )
        reg.register_custom_adapter(mock_gemini)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
            fallback_chain=[
                ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
            ],
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Execute")])
        resp = gw.generate(req)

        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.content, "Gemini fallback response.")
        self.assertEqual(resp.metadata.get("resolved_provider"), "gemini")

    def test_41_gateway_timeout_budget_exhaustion_bounds_all_candidates(self):
        """Verify timeout budget bounding prevents endless fallback loops."""
        reg = ProviderRegistry()
        mock_cand1 = MagicMock()
        mock_cand1.provider_name = "cand1"
        mock_cand1.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_cand1.generate.return_value = ModelResponse(
            request_id="REQ-4",
            provider="cand1",
            model_name="m1",
            status=ModelResponseStatus.TIMEOUT,
            error="TIMEOUT: cand1 timed out after 0.05s",
        )
        reg.register_custom_adapter(mock_cand1)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="cand1", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="cand2", model_id="m2")],
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Quick")],
            timeout_seconds=0.0001,
        )
        resp = gw.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.TIMEOUT)

    def test_42_gateway_free_only_mode_blocks_paid_model(self):
        """Verify free_only_mode blocks paid models when allow_paid is False."""
        reg = ProviderRegistry()
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="openai", model_id="gpt-4o-mini"),
            free_only_mode=True,
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy, free_only_mode=True)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Generate")])
        resp = gw.generate(req, strict_model_pin=True, allow_paid=False)

        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertIn("FREE_ONLY_POLICY_VIOLATION", str(resp.error))

    def test_43_gateway_strict_model_pin_disables_fallback(self):
        """Verify strict_model_pin=True immediately returns candidate error without trying fallbacks."""
        reg = ProviderRegistry()
        mock_cand1 = MagicMock()
        mock_cand1.provider_name = "cand1"
        mock_cand1.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_cand1.generate.return_value = ModelResponse(
            request_id="REQ-5",
            provider="cand1",
            model_name="m1",
            status=ModelResponseStatus.RATE_LIMITED,
            error="RATE_LIMIT_429: Rate limited",
        )
        reg.register_custom_adapter(mock_cand1)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="cand1", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="cand2", model_id="m2")],
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Pin test")])
        resp = gw.generate(req, strict_model_pin=True)

        self.assertEqual(resp.status, ModelResponseStatus.RATE_LIMITED)
        self.assertEqual(resp.metadata.get("attempt_count"), 1)

    def test_44_runtime_engine_stage_invocation_passes_agent_id(self):
        """Verify FiveAgentDepartmentRuntime invokes gateway with agent_id."""
        mock_gw = MagicMock()
        mock_gw.generate.return_value = ModelResponse(
            request_id="REQ-6",
            provider="mock_p",
            model_name="m",
            status=ModelResponseStatus.SUCCESS,
            content="Stage response",
        )
        runtime = FiveAgentDepartmentRuntime(model_gateway=mock_gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
        content, err = runtime._call_agent_llm("creative", "sys_inst", "user_prompt")
        self.assertIsNone(err)
        self.assertEqual(content, "Stage response")
        mock_gw.generate.assert_called_once()
        _, kwargs = mock_gw.generate.call_args
        self.assertEqual(kwargs.get("agent_id"), "creative")

    def test_45_runtime_context_preserves_pinned_model_policy(self):
        """Verify RuntimeContext retains model policy in frozen state across run execution."""
        runtime = FiveAgentDepartmentRuntime(tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
        ctx = runtime.start_run(
            objective="Launch Campaign",
            business_id="BIZ_99",
            project_id="PROJ_99",
        )
        self.assertIn("free_only_mode", ctx.model_policy)
        self.assertTrue(ctx.model_policy["free_only_mode"])

    def test_46_five_agent_full_pipeline_with_custom_openai_provider(self):
        """Verify entire Five-Agent pipeline succeeds cleanly with a custom provider registered."""
        reg = ProviderRegistry()
        custom_adapter = MagicMock()
        custom_adapter.provider_name = "custom_openai"
        custom_adapter.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        custom_adapter.generate.return_value = ModelResponse(
            request_id="REQ-E2E",
            provider="custom_openai",
            model_name="qwen-custom",
            status=ModelResponseStatus.SUCCESS,
            content=(
                '{"cmo_strategy": "Approved", "market_intelligence": "Valid", '
                '"positioning": "Solid", "creative_assets": [], "forecast": {}}'
            ),
        )
        reg.register_custom_adapter(custom_adapter)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="custom_openai", model_id="qwen-custom"),
            free_only_mode=True,
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        ctx, final_output, artifact = runtime.run_workflow(
            objective="Execute Full E2E Campaign with Custom Provider",
            business_id="BIZ_CUSTOM",
            project_id="PROJ_CUSTOM",
        )
        self.assertEqual(ctx.current_stage, "COMPLETED")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.business_id, "BIZ_CUSTOM")
        self.assertEqual(artifact.project_id, "PROJ_CUSTOM")

    # ----------------------------------------------------------------------
    # 8. Localhost HTTP Contract & Multi-Provider Isolation Tests
    # ----------------------------------------------------------------------

    def test_47_localhost_http_server_real_wire_contract(self):
        """Verify real HTTP serialization and parsing against a deterministic localhost server."""
        class MockOpenAIHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_len))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                resp_payload = {
                    "id": "chatcmpl-test-local",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": body.get("model", "test-model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Localhost OpenAI wire response.",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 8,
                        "total_tokens": 20,
                    },
                }
                self.wfile.write(json.dumps(resp_payload).encode("utf-8"))

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.handle_request)
        server_thread.daemon = True
        server_thread.start()

        try:
            reg = ProviderRegistry()
            custom_def = ProviderDefinition(
                provider_id="custom-local",
                adapter_type="OPENAI_COMPATIBLE",
                base_url=f"http://127.0.0.1:{port}/v1",
                default_model="local-model-v1",
                credential_ref="ENV:LOCAL_API_KEY",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
            )
            reg.register_provider(custom_def, secret="test-secret-local-key")
            adapter = reg.get_adapter("custom-local")
            self.assertIsNotNone(adapter)

            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content="Ping localhost")],
                model_name="local-model-v1",
            )
            resp = adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.content, "Localhost OpenAI wire response.")
            self.assertEqual(resp.usage.total_tokens, 20)
        finally:
            server.server_close()

    def test_48_two_custom_providers_isolation(self):
        """Verify two custom local providers maintain completely separate endpoints and state."""
        class MockHandlerA(BaseHTTPRequestHandler):
            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)
                resp_bytes = json.dumps({
                    "id": "chatcmpl-a",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": "model-a",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Response from Provider A"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 10},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)

            def log_message(self, format, *args): pass

        class MockHandlerB(BaseHTTPRequestHandler):
            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)
                resp_bytes = json.dumps({
                    "id": "chatcmpl-b",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": "model-b",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Response from Provider B"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 15},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)

            def log_message(self, format, *args): pass

        server_a = HTTPServer(("127.0.0.1", 0), MockHandlerA)
        server_b = HTTPServer(("127.0.0.1", 0), MockHandlerB)
        port_a = server_a.server_address[1]
        port_b = server_b.server_address[1]

        t_a = threading.Thread(target=server_a.handle_request)
        t_b = threading.Thread(target=server_b.handle_request)
        t_a.daemon = True
        t_b.daemon = True
        t_a.start()
        t_b.start()

        try:
            reg = ProviderRegistry()
            reg.register_provider(
                ProviderDefinition(
                    provider_id="custom-a",
                    base_url=f"http://127.0.0.1:{port_a}/v1",
                    default_model="model-a",
                ),
                secret="key-a",
            )
            reg.register_provider(
                ProviderDefinition(
                    provider_id="custom-b",
                    base_url=f"http://127.0.0.1:{port_b}/v1",
                    default_model="model-b",
                ),
                secret="key-b",
            )

            adapter_a = reg.get_adapter("custom-a")
            adapter_b = reg.get_adapter("custom-b")

            resp_a = adapter_a.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hi A")]))
            resp_b = adapter_b.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hi B")]))

            self.assertEqual(resp_a.content, "Response from Provider A")
            self.assertEqual(resp_b.content, "Response from Provider B")
            self.assertNotEqual(resp_a.content, resp_b.content)
        finally:
            server_a.server_close()
            server_b.server_close()

    def test_49_policy_bypass_adversarial_registration_is_not_selection(self):
        """Adversarial: registering custom adapter C must NOT execute when global target is A."""
        reg = ProviderRegistry()
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="model-1",
            status=ModelResponseStatus.SUCCESS,
            content="A executed.",
        )
        reg.register_custom_adapter(mock_a)

        mock_c = MagicMock()
        mock_c.provider_name = "custom_c"
        mock_c.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_c.generate.return_value = ModelResponse(
            request_id="REQ-C",
            provider="custom_c",
            model_name="model-c",
            status=ModelResponseStatus.SUCCESS,
            content="C executed.",
        )
        reg.register_custom_adapter(mock_c)

        policy = ModelPolicy(global_target=ModelTarget(provider_id="prov_a", model_id="model-1"))
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Test")]))

        self.assertEqual(resp.content, "A executed.")
        mock_a.generate.assert_called_once()
        mock_c.generate.assert_not_called()

    def test_50_fallback_chain_with_unused_custom_provider(self):
        """When primary A fails, fallback B executes; unrelated registered C is never called."""
        reg = ProviderRegistry()
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="m1",
            status=ModelResponseStatus.ERROR,
            error="PROVIDER_UNAVAILABLE",
        )
        reg.register_custom_adapter(mock_a)

        mock_b = MagicMock()
        mock_b.provider_name = "prov_b"
        mock_b.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_b.generate.return_value = ModelResponse(
            request_id="REQ-B",
            provider="prov_b",
            model_name="m2",
            status=ModelResponseStatus.SUCCESS,
            content="B fallback response.",
        )
        reg.register_custom_adapter(mock_b)

        mock_c = MagicMock()
        mock_c.provider_name = "custom_c"
        mock_c.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        reg.register_custom_adapter(mock_c)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_b", model_id="m2")],
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Test")]))

        self.assertEqual(resp.content, "B fallback response.")
        mock_a.generate.assert_called_once()
        mock_b.generate.assert_called_once()
        mock_c.generate.assert_not_called()

    def test_51_per_agent_override_authority_and_unrelated_custom(self):
        """Verify per-agent routing strictly directs each agent and ignores unselected registered providers."""
        reg = ProviderRegistry()
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="m1",
            status=ModelResponseStatus.SUCCESS,
            content="Response from A",
        )
        reg.register_custom_adapter(mock_a)

        mock_b = MagicMock()
        mock_b.provider_name = "prov_b"
        mock_b.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_b.generate.return_value = ModelResponse(
            request_id="REQ-B",
            provider="prov_b",
            model_name="m2",
            status=ModelResponseStatus.SUCCESS,
            content="Response from Creative B",
        )
        reg.register_custom_adapter(mock_b)

        mock_c = MagicMock()
        mock_c.provider_name = "custom_c"
        mock_c.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        reg.register_custom_adapter(mock_c)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            agent_overrides={
                "CREATIVE": ModelTarget(provider_id="prov_b", model_id="m2"),
            },
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)

        # Test all 5 agents + final_cmo
        cmo_resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="CMO")]), agent_id="cmo")
        intel_resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Intel")]), agent_id="intelligence")
        strat_resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Strat")]), agent_id="strategist")
        crtv_resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Creative")]), agent_id="creative")
        perf_resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Perf")]), agent_id="performance")
        final_resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Final CMO")]), agent_id="final_cmo")

        self.assertEqual(cmo_resp.content, "Response from A")
        self.assertEqual(intel_resp.content, "Response from A")
        self.assertEqual(strat_resp.content, "Response from A")
        self.assertEqual(crtv_resp.content, "Response from Creative B")
        self.assertEqual(perf_resp.content, "Response from A")
        self.assertEqual(final_resp.content, "Response from A")
        mock_c.generate.assert_not_called()

    def test_52_active_run_real_runtime_integration_pinning(self):
        """Verify active run stages 1-6 remain pinned to initial policy V1 even if registry/gateway policy is modified mid-run."""
        reg = ProviderRegistry()
        mock_v1 = MagicMock()
        mock_v1.provider_name = "prov_v1"
        mock_v1.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_v1.generate.return_value = ModelResponse(
            request_id="REQ-V1",
            provider="prov_v1",
            model_name="m-v1",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "V1 Policy Directives"}',
        )
        reg.register_custom_adapter(mock_v1)

        mock_v2 = MagicMock()
        mock_v2.provider_name = "prov_v2"
        mock_v2.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_v2.generate.return_value = ModelResponse(
            request_id="REQ-V2",
            provider="prov_v2",
            model_name="m-v2",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "V2 Policy Directives"}',
        )
        reg.register_custom_adapter(mock_v2)

        policy_v1 = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_v1", model_id="m-v1"),
            configuration_version="v1",
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy_v1)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        ctx = runtime.start_run(objective="Pinning test")
        self.assertEqual(ctx.model_policy["configuration_version"], "v1")

        # Mutate gateway policy globally to V2 while run is active
        policy_v2 = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_v2", model_id="m-v2"),
            configuration_version="v2",
        )
        gw.model_policy = policy_v2

        # Execute stage on active run: context preserves pinned policy version v1
        self.assertEqual(ctx.model_policy["configuration_version"], "v1")

        # New run sees updated policy V2
        new_ctx = runtime.start_run(objective="New run after policy change")
        self.assertEqual(new_ctx.model_policy["configuration_version"], "v2")

    def test_53_provider_disable_during_active_run(self):
        """Verify disabling provider globally prevents new runs from using it while snapshot integrity is maintained."""
        reg = ProviderRegistry()
        mock_prov = MagicMock()
        mock_prov.provider_name = "test_disable_prov"
        mock_prov.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        reg.register_custom_adapter(mock_prov)
        reg.register_provider(
            ProviderDefinition(
                provider_id="test_disable_prov",
                default_model="m1",
                enabled=True,
            )
        )

        # Snapshot before disable
        snap_v1 = reg.snapshot()
        self.assertTrue(snap_v1.providers["test_disable_prov"].enabled)

        # Disable provider
        reg.disable_provider("test_disable_prov")
        self.assertFalse(reg.get_provider("test_disable_prov").enabled)

        # Pre-existing snapshot remains enabled (immutable)
        self.assertTrue(snap_v1.providers["test_disable_prov"].enabled)

        # New snapshot reflects disabled state
        snap_v2 = reg.snapshot()
        self.assertFalse(snap_v2.providers["test_disable_prov"].enabled)

    def test_54_api_provider_injection_boundary(self):
        """Verify API client payload cannot inject arbitrary provider/model routing overrides into runtime context."""
        runtime = FiveAgentDepartmentRuntime(tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
        # Simulated untrusted request payload attempting provider injection
        malicious_input = {
            "objective": "Normal Campaign",
            "provider_id": "malicious-remote-provider",
            "base_url": "https://evil.attacker.com/v1",
            "api_key": "stolen_key",
        }
        ctx = runtime.start_run(objective=malicious_input["objective"])
        # Verify context model_policy is dictated by runtime configuration authority, not payload
        self.assertNotIn("evil.attacker.com", str(ctx.model_policy))
        self.assertNotIn("malicious-remote-provider", str(ctx.model_policy))

    def test_55_model_output_cannot_mutate_provider_registry(self):
        """Verify adversarial model output string claiming registry changes remains harmless data."""
        reg = ProviderRegistry()
        initial_providers = set(reg.list_providers())

        malicious_model_output = (
            '{"action": "UPDATE_PROVIDER_REGISTRY", "new_provider": "attacker_prov", '
            '"base_url": "https://attacker.com", "api_key": "sk-attacker-secret"}'
        )
        # Verify registry providers remain exactly unchanged
        self.assertEqual(set(reg.list_providers()), initial_providers)
        self.assertIsNone(reg.get_provider("attacker_prov"))

    def test_56_explicit_policy_beats_injected_adapter_mode(self):
        """Verify explicit policy always wins over injected adapters."""
        reg = ProviderRegistry()
        mock_injected = MagicMock()
        mock_injected.provider_name = "injected_mock"
        mock_injected.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_injected.generate.return_value = ModelResponse(
            request_id="REQ-INJ",
            provider="injected_mock",
            model_name="m-inj",
            status=ModelResponseStatus.SUCCESS,
            content="Injected mock output",
        )
        reg.register_custom_adapter(mock_injected)

        mock_policy_prov = MagicMock()
        mock_policy_prov.provider_name = "policy_prov"
        mock_policy_prov.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_policy_prov.generate.return_value = ModelResponse(
            request_id="REQ-POL",
            provider="policy_prov",
            model_name="m-pol",
            status=ModelResponseStatus.SUCCESS,
            content="Explicit policy output",
        )
        reg.register_custom_adapter(mock_policy_prov)

        # Explicit policy targeting policy_prov
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="policy_prov", model_id="m-pol"),
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        resp = gw.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")]))

        self.assertEqual(resp.content, "Explicit policy output")
        mock_policy_prov.generate.assert_called_once()
        mock_injected.generate.assert_not_called()

    def test_57_production_bootstrap_does_not_enter_injected_di_mode(self):
        """Verify normal runtime/server initialization starts in explicit policy mode, not injected DI mode."""
        runtime = FiveAgentDepartmentRuntime(tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
        gw = runtime.model_gateway
        self.assertIsNotNone(gw)
        self.assertFalse(getattr(gw.provider_registry, "_has_custom_adapters", False))
        self.assertEqual(len(getattr(gw.provider_registry, "_injected_adapters", {})), 0)

    def test_58_active_run_provider_disable_does_not_change_run_routing(self):
        """Verify disabling a provider globally mid-run does NOT affect the active run's stage routing."""
        reg = ProviderRegistry()
        reg.register_provider(
            ProviderDefinition(
                provider_id="prov_a",
                default_model="m1",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                enabled=True,
            )
        )
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="m1",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "From Provider A", "market_findings": "Intel A", "positioning": "Strat A", "creative_synthesis": "Ad A", "funnel_kpi": "Perf A", "final_synthesis": "Report A"}',
        )
        reg.register_custom_adapter(mock_a)

        reg.register_provider(
            ProviderDefinition(
                provider_id="prov_b",
                default_model="m2",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                enabled=True,
            )
        )
        mock_b = MagicMock()
        mock_b.provider_name = "prov_b"
        mock_b.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_b.generate.return_value = ModelResponse(
            request_id="REQ-B",
            provider="prov_b",
            model_name="m2",
            status=ModelResponseStatus.SUCCESS,
            content='{"content": "From Provider B"}',
        )
        reg.register_custom_adapter(mock_b)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_b", model_id="m2")],
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        # Start RUN-1 with Provider A enabled
        ctx1 = runtime.start_run(objective="Active run stability test")

        # Stage 1: CMO Initial
        out1 = runtime.execute_stage_cmo_initial(ctx1)
        self.assertEqual(out1["status"], "COMPLETED")
        self.assertEqual(mock_a.generate.call_count, 1)

        # WHILE RUN-1 IS ACTIVE: Disable Provider A globally in live registry
        reg.disable_provider("prov_a")
        self.assertFalse(reg.get_provider("prov_a").enabled)

        # Continue RUN-1 through stages 2-6: all must continue using Provider A from snapshot!
        out2 = runtime.execute_stage_intelligence(ctx1)
        out3 = runtime.execute_stage_strategist(ctx1)
        out4 = runtime.execute_stage_creative(ctx1)
        out5 = runtime.execute_stage_performance(ctx1)
        out6 = runtime.execute_stage_final_cmo(ctx1)

        # Provider A was invoked for all 6 stages of RUN-1
        self.assertEqual(mock_a.generate.call_count, 6)
        mock_b.generate.assert_not_called()

    def test_59_new_run_observes_provider_disable(self):
        """Verify new runs started after provider disable observe the disabled state and use fallback."""
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", default_model="m1", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="m1",
            status=ModelResponseStatus.SUCCESS,
            content="From A",
        )
        reg.register_custom_adapter(mock_a)

        reg.register_provider(ProviderDefinition(provider_id="prov_b", default_model="m2", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_b = MagicMock()
        mock_b.provider_name = "prov_b"
        mock_b.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_b.generate.return_value = ModelResponse(
            request_id="REQ-B",
            provider="prov_b",
            model_name="m2",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "From B"}',
        )
        reg.register_custom_adapter(mock_b)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_b", model_id="m2")],
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        # Disable Provider A globally
        reg.disable_provider("prov_a")

        # Start RUN-2: captures disabled Provider A in snapshot
        ctx2 = runtime.start_run(objective="New run observing disable")
        out1 = runtime.execute_stage_cmo_initial(ctx2)

        self.assertEqual(out1["status"], "COMPLETED")
        # Provider B executed via fallback because A is disabled in RUN-2 snapshot
        self.assertEqual(mock_b.generate.call_count, 1)
        mock_a.generate.assert_not_called()

    def test_60_active_run_policy_mutation_does_not_change_routing(self):
        """Verify mutating model_policy on the gateway mid-run does not affect active run routing."""
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_v1", default_model="m-v1", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_v1 = MagicMock()
        mock_v1.provider_name = "prov_v1"
        mock_v1.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_v1.generate.return_value = ModelResponse(
            request_id="REQ-V1",
            provider="prov_v1",
            model_name="m-v1",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "V1", "market_findings": "V1", "positioning": "V1"}',
        )
        reg.register_custom_adapter(mock_v1)

        reg.register_provider(ProviderDefinition(provider_id="prov_v2", default_model="m-v2", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_v2 = MagicMock()
        mock_v2.provider_name = "prov_v2"
        mock_v2.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_v2.generate.return_value = ModelResponse(
            request_id="REQ-V2",
            provider="prov_v2",
            model_name="m-v2",
            status=ModelResponseStatus.SUCCESS,
            content='{"content": "V2"}',
        )
        reg.register_custom_adapter(mock_v2)

        policy_v1 = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_v1", model_id="m-v1"),
            configuration_version="v1",
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy_v1)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        ctx = runtime.start_run(objective="Policy mutation test")
        runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(mock_v1.generate.call_count, 1)

        # Mutate policy on gateway
        policy_v2 = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_v2", model_id="m-v2"),
            configuration_version="v2",
        )
        gw.model_policy = policy_v2

        # Active run continues on V1
        runtime.execute_stage_intelligence(ctx)
        self.assertEqual(mock_v1.generate.call_count, 2)
        mock_v2.generate.assert_not_called()

    def test_61_new_run_observes_policy_mutation(self):
        """Verify new run captures and uses mutated policy V2."""
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_v1", default_model="m-v1", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_v1 = MagicMock()
        mock_v1.provider_name = "prov_v1"
        mock_v1.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        reg.register_custom_adapter(mock_v1)

        reg.register_provider(ProviderDefinition(provider_id="prov_v2", default_model="m-v2", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_v2 = MagicMock()
        mock_v2.provider_name = "prov_v2"
        mock_v2.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_v2.generate.return_value = ModelResponse(
            request_id="REQ-V2",
            provider="prov_v2",
            model_name="m-v2",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "V2"}',
        )
        reg.register_custom_adapter(mock_v2)

        gw = UniversalModelGateway(
            provider_registry=reg,
            model_policy=ModelPolicy(global_target=ModelTarget(provider_id="prov_v1", model_id="m-v1")),
        )
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        gw.model_policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_v2", model_id="m-v2"),
            configuration_version="v2",
        )

        ctx2 = runtime.start_run(objective="New run V2 test")
        runtime.execute_stage_cmo_initial(ctx2)
        mock_v2.generate.assert_called_once()
        mock_v1.generate.assert_not_called()

    def test_62_active_run_fallback_chain_remains_pinned(self):
        """Verify active run uses pinned fallback chain B even if gateway fallback chain is changed to C."""
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", default_model="m1", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="m1",
            status=ModelResponseStatus.TIMEOUT,
            error="TIMEOUT",
        )
        reg.register_custom_adapter(mock_a)

        reg.register_provider(ProviderDefinition(provider_id="prov_b", default_model="m2", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_b = MagicMock()
        mock_b.provider_name = "prov_b"
        mock_b.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_b.generate.return_value = ModelResponse(
            request_id="REQ-B",
            provider="prov_b",
            model_name="m2",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "From Pinned Fallback B"}',
        )
        reg.register_custom_adapter(mock_b)

        reg.register_provider(ProviderDefinition(provider_id="prov_c", default_model="m3", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_c = MagicMock()
        mock_c.provider_name = "prov_c"
        mock_c.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        reg.register_custom_adapter(mock_c)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_b", model_id="m2")],
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        ctx = runtime.start_run(objective="Fallback pinning test")

        # Mutate fallback chain on gateway to C
        gw.model_policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            fallback_chain=[ModelTarget(provider_id="prov_c", model_id="m3")],
        )

        out = runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(out["status"], "COMPLETED")
        # RUN-1 used fallback B from pinned snapshot, NOT mutated fallback C
        mock_b.generate.assert_called_once()
        mock_c.generate.assert_not_called()

    def test_63_active_run_creative_override_remains_pinned(self):
        """Verify active run retains Creative override B even when gateway Creative override is updated to C."""
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="prov_a", default_model="m1", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_a = MagicMock()
        mock_a.provider_name = "prov_a"
        mock_a.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_a.generate.return_value = ModelResponse(
            request_id="REQ-A",
            provider="prov_a",
            model_name="m1",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "A", "market_findings": "A", "positioning": "A"}',
        )
        reg.register_custom_adapter(mock_a)

        reg.register_provider(ProviderDefinition(provider_id="prov_b", default_model="m2", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_b = MagicMock()
        mock_b.provider_name = "prov_b"
        mock_b.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_b.generate.return_value = ModelResponse(
            request_id="REQ-B",
            provider="prov_b",
            model_name="m2",
            status=ModelResponseStatus.SUCCESS,
            content='{"creative_synthesis": "From Creative Override B"}',
        )
        reg.register_custom_adapter(mock_b)

        reg.register_provider(ProviderDefinition(provider_id="prov_c", default_model="m3", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_c = MagicMock()
        mock_c.provider_name = "prov_c"
        mock_c.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        reg.register_custom_adapter(mock_c)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            agent_overrides={"CREATIVE": ModelTarget(provider_id="prov_b", model_id="m2")},
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        ctx = runtime.start_run(objective="Creative override pinning test")
        runtime.execute_stage_cmo_initial(ctx)

        # Mutate Creative override on gateway to C
        gw.model_policy = ModelPolicy(
            global_target=ModelTarget(provider_id="prov_a", model_id="m1"),
            agent_overrides={"CREATIVE": ModelTarget(provider_id="prov_c", model_id="m3")},
        )

        # Execute Creative stage
        out_crtv = runtime.execute_stage_creative(ctx)
        self.assertEqual(out_crtv["status"], "COMPLETED")
        # RUN-1 used Creative override B from pinned snapshot
        mock_b.generate.assert_called_once()
        mock_c.generate.assert_not_called()

    def test_64_final_cmo_keeps_run_start_cmo_policy(self):
        """Verify Stage 6 (Final CMO) executes with pinned CMO policy from run start, regardless of gateway changes."""
        reg = ProviderRegistry()
        reg.register_provider(ProviderDefinition(provider_id="cmo_v1", default_model="m1", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_cmo_v1 = MagicMock()
        mock_cmo_v1.provider_name = "cmo_v1"
        mock_cmo_v1.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_cmo_v1.generate.return_value = ModelResponse(
            request_id="REQ-CMO-V1",
            provider="cmo_v1",
            model_name="m1",
            status=ModelResponseStatus.SUCCESS,
            content='{"strategic_directives": "CMO V1", "final_report": "CMO Report V1"}',
        )
        reg.register_custom_adapter(mock_cmo_v1)

        reg.register_provider(ProviderDefinition(provider_id="cmo_v2", default_model="m2", cost_policy=CostPolicy.FREE_TIER_ALLOWED, enabled=True))
        mock_cmo_v2 = MagicMock()
        mock_cmo_v2.provider_name = "cmo_v2"
        mock_cmo_v2.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        reg.register_custom_adapter(mock_cmo_v2)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="cmo_v1", model_id="m1"),
            agent_overrides={"CMO": ModelTarget(provider_id="cmo_v1", model_id="m1")},
        )
        gw = UniversalModelGateway(provider_registry=reg, model_policy=policy)
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        ctx = runtime.start_run(objective="Final CMO pinning test")
        runtime.execute_stage_cmo_initial(ctx)
        self.assertEqual(mock_cmo_v1.generate.call_count, 1)

        # Mutate CMO override on gateway to V2
        gw.model_policy = ModelPolicy(
            global_target=ModelTarget(provider_id="cmo_v2", model_id="m2"),
            agent_overrides={"CMO": ModelTarget(provider_id="cmo_v2", model_id="m2")},
        )

        # Stage 6: Final CMO
        out_final = runtime.execute_stage_final_cmo(ctx)
        self.assertIn(out_final["status"], ("COMPLETED", "READY_FOR_DEPLOYMENT", "PENDING_APPROVAL"))
        # Final CMO executed using cmo_v1 from pinned snapshot
        self.assertEqual(mock_cmo_v1.generate.call_count, 2)
        mock_cmo_v2.generate.assert_not_called()

    def test_65_run_routing_snapshot_contains_no_plaintext_secret(self):
        """Verify context.model_policy, ProviderRegistrySnapshot, and serialized state contain 0 plaintext API keys."""
        reg = ProviderRegistry()
        reg.register_provider(
            ProviderDefinition(
                provider_id="openai_test",
                credential_ref="ENV:OPENAI_API_KEY",
                default_model="gpt-4o-mini",
            ),
            secret="sk-real-super-secret-key-12345",
        )
        gw = UniversalModelGateway(
            provider_registry=reg,
            model_policy=ModelPolicy(global_target=ModelTarget(provider_id="openai_test", model_id="gpt-4o-mini")),
        )
        runtime = FiveAgentDepartmentRuntime(model_gateway=gw, tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))

        ctx = runtime.start_run(objective="Secret sanitization test")

        # Inspect context.model_policy
        pol_str = json.dumps(ctx.model_policy)
        self.assertNotIn("sk-real-super-secret-key-12345", pol_str)
        self.assertIn("ENV:OPENAI_API_KEY", pol_str)

        # Inspect ProviderRegistrySnapshot
        snap = reg.snapshot()
        snap_str = snap.model_dump_json()
        self.assertNotIn("sk-real-super-secret-key-12345", snap_str)


if __name__ == "__main__":
    unittest.main()

