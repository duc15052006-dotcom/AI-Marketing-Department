"""Regression tests for public-safe SSE error redaction.

FIX-STREAM-ERROR-REDACTION-10
"""

from __future__ import annotations

import json
import unittest

from app_api.streaming import StreamingChatBridge, sanitize_error_for_stream


class StructuredFailure(Exception):
    error_code = "PROVIDER_RESPONSE_ERROR"


class TestStreamErrorRedaction10(unittest.TestCase):
    def test_generic_exception_never_echoes_secret_or_internal_path(self) -> None:
        secret = "sk-super-private-token-123456789"
        internal_path = r"C:\\Users\\DUCK\\private\\provider.json"
        result = sanitize_error_for_stream(
            RuntimeError(f"request failed api_key='{secret}' config={internal_path}")
        )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["error"], "EXECUTION_ERROR")
        self.assertNotIn(secret, serialized)
        self.assertNotIn(internal_path, serialized)
        self.assertNotIn("api_key", result["message"].lower())

    def test_structured_machine_code_is_preserved_without_raw_details(self) -> None:
        secret = "Bearer top-secret-credential"
        err = StructuredFailure(f"PROVIDER_RESPONSE_ERROR: {secret} C:\\private\\trace.txt")
        result = sanitize_error_for_stream(err)

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["error"], "PROVIDER_RESPONSE_ERROR")
        self.assertNotIn("top-secret-credential", serialized)
        self.assertNotIn("trace.txt", serialized)

    def test_structured_dict_code_is_preserved_but_message_is_not_reflected(self) -> None:
        result = sanitize_error_for_stream(
            {
                "error": "MISSING_CREDENTIAL",
                "message": "Authorization: Bearer should-never-reach-browser",
            }
        )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["error"], "MISSING_CREDENTIAL")
        self.assertNotIn("should-never-reach-browser", serialized)
        self.assertNotIn("Authorization", serialized)

    def test_unsafe_error_code_is_not_reflected(self) -> None:
        result = sanitize_error_for_stream(
            {"error": "BAD\nINJECT", "message": "sensitive internal detail"}
        )
        self.assertEqual(result["error"], "EXECUTION_ERROR")
        self.assertNotIn("sensitive internal detail", result["message"])

    def test_known_categories_remain_actionable_without_raw_details(self) -> None:
        connection = sanitize_error_for_stream(
            RuntimeError("Connection refused at 127.0.0.1:9999 token=abc-secret")
        )
        auth = sanitize_error_for_stream(
            RuntimeError("HTTP 401 Unauthorized api_key=sk-private-private")
        )
        rate = sanitize_error_for_stream(
            RuntimeError("HTTP 429 rate limit exceeded Bearer private-rate-token")
        )

        self.assertEqual(connection["error"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(auth["error"], "AUTHENTICATION_FAILED")
        self.assertEqual(rate["error"], "RATE_LIMITED")
        serialized = json.dumps([connection, auth, rate], ensure_ascii=False)
        for leaked in ("abc-secret", "sk-private-private", "private-rate-token"):
            self.assertNotIn(leaked, serialized)

    def test_bridge_terminal_error_frame_contains_only_sanitized_payload(self) -> None:
        bridge = StreamingChatBridge()
        secret = "sk-bridge-secret-123456789"
        bridge.send_error(RuntimeError(f"password={secret} C:\\private\\bridge.log"))

        frames: list[bytes] = []
        bridge.drain_to_writer(frames.append, lambda: None)

        payload = b"".join(frames).decode("utf-8")
        self.assertIn("event: error", payload)
        self.assertIn("EXECUTION_ERROR", payload)
        self.assertNotIn(secret, payload)
        self.assertNotIn("bridge.log", payload)


if __name__ == "__main__":
    unittest.main()
