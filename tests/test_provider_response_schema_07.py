"""Regression tests for malformed OpenAI-compatible provider responses.

FIX-PROVIDER-RESPONSE-SCHEMA-07
"""

from __future__ import annotations

import json
import unittest

from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter


class StaticTransport:
    def __init__(self, response_body=None, stream_events=None):
        self.response_body = response_body
        self.stream_events = list(stream_events or [])

    def post_json(self, endpoint_path, payload, timeout_seconds=None):
        body = self.response_body
        if not isinstance(body, str):
            body = json.dumps(body)
        return 200, {}, body

    def post_json_stream(self, endpoint_path, payload, timeout_seconds=None):
        for event in self.stream_events:
            yield event


class TestProviderResponseSchema07(unittest.TestCase):
    def _request(self):
        return ModelRequest(
            request_id="REQ-RESP-SCHEMA-07",
            model_name="model-test",
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
        )

    def _adapter(self, *, response_body=None, stream_events=None):
        return OpenAICompatibleProviderAdapter(
            provider_id="schema-test",
            base_url="https://api.example.com/v1",
            api_key_env="SCHEMA_TEST_KEY",
            default_model="model-test",
            api_key="test-secret",
            transport=StaticTransport(
                response_body=response_body,
                stream_events=stream_events,
            ),
        )

    def _assert_sync_response_error(self, body):
        adapter = self._adapter(response_body=body)
        response = adapter.generate(self._request())
        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("PROVIDER_RESPONSE_ERROR", response.error or "")
        self.assertEqual(response.metadata.get("error_code"), "PROVIDER_RESPONSE_ERROR")
        self.assertEqual(response.usage.usage_source, "NOT_AVAILABLE")

    def test_sync_malformed_structures_fail_closed_without_exception(self):
        malformed_bodies = [
            [],
            {"choices": None},
            {"choices": {}},
            {"choices": "not-a-list"},
            {"choices": [None]},
            {"choices": [{"message": None}]},
            {"choices": [{"message": "not-an-object"}]},
            {"choices": [{"message": {"content": ["not", "text"]}}]},
            {"choices": [{"message": {"content": "ok"}, "finish_reason": {"bad": True}}]},
        ]
        for body in malformed_bodies:
            with self.subTest(body=body):
                self._assert_sync_response_error(body)

    def test_sync_malformed_json_is_structured_error(self):
        adapter = self._adapter(response_body="{not-valid-json")
        response = adapter.generate(self._request())
        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("PROVIDER_RESPONSE_ERROR", response.error or "")
        self.assertEqual(response.metadata.get("error_code"), "PROVIDER_RESPONSE_ERROR")

    def test_sync_missing_or_malformed_usage_does_not_destroy_valid_content(self):
        usage_variants = [
            None,
            "not-an-object",
            [],
            {"prompt_tokens": "bad"},
            {"completion_tokens": -1},
            {"total_tokens": True},
        ]
        for usage in usage_variants:
            with self.subTest(usage=usage):
                adapter = self._adapter(
                    response_body={
                        "model": "provider-model",
                        "choices": [
                            {"message": {"content": "valid answer"}, "finish_reason": "stop"}
                        ],
                        "usage": usage,
                    }
                )
                response = adapter.generate(self._request())
                self.assertEqual(response.status, ModelResponseStatus.SUCCESS)
                self.assertEqual(response.content, "valid answer")
                self.assertEqual(response.usage.usage_source, "NOT_AVAILABLE")

    def test_sync_valid_usage_accepts_safe_numeric_strings_and_null_detail_objects(self):
        adapter = self._adapter(
            response_body={
                "model": None,
                "choices": [{"message": {"content": "ok"}, "finish_reason": None}],
                "usage": {
                    "prompt_tokens": "3",
                    "completion_tokens": 2,
                    "total_tokens": 5.0,
                    "completion_tokens_details": None,
                    "prompt_tokens_details": None,
                },
            }
        )
        response = adapter.generate(self._request())
        self.assertEqual(response.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(response.model_name, "model-test")
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.usage.usage_source, "PROVIDER_REPORTED")
        self.assertEqual(response.usage.prompt_tokens, 3)
        self.assertEqual(response.usage.completion_tokens, 2)
        self.assertEqual(response.usage.total_tokens, 5)

    def test_sync_valid_nested_usage_details_are_parsed(self):
        adapter = self._adapter(
            response_body={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 4,
                    "total_tokens": 11,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                    "prompt_tokens_details": {"cached_tokens": 3},
                    "tool_use_prompt_tokens": 1,
                },
            }
        )
        response = adapter.generate(self._request())
        self.assertEqual(response.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(response.usage.thoughts_tokens, 2)
        self.assertEqual(response.usage.cached_tokens, 3)
        self.assertEqual(response.usage.tool_use_prompt_tokens, 1)

    def _assert_stream_schema_error(self, events):
        adapter = self._adapter(stream_events=events)
        deltas = list(adapter.generate_stream(self._request()))
        self.assertEqual(len(deltas), 1)
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertEqual(deltas[0].error.code, "PROVIDER_RESPONSE_ERROR")
        self.assertEqual(deltas[0].error.category, "RESPONSE_ERROR")

    def test_stream_malformed_events_fail_closed_without_exception(self):
        malformed_streams = [
            ["not-an-object"],
            [{"choices": {}}],
            [{"choices": [None]}],
            [{"choices": [{"delta": "not-an-object"}]}],
            [{"choices": [{"delta": {"content": ["not", "text"]}}]}],
            [{"choices": [{"delta": {"content": "ok"}, "finish_reason": {"bad": True}}]}],
        ]
        for events in malformed_streams:
            with self.subTest(events=events):
                self._assert_stream_schema_error(events)

    def test_stream_metadata_only_event_can_be_ignored_before_valid_content(self):
        adapter = self._adapter(
            stream_events=[
                {"usage": {"prompt_tokens": 1}},
                {"model": None, "choices": [{"delta": {"role": "assistant", "content": "hi"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
        )
        deltas = list(adapter.generate_stream(self._request()))
        self.assertEqual([d.content for d in deltas], ["hi", ""])
        self.assertIsNone(deltas[0].error)
        self.assertEqual(deltas[0].model_name, "model-test")
        self.assertEqual(deltas[-1].finish_reason, "stop")
        self.assertIsNone(deltas[-1].error)


if __name__ == "__main__":
    unittest.main()
