"""Backend Streaming Transport & SSE Bridge for AI Marketing Department.

Provides clean, typed, and isolated Server-Sent Events (SSE) streaming transport:
- Separates trusted runtime progress events from user-visible model text deltas.
- Preserves the canonical safe runtime/provider error contract end-to-end.
- Enforces strict UTF-8 serialization, immediate flushes, and finite SSE event types.
- Isolates run-scoped streams with bounded thread-safe queues.
- Resilient client disconnect handling without server crashes or leaked threads.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union

from runtime.progress import RuntimeProgressEvent
from runtime.public_errors import PublicRuntimeError

logger = logging.getLogger("app_api.streaming")

TextDeltaSink = Callable[[str], None]


class SSEEventType(str, Enum):
    """Finite canonical SSE event types for backend-to-desktop transport."""
    PROGRESS = "progress"
    DELTA = "delta"
    COMPLETE = "complete"
    ERROR = "error"


def format_sse_event(event_type: Union[SSEEventType, str], data: Any) -> bytes:
    """Format an SSE message block with event type, JSON data, and blank-line termination."""
    event_str = event_type.value if isinstance(event_type, SSEEventType) else str(event_type).strip()
    if "\n" in event_str or "\r" in event_str:
        raise ValueError("SECURITY_ERROR: Event type must not contain newline characters.")

    if hasattr(data, "model_dump") and callable(data.model_dump):
        json_payload = json.dumps(data.model_dump(), ensure_ascii=False, default=str)
    elif isinstance(data, (dict, list, str, int, float, bool)) or data is None:
        json_payload = json.dumps(data, ensure_ascii=False, default=str)
    else:
        # Non-public objects must never expose repr/exception details through SSE.
        json_payload = json.dumps({"type": "UNSERIALIZABLE_PUBLIC_PAYLOAD"}, ensure_ascii=False)

    frame = f"event: {event_str}\ndata: {json_payload}\n\n"
    return frame.encode("utf-8")


def _bounded_text(value: Any, max_chars: int) -> str:
    return value[:max_chars] if isinstance(value, str) else ""


def _canonical_error_dict(error: PublicRuntimeError) -> Dict[str, Any]:
    payload = error.model_dump()
    # Compatibility aliases retained for existing desktop consumers while the
    # canonical fields remain authoritative.
    payload["error"] = payload["code"]
    payload["message"] = payload["safe_message"]
    return payload


def sanitize_error_for_stream(error: Any) -> Dict[str, Any]:
    """Return a finite, credential-safe public error payload.

    Typed PublicRuntimeError instances pass through unchanged apart from
    compatibility aliases.  Legacy dictionaries are accepted only through a
    strict allow-list.  Arbitrary exception/string detail is never reflected
    to the client.
    """
    if isinstance(error, PublicRuntimeError):
        return _canonical_error_dict(error)

    if isinstance(error, dict):
        code = _bounded_text(error.get("code") or error.get("error"), 80)
        category = _bounded_text(error.get("category"), 80)
        safe_message = _bounded_text(error.get("safe_message") or error.get("message"), 500)
        retryable_raw = error.get("retryable", False)
        status_raw = error.get("http_status")
        provider = _bounded_text(error.get("provider"), 120)
        model_name = _bounded_text(error.get("model_name"), 160)
        stage = _bounded_text(error.get("stage"), 80)
        agent = _bounded_text(error.get("agent"), 80)

        payload: Dict[str, Any] = {
            "code": code or "EXECUTION_ERROR",
            "category": category or "INTERNAL",
            "safe_message": safe_message or "The agent run could not be completed.",
            "retryable": retryable_raw if type(retryable_raw) is bool else False,
            "http_status": status_raw if type(status_raw) is int and 100 <= status_raw <= 599 else None,
            "provider": provider,
            "model_name": model_name,
            "stage": stage,
            "agent": agent,
        }
        payload["error"] = payload["code"]
        payload["message"] = payload["safe_message"]
        return payload

    # Fail closed for arbitrary exceptions and strings.  Never echo str(error)
    # because it may contain API keys, raw provider bodies, URLs, or OS paths.
    return {
        "code": "EXECUTION_ERROR",
        "category": "INTERNAL",
        "safe_message": "The agent run could not be completed.",
        "retryable": False,
        "http_status": None,
        "provider": "",
        "model_name": "",
        "stage": "",
        "agent": "",
        "error": "EXECUTION_ERROR",
        "message": "The agent run could not be completed.",
    }


class StreamState(str, Enum):
    """Explicit lifecycle state machine for SSE streaming bridge."""
    OPEN = "OPEN"
    TERMINAL_PENDING = "TERMINAL_PENDING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


class StreamingChatBridge:
    """Run-scoped queue bridge connecting worker execution with HTTP SSE response writer."""

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
        """Enqueue one terminal, typed, sanitized ERROR event."""
        with self._cond:
            if self.state != StreamState.OPEN:
                return
            self._terminal_event = (SSEEventType.ERROR, sanitize_error_for_stream(error))
            self.state = StreamState.TERMINAL_PENDING
            self._cond.notify_all()

    def close(self) -> None:
        """Mark bridge disconnected / closed and unblock waiting producers/consumers."""
        with self._cond:
            if self.state in (StreamState.OPEN, StreamState.TERMINAL_PENDING):
                self.state = StreamState.DISCONNECTED
            self._cond.notify_all()

    def drain_to_writer(self, write_fn: Callable[[bytes], None], flush_fn: Callable[[], None]) -> None:
        """Drain normal queue events in FIFO order, followed by the terminal event."""
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
            logger.info("Client disconnected during streaming: %s", type(ex).__name__)
            with self._cond:
                self.state = StreamState.DISCONNECTED
                self._cond.notify_all()
        except Exception as ex:
            logger.warning("Error during SSE queue draining: %s", type(ex).__name__)
            with self._cond:
                self.state = StreamState.DISCONNECTED
                self._cond.notify_all()
