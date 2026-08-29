"""Production Test Suite for Python Backend Streaming Endpoint (B3).

Validates:
- Strict authenticated boundary (401 on missing/invalid bearer token).
- text/event-stream Content-Type with NO Content-Length header.
- Well-formed UTF-8 double-newline delimited SSE frame structure.
- Clean separation of B2 trusted RuntimeProgressEvents from B1 user-visible StreamDeltas.
- Zero leakage of internal reasoning tokens, secrets, API keys, or raw provider headers.
- Single terminal outcome: exactly one complete OR error, never both.
- General conversation streaming: emits RUN_STARTED/MODEL_STARTED/deltas/complete, no fake research/department progress.
- Research fast-path streaming: emits evidence-ready progress before first Intelligence text delta, 0 fake Final CMO.
- Full 6-stage workflow streaming: 6-stage progress emitted; only Final CMO emits visible text deltas (internal agents do not stream raw text).
- Single model execution (no redundant non-streaming generate() call for final response).
- Resilient client disconnect handling without backend crashes or resource leaks.
- Preserves existing synchronous chat and health endpoints.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import HTTPServer
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from app_api.server import (
    GLOBAL_API_SESSION_TOKEN,
    DepartmentAPIHandler,
    APP_BACKEND,
)
from app_api.streaming import (
    SSEEventType,
    StreamState,
    StreamingChatBridge,
    format_sse_event,
    sanitize_error_for_stream,
)
from chat.session import ChatRole
from tools.receipts import ExecutionReceipt, ExecutionStatus
from integrations.models.base import (
    CostPolicy,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    StreamDelta,
)
from integrations.models.gateway import UniversalModelGateway
from runtime.context import RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.progress import (
    ProgressEventType,
    ProgressMode,
    ProgressStage,
    RuntimeProgressEvent,
)


class FakeStreamingModelGateway(UniversalModelGateway):
    """Mock Gateway capable of streaming pre-configured chunks."""

    def __init__(self, chunks: Optional[List[str]] = None, fail_after_chunk: int = -1, raise_immediate: Optional[Exception] = None) -> None:
        super().__init__(free_only_mode=True)
        self.chunks = chunks if chunks is not None else ["Xin ", "chào! ", "Tôi ", "có ", "thể ", "giúp ", "gì?"]
        self.fail_after_chunk = fail_after_chunk
        self.raise_immediate = raise_immediate
        self.generate_call_count = 0
        self.generate_stream_call_count = 0

    def generate(self, request: ModelRequest, *args: Any, **kwargs: Any) -> ModelResponse:
        self.generate_call_count += 1
        if self.raise_immediate:
            raise self.raise_immediate
        return ModelResponse(
            request_id="REQ-TEST",
            provider="fake_streaming",
            model_name="fake-model",
            status=ModelResponseStatus.SUCCESS,
            content="".join(self.chunks),
        )

    def generate_stream(self, request: ModelRequest, *args: Any, **kwargs: Any) -> Any:
        self.generate_stream_call_count += 1
        if self.raise_immediate:
            raise self.raise_immediate

        def _gen():
            for idx, c in enumerate(self.chunks):
                if self.fail_after_chunk >= 0 and idx >= self.fail_after_chunk:
                    yield StreamDelta(
                        content="",
                        finish_reason="error",
                        provider="fake_streaming",
                        model_name="fake-model",
                    )
                    return
                yield StreamDelta(
                    content=c,
                    finish_reason=None if idx < len(self.chunks) - 1 else "stop",
                    provider="fake_streaming",
                    model_name="fake-model",
                )
        return _gen()


def parse_sse_frames(raw_body: str) -> List[Dict[str, Any]]:
    """Parse raw SSE text into a list of event objects {event, data}."""
    frames = []

    for block in raw_body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = "message"
        data_lines = []
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            data_str = "\n".join(data_lines)
            try:
                parsed_json = json.loads(data_str)
            except Exception:
                parsed_json = data_str
            frames.append({"event": event_name, "data": parsed_json})

    return frames


def make_mock_receipt(exec_id: str = "mock_exec") -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=exec_id,
        run_id="RUN-MOCK-01",
        agent_id="intelligence",
        capability_id="web_search",
        provider="mock",
        request_hash="mock_hash",
        status=ExecutionStatus.SUCCESS,
        data={"results": [{"title": "Mock search", "snippet": "Market info", "url": "https://example.com"}]},
    )


class TestPythonStreamingEndpoint01(unittest.TestCase):
    """B3 Suite: Authenticated Python Backend Streaming Endpoint Tests."""

    @classmethod
    def setUpClass(cls) -> None:
        # Start a local test HTTP server
        cls.server = HTTPServer(("127.0.0.1", 0), DepartmentAPIHandler)
        cls.server_port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.server_port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.orig_chat_gw = APP_BACKEND.chat_engine.model_gateway
        self.orig_runtime_gw = APP_BACKEND.runtime.model_gateway
        self.orig_tool_gw_exec = APP_BACKEND.runtime.tool_gateway.execute
        self.fake_gw = FakeStreamingModelGateway()
        APP_BACKEND.chat_engine.model_gateway = self.fake_gw  # type: ignore[assignment]
        APP_BACKEND.runtime.model_gateway = self.fake_gw  # type: ignore[assignment]
        APP_BACKEND.runtime.tool_gateway.execute = MagicMock(side_effect=lambda req: make_mock_receipt(req.run_id))

    def tearDown(self) -> None:
        APP_BACKEND.chat_engine.model_gateway = self.orig_chat_gw
        APP_BACKEND.runtime.model_gateway = self.orig_runtime_gw
        APP_BACKEND.runtime.tool_gateway.execute = self.orig_tool_gw_exec

    def _post_json(self, path: str, body: Dict[str, Any], token: Optional[str] = GLOBAL_API_SESSION_TOKEN, headers_extra: Optional[Dict[str, str]] = None) -> urllib.request.HTTPResponse:
        url = f"{self.base_url}{path}"
        data_bytes = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Host", f"127.0.0.1:{self.server_port}")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        if headers_extra:
            for k, v in headers_extra.items():
                req.add_header(k, v)
        return urllib.request.urlopen(req, timeout=10.0)

    # 1. streaming endpoint requires backend authentication
    def test_01_streaming_endpoint_requires_authentication(self) -> None:
        url = f"{self.base_url}/api/chat/stream"
        req = urllib.request.Request(url, data=b'{"content":"test"}', method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Host", f"127.0.0.1:{self.server_port}")
        # Missing Authorization
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5.0)
        self.assertEqual(ctx.exception.code, 401)

    # 2. invalid bearer rejected
    def test_02_invalid_bearer_token_rejected(self) -> None:
        url = f"{self.base_url}/api/chat/stream"
        req = urllib.request.Request(url, data=b'{"content":"test"}', method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Host", f"127.0.0.1:{self.server_port}")
        req.add_header("Authorization", "Bearer invalid_fabricated_token_xyz")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5.0)
        self.assertEqual(ctx.exception.code, 401)

    # 3. Content-Type is text/event-stream; charset=utf-8
    def test_03_content_type_is_event_stream(self) -> None:
        resp = self._post_json("/api/chat/stream", {"content": "xin chào"})
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn("text/event-stream", content_type)

    # 4. No Content-Length on live SSE
    def test_04_no_content_length_on_live_sse(self) -> None:
        resp = self._post_json("/api/chat/stream", {"content": "xin chào"})
        content_length = resp.headers.get("Content-Length")
        self.assertIsNone(content_length)

    # 5. SSE frames are valid UTF-8 and blank-line terminated
    def test_05_sse_frames_valid_utf8_and_terminated(self) -> None:
        frame = format_sse_event(SSEEventType.DELTA, {"content": "Tiếng Việt có dấu 🚀"})
        self.assertIsInstance(frame, bytes)
        decoded = frame.decode("utf-8")
        self.assertTrue(decoded.endswith("\n\n"))
        self.assertTrue(decoded.startswith("event: delta\n"))

    # 6. format_sse_event rejects newline injection
    def test_06_format_sse_event_rejects_newline_injection(self) -> None:
        with self.assertRaises(ValueError):
            format_sse_event("delta\ninjected: header", {"test": 1})

    # 7. Progress frame contains RuntimeProgressEvent data
    def test_07_progress_frame_contains_runtime_progress_event(self) -> None:
        event = RuntimeProgressEvent(
            run_id="RUN-TEST-01",
            sequence=1,
            event_type=ProgressEventType.RUN_STARTED,
            mode=ProgressMode.GENERAL_CONVERSATION.value,
            message="Khởi động",
        )
        frame = format_sse_event(SSEEventType.PROGRESS, event)
        decoded = frame.decode("utf-8")
        self.assertIn("RUN_STARTED", decoded)
        self.assertIn("RUN-TEST-01", decoded)

    # 8. Model delta frame contains visible assistant text only
    def test_08_model_delta_frame_contains_visible_assistant_text_only(self) -> None:
        bridge = StreamingChatBridge()
        bridge.send_delta("Đoạn văn bản đầu tiên", provider="xkiro", model_name="v4-pro")
        bridge.send_complete({"status": "COMPLETED"})
        frames = []
        bridge.drain_to_writer(frames.append, lambda: None)
        raw_sse = b"".join(frames).decode("utf-8")
        parsed = parse_sse_frames(raw_sse)
        deltas = [f for f in parsed if f["event"] == "delta"]
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0]["data"]["content"], "Đoạn văn bản đầu tiên")

    # 9. No reasoning / internal provider text leaks
    def test_09_no_reasoning_or_internal_keys_leak(self) -> None:
        delta = StreamDelta(content="Hello", finish_reason="stop", provider="test", model_name="m1")
        self.assertFalse(hasattr(delta, "reasoning_content"))
        self.assertFalse(hasattr(delta, "api_key"))

    # 10. Exactly one terminal complete on success
    def test_10_exactly_one_terminal_complete_on_success(self) -> None:
        resp = self._post_json("/api/chat/stream", {"content": "xin chào"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        terminal_completes = [f for f in parsed if f["event"] == "complete"]
        terminal_errors = [f for f in parsed if f["event"] == "error"]
        self.assertEqual(len(terminal_completes), 1)
        self.assertEqual(len(terminal_errors), 0)

    # 11. Exactly one terminal error on failure
    def test_11_exactly_one_terminal_error_on_failure(self) -> None:
        bridge = StreamingChatBridge()
        bridge.send_error("Simulated execution failure")
        frames = []
        bridge.drain_to_writer(frames.append, lambda: None)
        raw_sse = b"".join(frames).decode("utf-8")
        parsed = parse_sse_frames(raw_sse)
        terminal_completes = [f for f in parsed if f["event"] == "complete"]
        terminal_errors = [f for f in parsed if f["event"] == "error"]
        self.assertEqual(len(terminal_errors), 1)
        self.assertEqual(len(terminal_completes), 0)

    # 12. Complete never follows error
    def test_12_complete_never_follows_error(self) -> None:
        bridge = StreamingChatBridge()
        bridge.send_error("First error")
        bridge.send_complete({"status": "COMPLETED"})  # Ignored
        frames = []
        bridge.drain_to_writer(frames.append, lambda: None)
        raw_sse = b"".join(frames).decode("utf-8")
        parsed = parse_sse_frames(raw_sse)
        events = [f["event"] for f in parsed]
        self.assertEqual(events, ["error"])

    # 13. Error never follows successful complete
    def test_13_error_never_follows_complete(self) -> None:
        bridge = StreamingChatBridge()
        bridge.send_complete({"status": "COMPLETED"})
        bridge.send_error("Late error")  # Ignored
        frames = []
        bridge.drain_to_writer(frames.append, lambda: None)
        raw_sse = b"".join(frames).decode("utf-8")
        parsed = parse_sse_frames(raw_sse)
        events = [f["event"] for f in parsed]
        self.assertEqual(events, ["complete"])

    # 14. General model stream assembles exact final answer
    def test_14_general_model_stream_assembles_exact_final_answer(self) -> None:
        self.fake_gw.chunks = ["Xin ", "chào ", "bạn!"]
        resp = self._post_json("/api/chat/stream", {"content": "Ai là người tạo ra tiếp thị?"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        deltas = [f["data"]["content"] for f in parsed if f["event"] == "delta"]
        self.assertEqual("".join(deltas), "Xin chào bạn!")
        complete_event = next(f for f in parsed if f["event"] == "complete")
        self.assertEqual(complete_event["data"]["content"], "Xin chào bạn!")

    # 15. General does not emit fake research / stage progress
    def test_15_general_does_not_emit_fake_research_or_stage_progress(self) -> None:
        self.fake_gw.chunks = ["Trả ", "lời."]
        resp = self._post_json("/api/chat/stream", {"content": "Giải thích khái niệm ROI?"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        progress_events = [f["data"] for f in parsed if f["event"] == "progress" and isinstance(f["data"], dict)]
        for pe in progress_events:
            self.assertNotEqual(pe.get("event_type"), "RESEARCH_STARTED")
            self.assertNotEqual(pe.get("stage"), "INTELLIGENCE")
            self.assertNotEqual(pe.get("stage"), "CMO_INITIAL")

    # 16. Research streams progress before first model text delta
    def test_16_research_streams_progress_before_first_delta(self) -> None:
        self.fake_gw.chunks = ["Kết ", "quả ", "nghiên ", "cứu."]
        resp = self._post_json("/api/chat/stream", {"content": "Tìm thông tin thị trường trà sữa 2026"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        events_order = [f["event"] for f in parsed]
        self.assertIn("progress", events_order)
        self.assertIn("delta", events_order)
        self.assertIn("complete", events_order)
        first_delta_idx = events_order.index("delta")
        # Evidence ready must occur before first delta
        progress_types_before_delta = [
            f["data"]["event_type"] for idx, f in enumerate(parsed)
            if idx < first_delta_idx and f["event"] == "progress" and isinstance(f["data"], dict)
        ]
        self.assertIn("RESEARCH_EVIDENCE_READY", progress_types_before_delta)

    # 17. Research remains exactly 1 search + 1 Intelligence execution
    def test_17_research_remains_1_search_and_1_intelligence_execution(self) -> None:
        self.fake_gw.chunks = ["Nghiên ", "cứu."]
        resp = self._post_json("/api/chat/stream", {"content": "Khảo sát thị trường bán lẻ"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        complete_event = next(f for f in parsed if f["event"] == "complete")
        self.assertEqual(complete_event["data"]["five_agent_call_count"], 1)

    # 18. Research emits no fake Final CMO
    def test_18_research_emits_no_fake_final_cmo(self) -> None:
        self.fake_gw.chunks = ["Báo ", "cáo."]
        resp = self._post_json("/api/chat/stream", {"content": "Tìm thông tin thị trường xe điện"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        progress_events = [f["data"] for f in parsed if f["event"] == "progress" and isinstance(f["data"], dict)]
        for pe in progress_events:
            self.assertNotEqual(pe.get("stage"), "FINAL_CMO")

    # 19. Full workflow emits six-stage progress
    def test_19_full_workflow_emits_six_stage_progress(self) -> None:
        self.fake_gw.chunks = ["Kế ", "hoạch ", "tổng ", "thể."]
        resp = self._post_json("/api/chat/stream", {"content": "Lập kế hoạch marketing 90 ngày cho chuỗi spa"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        progress_stages = [
            f["data"]["stage"] for f in parsed
            if f["event"] == "progress" and isinstance(f["data"], dict) and f["data"].get("event_type") == "STAGE_STARTED"
        ]
        self.assertEqual(
            progress_stages,
            ["CMO_INITIAL", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE", "FINAL_CMO"],
        )

    # 20. Final CMO has agent=CMO
    def test_20_final_cmo_has_agent_cmo(self) -> None:
        self.fake_gw.chunks = ["Kế ", "hoạch."]
        resp = self._post_json("/api/chat/stream", {"content": "Lập chiến dịch quảng cáo TikTok Shop"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        final_cmo_stage_events = [
            f["data"] for f in parsed
            if f["event"] == "progress" and isinstance(f["data"], dict) and f["data"].get("stage") == "FINAL_CMO"
        ]
        for fce in final_cmo_stage_events:
            self.assertEqual(fce.get("agent"), "CMO")

    # 21. Only Final CMO text is streamed for full workflow
    def test_21_only_final_cmo_text_streamed_in_full_workflow(self) -> None:
        self.fake_gw.chunks = ["Báo ", "cáo ", "GTM ", "cuối ", "cùng."]
        resp = self._post_json("/api/chat/stream", {"content": "Triển khai chiến dịch ra mắt sản phẩm mới"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        deltas = [f["data"]["content"] for f in parsed if f["event"] == "delta"]
        # Exactly the Final CMO chunks streamed
        self.assertEqual("".join(deltas), "Báo cáo GTM cuối cùng.")

    # 22. Internal stages 1-5 emit zero text deltas in full workflow
    def test_22_internal_stages_emit_zero_text_deltas_in_full_workflow(self) -> None:
        self.fake_gw.chunks = ["Chỉ ", "Final ", "CMO."]
        resp = self._post_json("/api/chat/stream", {"content": "Lập chiến lược content marketing 6 tháng"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        events_order = [f["event"] for f in parsed]
        # Find index of first delta
        self.assertIn("delta", events_order)
        first_delta_idx = events_order.index("delta")
        # All events prior to first delta must be progress events (stages 1 to 5 + stage 6 start)
        events_before_delta = events_order[:first_delta_idx]
        self.assertTrue(all(e == "progress" for e in events_before_delta))
        # Ensure Final CMO stage started before first delta
        progress_types_before_delta = [
            f["data"] for idx, f in enumerate(parsed)
            if idx < first_delta_idx and f["event"] == "progress" and isinstance(f["data"], dict)
        ]
        stages_before_delta = [p.get("stage") for p in progress_types_before_delta if p.get("event_type") == "STAGE_STARTED"]
        self.assertEqual(stages_before_delta, ["CMO_INITIAL", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE", "FINAL_CMO"])

    # 23. Streaming path does not perform second final generate() call
    def test_23_streaming_path_does_not_perform_second_generate_call(self) -> None:
        fake_gw = FakeStreamingModelGateway(chunks=["Nội ", "dung."])
        engine = APP_BACKEND.chat_engine
        engine.model_gateway = fake_gw  # type: ignore[assignment]
        res = engine.generate_chat_response(
            session=APP_BACKEND.chat_mgr.create_session("Test Single Call"),
            user_message="Một câu hỏi bình thường",
            text_delta_sink=lambda d: None,
        )
        self.assertTrue(res["success"])
        # Exactly 1 stream call and 0 generate calls
        self.assertEqual(fake_gw.generate_stream_call_count, 1)
        self.assertEqual(fake_gw.generate_call_count, 0)

    # 24. Sanitized error suppresses WinError and OS details
    def test_24_sanitized_error_suppresses_winerror_and_os_internals(self) -> None:
        raw_error = "WinError 10061 No connection could be made because target machine refused it"
        sanitized = sanitize_error_for_stream(raw_error)
        self.assertEqual(sanitized["error"], "PROVIDER_UNAVAILABLE")
        self.assertNotIn("WinError", sanitized["message"])
        self.assertNotIn("10061", sanitized["message"])

    # 25. Stream contains no secret keys or Authorization tokens
    def test_25_stream_contains_no_api_key_or_auth_token(self) -> None:
        resp = self._post_json("/api/chat/stream", {"content": "xin chào"})
        raw_body = resp.read().decode("utf-8")
        self.assertNotIn(GLOBAL_API_SESSION_TOKEN, raw_body)
        self.assertNotIn("Bearer", raw_body)

    # 26. Sync chat endpoint behavior remains intact
    def test_26_sync_chat_endpoint_behavior_remains_intact(self) -> None:
        resp = self._post_json("/api/chat/sessions/first_turn", {"content": "xin chào", "auto_execute": True})
        self.assertEqual(resp.status, 201)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("message", data)
        self.assertEqual(data["route"], "GENERAL_CONVERSATION")

    # 27. Health endpoint remains intact
    def test_27_health_endpoint_remains_intact(self) -> None:
        url = f"{self.base_url}/api/health"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Host", f"127.0.0.1:{self.server_port}")
        req.add_header("Authorization", f"Bearer {GLOBAL_API_SESSION_TOKEN}")
        resp = urllib.request.urlopen(req, timeout=5.0)
        self.assertEqual(resp.status, 200)

    # 28. Client disconnect does not crash bridge
    def test_28_client_disconnect_does_not_crash_bridge(self) -> None:
        bridge = StreamingChatBridge()
        bridge.send_delta("Chunk 1")
        bridge.send_delta("Chunk 2")
        bridge.send_complete({"status": "COMPLETED"})

        # Simulate broken pipe on writer
        def broken_writer(b: bytes) -> None:
            raise BrokenPipeError("Connection lost")

        # Must exit cleanly without unhandled exception
        bridge.drain_to_writer(broken_writer, lambda: None)
        self.assertTrue(bridge.is_closed)

    # 29. Path /api/chat/sessions/<chat_id>/stream works identically
    def test_29_session_scoped_streaming_endpoint_works(self) -> None:
        session = APP_BACKEND.chat_mgr.create_session("Test Session Route")
        resp = self._post_json(f"/api/chat/sessions/{session.chat_id}/stream", {"content": "xin chào từ session"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        events = [f["event"] for f in parsed]
        self.assertIn("delta", events)
        self.assertIn("complete", events)

    # 30. Post-visible token error emits terminal error
    def test_30_post_visible_token_error_emits_terminal_error(self) -> None:
        # Fails after emitting first chunk
        self.fake_gw.fail_after_chunk = 1
        resp = self._post_json("/api/chat/stream", {"content": "Câu hỏi gây lỗi giữa chừng"})
        raw_body = resp.read().decode("utf-8")
        parsed = parse_sse_frames(raw_body)
        events = [f["event"] for f in parsed]
        self.assertIn("delta", events)
        self.assertIn("error", events)
        self.assertNotIn("complete", events)

    # 31. Stream contains no Authorization header or bearer token
    def test_31_stream_contains_no_bearer_or_auth_header(self) -> None:
        resp = self._post_json("/api/chat/stream", {"content": "Kiểm tra rò rỉ bảo mật"})
        raw_body = resp.read().decode("utf-8")
        self.assertNotIn("Authorization:", raw_body)
        self.assertNotIn("Bearer ", raw_body)

    # 32. Stream contains no credential value
    def test_32_stream_contains_no_credential_value(self) -> None:
        resp = self._post_json("/api/chat/stream", {"content": "Kiểm tra token"})
        raw_body = resp.read().decode("utf-8")
        self.assertNotIn("a9fca20f039a", raw_body)

    # 33. Run A frames never appear in Run B stream
    def test_33_run_a_frames_never_appear_in_run_b_stream(self) -> None:
        self.fake_gw.chunks = ["Phản ", "hồi ", "A"]
        resp_a = self._post_json("/api/chat/stream", {"content": "Request A"})
        raw_a = resp_a.read().decode("utf-8")
        parsed_a = parse_sse_frames(raw_a)
        deltas_a = [f["data"]["content"] for f in parsed_a if f["event"] == "delta"]

        self.fake_gw.chunks = ["Phản ", "hồi ", "B"]
        resp_b = self._post_json("/api/chat/stream", {"content": "Request B"})
        raw_b = resp_b.read().decode("utf-8")
        parsed_b = parse_sse_frames(raw_b)
        deltas_b = [f["data"]["content"] for f in parsed_b if f["event"] == "delta"]

        self.assertEqual("".join(deltas_a), "Phản hồi A")
        self.assertEqual("".join(deltas_b), "Phản hồi B")
        self.assertNotIn("Phản hồi B", raw_a)
        self.assertNotIn("Phản hồi A", raw_b)

    # 34. Terminal stream resources are cleaned up
    def test_34_terminal_stream_resources_are_cleaned_up(self) -> None:
        bridge = StreamingChatBridge()
        bridge.send_delta("chunk")
        bridge.send_complete({"status": "COMPLETED"})
        frames = []
        bridge.drain_to_writer(frames.append, lambda: None)
        self.assertTrue(bridge.is_closed)
        self.assertTrue(bridge.queue.empty())

    # 35. CORS headers are present on streaming responses
    def test_35_cors_headers_present_on_streaming_response(self) -> None:
        resp = self._post_json("/api/chat/stream", {"content": "test cors"}, headers_extra={"Origin": "http://127.0.0.1:3000"})
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:3000")

    # 36. Flush spy: write -> flush verified for progress, delta, complete, error
    def test_36_flush_spy_verifies_exact_write_then_flush_sequence(self) -> None:
        ops = []
        def spy_write(b: bytes) -> None:
            ops.append(("write", b))
        def spy_flush() -> None:
            ops.append(("flush", None))

        bridge = StreamingChatBridge(max_queue_size=10)
        p_event = RuntimeProgressEvent(
            run_id="RUN-SPY-01",
            sequence=1,
            event_type=ProgressEventType.RUN_STARTED,
            mode=ProgressMode.GENERAL_CONVERSATION.value,
            message="Khởi động",
        )
        bridge.send_progress(p_event)
        bridge.send_delta("Chunk 1")
        bridge.send_complete({"status": "COMPLETED"})

        bridge.drain_to_writer(spy_write, spy_flush)

        # Order must strictly be: write, flush, write, flush, write, flush
        op_types = [o[0] for o in ops]
        self.assertEqual(op_types, ["write", "flush", "write", "flush", "write", "flush"])
        self.assertIn(b"event: progress\n", ops[0][1])
        self.assertIn(b"event: delta\n", ops[2][1])
        self.assertIn(b"event: complete\n", ops[4][1])

    # 37. Flush spy for error terminal
    def test_37_flush_spy_verifies_error_write_then_flush(self) -> None:
        ops = []
        bridge = StreamingChatBridge(max_queue_size=10)
        bridge.send_delta("Partial delta")
        bridge.send_error("Provider error")
        bridge.drain_to_writer(lambda b: ops.append(("write", b)), lambda: ops.append(("flush", None)))

        op_types = [o[0] for o in ops]
        self.assertEqual(op_types, ["write", "flush", "write", "flush"])
        self.assertIn(b"event: error\n", ops[2][1])

    # 38. Tiny queue (maxsize=1) blocks producer until consumer frees capacity (Zero Drop)
    def test_38_tiny_queue_zero_drop_backpressure(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=1)
        delivered_frames = []
        prod_errors: list[Exception] = []

        def slow_writer(b: bytes) -> None:
            time.sleep(0.02)
            delivered_frames.append(b)

        def producer() -> None:
            try:
                bridge.send_delta("Token 1")
                bridge.send_delta("Token 2")
                bridge.send_delta("Token 3")
                bridge.send_complete({"status": "COMPLETED"})
            except Exception as e:
                prod_errors.append(e)
                bridge.close()

        prod_thread = threading.Thread(target=producer)
        prod_thread.start()

        bridge.drain_to_writer(slow_writer, lambda: None)
        prod_thread.join(timeout=5.0)

        self.assertEqual(prod_errors, [], f"Producer thread failed with errors: {prod_errors}")
        self.assertFalse(prod_thread.is_alive())
        self.assertEqual(len(delivered_frames), 4)
        parsed = [parse_sse_frames(f.decode("utf-8"))[0] for f in delivered_frames]
        deltas = [p["data"]["content"] for p in parsed if p["event"] == "delta"]
        self.assertEqual(deltas, ["Token 1", "Token 2", "Token 3"])
        self.assertEqual(parsed[-1]["event"], "complete")

    # 39. Progress sequence continuity preserved under saturation
    def test_39_progress_sequence_continuous_under_saturation(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=1)
        delivered_frames = []
        prod_errors: list[Exception] = []

        def producer() -> None:
            try:
                for seq in range(1, 6):
                    ev = RuntimeProgressEvent(
                        run_id="RUN-SAT-01",
                        sequence=seq,
                        event_type=ProgressEventType.STAGE_STARTED,
                        mode=ProgressMode.FULL_WORKFLOW.value,
                        stage=ProgressStage.CMO_INITIAL.value,
                        message=f"Step {seq}",
                    )
                    bridge.send_progress(ev)
                bridge.send_complete({"status": "COMPLETED"})
            except Exception as e:
                prod_errors.append(e)
                bridge.close()

        prod_thread = threading.Thread(target=producer)
        prod_thread.start()

        bridge.drain_to_writer(delivered_frames.append, lambda: None)
        prod_thread.join(timeout=5.0)

        self.assertEqual(prod_errors, [], f"Producer thread failed with errors: {prod_errors}")
        self.assertFalse(prod_thread.is_alive())
        parsed_events = [
            parse_sse_frames(f.decode("utf-8"))[0] for f in delivered_frames
        ]
        seqs = [p["data"]["sequence"] for p in parsed_events if p["event"] == "progress"]
        self.assertEqual(seqs, [1, 2, 3, 4, 5])

    # 40. Normal queue fullness does NOT lose terminal COMPLETE
    def test_40_normal_queue_full_does_not_lose_complete(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=2)
        bridge.send_delta("A")
        bridge.send_delta("B")
        # Queue is now 100% full (2/2)
        self.assertTrue(bridge.queue.full())

        # Calling send_complete must succeed immediately without dropping complete
        bridge.send_complete({"status": "COMPLETED"})
        self.assertEqual(bridge.state, StreamState.TERMINAL_PENDING)

        delivered = []
        bridge.drain_to_writer(delivered.append, lambda: None)

        parsed = [parse_sse_frames(d.decode("utf-8"))[0] for d in delivered]
        events = [p["event"] for p in parsed]
        self.assertEqual(events, ["delta", "delta", "complete"])
        self.assertEqual(bridge.state, StreamState.COMPLETE)

    # 41. Normal queue fullness does NOT lose terminal ERROR
    def test_41_normal_queue_full_does_not_lose_error(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=1)
        bridge.send_delta("A")
        self.assertTrue(bridge.queue.full())

        bridge.send_error("Fatal pipeline error")
        self.assertEqual(bridge.state, StreamState.TERMINAL_PENDING)

        delivered = []
        bridge.drain_to_writer(delivered.append, lambda: None)

        parsed = [parse_sse_frames(d.decode("utf-8"))[0] for d in delivered]
        events = [p["event"] for p in parsed]
        self.assertEqual(events, ["delta", "error"])
        self.assertEqual(bridge.state, StreamState.ERROR)

    # 42. No normal events accepted after terminal pending
    def test_42_no_normal_events_accepted_after_terminal_pending(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=5)
        bridge.send_delta("Accepted 1")
        bridge.send_complete({"status": "COMPLETED"})
        # Subsequent normal events must be rejected
        bridge.send_delta("Late rejected delta")
        ev = RuntimeProgressEvent(
            run_id="RUN-LATE",
            sequence=99,
            event_type=ProgressEventType.STAGE_COMPLETED,
            mode=ProgressMode.GENERAL_CONVERSATION.value,
        )
        bridge.send_progress(ev)

        delivered = []
        bridge.drain_to_writer(delivered.append, lambda: None)

        parsed = [parse_sse_frames(d.decode("utf-8"))[0] for d in delivered]
        events = [p["event"] for p in parsed]
        self.assertEqual(events, ["delta", "complete"])
        deltas = [p["data"]["content"] for p in parsed if p["event"] == "delta"]
        self.assertEqual(deltas, ["Accepted 1"])

    # 43. Duplicate terminal calls ignored / single terminal guaranteed
    def test_43_duplicate_terminal_calls_ignored(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=5)
        bridge.send_complete({"first": True})
        bridge.send_complete({"second": True})
        bridge.send_error("late error")

        delivered = []
        bridge.drain_to_writer(delivered.append, lambda: None)

        parsed = [parse_sse_frames(d.decode("utf-8"))[0] for d in delivered]
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["event"], "complete")
        self.assertEqual(parsed[0]["data"], {"first": True})

    # 44. Disconnect unblocks producer waiting on full queue without deadlock
    def test_44_disconnect_unblocks_waiting_producer(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=1)
        bridge.send_delta("Fill slot")
        producer_exited = threading.Event()
        prod_errors: list[Exception] = []

        def blocked_producer() -> None:
            try:
                # This put will block because queue maxsize=1 is full
                bridge.send_delta("Blocked delta")
                producer_exited.set()
            except Exception as e:
                prod_errors.append(e)
                bridge.close()

        prod_thread = threading.Thread(target=blocked_producer)
        prod_thread.start()

        # Simulate client disconnect on writer
        def broken_writer(b: bytes) -> None:
            raise ConnectionResetError("Client dropped connection")

        bridge.drain_to_writer(broken_writer, lambda: None)

        # Producer must unblock quickly and exit
        success = producer_exited.wait(timeout=2.0)
        self.assertTrue(success, "Producer remained permanently blocked after disconnect")
        self.assertEqual(bridge.state, StreamState.DISCONNECTED)
        prod_thread.join(timeout=1.0)
        self.assertFalse(prod_thread.is_alive())
        self.assertEqual(prod_errors, [])

    # 45. Concurrent producer and slow consumer preserve strict FIFO
    def test_45_concurrent_producer_and_slow_consumer_preserve_fifo(self) -> None:
        bridge = StreamingChatBridge(max_queue_size=2)
        delivered = []
        prod_errors: list[Exception] = []

        def slow_writer(b: bytes) -> None:
            time.sleep(0.01)
            delivered.append(b)

        def producer() -> None:
            try:
                ev1 = RuntimeProgressEvent(run_id="R", sequence=1, event_type=ProgressEventType.RUN_STARTED, mode=ProgressMode.GENERAL_CONVERSATION.value)
                ev2 = RuntimeProgressEvent(run_id="R", sequence=2, event_type=ProgressEventType.MODEL_STARTED, mode=ProgressMode.GENERAL_CONVERSATION.value)
                bridge.send_progress(ev1)
                bridge.send_progress(ev2)
                bridge.send_delta("A")
                bridge.send_delta("B")
                bridge.send_delta("C")
                bridge.send_complete({"status": "COMPLETED"})
            except Exception as e:
                prod_errors.append(e)
                bridge.close()

        prod_thread = threading.Thread(target=producer)
        prod_thread.start()

        bridge.drain_to_writer(slow_writer, lambda: None)
        prod_thread.join(timeout=5.0)

        self.assertEqual(prod_errors, [], f"Producer thread failed with errors: {prod_errors}")
        self.assertFalse(prod_thread.is_alive())
        parsed = [parse_sse_frames(d.decode("utf-8"))[0] for d in delivered]
        events_order = [p["event"] for p in parsed]
        self.assertEqual(events_order, ["progress", "progress", "delta", "delta", "delta", "complete"])
        self.assertEqual([p["data"]["sequence"] for p in parsed if p["event"] == "progress"], [1, 2])
        self.assertEqual([p["data"]["content"] for p in parsed if p["event"] == "delta"], ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
