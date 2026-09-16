from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from integrations.models.base import ModelMessage, ModelRequest, ModelResponseStatus, ModelRole
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter


class SequenceTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post_json(self, *, endpoint_path, payload, timeout_seconds):
        self.calls += 1
        if not self.responses:
            raise AssertionError("Transport called more times than expected")
        return self.responses.pop(0)


def success_response(content: str = "ok"):
    return (
        200,
        {},
        json.dumps(
            {
                "id": "chatcmpl-retry-test",
                "object": "chat.completion",
                "model": "retry-test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ),
    )


def error_response(status_code: int, message: str):
    return (
        status_code,
        {},
        json.dumps({"error": {"message": message}}),
    )


class OpenAICompatibleTransientRetryV1Tests(unittest.TestCase):
    def _request(self) -> ModelRequest:
        return ModelRequest(
            model_name="retry-test-model",
            messages=[ModelMessage(role=ModelRole.USER, content="ping")],
            timeout_seconds=10.0,
        )

    def _adapter(self, transport: SequenceTransport) -> OpenAICompatibleProviderAdapter:
        return OpenAICompatibleProviderAdapter(
            provider_id="retry-test",
            base_url="https://example.invalid/v1",
            api_key_env="",
            default_model="retry-test-model",
            api_key="temporary-test-secret",
            timeout_seconds=10.0,
            transport=transport,
        )

    @patch("integrations.models.openai_compatible_adapter.time.sleep")
    def test_transient_502_then_200_recovers_with_one_retry(self, sleep_mock) -> None:
        transport = SequenceTransport(
            [
                error_response(502, "temporary bad gateway"),
                success_response("recovered"),
            ]
        )
        response = self._adapter(transport).generate(self._request())

        self.assertEqual(ModelResponseStatus.SUCCESS, response.status)
        self.assertEqual("recovered", response.content)
        self.assertEqual(2, transport.calls)
        self.assertEqual(2, response.metadata.get("transport_attempts"))
        self.assertEqual(1, sleep_mock.call_count)

    @patch("integrations.models.openai_compatible_adapter.time.sleep")
    def test_persistent_502_stops_after_three_transport_attempts(self, sleep_mock) -> None:
        transport = SequenceTransport(
            [
                error_response(502, "temporary bad gateway 1"),
                error_response(502, "temporary bad gateway 2"),
                error_response(502, "temporary bad gateway 3"),
            ]
        )
        response = self._adapter(transport).generate(self._request())

        self.assertEqual(ModelResponseStatus.ERROR, response.status)
        self.assertEqual(3, transport.calls)
        self.assertTrue(response.metadata.get("retryable"))
        self.assertTrue(response.metadata.get("retry_exhausted"))
        self.assertEqual(3, response.metadata.get("transport_attempts"))
        self.assertEqual(2, sleep_mock.call_count)

    @patch("integrations.models.openai_compatible_adapter.time.sleep")
    def test_non_retryable_401_is_not_retried(self, sleep_mock) -> None:
        transport = SequenceTransport([error_response(401, "invalid credential")])
        response = self._adapter(transport).generate(self._request())

        self.assertEqual(ModelResponseStatus.ERROR, response.status)
        self.assertEqual(1, transport.calls)
        self.assertFalse(response.metadata.get("retryable"))
        self.assertFalse(response.metadata.get("retry_exhausted"))
        self.assertEqual(1, response.metadata.get("transport_attempts"))
        sleep_mock.assert_not_called()

    def test_retry_policy_preserves_one_logical_model_request(self) -> None:
        self.assertEqual(3, OpenAICompatibleProviderAdapter._SYNC_MAX_TRANSPORT_ATTEMPTS)
        self.assertEqual(2, len(OpenAICompatibleProviderAdapter._SYNC_RETRY_BACKOFF_SECONDS))


if __name__ == "__main__":
    unittest.main()
