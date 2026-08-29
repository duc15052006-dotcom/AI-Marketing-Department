import json

from app_api.streaming import SSEEventType, StreamingChatBridge, sanitize_error_for_stream
from runtime.public_errors import PublicRuntimeError


def test_typed_runtime_error_preserves_public_fields():
    err = PublicRuntimeError(
        code="AUTH_ERROR",
        category="AUTHENTICATION",
        safe_message="Authentication failed.",
        retryable=False,
        http_status=401,
        provider="xkiro",
        model_name="deepseek/deepseek-v4-pro",
        stage="CMO_INITIAL",
        agent="CMO",
    )
    payload = sanitize_error_for_stream(err)
    assert payload["code"] == "AUTH_ERROR"
    assert payload["category"] == "AUTHENTICATION"
    assert payload["http_status"] == 401
    assert payload["provider"] == "xkiro"
    assert payload["model_name"] == "deepseek/deepseek-v4-pro"
    assert payload["stage"] == "CMO_INITIAL"
    assert payload["agent"] == "CMO"
    assert payload["error"] == payload["code"]
    assert payload["message"] == payload["safe_message"]


def test_arbitrary_exception_detail_never_reflected_to_client():
    secret = "Bearer abc123 SUPER_SECRET_KEY=C:\\private\\key.txt"
    payload = sanitize_error_for_stream(RuntimeError(secret))
    serialized = json.dumps(payload)
    assert "abc123" not in serialized
    assert "SUPER_SECRET_KEY" not in serialized
    assert "private" not in serialized
    assert payload["code"] == "EXECUTION_ERROR"


def test_legacy_dict_is_strictly_bounded_and_retryable_is_not_truthy_coerced():
    payload = sanitize_error_for_stream({
        "code": "TIMEOUT",
        "category": "TIMEOUT",
        "safe_message": "Provider timed out.",
        "retryable": "false",
        "http_status": "408",
    })
    assert payload["retryable"] is False
    assert payload["http_status"] is None


def test_bridge_emits_structured_error_terminal_frame():
    bridge = StreamingChatBridge()
    bridge.send_error(PublicRuntimeError(
        code="RATE_LIMITED",
        category="RATE_LIMIT",
        safe_message="Try again later.",
        retryable=True,
        http_status=429,
        provider="xkiro",
        model_name="m",
        stage="INTELLIGENCE",
        agent="INTELLIGENCE",
    ))

    frames = []
    bridge.drain_to_writer(frames.append, lambda: None)
    assert len(frames) == 1
    text = frames[0].decode("utf-8")
    assert text.startswith(f"event: {SSEEventType.ERROR.value}\n")
    assert '"code": "RATE_LIMITED"' in text
    assert '"retryable": true' in text
    assert '"stage": "INTELLIGENCE"' in text
