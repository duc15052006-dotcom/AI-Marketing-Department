"""Hermetic regression tests for OpenAI-compatible SSE transport parsing.

FIX-SSE-PARSER-06
"""

from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from integrations.models.transport import OpenAICompatibleTransport


class FakeSSEHeaders:
    def items(self):
        return []


class FakeSSEResponse:
    def __init__(self, lines=None, read_error=None, read_error_at=0):
        self._lines = list(lines or [])
        self._index = 0
        self._read_error = read_error
        self._read_error_at = read_error_at
        self.closed = False
        self.headers = FakeSSEHeaders()

    def readline(self):
        if self._read_error is not None and self._index == self._read_error_at:
            self._index += 1
            raise self._read_error
        if self._index >= len(self._lines):
            return b""
        value = self._lines[self._index]
        self._index += 1
        return value

    def read(self, *args, **kwargs):
        raise AssertionError("post_json_stream must not use byte/body read()")

    def close(self):
        self.closed = True


class TestSSEParser06(unittest.TestCase):
    def setUp(self):
        self.transport = OpenAICompatibleTransport(
            base_url="https://api.example.com/v1",
            api_key="test-key",
        )

    def _collect(self, lines):
        response = FakeSSEResponse(lines=lines)
        with patch("urllib.request.urlopen", return_value=response):
            events = list(self.transport.post_json_stream("/chat/completions", {"stream": True}))
        return events, response

    def test_accepts_data_field_with_and_without_optional_space(self):
        events, response = self._collect([
            b'data:{"n":1}\n', b'\n',
            b'data: {"n":2}\n', b'\n',
        ])
        self.assertEqual(events, [{"n": 1}, {"n": 2}])
        self.assertTrue(response.closed)

    def test_crlf_and_multiple_events_preserve_order(self):
        events, response = self._collect([
            b'data: {"n":1}\r\n', b'\r\n',
            b'data:{"n":2}\r\n', b'\r\n',
            b'data: [DONE]\r\n', b'\r\n',
        ])
        self.assertEqual(events, [{"n": 1}, {"n": 2}, {"_done": True}])
        self.assertTrue(response.closed)

    def test_multiline_data_event_is_joined_before_json_parse(self):
        events, response = self._collect([
            b'data: {"a":\n',
            b'data: 1}\n',
            b'\n',
        ])
        self.assertEqual(events, [{"a": 1}])
        self.assertTrue(response.closed)

    def test_comments_and_non_data_fields_are_ignored(self):
        events, _ = self._collect([
            b': keepalive\n',
            b'event: message\n',
            b'id: 42\n',
            b'retry: 1000\n',
            b'data: {"ok":true}\n',
            b'\n',
        ])
        self.assertEqual(events, [{"ok": True}])

    def test_done_without_trailing_newline_is_dispatched_at_eof(self):
        events, response = self._collect([b'data: [DONE]'])
        self.assertEqual(events, [{"_done": True}])
        self.assertTrue(response.closed)

    def test_json_event_without_trailing_blank_line_is_dispatched_at_eof(self):
        events, _ = self._collect([b'data:{"ok":true}'])
        self.assertEqual(events, [{"ok": True}])

    def test_malformed_event_is_ignored_and_next_valid_event_survives(self):
        events, _ = self._collect([
            b'data: {not-json}\n', b'\n',
            b'data: {"ok":true}\n', b'\n',
        ])
        self.assertEqual(events, [{"ok": True}])

    def test_non_object_json_event_is_ignored(self):
        events, _ = self._collect([
            b'data: [1,2,3]\n', b'\n',
            b'data: {"ok":true}\n', b'\n',
        ])
        self.assertEqual(events, [{"ok": True}])

    def test_response_closes_when_consumer_closes_generator_early(self):
        response = FakeSSEResponse(lines=[
            b'data: {"n":1}\n', b'\n',
            b'data: {"n":2}\n', b'\n',
        ])
        with patch("urllib.request.urlopen", return_value=response):
            gen = self.transport.post_json_stream("/chat/completions", {"stream": True})
            self.assertEqual(next(gen), {"n": 1})
            self.assertFalse(response.closed)
            gen.close()
        self.assertTrue(response.closed)

    def test_timeout_during_read_yields_structured_error_and_closes(self):
        response = FakeSSEResponse(read_error=socket.timeout("read timed out"))
        with patch("urllib.request.urlopen", return_value=response):
            events = list(self.transport.post_json_stream("/chat/completions", {"stream": True}))
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["_error"])
        self.assertEqual(events[0]["status_code"], 408)
        self.assertTrue(events[0]["is_timeout"])
        self.assertFalse(events[0]["is_network"])
        self.assertTrue(response.closed)

    def test_network_error_during_read_yields_structured_error_and_closes(self):
        response = FakeSSEResponse(read_error=ConnectionResetError("connection reset"))
        with patch("urllib.request.urlopen", return_value=response):
            events = list(self.transport.post_json_stream("/chat/completions", {"stream": True}))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status_code"], 599)
        self.assertTrue(events[0]["is_network"])
        self.assertFalse(events[0]["is_timeout"])
        self.assertTrue(response.closed)

    def test_generic_read_error_is_internal_and_closes(self):
        response = FakeSSEResponse(read_error=RuntimeError("parser-side failure"))
        with patch("urllib.request.urlopen", return_value=response):
            events = list(self.transport.post_json_stream("/chat/completions", {"stream": True}))
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["status_code"])
        self.assertTrue(events[0]["is_internal"])
        self.assertFalse(events[0]["is_network"])
        self.assertFalse(events[0]["is_timeout"])
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
