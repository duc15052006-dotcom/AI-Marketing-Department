"""Typed SSE bridge for the desktop chat stream.

Trusted runtime progress and visible model text are separate channels. Public
errors use a strict allow-list and never reflect arbitrary exception strings.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union

from runtime.progress import RuntimeProgressEvent
from runtime.public_errors import PublicRuntimeError, public_error_payload

logger = logging.getLogger("app_api.streaming")
TextDeltaSink = Callable[[str], None]


class SSEEventType(str, Enum):
    PROGRESS = "progress"
    DELTA = "delta"
    COMPLETE = "complete"
    ERROR = "error"


def format_sse_event(event_type: Union[SSEEventType, str], data: Any) -> bytes:
    event_str = event_type.value if isinstance(event_type, SSEEventType) else str(event_type).strip()
    if "\n" in event_str or "\r" in event_str:
        raise ValueError("SECURITY_ERROR: Event type must not contain newline characters.")

    if hasattr(data, "model_dump") and callable(data.model_dump):
        payload = data.model_dump()
    elif isinstance(data, (dict, list, str, int, float, bool)) or data is None:
        payload = data
    else:
        payload = {"type": "UNSERIALIZABLE_PUBLIC_PAYLOAD"}
    frame = f"event: {event_str}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
    return frame.encode("utf-8")


def sanitize_error_for_stream(error: Any) -> Dict[str, Any]:
    """Normalize explicitly safe structured errors; arbitrary values fail closed."""
    payload = public_error_payload(error)
    # Compatibility aliases for existing native/UI consumers. Canonical fields
    # remain code/category/safe_message/retryable/http_status/provenance.
    payload["error"] = payload["code"]
    payload["message"] = payload["safe_message"]
    return payload


class StreamState(str, Enum):
    OPEN = "OPEN"
    TERMINAL_PENDING = "TERMINAL_PENDING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


class StreamingChatBridge:
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

    def _put(self, event_type: SSEEventType, payload: Any) -> None:
        with self._cond:
            while self.state == StreamState.OPEN and self.queue.full():
                self._cond.wait(timeout=0.1)
            if self.state != StreamState.OPEN:
                return
            self.queue.put_nowait((event_type, payload))
            self._cond.notify_all()

    def send_progress(self, event: RuntimeProgressEvent) -> None:
        self._put(SSEEventType.PROGRESS, event)

    def send_delta(self, delta_text: str, provider: str = "", model_name: str = "") -> None:
        if delta_text:
            self._put(SSEEventType.DELTA, {"content": delta_text, "provider": provider, "model_name": model_name})

    def send_complete(self, payload: Dict[str, Any]) -> None:
        with self._cond:
            if self.state != StreamState.OPEN:
                return
            self._terminal_event = (SSEEventType.COMPLETE, payload)
            self.state = StreamState.TERMINAL_PENDING
            self._cond.notify_all()

    def send_error(self, error: Any) -> None:
        with self._cond:
            if self.state != StreamState.OPEN:
                return
            self._terminal_event = (SSEEventType.ERROR, sanitize_error_for_stream(error))
            self.state = StreamState.TERMINAL_PENDING
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            if self.state in (StreamState.OPEN, StreamState.TERMINAL_PENDING):
                self.state = StreamState.DISCONNECTED
            self._cond.notify_all()

    def drain_to_writer(self, write_fn: Callable[[bytes], None], flush_fn: Callable[[], None]) -> None:
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
                write_fn(format_sse_event(event_type, data))
                flush_fn()

            with self._cond:
                if self.state != StreamState.TERMINAL_PENDING or self._terminal_event is None:
                    return
                term_type, term_data = self._terminal_event

            write_fn(format_sse_event(term_type, term_data))
            flush_fn()

            with self._cond:
                self.state = StreamState.COMPLETE if term_type == SSEEventType.COMPLETE else StreamState.ERROR
                self._cond.notify_all()

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as ex:
            logger.info("Client disconnected during streaming: %s", type(ex).__name__)
            with self._cond:
                self.state = StreamState.DISCONNECTED
                self._cond.notify_all()
        except Exception as ex:
            logger.warning("SSE drain failed: %s", type(ex).__name__)
            with self._cond:
                self.state = StreamState.DISCONNECTED
                self._cond.notify_all()
