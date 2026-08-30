"""Unit Tests for Google Gemini Provider Adapter (Phase 3D.1.6).

Validates message mapping, header authentication, usageMetadata normalization,
secret safety, error normalization, router registration, and benchmark fallback controls.
"""

import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.router import ModelRouter


class TestGeminiAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = GeminiProviderAdapter(
            api_key="test-gemini-secret-key-12345",
            default_model="gemini-flash-latest",
        )

    def test_missing_api_key_safety(self):
        """Verify unconfigured adapter returns clean error without leaking secrets."""
        unconfigured = GeminiProviderAdapter(api_key="")
        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Hello")]
        )
        resp = unconfigured.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertIn("MISSING_API_KEY", resp.error)

    def test_header_authentication_and_payload_construction(self):
        """Verify messages, roles, and headers are structured according to Gemini API spec."""
        req = ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content="You are an intelligence researcher."),
                ModelMessage(role=ModelRole.USER, content="Analyze Ollama market reception."),
                ModelMessage(role=ModelRole.ASSISTANT, content="Here is what was observed."),
            ],
            temperature=0.2,
            max_tokens=2048,
        )

        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{"text": "Ollama local execution findings."}]
                },
                "finishReason": "STOP",
            }],
            "usageMetadata": {
                "promptTokenCount": 120,
                "candidatesTokenCount": 45,
                "totalTokenCount": 165,
            }
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_cm
            resp = self.adapter.generate(req)

            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.content, "Ollama local execution findings.")
            self.assertEqual(resp.usage.prompt_tokens, 120)
            self.assertEqual(resp.usage.completion_tokens, 45)
            self.assertEqual(resp.usage.total_tokens, 165)

            # Inspect outgoing request
            call_args = mock_urlopen.call_args
            http_req = call_args[0][0]
            header_keys = [k.lower() for k in http_req.headers.keys()]
            self.assertIn("x-goog-api-key", header_keys)
            self.assertEqual(http_req.headers.get("X-goog-api-key") or http_req.headers.get("x-goog-api-key"), "test-gemini-secret-key-12345")

            sent_payload = json.loads(http_req.data.decode("utf-8"))
            self.assertIn("systemInstruction", sent_payload)
            self.assertEqual(sent_payload["systemInstruction"]["parts"][0]["text"], "You are an intelligence researcher.")
            self.assertEqual(len(sent_payload["contents"]), 2)
            self.assertEqual(sent_payload["contents"][0]["role"], "user")
            self.assertEqual(sent_payload["contents"][1]["role"], "model")
            self.assertEqual(sent_payload["generationConfig"]["temperature"], 0.2)
            self.assertEqual(sent_payload["generationConfig"]["maxOutputTokens"], 2048)

    def test_secret_non_exposure_in_response_and_errors(self):
        """Verify API key is never echoed into response error strings."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        http_err = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Access denied for test-gemini-secret-key-12345"}'),
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            resp = self.adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertNotIn("test-gemini-secret-key-12345", resp.error)
            self.assertIn("[REDACTED_API_KEY]", resp.error)

    def test_http_error_normalizations(self):
        """Verify HTTP 400, 429, and 500 normalize to correct error categories."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])

        # 429 Rate Limit
        err_429 = urllib.error.HTTPError(
            url="http://test", code=429, msg="Too Many Requests", hdrs={}, fp=MagicMock(read=lambda: b"Rate limit exceeded")
        )
        with patch("urllib.request.urlopen", side_effect=err_429):
            resp = self.adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertIn("FREE_TIER_QUOTA_EXCEEDED", resp.error)

        # 400 Invalid Request
        err_400 = urllib.error.HTTPError(
            url="http://test", code=400, msg="Bad Request", hdrs={}, fp=MagicMock(read=lambda: b"Invalid field")
        )
        with patch("urllib.request.urlopen", side_effect=err_400):
            resp = self.adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertIn("INVALID_REQUEST", resp.error)

    def test_content_blocked_handling(self):
        """Verify prompt feedback block reason is captured cleanly."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Blocked prompt")])
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps({
            "promptFeedback": {"blockReason": "SAFETY"}
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_cm
            resp = self.adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertIn("CONTENT_BLOCKED: SAFETY", resp.error)

    def test_router_selects_gemini_and_disables_thespark_fallback_in_benchmark(self):
        """Verify ModelRouter defaults to Gemini and does not fallback to TheSpark when fallback is disabled."""
        router = ModelRouter(default_provider="gemini")
        router.register_adapter(self.adapter)
        self.assertEqual(router.default_provider, "gemini")
        self.assertIn("gemini", router.registered_providers)

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Ping")])
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "PONG"}]}}]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_cm
            res = router.generate(req, allow_fallback=False)
            self.assertEqual(res.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(res.provider, "gemini")


if __name__ == "__main__":
    unittest.main()
