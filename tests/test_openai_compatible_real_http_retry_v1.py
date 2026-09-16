from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from integrations.models.base import ModelMessage, ModelRequest, ModelResponseStatus, ModelRole
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter


class _RetryProbeHandler(BaseHTTPRequestHandler):
    request_count = 0
    lock = threading.Lock()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length:
            self.rfile.read(content_length)

        with type(self).lock:
            type(self).request_count += 1
            attempt = type(self).request_count

        if attempt == 1:
            status = 502
            payload = {"error": {"message": "synthetic transient bad gateway"}}
        else:
            status = 200
            payload = {
                "id": "chatcmpl-real-http-retry",
                "object": "chat.completion",
                "model": "retry-http-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "recovered-over-http"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


class OpenAICompatibleRealHttpRetryV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        _RetryProbeHandler.request_count = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _RetryProbeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @patch("integrations.models.openai_compatible_adapter.time.sleep")
    def test_real_http_502_then_200_retries_and_recovers(self, sleep_mock) -> None:
        host, port = self.server.server_address
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="real-http-retry",
            base_url=f"http://{host}:{port}/v1",
            api_key_env="",
            default_model="retry-http-model",
            api_key="temporary-test-secret",
            timeout_seconds=5.0,
        )
        request = ModelRequest(
            model_name="retry-http-model",
            messages=[ModelMessage(role=ModelRole.USER, content="ping")],
            timeout_seconds=5.0,
        )

        response = adapter.generate(request)

        self.assertEqual(ModelResponseStatus.SUCCESS, response.status)
        self.assertEqual("recovered-over-http", response.content)
        self.assertEqual(2, _RetryProbeHandler.request_count)
        self.assertEqual(2, response.metadata.get("transport_attempts"))
        self.assertEqual(1, sleep_mock.call_count)


if __name__ == "__main__":
    unittest.main()
