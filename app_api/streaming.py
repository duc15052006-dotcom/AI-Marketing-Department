"""Backend Streaming Transport & SSE Bridge for AI Marketing Department.

Provides clean, typed, and isolated Server-Sent Events (SSE) streaming transport:
- Separates trusted runtime progress events (B2) from user-visible model text deltas (B1).
- Enforces strict UTF-8 serialization, immediate flushes, and finite SSE event types.
- Isolates run-scoped streams with bounded thread-safe queues.
- Resilient client disconnect handling without server crashes or leaked threads.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union

from governance.redaction import sanitize_sensitive_text
from runtime.progress import RuntimeProgressEvent

logger = logging.getLogger("app_api.streaming")

TextDeltaSink = Callable[[str], None]


class SSEEventType(str, Enum):
    """Finite canonical SSE event types for backend-to-desktop transport."""
    PROGRESS = "progress"
    DELTA = "delta"
    COMPLETE = "complete"
    ERROR = "error"


def format_sse_event(event_type: Union[SSEEventType, str], data: Any) -> bytes:
    """Format an SSE message block with event type, JSON-encoded data, and blank line termination.

    Rejects newline injection in event types and safely serializes structured data to UTF-8.
    """
    event_str = event_type.value if isinstance(event_type, SSEEventType) else str(event_type).strip()
    if "\n" in event_str or "\r" in event_str:
        raise ValueError("SECURITY_ERROR: Event type must not contain newline characters.")

    if hasattr(data, "model_dump") and callable(data.model_dump):
        json_payload = json.dumps(data.model_dump(), ensure_ascii=False, default=str)
    elif isinstance(data, (dict, list, str, int, float, bool)) or data is None:
        json_payload = json.dumps(data, ensure_ascii=False, default=str)
    else:
        json_payload = json.dumps(str(data), ensure_ascii=False)

    frame = f"event: {event_str}\ndata: {json_payload}\n\n"
    return frame.encode("utf-8")


def _safe_error_code(error: Any) -> Optional[str]:
    """Extract only a bounded machine-style error code from structured errors."""
    candidate: Any = None
    if isinstance(error, dict):
        candidate = error.get("error") or error.get("error_code") or error.get("code")
    else:
        for attr in ("error_code", "code"):
            value = getattr(error, attr, None)
            if value:
                candidate = value
                break

    if candidate is None:
        return None
    code = str(candidate).strip().upper()
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", code):
        return code
    return None


def sanitize_error_for_stream(error: Any) -> Dict[str, str]:
    """Return a public-safe streaming error without echoing raw exception text.

    Raw exception details are used only for coarse category detection. They are
    never returned to the browser because arbitrary provider/OS exceptions may
    contain API keys, authorization headers, URLs with credentials, local file
    paths, or other internal diagnostics.
    """
    raw_error = str(error) if error else "INTERNAL_SERVER_ERROR"
    err_str = sanitize_sensitive_text(raw_error)
    err_lower = err_str.lower()

    if "winerror" in err_lower or "http 599" in err_lower or "connection refused" in err_lower:
        return {
            "error": "PROVIDER_UNAVAILABLE",
            "message": "Không thể kết nối đến nhà cung cấp mô hình AI. Vui lòng kiểm tra lại cấu hình hoặc kết nối mạng.",
        }

    if (
        ("key" in err_lower and "invalid" in err_lower)
        or "authentication failed" in err_lower
        or "unauthorized" in err_lower
        or "http 401" in err_lower
    ):
        return {
            "error": "AUTHENTICATION_FAILED",
            "message": "Xác thực với nhà cung cấp mô hình AI thất bại. Vui lòng kiểm tra lại cấu hình khóa API.",
        }

    if "rate limit" in err_lower or "http 429" in err_lower or " 429" in err_lower:
        return {
            "error": "RATE_LIMITED",
            "message": "Đã vượt quá giới hạn tần suất yêu cầu (Rate Limit). Vui lòng thử lại sau.",
        }

    safe_code = _safe_error_code(error) or "EXECUTION_ERROR"
    return {
        "error": safe_code,
        "message": "Không thể hoàn tất yêu cầu do lỗi thực thi nội bộ. Vui lòng thử lại hoặc kiểm tra cấu hình.",
    }


class StreamState(str, Enum):
    """Explicit lifecycle state machine for SSE streaming bridge."""
    OPEN = "OPEN"
    TERMINAL_PENDING = "TERMINAL_PENDING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


class StreamingChatBridge:
    """Run-scoped queue bridge connecting worker thread execution with HTTP SSE response writer."""

    def __init__(self, max_queue_size: int = 1000) -> None:
        self.max_queue_size = max_queue_size
        self.queue: queue.Queue[tuple[SSEEventType, Any]] = queue.Queue(maxsize=max_queue_size)
        self.state: StreamState = StreamState.OPEN
        self._terminal_event: Optional[tuple[SSEEventType, Any]] = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self.state in (StreamState.COMPLETE, StreamState.ERROR, StreamState.DISCONNECTED)

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self.state in (StreamState.OPEN, StreamState.TERMINAL_PENDING)

    def send_progress(self, event: RuntimeProgressEvent) -> None:
        """Enqueue a certified RuntimeProgressEvent with zero-drop backpressure."""
        with self._cond:
            while self.state == StreamState.OPEN and self.queue.full():
                self._cond.wait(timeout=0.1)

            if self.state != StreamState.OPEN:
                return

            self.queue.put_nowait((SSEEventType.PROGRESS, event))
            self._cond.notify_all()

    def send_delta(self, delta_text: str, provider: str = "", model_name: str = "") -> None:
        """Enqueue a user-visible assistant text delta with zero-drop backpressure."""
        if not delta_text:
            return
        payload = {
            "content": delta_text,
            "provider": provider,
            "model_name": model_name,
        }
        with self._cond:
            while self.state == StreamState.OPEN and self.queue.full():
                self._cond.wait(timeout=0.1)

            if self.state != StreamState.OPEN:
                return

            self.queue.put_nowait((SSEEventType.DELTA, payload))
            self._cond.notify_all()

    def send_complete(self, payload: Dict[str, Any]) -> None:
        """Enqueue terminal COMPLETE event outside normal capacity failure."""
        with self._cond:
            if self.state != StreamState.OPEN:
                return
            self._terminal_event = (SSEEventType.COMPLETE, payload)
            self.state = StreamState.TERMINAL_PENDING
            self._cond.notify_all()

    def send_error(self, error: Any) -> None:
        """Enqueue terminal ERROR event outside normal capacity failure."""
        with self._cond:
            if self.state != StreamState.OPEN:
                return
            sanitized = sanitize_error_for_stream(error)
            self._terminal_event = (SSEEventType.ERROR, sanitized)
            self.state = StreamState.TERMINAL_PENDING
            self._cond.notify_all()

    def close(self) -> None:
        """Mark bridge disconnected / closed and unblock any waiting producers/consumers."""
        with self._cond:
            if self.state in (StreamState.OPEN, StreamState.TERMINAL_PENDING):
                self.state = StreamState.DISCONNECTED
            self._cond.notify_all()

    def drain_to_writer(self, write_fn: Callable[[bytes], None], flush_fn: Callable[[], None]) -> None:
        """Synchronously drain normal queue events in strict FIFO order, followed by the terminal event."""
        try:
            while True:
                with self._cond:
                    while self.queue.empty() and self.state == StreamState.OPEN:
                        self._cond.wait(timeout=0.1)

                    if not self.queue.empty():
                        item = self.queue.get_nowait()
                        self._cond.notify_all()
                    elif self.state == StreamState.TERMINAL_PENDING:
                        break
                    else:
                        return

                event_type, data = item
                frame_bytes = format_sse_event(event_type, data)
                write_fn(frame_bytes)
                flush_fn()

            with self._cond:
                if self.state == StreamState.TERMINAL_PENDING and self._terminal_event is not None:
                    term_type, term_data = self._terminal_event
                else:
                    return

            frame_bytes = format_sse_event(term_type, term_data)
            write_fn(frame_bytes)
            flush_fn()

            with self._cond:
                if term_type == SSEEventType.COMPLETE:
                    self.state = StreamState.COMPLETE
                else:
                    self.state = StreamState.ERROR
                self._cond.notify_all()

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as ex:
            logger.info(f"Client disconnected during streaming: {sanitize_sensitive_text(ex)}")
            with self._cond:
                self.state = StreamState.DISCONNECTED
                self._cond.notify_all()
        except Exception as ex:
            logger.warning(f"Error during SSE queue draining: {sanitize_sensitive_text(ex)}")
            with self._cond:
                self.state = StreamState.DISCONNECTED
                self._cond.notify_all()
