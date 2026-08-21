"""Phase 4.3C.2: Model Request Contract Normalization & Pre-Network Telemetry Tests.

Tests:
1. Canonical ModelMessage input normalization
2. Legacy dict message input normalization
3. Mixed ModelMessage / dict list normalization
4. Malformed message fail-closed validation (missing role, missing content, invalid types)
5. OpenAI-compatible serialization exact outgoing payload shape
6. Gemini native adapter compatibility with normalized requests
7. Live-shaped Single benchmark request serialization
8. Live-shaped CMO Initial (Stage 1) benchmark request serialization
9. Full 6-stage Five-Agent request serialization
10. Pre-network telemetry semantics (usage_source == "NOT_AVAILABLE")
11. Pre-network error observability (provider_id and requested_model preserved)
12. Zero secret leaks
"""

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import BenchmarkHarness
from integrations.models.base import (
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
    normalize_model_message,
    normalize_model_request,
)
from integrations.models.fake_gemini_adapter import FakeGeminiProviderAdapter
from integrations.models.gateway import UniversalModelGateway
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.registry import ModelMetadata, ModelRegistry, ProviderConfig, ProviderProtocol, ProviderRegistry


class TestPhase43C2RequestNormalization(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"

    def test_canonical_model_message_input(self):
        """Verify standard ModelMessage objects are preserved during normalization."""
        msg = ModelMessage(role=ModelRole.USER, content="Strategy prompt")
        norm = normalize_model_message(msg)
        self.assertIsInstance(norm, ModelMessage)
        self.assertEqual(norm.role, ModelRole.USER)
        self.assertEqual(norm.content, "Strategy prompt")

        req = ModelRequest(messages=[msg], model_name="mistralai/mistral-large-2512")
        norm_req = normalize_model_request(req)
        self.assertEqual(len(norm_req.messages), 1)
        self.assertIsInstance(norm_req.messages[0], ModelMessage)
        self.assertEqual(norm_req.messages[0].content, "Strategy prompt")

    def test_legacy_dict_message_input(self):
        """Verify legacy dict messages are automatically coerced into canonical ModelMessage."""
        dict_msg = {"role": "system", "content": "You are CMO"}
        norm = normalize_model_message(dict_msg)
        self.assertIsInstance(norm, ModelMessage)
        self.assertEqual(norm.role, ModelRole.SYSTEM)
        self.assertEqual(norm.content, "You are CMO")

        req = ModelRequest(messages=[dict_msg], model_name="mistralai/mistral-large-2512")
        norm_req = normalize_model_request(req)
        self.assertEqual(len(norm_req.messages), 1)
        self.assertIsInstance(norm_req.messages[0], ModelMessage)
        self.assertEqual(norm_req.messages[0].role, ModelRole.SYSTEM)

    def test_mixed_message_input(self):
        """Verify mixed lists of ModelMessage and dicts normalize seamlessly."""
        mixed = [
            ModelMessage(role=ModelRole.SYSTEM, content="System prompt"),
            {"role": "user", "content": "User prompt"},
        ]
        req = ModelRequest(messages=mixed, model_name="mistralai/mistral-large-2512")
        norm_req = normalize_model_request(req)
        self.assertEqual(len(norm_req.messages), 2)
        self.assertEqual(norm_req.messages[0].role, ModelRole.SYSTEM)
        self.assertEqual(norm_req.messages[1].role, ModelRole.USER)

    def test_malformed_messages_fail_closed(self):
        """Verify malformed messages fail closed with REQUEST_SCHEMA_ERROR."""
        bad_cases = [
            {},
            {"role": "user"},
            {"content": "No role"},
            {"role": 123, "content": "Bad role type"},
            {"role": "user", "content": 456},
            None,
            "plain string instead of message",
        ]

        for bad in bad_cases:
            with self.assertRaises(ValueError) as ctx:
                normalize_model_message(bad)
            self.assertIn("REQUEST_SCHEMA_ERROR", str(ctx.exception))

        # Empty messages list in request
        with self.assertRaises(ValueError) as ctx:
            normalize_model_request(ModelRequest(messages=[]))
        self.assertIn("REQUEST_SCHEMA_ERROR", str(ctx.exception))

    def test_openai_compatible_serialization_exact_shape(self):
        """Verify outgoing payload to OpenAI-compatible endpoint has exact standard shape."""
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
        )

        # Pass dict messages intentionally to verify adapter normalizes internally
        req = ModelRequest(
            messages=[
                {"role": "system", "content": "You are CMO"},
                {"role": "user", "content": "Create GTM plan"},
            ],
            model_name="mistralai/mistral-large-2512",
            temperature=0.2,
        )

        fake_resp_body = {
            "id": "cmpl-1",
            "model": "mistralai/mistral-large-2512",
            "choices": [{"message": {"role": "assistant", "content": '{"plan": "Done"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(fake_resp_body).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_cm

            resp = adapter.generate(req)

            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            # Verify exact call arguments
            call_args = mock_urlopen.call_args
            http_req = call_args[0][0]
            self.assertEqual(http_req.full_url, "https://api.xkiro.com/v1/chat/completions")
            payload = json.loads(http_req.data.decode("utf-8"))

            self.assertEqual(payload["model"], "mistralai/mistral-large-2512")
            self.assertEqual(payload["temperature"], 0.2)
            self.assertEqual(
                payload["messages"],
                [
                    {"role": "system", "content": "You are CMO"},
                    {"role": "user", "content": "Create GTM plan"},
                ],
            )

    def test_gemini_adapter_request_normalization(self):
        """Verify GeminiProviderAdapter accepts dict messages and normalizes without crashing."""
        adapter = GeminiProviderAdapter(api_key="test-gemini-key")

        req = ModelRequest(
            messages=[
                {"role": "system", "content": "System directive"},
                {"role": "user", "content": "User input"},
            ],
            model_name="gemini-flash-latest",
        )

        fake_resp = {
            "candidates": [{"content": {"parts": [{"text": "Gemini response"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 15, "totalTokenCount": 45},
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(fake_resp).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_cm

            resp = adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.content, "Gemini response")

    def test_live_shaped_single_request_through_gateway(self):
        """Verify Phase 4.3 live single-model request passes through UniversalModelGateway to xKiro."""
        gateway = UniversalModelGateway(free_only_mode=True)
        # Register test adapter instance with API key
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
        )
        gateway.provider_registry.register_custom_adapter(adapter)

        harness = BenchmarkHarness(benchmark_dir=self.bench_dir, provider_id="xkiro", model_name="mistralai/mistral-large-2512", gateway=gateway)
        prompt = harness.build_single_model_prompt()

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=prompt)],
            model_name="mistralai/mistral-large-2512",
            temperature=0.2,
        )

        fake_resp_body = {
            "id": "cmpl-single",
            "model": "mistralai/mistral-large-2512",
            "choices": [{"message": {"role": "assistant", "content": '{"executive_summary": "Single plan"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 400, "total_tokens": 1600},
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(fake_resp_body).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_cm

            resp = gateway.generate(req, provider_id="xkiro", strict_model_pin=True)

            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.provider, "xkiro")
            self.assertEqual(resp.model_name, "mistralai/mistral-large-2512")
            self.assertEqual(resp.usage.usage_source, "PROVIDER_REPORTED")

    def test_live_shaped_cmo_stage1_request_through_gateway(self):
        """Verify Phase 4.3 live CMO Stage 1 request passes through UniversalModelGateway to xKiro."""
        gateway = UniversalModelGateway(free_only_mode=True)
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
        )
        gateway.provider_registry.register_custom_adapter(adapter)

        harness = BenchmarkHarness(benchmark_dir=self.bench_dir, provider_id="xkiro", model_name="mistralai/mistral-large-2512", gateway=gateway)
        cmo_prompt = f"Decompose business objective for {harness.product_facts['product_id']}:\nFacts: {json.dumps(harness.product_facts)}\nEvidence: {json.dumps(harness.evidence_bundle)}"

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content=cmo_prompt)], model_name="mistralai/mistral-large-2512")

        fake_resp_body = {
            "id": "cmpl-stage1",
            "model": "mistralai/mistral-large-2512",
            "choices": [{"message": {"role": "assistant", "content": '{"summary": "CMO Decomposition"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000},
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(fake_resp_body).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_cm

            resp = gateway.generate(req, provider_id="xkiro", strict_model_pin=True)

            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.provider, "xkiro")
            self.assertIn("CMO Decomposition", resp.content)

    def test_pre_network_telemetry_correctness(self):
        """Verify pre-network failures set usage_source='NOT_AVAILABLE' and do NOT claim PROVIDER_REPORTED."""
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="NONEXISTENT_KEY_ENV",
            default_model="mistralai/mistral-large-2512",
            api_key=None,  # Missing key
        )

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        resp = adapter.generate(req)

        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertIn("MISSING_API_KEY", resp.error or "")
        self.assertEqual(resp.usage.usage_source, "NOT_AVAILABLE")
        self.assertEqual(resp.usage.total_tokens, 0)
        self.assertEqual(resp.provider, "xkiro")
        self.assertEqual(resp.model_name, "mistralai/mistral-large-2512")

    def test_pre_network_error_preserves_provider_and_model(self):
        """Verify error responses preserve provider_id and requested model before network calls."""
        gateway = UniversalModelGateway(free_only_mode=True)
        # 1. Invalid schema passed to gateway directly
        resp = gateway.generate(request="not_a_model_request", provider_id="xkiro", strict_model_pin=True)
        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertIn("REQUEST_SCHEMA_ERROR", resp.error or "")
        self.assertEqual(resp.provider, "xkiro")
        self.assertEqual(resp.usage.usage_source, "NOT_AVAILABLE")

        # 2. Missing API key pre-network failure preserves provider and requested model
        p_reg = ProviderRegistry()
        p_reg.register_provider(
            ProviderConfig(
                provider_id="unconfigured_provider",
                protocol=ProviderProtocol.OPENAI_COMPATIBLE,
                base_url="https://api.example.com/v1",
                api_key_env="NONEXISTENT_KEY_ENV_9999",
                default_model="test-model",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
            )
        )
        m_reg = ModelRegistry()
        m_reg.register_model(
            ModelMetadata(
                provider_id="unconfigured_provider",
                model_id="test-model",
                display_name="Test Model",
                cost_tier=CostPolicy.FREE_TIER_ALLOWED,
            )
        )
        gw_missing = UniversalModelGateway(provider_registry=p_reg, model_registry=m_reg, free_only_mode=True)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Valid prompt")], model_name="test-model")
        resp2 = gw_missing.generate(req, provider_id="unconfigured_provider", strict_model_pin=True)
        self.assertEqual(resp2.status, ModelResponseStatus.ERROR)
        self.assertIn("MISSING_API_KEY", resp2.error or "")
        self.assertEqual(resp2.provider, "unconfigured_provider")
        self.assertEqual(resp2.model_name, "test-model")
        self.assertEqual(resp2.usage.usage_source, "NOT_AVAILABLE")

    def test_zero_secret_leaks(self):
        """Verify API keys are never included in error strings, dumps, or telemetry."""
        secret = "SECRET_BEARER_XKIRO_TOKEN_8888"
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key=secret,
        )

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hi")])

        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="https://api.xkiro.com/v1/chat/completions",
                code=403,
                msg="Forbidden",
                hdrs={},
                fp=BytesIO(b'{"error": "Forbidden token"}'),
            )

            resp = adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertNotIn(secret, resp.error or "")
            self.assertNotIn(secret, json.dumps(resp.model_dump()))

    def test_full_six_stage_five_agent_pipeline_offline(self):
        """Verify all 6 stages of Five-Agent condition execute cleanly through UniversalModelGateway."""
        fake_adapter = FakeGeminiProviderAdapter()
        p_reg = ProviderRegistry()
        p_reg.register_custom_adapter(fake_adapter)

        gateway = UniversalModelGateway(provider_registry=p_reg, free_only_mode=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(
                benchmark_dir=self.bench_dir,
                checkpoints_dir=chk_dir,
                cooldown_seconds=0.0,
                provider_id="fake_gemini",
                model_name="gemini-flash-latest",
                gateway=gateway,
            )
            harness.adapter = fake_adapter

            single_res = harness.run_single_condition(dry_run=False)
            self.assertEqual(single_res["status"], "SUCCESS")

            five_res = harness.run_five_agent_condition(dry_run=False)
            self.assertEqual(five_res["status"], "COMPLETED")
            self.assertEqual(len(five_res["stages"]), 6)
            for stage_name, stage_data in five_res["stages"].items():
                self.assertEqual(stage_data["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
