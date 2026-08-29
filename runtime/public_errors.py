"""Safe typed runtime error boundary for model/provider failures.

A1 Half-2 contract: preserve the canonical structured provider error produced
by UniversalModelGateway while adding runtime stage/agent provenance.  This
module deliberately contains no raw exception text, provider body, headers, or
credentials.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from integrations.models.base import ModelStreamError, StreamDelta


@dataclass(frozen=True)
class PublicRuntimeError:
    code: str
    category: str
    safe_message: str
    retryable: bool
    http_status: Optional[int]
    provider: str
    model_name: str
    stage: str
    agent: str

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


_INTERNAL_FALLBACK = PublicRuntimeError(
    code="RUNTIME_INTERNAL_ERROR",
    category="INTERNAL",
    safe_message="The agent run failed inside the runtime boundary.",
    retryable=False,
    http_status=None,
    provider="",
    model_name="",
    stage="",
    agent="",
)


def _safe_text(value: Any, *, max_chars: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return value[:max_chars]


def from_stream_delta(
    delta: StreamDelta,
    *,
    stage: str,
    agent: str,
) -> PublicRuntimeError:
    """Convert a gateway-normalized error delta to the public runtime contract.

    UniversalModelGateway is the authority for provider/model and canonical
    ModelStreamError fields.  Missing/malformed terminal errors fail closed to
    a generic runtime-safe value instead of leaking arbitrary adapter data.
    """
    if not isinstance(delta, StreamDelta) or delta.finish_reason != "error":
        return PublicRuntimeError(
            **{
                **_INTERNAL_FALLBACK.model_dump(),
                "stage": _safe_text(stage, max_chars=80),
                "agent": _safe_text(agent, max_chars=80),
            }
        )

    err = delta.error
    if not isinstance(err, ModelStreamError):
        return PublicRuntimeError(
            code="STREAM_PROTOCOL_ERROR",
            category="STREAM_PROTOCOL",
            safe_message="The model stream ended with an invalid error frame.",
            retryable=False,
            http_status=None,
            provider=_safe_text(delta.provider, max_chars=120),
            model_name=_safe_text(delta.model_name, max_chars=160),
            stage=_safe_text(stage, max_chars=80),
            agent=_safe_text(agent, max_chars=80),
        )

    return PublicRuntimeError(
        code=_safe_text(err.code, max_chars=80) or "PROVIDER_RESPONSE_ERROR",
        category=_safe_text(err.category, max_chars=80) or "RESPONSE_ERROR",
        safe_message=_safe_text(err.safe_message) or "The model provider request failed.",
        retryable=err.retryable if type(err.retryable) is bool else False,
        http_status=err.http_status if type(err.http_status) is int and 100 <= err.http_status <= 599 else None,
        provider=_safe_text(delta.provider, max_chars=120),
        model_name=_safe_text(delta.model_name, max_chars=160),
        stage=_safe_text(stage, max_chars=80),
        agent=_safe_text(agent, max_chars=80),
    )


def internal_runtime_error(*, stage: str, agent: str) -> PublicRuntimeError:
    """Return a fixed safe error for unexpected runtime/programming failures."""
    return PublicRuntimeError(
        **{
            **_INTERNAL_FALLBACK.model_dump(),
            "stage": _safe_text(stage, max_chars=80),
            "agent": _safe_text(agent, max_chars=80),
        }
    )
