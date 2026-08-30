"""Regression tests for finite SSE fallback on nonstandard response wrappers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from integrations.models.transport import OpenAICompatibleTransport


class TestSSEResponseWrapper06B(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = OpenAICompatibleTransport("https://api.example.com/v1", api_key="test-key")

    def _collect(self, response: MagicMock):
        with patch("urllib.request.urlopen", return_value=response):
            return list(self.transport.post_json_stream("/chat/completions", {"stream": True}))

    @staticmethod
    def _legacy_response() -> MagicMock:
        response = MagicMock()
        # Mirrors legacy/custom wrappers whose readline() does not implement
        # HTTPResponse's binary contract. This must trigger one finite read().
        response.readline.return_value = MagicMock(name="opaque-line")
        return response

    def test_legacy_read_valueerror_is_internal_and_finite(self) -> None:
        response = self._legacy_response()
        response.read.side_effect = ValueError("unexpected parser bug")
        events = self._collect(response)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["is_internal"])
        self.assertFalse(events[0]["is_network"])
        self.assertEqual(response.read.call_count, 1)
        response.close.assert_called_once()

    def test_legacy_permissionerror_is_internal_not_network(self) -> None:
        response = self._legacy_response()
        response.read.side_effect = PermissionError("local filesystem permission denied")
        events = self._collect(response)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["is_internal"])
        self.assertFalse(events[0]["is_network"])
        self.assertEqual(response.read.call_count, 1)

    def test_legacy_connection_reset_is_network(self) -> None:
        response = self._legacy_response()
        response.read.side_effect = ConnectionResetError("connection reset by peer")
        events = self._collect(response)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status_code"], 599)
        self.assertTrue(events[0]["is_network"])
        self.assertEqual(response.read.call_count, 1)

    def test_legacy_body_is_parsed_once_and_done_terminates(self) -> None:
        response = self._legacy_response()
        response.read.return_value = (
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            b'data: [DONE]\n\n'
            b'data: {"ignored":true}\n\n'
        )
        events = self._collect(response)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["choices"][0]["delta"]["content"], "hello")
        self.assertEqual(events[1], {"_done": True})
        self.assertEqual(response.read.call_count, 1)
        response.close.assert_called_once()

    def test_nonbinary_fallback_body_fails_closed_and_finite(self) -> None:
        response = self._legacy_response()
        response.read.return_value = MagicMock(name="opaque-body")
        events = self._collect(response)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["is_internal"])
        self.assertIn("STREAM_RESPONSE_READ_TYPE_ERROR", events[0]["body"])
        self.assertEqual(response.read.call_count, 1)
        response.close.assert_called_once()

    def test_normal_binary_readline_path_does_not_call_body_read(self) -> None:
        response = MagicMock()
        response.readline.side_effect = [b'data: {"ok":true}\n', b'\n', b'']
        response.read.side_effect = AssertionError("body fallback must not run")
        events = self._collect(response)
        self.assertEqual(events, [{"ok": True}])
        response.read.assert_not_called()
        response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
