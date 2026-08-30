"""Unit Tests for Free-Only Model Router & Cost Governance (Phase 3D.2.1).

Validates:
- Gemini is selected in FREE_ONLY_MODE
- Paid TheSpark is not selected automatically in FREE_ONLY_MODE
- Paid OpenAI is not selected automatically in FREE_ONLY_MODE
- Free quota exhaustion does not trigger paid fallback in FREE_ONLY_MODE
- Explicit allow_paid=True enables paid provider invocation
- API key is never leaked in error messages
"""

import json
import unittest
from unittest.mock import MagicMock, patch
from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.openai_adapter import OpenAIProviderAdapter
from integrations.models.router import ModelRouter
from integrations.models.thespark_adapter import TheSparkProviderAdapter


class TestFreeOnlyRouter(unittest.TestCase):
    def setUp(self):
        self.router = ModelRouter(default_provider="gemini", free_only_mode=True)
        self.router.register_adapter(GeminiProviderAdapter(api_key="test-gemini-key"))

    def test_gemini_selected_in_free_only_mode(self):
        """Verify Gemini (FREE_TIER_ALLOWED) executes normally in free-only mode."""
        self.assertTrue(self.router.free_only_mode)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Ping")])

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "PONG"}]}}]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_resp
            res = self.router.generate(req)
            self.assertEqual(res.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(res.provider, "gemini")

    def test_paid_thespark_not_selected_automatically_in_free_only_mode(self):
        """Verify requesting paid TheSpark in FREE_ONLY_MODE is strictly rejected."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        res = self.router.generate(req, preferred_provider="thespark", allow_paid=False)

        self.assertEqual(res.status, ModelResponseStatus.ERROR)
        self.assertIn("PAID_PROVIDER_BLOCKED_IN_FREE_ONLY_MODE", res.error)

    def test_paid_openai_not_selected_automatically_in_free_only_mode(self):
        """Verify requesting paid OpenAI in FREE_ONLY_MODE is strictly rejected."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        res = self.router.generate(req, preferred_provider="openai", allow_paid=False)

        self.assertEqual(res.status, ModelResponseStatus.ERROR)
        self.assertIn("PAID_PROVIDER_BLOCKED_IN_FREE_ONLY_MODE", res.error)

    def test_free_quota_exhaustion_does_not_fallback_to_paid_providers(self):
        """Verify that when free Gemini fails, router does not automatically fallback to paid TheSpark/OpenAI."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])

        # Mock Gemini failing
        with patch.object(
            self.router.get_adapter("gemini"),
            "generate",
            return_value=ModelResponse(
                request_id="REQ-1",
                provider="gemini",
                model_name="gemini-flash-latest",
                status=ModelResponseStatus.ERROR,
                error="FREE_TIER_QUOTA_EXCEEDED: Rate limit",
            ),
        ):
            res = self.router.generate(req, allow_fallback=True, allow_paid=False)
            self.assertEqual(res.status, ModelResponseStatus.ERROR)
            self.assertIn("FREE_TIER_QUOTA_EXCEEDED", res.error)
            self.assertEqual(res.provider, "gemini")

    def test_explicit_paid_approval_enables_paid_provider(self):
        """Verify setting allow_paid=True permits invoking a paid provider."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        mock_spark_adapter = MagicMock()
        mock_spark_adapter.provider_name = "thespark"
        mock_spark_adapter.cost_policy = CostPolicy.PAID
        mock_spark_adapter.generate.return_value = ModelResponse(
            request_id="REQ-PAID-001",
            provider="thespark",
            model_name="gpt-5.6-sol",
            status=ModelResponseStatus.SUCCESS,
            content="Paid model response",
        )

        self.router.register_adapter(mock_spark_adapter)
        res = self.router.generate(req, preferred_provider="thespark", allow_paid=True)
        self.assertEqual(res.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(res.content, "Paid model response")

    def test_no_api_key_leak_in_paid_block_error(self):
        """Verify error messages never expose environment secrets."""
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])
        res = self.router.generate(req, preferred_provider="openai", allow_paid=False)
        self.assertNotIn("sk-", res.error)
        self.assertNotIn("test-", res.error)


if __name__ == "__main__":
    unittest.main()
