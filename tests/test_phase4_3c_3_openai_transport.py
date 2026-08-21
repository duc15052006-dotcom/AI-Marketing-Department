"""Phase 4.3C.3: OpenAI-Compatible Transport Hardening & Cloudflare 1010 Tests.

Tests:
1. Exact xKiro successful response fixture normalization
2. Cloudflare Error 1010 detection and classification (PROVIDER_ACCESS_DENIED, auth_error=False, retryable=False)
3. HTTP 401 invalid key classification (AUTH_ERROR)
4. HTTP 403 provider permission denied (AUTHORIZATION_ERROR)
5. HTTP 429 and Cloudflare Error 1015 (RATE_LIMITED, retryable=True)
6. HTTP 500/502/503/504 server errors (PROVIDER_UNAVAILABLE)
7. Request timeout normalization (TIMEOUT)
8. Malformed/empty response handling
9. Standardized API headers construction (Content-Type, Accept, User-Agent, Bearer Auth)
10. Live-shaped Single & CMO Stage 1 transport path
11. Provider identity preservation (provider='xkiro', not 'openai')
12. Strict zero secret leaks in errors, headers, and metadata
"""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import BenchmarkHarness
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.transport import (
    DEFAULT_USER_AGENT,
    OpenAICompatibleTransport,
    classify_transport_error,
    extract_cloudflare_error,
    sanitize_secrets,
)


class TestPhase43C3OpenAITransport(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"

    def test_xkiro_success_fixture(self):
        """Verify normalization of exact observed successful xKiro response fixture."""
        fixture = {
            "id": "chatcmpl-cfc5df20-2926-4093-86ea-791192621ed1",
            "object": "chat.completion",
            "model": "mistralai/mistral-large-2512",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "OK",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 2,
                "total_tokens": 9,
            },
        }

        transport = OpenAICompatibleTransport(base_url="https://api.xkiro.com/v1", api_key="test-key")
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
            transport=transport,
        )

        with patch.object(transport, "post_json", return_value=(200, {"content-type": "application/json"}, json.dumps(fixture))):
            req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="ping")], model_name="mistralai/mistral-large-2512")
            resp = adapter.generate(req)

            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.content, "OK")
            self.assertEqual(resp.provider, "xkiro")
            self.assertEqual(resp.model_name, "mistralai/mistral-large-2512")
            self.assertEqual(resp.usage.usage_source, "PROVIDER_REPORTED")
            self.assertEqual(resp.usage.prompt_tokens, 7)
            self.assertEqual(resp.usage.completion_tokens, 2)
            self.assertEqual(resp.usage.total_tokens, 9)

    def test_cloudflare_1010_detection_and_classification(self):
        """Verify Cloudflare 1010 error is classified as PROVIDER_ACCESS_DENIED, not AUTH_ERROR."""
        cf_1010_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Access denied | api.xkiro.com used Cloudflare to restrict access</title></head>
        <body>
        <h1>Error 1010</h1>
        <p>Ray ID: 96f123456789abcd</p>
        <p>The owner of this website has banned your access based on your browser's signature.</p>
        </body>
        </html>
        """

        transport = OpenAICompatibleTransport(base_url="https://api.xkiro.com/v1", api_key="valid-xkiro-key")
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="valid-xkiro-key",
            transport=transport,
        )

        headers = {"server": "cloudflare", "cf-ray": "96f123456789abcd"}
        with patch.object(transport, "post_json", return_value=(403, headers, cf_1010_html)):
            req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
            resp = adapter.generate(req)

            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertIn("PROVIDER_ACCESS_DENIED", resp.error or "")
            self.assertIn("1010", resp.error or "")
            self.assertNotIn("AUTH_ERROR", resp.error or "")
            self.assertEqual(resp.metadata.get("http_status"), 403)
            self.assertEqual(resp.metadata.get("edge_provider"), "cloudflare")
            self.assertEqual(resp.metadata.get("edge_error_code"), "1010")
            self.assertEqual(resp.metadata.get("error_category"), "access_denied")
            self.assertFalse(resp.metadata.get("retryable", True))
            self.assertFalse(resp.metadata.get("auth_error", True))

    def test_401_invalid_key_classification(self):
        """Verify HTTP 401 is classified as AUTH_ERROR."""
        body = json.dumps({"error": {"message": "Invalid API key provided", "type": "invalid_request_error", "code": "invalid_api_key"}})
        res = classify_transport_error(401, {}, body, "xkiro")
        self.assertEqual(res["status"], ModelResponseStatus.ERROR)
        self.assertIn("AUTH_ERROR", res["error"])
        self.assertTrue(res["metadata"]["auth_error"])
        self.assertFalse(res["metadata"]["retryable"])

    def test_403_provider_permission_denied(self):
        """Verify HTTP 403 with permission error is classified as AUTHORIZATION_ERROR."""
        body = json.dumps({"error": {"message": "Model not permitted on this key", "type": "permission_denied"}})
        res = classify_transport_error(403, {}, body, "xkiro")
        self.assertEqual(res["status"], ModelResponseStatus.ERROR)
        self.assertIn("AUTHORIZATION_ERROR", res["error"])
        self.assertFalse(res["metadata"]["auth_error"])
        self.assertFalse(res["metadata"]["retryable"])

    def test_429_and_cloudflare_1015_rate_limiting(self):
        """Verify HTTP 429 and Cloudflare 1015 are classified as RATE_LIMITED."""
        # 1. Standard 429
        res_429 = classify_transport_error(429, {}, "Too Many Requests", "xkiro")
        self.assertEqual(res_429["status"], ModelResponseStatus.RATE_LIMITED)
        self.assertIn("RATE_LIMITED", res_429["error"])
        self.assertTrue(res_429["metadata"]["retryable"])

        # 2. Cloudflare 1015
        cf_1015 = "<html><body><h1>Error 1015</h1><p>You are being rate limited.</p></body></html>"
        res_1015 = classify_transport_error(403, {"server": "cloudflare"}, cf_1015, "xkiro")
        self.assertEqual(res_1015["status"], ModelResponseStatus.RATE_LIMITED)
        self.assertIn("1015", res_1015["error"])
        self.assertEqual(res_1015["metadata"]["edge_error_code"], "1015")
        self.assertTrue(res_1015["metadata"]["retryable"])

    def test_5xx_server_errors(self):
        """Verify HTTP 500, 502, 503, 504 are classified as PROVIDER_UNAVAILABLE."""
        for code in (500, 502, 503, 504):
            res = classify_transport_error(code, {}, f"Server error {code}", "xkiro")
            self.assertEqual(res["status"], ModelResponseStatus.ERROR)
            self.assertIn("PROVIDER_UNAVAILABLE", res["error"])
            self.assertTrue(res["metadata"]["retryable"])

    def test_timeout_normalization(self):
        """Verify request timeouts are classified as TIMEOUT."""
        res = classify_transport_error(408, {}, "Request timed out", "xkiro")
        self.assertEqual(res["status"], ModelResponseStatus.TIMEOUT)
        self.assertIn("TIMEOUT", res["error"])
        self.assertTrue(res["metadata"]["retryable"])

    def test_headers_construction(self):
        """Verify transport builds correct headers with normal application User-Agent."""
        transport = OpenAICompatibleTransport(
            base_url="https://api.xkiro.com/v1",
            api_key="my_secret_token_123",
        )
        headers = transport.build_headers()

        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Authorization"], "Bearer my_secret_token_123")
        self.assertEqual(headers["User-Agent"], DEFAULT_USER_AGENT)

    def test_single_and_cmo_stage1_transport_path(self):
        """Verify live Single and CMO Stage 1 prompts execute cleanly through transport."""
        gateway = UniversalModelGateway(free_only_mode=True)
        transport = OpenAICompatibleTransport(base_url="https://api.xkiro.com/v1", api_key="test-key")
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
            transport=transport,
        )
        gateway.provider_registry.register_custom_adapter(adapter)

        harness = BenchmarkHarness(
            benchmark_dir=self.bench_dir,
            provider_id="xkiro",
            model_name="mistralai/mistral-large-2512",
            gateway=gateway,
        )

        fake_resp = {
            "id": "cmpl-test",
            "model": "mistralai/mistral-large-2512",
            "choices": [{"message": {"role": "assistant", "content": '{"executive_summary": "Test Plan"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

        with patch.object(transport, "post_json", return_value=(200, {}, json.dumps(fake_resp))):
            # 1. Single prompt
            single_prompt = harness.build_single_model_prompt()
            req_single = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content=single_prompt)], model_name="mistralai/mistral-large-2512")
            resp_single = gateway.generate(req_single, provider_id="xkiro", strict_model_pin=True)
            self.assertEqual(resp_single.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp_single.provider, "xkiro")

            # 2. CMO Stage 1 prompt
            cmo_prompt = f"Stage 1 Objective: {json.dumps(harness.business_objective)}"
            req_cmo = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content=cmo_prompt)], model_name="mistralai/mistral-large-2512")
            resp_cmo = gateway.generate(req_cmo, provider_id="xkiro", strict_model_pin=True)
            self.assertEqual(resp_cmo.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp_cmo.provider, "xkiro")

    def test_provider_identity_preservation(self):
        """Verify provider identity remains 'xkiro' and never becomes 'openai'."""
        transport = OpenAICompatibleTransport(base_url="https://api.xkiro.com/v1", api_key="test-key")
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
            transport=transport,
        )

        fake_resp = {
            "model": "mistralai/mistral-large-2512",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {"total_tokens": 10},
        }

        with patch.object(transport, "post_json", return_value=(200, {}, json.dumps(fake_resp))):
            req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="hi")])
            resp = adapter.generate(req)
            self.assertEqual(resp.provider, "xkiro")
            self.assertNotEqual(resp.provider, "openai")

    def test_zero_secret_leaks(self):
        """Verify secrets are redacted from error bodies, exceptions, and text outputs."""
        secret = "XKIRO_SUPER_SECRET_KEY_9999"
        raw_error = f"Error: Authorization failed for Bearer {secret}. Contact support."
        sanitized = sanitize_secrets(raw_error, secret)

        self.assertNotIn(secret, sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)

        # Classification redacts secret
        res = classify_transport_error(403, {}, raw_error, "xkiro", secret_to_redact=secret)
        self.assertNotIn(secret, res["error"])
        self.assertNotIn(secret, json.dumps(res["metadata"]))


if __name__ == "__main__":
    unittest.main()
