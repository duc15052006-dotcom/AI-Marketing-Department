"""Regression tests for shared secret redaction at public/persisted boundaries.

FIX-SECRET-SANITIZATION-03
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from integrations.models.base import ModelResponse, ModelResponseStatus, ModelStreamError
from tools.receipts import ExecutionReceipt, ExecutionStatus


class TestSecretSanitization03(unittest.TestCase):
    def test_exact_transient_secret_is_removed_when_authority_knows_it(self) -> None:
        secret = "opaque-provider-credential-123456"
        raw = f"Connection failed while using credential {secret}"

        sanitized = sanitize_sensitive_text(raw, secret=secret)

        self.assertNotIn(secret, sanitized)
        self.assertIn("[REDACTED_SECRET]", sanitized)

    def test_generic_authorization_and_query_secrets_are_redacted(self) -> None:
        raw = (
            "Authorization: Bearer abc.def-secret-123 "
            "url=https://example.test/v1?api_key=query-secret-999&token=token-secret-888 "
            "password=plain-password"
        )

        sanitized = sanitize_sensitive_text(raw)

        self.assertNotIn("abc.def-secret-123", sanitized)
        self.assertNotIn("query-secret-999", sanitized)
        self.assertNotIn("token-secret-888", sanitized)
        self.assertNotIn("plain-password", sanitized)
        self.assertIn("[REDACTED", sanitized)

    def test_common_bare_provider_token_prefixes_are_redacted(self) -> None:
        raw = "upstream echoed sk-supersecret123456 and ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"

        sanitized = sanitize_sensitive_text(raw)

        self.assertNotIn("sk-supersecret123456", sanitized)
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234", sanitized)

    def test_recursive_payload_redacts_sensitive_keys_and_nested_strings(self) -> None:
        raw = {
            "api_key": "top-secret-key",
            "nested": {
                "safe": "keep-me",
                "message": "Bearer nested-token-123456",
            },
            "items": [{"client_secret": "client-secret-value"}],
        }

        sanitized = sanitize_sensitive_payload(raw)

        self.assertEqual(sanitized["api_key"], "[REDACTED_SECRET]")
        self.assertEqual(sanitized["nested"]["safe"], "keep-me")
        self.assertNotIn("nested-token-123456", sanitized["nested"]["message"])
        self.assertEqual(sanitized["items"][0]["client_secret"], "[REDACTED_SECRET]")

    def test_model_response_error_is_sanitized_at_model_boundary(self) -> None:
        response = ModelResponse(
            request_id="REQ-SECRET-01",
            provider="custom",
            model_name="model-1",
            status=ModelResponseStatus.ERROR,
            error="ADAPTER_EXCEPTION: Authorization: Bearer provider-token-123456 api_key=secret-value-999",
        )

        self.assertNotIn("provider-token-123456", response.error or "")
        self.assertNotIn("secret-value-999", response.error or "")
        self.assertIn("[REDACTED", response.error or "")

    def test_stream_error_safe_message_is_sanitized_defense_in_depth(self) -> None:
        error = ModelStreamError(
            code="AUTH_ERROR",
            category="AUTHENTICATION",
            safe_message="provider failed with password=hunter2 and Bearer stream-token-123456",
            retryable=False,
        )

        self.assertNotIn("hunter2", error.safe_message)
        self.assertNotIn("stream-token-123456", error.safe_message)

    def test_execution_receipt_error_message_is_sanitized_before_persistence(self) -> None:
        now = datetime.now(timezone.utc)
        receipt = ExecutionReceipt(
            run_id="RUN-SECRET-01",
            agent_id="intelligence",
            capability_id="web_search",
            provider="real_web_connector",
            request_hash="a" * 64,
            started_at=now,
            completed_at=now,
            status=ExecutionStatus.ERROR,
            error_class="EXECUTION_EXCEPTION",
            error_message="request failed: Authorization: Bearer tool-token-123456 api_key=tool-key-999999",
        )

        self.assertNotIn("tool-token-123456", receipt.error_message or "")
        self.assertNotIn("tool-key-999999", receipt.error_message or "")
        self.assertIn("[REDACTED", receipt.error_message or "")

    def test_benign_diagnostics_are_preserved(self) -> None:
        raw = "NETWORK_ERROR: connection reset by peer"
        self.assertEqual(sanitize_sensitive_text(raw), raw)


if __name__ == "__main__":
    unittest.main()
