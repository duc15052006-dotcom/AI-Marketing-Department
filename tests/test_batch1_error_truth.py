from integrations.models.base import ModelResponse, ModelResponseStatus
from runtime.public_errors import from_model_response


def _response(error: str, *, status=ModelResponseStatus.ERROR, metadata=None):
    return ModelResponse(
        request_id="r1",
        provider="xkiro",
        model_name="m1",
        status=status,
        error=error,
        metadata=metadata or {},
    )


def test_unstructured_raw_transport_detail_is_never_reflected_publicly():
    raw = "PROVIDER_UNAVAILABLE: HTTP 599 <urlopen error [WinError 10061] Connection refused> Bearer abc123"
    public = from_model_response(_response(raw), stage="GENERAL_CONVERSATION", agent="")
    dumped = public.model_dump()
    assert "WinError" not in dumped["safe_message"]
    assert "10061" not in dumped["safe_message"]
    assert "abc123" not in dumped["safe_message"]
    assert dumped["code"] == "PROVIDER_RESPONSE_ERROR"
    assert dumped["safe_message"] == "The model provider request failed."


def test_structural_timeout_uses_generic_safe_message_not_raw_detail():
    raw = "socket timeout at C:/private/path Authorization: Bearer SECRET"
    public = from_model_response(_response(raw, status=ModelResponseStatus.TIMEOUT), stage="INTELLIGENCE", agent="intelligence")
    assert public.code == "TIMEOUT"
    assert public.retryable is True
    assert public.http_status == 408
    assert "private" not in public.safe_message
    assert "SECRET" not in public.safe_message


def test_trusted_machine_safe_message_is_allowed_but_sanitized():
    response = _response(
        "raw body must not win",
        metadata={
            "error_code": "AUTH_ERROR",
            "error_category": "AUTHENTICATION",
            "safe_message": "Credential rejected: Bearer short",
            "retryable": False,
            "http_status": 401,
        },
    )
    public = from_model_response(response, stage="CMO_INITIAL", agent="cmo")
    assert public.code == "AUTH_ERROR"
    assert public.http_status == 401
    assert "short" not in public.safe_message
    assert "[REDACTED_TOKEN]" in public.safe_message


def test_missing_machine_safe_message_uses_code_specific_generic_message():
    response = _response(
        "raw provider detail with /home/private/key",
        metadata={
            "error_code": "RATE_LIMITED",
            "error_category": "RATE_LIMIT",
            "retryable": True,
            "http_status": 429,
        },
    )
    public = from_model_response(response)
    assert public.safe_message == "The model provider rate limit was reached. Please try again later."
    assert "/home/private" not in public.safe_message
