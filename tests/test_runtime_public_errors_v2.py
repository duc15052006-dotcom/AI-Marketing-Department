from integrations.models.base import ModelStreamError, StreamDelta
from runtime.public_errors import from_stream_delta, internal_runtime_error


def test_preserves_gateway_typed_error_and_provenance():
    delta = StreamDelta(
        content="",
        finish_reason="error",
        provider="xkiro",
        model_name="deepseek/deepseek-v4-pro",
        error=ModelStreamError(
            code="RATE_LIMITED",
            category="RATE_LIMIT",
            safe_message="Provider rate limit reached.",
            retryable=True,
            http_status=429,
        ),
    )
    err = from_stream_delta(delta, stage="CMO_INITIAL", agent="CMO")
    assert err.code == "RATE_LIMITED"
    assert err.category == "RATE_LIMIT"
    assert err.retryable is True
    assert err.http_status == 429
    assert err.provider == "xkiro"
    assert err.model_name == "deepseek/deepseek-v4-pro"
    assert err.stage == "CMO_INITIAL"
    assert err.agent == "CMO"


def test_non_error_delta_fails_closed_without_content_leakage():
    delta = StreamDelta(content="secret arbitrary content", finish_reason="stop")
    err = from_stream_delta(delta, stage="INTELLIGENCE", agent="INTELLIGENCE")
    payload = err.model_dump()
    assert payload["code"] == "RUNTIME_INTERNAL_ERROR"
    assert "secret arbitrary content" not in str(payload)


def test_internal_runtime_error_is_fixed_safe_message():
    err = internal_runtime_error(stage="CREATIVE", agent="CREATIVE")
    payload = err.model_dump()
    assert payload["code"] == "RUNTIME_INTERNAL_ERROR"
    assert payload["retryable"] is False
    assert payload["http_status"] is None
    assert "traceback" not in payload["safe_message"].lower()
