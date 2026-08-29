"""Safe public runtime error contract.

The UniversalModelGateway is the authority for provider/model stream errors.
This module only adds runtime provenance and converts unexpected internal
failures to a fixed fail-closed diagnostic. Raw exception strings, provider
bodies, headers, credentials and chain-of-thought never belong here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from integrations.models.base import ModelResponse, ModelStreamError, StreamDelta


@dataclass(frozen=True)
class PublicRuntimeError:
    code: str
    category: str
    safe_message: str
    retryable: bool = False
    http_status: Optional[int] = None
    provider: str = ""
    model_name: str = ""
    stage: str = ""
    agent: str = ""

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


def _bounded(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _valid_status(value: Any) -> Optional[int]:
    return value if type(value) is int and 100 <= value <= 599 else None


def from_model_stream_error(
    error: Optional[ModelStreamError],
    *,
    provider: str = "",
    model_name: str = "",
    stage: str = "",
    agent: str = "",
) -> PublicRuntimeError:
    if not isinstance(error, ModelStreamError):
        return PublicRuntimeError(
            code="STREAM_PROTOCOL_ERROR",
            category="STREAM_PROTOCOL",
            safe_message="The model stream ended with an invalid error frame.",
            provider=_bounded(provider, 120),
            model_name=_bounded(model_name, 160),
            stage=_bounded(stage, 80),
            agent=_bounded(agent, 80),
        )
    return PublicRuntimeError(
        code=_bounded(error.code, 80) or "PROVIDER_RESPONSE_ERROR",
        category=_bounded(error.category, 80) or "RESPONSE_ERROR",
        safe_message=_bounded(error.safe_message, 500) or "The model provider request failed.",
        retryable=error.retryable if type(error.retryable) is bool else False,
        http_status=_valid_status(error.http_status),
        provider=_bounded(provider, 120),
        model_name=_bounded(model_name, 160),
        stage=_bounded(stage, 80),
        agent=_bounded(agent, 80),
    )


def from_stream_delta(delta: StreamDelta, *, stage: str = "", agent: str = "") -> PublicRuntimeError:
    if not isinstance(delta, StreamDelta) or delta.finish_reason != "error":
        return internal_runtime_error(stage=stage, agent=agent)
    return from_model_stream_error(
        delta.error,
        provider=delta.provider,
        model_name=delta.model_name,
        stage=stage,
        agent=agent,
    )


def from_model_response(response: ModelResponse, *, stage: str = "", agent: str = "") -> PublicRuntimeError:
    # Import lazily to avoid creating a second error-classification authority.
    from integrations.models.gateway import model_response_to_stream_error, normalize_public_stream_error

    err = normalize_public_stream_error(
        model_response_to_stream_error(response, provider_name=getattr(response, "provider", "provider")),
        default_provider=getattr(response, "provider", "provider"),
    )
    return from_model_stream_error(
        err,
        provider=getattr(response, "provider", ""),
        model_name=getattr(response, "model_name", ""),
        stage=stage,
        agent=agent,
    )


def internal_runtime_error(*, stage: str = "", agent: str = "") -> PublicRuntimeError:
    return PublicRuntimeError(
        code="RUNTIME_INTERNAL_ERROR",
        category="INTERNAL",
        safe_message="The agent run failed inside the runtime boundary.",
        retryable=False,
        stage=_bounded(stage, 80),
        agent=_bounded(agent, 80),
    )


def public_error_payload(value: Any, *, stage: str = "", agent: str = "") -> Dict[str, Any]:
    """Normalize only explicitly safe structured public errors.

    Arbitrary strings/exceptions fail closed and are never reflected.
    """
    if isinstance(value, PublicRuntimeError):
        return value.model_dump()
    if isinstance(value, dict):
        retryable = value.get("retryable", False)
        status = value.get("http_status")
        return PublicRuntimeError(
            code=_bounded(value.get("code"), 80) or "EXECUTION_ERROR",
            category=_bounded(value.get("category"), 80) or "INTERNAL",
            safe_message=_bounded(value.get("safe_message"), 500) or "The agent run could not be completed.",
            retryable=retryable if type(retryable) is bool else False,
            http_status=_valid_status(status),
            provider=_bounded(value.get("provider"), 120),
            model_name=_bounded(value.get("model_name"), 160),
            stage=_bounded(value.get("stage"), 80) or _bounded(stage, 80),
            agent=_bounded(value.get("agent"), 80) or _bounded(agent, 80),
        ).model_dump()
    return internal_runtime_error(stage=stage, agent=agent).model_dump()
