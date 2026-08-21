"""Unit Tests for TheSparkDaily Third-Party OpenAI-Compatible Provider Adapter (Phase 3A.0.1).

Validates provider provenance, base URL handling, Bearer authentication headers,
secret non-exposure, usage normalization, router registration, and benchmark fallback controls.
"""

import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
from integrations.models import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelRouter,
    TheSparkProviderAdapter,
)


class TestTheSparkAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = TheSparkProviderAdapter(
            api_key="test-spark-secret-key-12345",
            base_url="https://llm.thesparkdaily.com/v1",
            default_model="gpt-5.6-sol",
        )

    def test_third_party_provider_identity_and_provenance(self):
        """Verify TheSparkProviderAdapter sets explicit third-party provenance metadata."""
        self.assertEqual(self.adapter.provider_name, "thespark")
        self.assertEqual(self.adapter.base_url, "https://llm.thesparkdaily.com/v1")
        self.assertEqual(self.adapter.default_model, "gpt-5.6-sol")

    def test_missing_api_key_safety(self):
        """Verify unconfigured adapter returns error without leaking secrets or crashing."""
        unconfigured = TheSparkProviderAdapter(api_key="")
        self.assertFalse(unconfigured.is_configured())

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Test prompt")]
        )
        resp = unconfigured.generate(req)
        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertIn("MISSING_API_KEY", resp.error)
        self.assertEqual(resp.provider, "thespark")
        self.assertEqual(resp.provider_type, "third_party_openai_compatible")
        self.assertEqual(resp.provider_provenance, "THIRD_PARTY")
        self.assertEqual(resp.model_provenance, "UNVERIFIED_THIRD_PARTY_CLAIM")
        self.assertEqual(resp.trust_status, "UNVERIFIED")

    @patch("urllib.request.urlopen")
    def test_bearer_authentication_and_payload_construction(self, mock_urlopen):
        """Verify HTTP request uses Bearer token, correct endpoint, and OpenAI-compatible payload."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "id": "chatcmpl-test-001",
                "object": "chat.completion",
                "created": 1723849200,
                "model": "gpt-5.6-sol",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "THESPARK API WORKING"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 5,
                    "total_tokens": 20,
                },
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        req = ModelRequest(
            model_name="gpt-5.6-sol",
            messages=[ModelMessage(role=ModelRole.USER, content="Reply exactly with: THESPARK API WORKING")],
        )

        resp = self.adapter.generate(req)

        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.content, "THESPARK API WORKING")
        self.assertEqual(resp.provider, "thespark")
        self.assertEqual(resp.provider_type, "third_party_openai_compatible")
        self.assertEqual(resp.provider_provenance, "THIRD_PARTY")
        self.assertEqual(resp.model_provenance, "UNVERIFIED_THIRD_PARTY_CLAIM")
        self.assertEqual(resp.trust_status, "UNVERIFIED")
        self.assertEqual(resp.usage.prompt_tokens, 15)
        self.assertEqual(resp.usage.completion_tokens, 5)
        self.assertEqual(resp.usage.total_tokens, 20)

        # Inspect the HTTP Request sent to urlopen
        called_req = mock_urlopen.call_args[0][0]
        self.assertEqual(called_req.full_url, "https://llm.thesparkdaily.com/v1/chat/completions")
        self.assertEqual(called_req.headers["Authorization"], "Bearer test-spark-secret-key-12345")
        self.assertEqual(called_req.headers["Content-type"], "application/json")

        payload_sent = json.loads(called_req.data.decode("utf-8"))
        self.assertEqual(payload_sent["model"], "gpt-5.6-sol")
        self.assertEqual(payload_sent["messages"][0]["content"], "Reply exactly with: THESPARK API WORKING")

    def test_secret_non_exposure_in_response_and_errors(self):
        """Verify API key is never placed into ModelResponse error strings."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("https://llm.thesparkdaily.com/v1", 401, "Unauthorized", {}, None)):
            req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Test")])
            resp = self.adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertIn("401", resp.error)
            self.assertNotIn("test-spark-secret-key-12345", resp.error)

    def test_router_registration_and_benchmark_fallback_disabled(self):
        """Verify ModelRouter registers TheSpark and disables fallback in benchmark mode."""
        router = ModelRouter(default_provider="thespark", free_only_mode=False)

        failing_spark = TheSparkProviderAdapter(api_key="")  # unconfigured = fails
        fallback_mock = MagicMock()
        fallback_mock.provider_name = "mock_backup"
        fallback_mock.generate.return_value = ModelResponse(
            request_id="REQ-BACKUP",
            provider="mock_backup",
            model_name="backup-model",
            content="Backup content",
            status=ModelResponseStatus.SUCCESS,
        )

        router.register_adapter(failing_spark)
        router.register_adapter(fallback_mock)
        router.set_fallback_chain(["thespark", "mock_backup"])

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])

        # 1. Normal mode: fallback permitted
        resp_fallback = router.generate(req, preferred_provider="thespark", allow_fallback=True)
        self.assertEqual(resp_fallback.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp_fallback.provider, "mock_backup")

        # 2. Benchmark mode: fallback explicitly disabled
        resp_benchmark = router.generate(req, preferred_provider="thespark", allow_fallback=False)
        self.assertEqual(resp_benchmark.status, ModelResponseStatus.ERROR)
        self.assertEqual(resp_benchmark.provider, "thespark")
        self.assertIn("MISSING_API_KEY", resp_benchmark.error)


if __name__ == "__main__":
    unittest.main()
