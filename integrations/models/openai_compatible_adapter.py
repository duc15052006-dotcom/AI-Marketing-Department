"""Generic OpenAI-Compatible Provider Adapter (Phase 4.3C).

Configuration-driven adapter for standard OpenAI-compatible REST endpoints:
- xKiro (https://api.xkiro.com/v1)
- TheSpark (https://api.thespark.io/v1)
- Official OpenAI (https://api.openai.com/v1)
- Local Ollama / vLLM / LiteLLM / Any custom OpenAI-compatible server

Preserves secret safety: never logs or leaks API keys.
Normalizes request/response payload, token telemetry, error categories, and latency.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Generator, Optional, Set
import urllib.error
import urllib.request

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelStreamError,
    ModelUsage,
    StreamDelta,
    normalize_model_request,
)
from integrations.models.transport import (
    DEFAULT_USER_AGENT,
    OpenAICompatibleTransport,
    classify_transport_error,
    classify_transport_to_stream_error,
    sanitize_secrets,
)

logger = logging.getLogger("openai_compatible_adapter")


class OpenAICompatibleProviderAdapter(BaseModelAdapter):
    """Generic, configuration-driven adapter for any OpenAI-compatible API."""

    def __init__(
        self,
        provider_id: str,
        base_url: str,
        api_key_env: str,
        default_model: str,
        api_key: Optional[str] = None,
        chat_completions_path: str = "/chat/completions",
        cost_policy: CostPolicy = CostPolicy.FREE_TIER_ALLOWED,
        timeout_seconds: float = 60.0,
        capabilities: Optional[Dict[str, Any]] = None,
        transport: Optional[OpenAICompatibleTransport] = None,
    ) -> None:
        self._provider_id = provider_id.lower()
        self._base_url = base_url.rstrip("/")
        self._api_key_env = api_key_env
        self._api_key = api_key if api_key is not None else os.environ.get(api_key_env)
        self._default_model = default_model
        self._chat_completions_path = "/" + chat_completions_path.lstrip("/")
        self._cost_policy = cost_policy
        self._timeout_seconds = timeout_seconds
        self._capabilities = capabilities or {}
        self._transport = transport or OpenAICompatibleTransport(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout_seconds=self._timeout_seconds,
        )

    @property
    def provider_name(self) -> str:
        return self._provider_id

    @property
    def cost_policy(self) -> CostPolicy:
        return self._cost_policy

    @property
    def automatic_fallback_allowed(self) -> bool:
        return self._cost_policy == CostPolicy.FREE_TIER_ALLOWED

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def transport(self) -> OpenAICompatibleTransport:
        return self._transport

    def is_configured(self) -> bool:
        """Check if API key is present without exposing it."""
        return bool(self._api_key and len(self._api_key.strip()) > 0)

    @staticmethod
    def _coerce_nonnegative_int(value: Any) -> Optional[int]:
        """Normalize provider token telemetry without accepting ambiguous values."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float):
            return int(value) if value >= 0 and value.is_integer() else None
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.isdigit():
                return int(cleaned)
        return None

    @classmethod
    def _parse_usage(cls, usage_raw: Any) -> ModelUsage:
        """Parse optional token telemetry defensively.

        Provider content is still usable when telemetry is absent, null, empty,
        or malformed. In that case usage is marked NOT_AVAILABLE rather than
        inventing token counts or crashing an otherwise valid completion.
        """
        if not isinstance(usage_raw, dict) or not usage_raw:
            return ModelUsage(usage_source="NOT_AVAILABLE")

        prompt_tokens = 0
        completion_tokens = 0
        if "prompt_tokens" in usage_raw:
            parsed = cls._coerce_nonnegative_int(usage_raw.get("prompt_tokens"))
            if parsed is None:
                return ModelUsage(usage_source="NOT_AVAILABLE")
            prompt_tokens = parsed
        if "completion_tokens" in usage_raw:
            parsed = cls._coerce_nonnegative_int(usage_raw.get("completion_tokens"))
            if parsed is None:
                return ModelUsage(usage_source="NOT_AVAILABLE")
            completion_tokens = parsed

        if "total_tokens" in usage_raw:
            total_tokens = cls._coerce_nonnegative_int(usage_raw.get("total_tokens"))
            if total_tokens is None:
                return ModelUsage(usage_source="NOT_AVAILABLE")
        else:
            total_tokens = prompt_tokens + completion_tokens

        def optional_token(field_name: str) -> Optional[int]:
            if field_name not in usage_raw:
                return None
            return cls._coerce_nonnegative_int(usage_raw.get(field_name))

        thoughts_tokens = optional_token("reasoning_tokens")
        if "reasoning_tokens" in usage_raw and thoughts_tokens is None:
            return ModelUsage(usage_source="NOT_AVAILABLE")
        if thoughts_tokens is None:
            details = usage_raw.get("completion_tokens_details")
            if isinstance(details, dict) and "reasoning_tokens" in details:
                thoughts_tokens = cls._coerce_nonnegative_int(details.get("reasoning_tokens"))
                if thoughts_tokens is None:
                    return ModelUsage(usage_source="NOT_AVAILABLE")

        cached_tokens = optional_token("cached_tokens")
        if "cached_tokens" in usage_raw and cached_tokens is None:
            return ModelUsage(usage_source="NOT_AVAILABLE")
        if cached_tokens is None:
            details = usage_raw.get("prompt_tokens_details")
            if isinstance(details, dict) and "cached_tokens" in details:
                cached_tokens = cls._coerce_nonnegative_int(details.get("cached_tokens"))
                if cached_tokens is None:
                    return ModelUsage(usage_source="NOT_AVAILABLE")

        tool_tokens = optional_token("tool_use_prompt_tokens")
        if "tool_use_prompt_tokens" in usage_raw and tool_tokens is None:
            return ModelUsage(usage_source="NOT_AVAILABLE")

        return ModelUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            thoughts_tokens=thoughts_tokens,
            cached_tokens=cached_tokens,
            tool_use_prompt_tokens=tool_tokens,
            total_tokens=total_tokens,
            usage_source="PROVIDER_REPORTED",
        )

    def _provider_response_error(
        self,
        *,
        request_id: str,
        model_name: str,
        latency_ms: float,
        detail: str,
    ) -> ModelResponse:
        clean_detail = sanitize_secrets(str(detail), self._api_key)
        return ModelResponse(
            request_id=request_id,
            provider=self.provider_name,
            model_name=model_name,
            status=ModelResponseStatus.ERROR,
            error=f"PROVIDER_RESPONSE_ERROR: {clean_detail}",
            metadata={
                "error_code": "PROVIDER_RESPONSE_ERROR",
                "error_category": "RESPONSE_ERROR",
                "retryable": False,
            },
            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
            latency_ms=latency_ms,
        )

    def _stream_provider_response_error(self, model_name: str, detail: str) -> StreamDelta:
        clean_detail = sanitize_secrets(str(detail), self._api_key)
        return StreamDelta(
            content="",
            finish_reason="error",
            provider=self.provider_name,
            model_name=model_name,
            error=ModelStreamError(
                code="PROVIDER_RESPONSE_ERROR",
                category="RESPONSE_ERROR",
                safe_message=f"PROVIDER_RESPONSE_ERROR: {clean_detail}",
                retryable=False,
                http_status=None,
            ),
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute completion synchronously via OpenAI-compatible chat completions endpoint."""
        start_time = time.perf_counter()

        try:
            norm_req = normalize_model_request(request)
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=getattr(request, "request_id", "REQ-UNKNOWN"),
                provider=self.provider_name,
                model_name=getattr(request, "model_name", self._default_model),
                status=ModelResponseStatus.ERROR,
                error=f"REQUEST_SCHEMA_ERROR: {str(e)}",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=latency_ms,
            )

        if not self.is_configured():
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=norm_req.request_id,
                provider=self.provider_name,
                model_name=norm_req.model_name if norm_req.model_name not in ("default", "", None) else self._default_model,
                status=ModelResponseStatus.ERROR,
                error=f"MISSING_API_KEY: {self._api_key_env} is not configured in the environment.",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=latency_ms,
            )

        model_name = norm_req.model_name if norm_req.model_name not in ("default", "", None) else self._default_model

        messages = [
            {
                "role": msg.role.value if isinstance(msg.role, ModelRole) else str(msg.role),
                "content": msg.content,
            }
            for msg in norm_req.messages
        ]

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": norm_req.temperature,
        }

        if norm_req.max_tokens:
            payload["max_tokens"] = norm_req.max_tokens

        if norm_req.response_schema:
            payload["response_format"] = {"type": "json_object"}

        timeout = norm_req.timeout_seconds if norm_req.timeout_seconds else self._timeout_seconds

        status_code, resp_headers, body_str = self._transport.post_json(
            endpoint_path=self._chat_completions_path,
            payload=payload,
            timeout_seconds=timeout,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if 200 <= status_code < 300:
            try:
                resp_data = json.loads(body_str)
            except Exception as e:
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail=f"Malformed JSON returned by {self.provider_name} (HTTP {status_code}). Detail: {str(e)[:100]}",
                )

            if not isinstance(resp_data, dict):
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail="Provider response root must be a JSON object.",
                )

            choices = resp_data.get("choices")
            if not isinstance(choices, list):
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail="Provider response field 'choices' must be a list.",
                )
            if not choices:
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail=f"No choices returned by {self.provider_name} API.",
                )

            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail="Provider response first choice must be a JSON object.",
                )

            message_obj = first_choice.get("message")
            if not isinstance(message_obj, dict):
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail="Provider response choice.message must be a JSON object.",
                )

            content_raw = message_obj.get("content")
            if content_raw is None:
                content = ""
            elif isinstance(content_raw, str):
                content = content_raw
            else:
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail="Provider response choice.message.content must be a string or null.",
                )

            finish_reason_raw = first_choice.get("finish_reason", "stop")
            if finish_reason_raw is None:
                finish_reason = "stop"
            elif isinstance(finish_reason_raw, str):
                finish_reason = finish_reason_raw
            else:
                return self._provider_response_error(
                    request_id=norm_req.request_id,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    detail="Provider response choice.finish_reason must be a string or null.",
                )

            usage = self._parse_usage(resp_data.get("usage"))

            structured = None
            if norm_req.response_schema or content.strip().startswith("{"):
                try:
                    structured = json.loads(content.strip())
                except Exception:
                    structured = None

            provider_model = resp_data.get("model")
            if not isinstance(provider_model, str) or not provider_model.strip():
                provider_model = model_name

            return ModelResponse(
                request_id=norm_req.request_id,
                provider=self.provider_name,
                model_name=provider_model,
                status=ModelResponseStatus.SUCCESS,
                content=content,
                structured_output=structured,
                usage=usage,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
            )

        classified = classify_transport_error(
            status_code=status_code,
            headers=resp_headers,
            body_str=body_str,
            provider_name=self.provider_name,
            secret_to_redact=self._api_key,
        )

        metadata = dict(classified.get("metadata", {}))
        metadata["error_code"] = classified["code"]
        metadata["error_category"] = classified["category"]
        metadata["retryable"] = classified["retryable"]
        metadata["http_status"] = classified["http_status"]
        metadata["safe_message"] = classified["safe_message"]

        return ModelResponse(
            request_id=norm_req.request_id,
            provider=self.provider_name,
            model_name=model_name,
            status=classified["status"],
            error=classified["error"],
            metadata=metadata,
            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
            latency_ms=latency_ms,
        )

    def generate_stream(self, request: ModelRequest) -> Generator[StreamDelta, None, None]:
        """Execute completion with streaming via OpenAI-compatible SSE endpoint.

        Yields StreamDelta instances with visible-only content deltas.
        Uses same request construction as synchronous generate().
        Adds "stream": True to payload.
        Emits structured ModelStreamError on failures.
        """
        try:
            norm_req = normalize_model_request(request)
        except Exception as e:
            clean_err = sanitize_secrets(str(e))
            yield StreamDelta(
                content="",
                finish_reason="error",
                provider=self.provider_name,
                model_name=getattr(request, "model_name", self._default_model),
                error=ModelStreamError(
                    code="REQUEST_SCHEMA_ERROR",
                    category="VALIDATION",
                    safe_message=clean_err,
                    retryable=False,
                    http_status=None,
                ),
            )
            return

        if not self.is_configured():
            yield StreamDelta(
                content="",
                finish_reason="error",
                provider=self.provider_name,
                model_name=norm_req.model_name if norm_req.model_name not in ("default", "", None) else self._default_model,
                error=ModelStreamError(
                    code="NO_CREDENTIAL",
                    category="CONFIGURATION",
                    safe_message=f"NO_CREDENTIAL: Provider '{self.provider_name}' has no API key configured.",
                    retryable=False,
                    http_status=None,
                ),
            )
            return

        model_name = norm_req.model_name if norm_req.model_name not in ("default", "", None) else self._default_model

        messages = [
            {
                "role": msg.role.value if isinstance(msg.role, ModelRole) else str(msg.role),
                "content": msg.content,
            }
            for msg in norm_req.messages
        ]

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": norm_req.temperature,
            "stream": True,
        }

        if norm_req.max_tokens:
            payload["max_tokens"] = norm_req.max_tokens

        if norm_req.response_schema:
            payload["response_format"] = {"type": "json_object"}

        timeout = norm_req.timeout_seconds if norm_req.timeout_seconds else self._timeout_seconds

        received_visible_content = False
        received_valid_completion = False

        for sse_event in self._transport.post_json_stream(
            endpoint_path=self._chat_completions_path,
            payload=payload,
            timeout_seconds=timeout,
        ):
            if not isinstance(sse_event, dict):
                yield self._stream_provider_response_error(
                    model_name,
                    "Streaming provider event must be a JSON object.",
                )
                return

            if sse_event.get("_error"):
                stream_err = classify_transport_to_stream_error(
                    status_code=sse_event.get("status_code"),
                    headers=sse_event.get("headers", {}),
                    body_str=sse_event.get("body", ""),
                    provider_name=self.provider_name,
                    secret_to_redact=self._api_key,
                    is_timeout=sse_event.get("is_timeout", False),
                    is_network_err=sse_event.get("is_network", False),
                    is_internal_err=sse_event.get("is_internal", False),
                )
                yield StreamDelta(
                    content="",
                    finish_reason="error",
                    provider=self.provider_name,
                    model_name=model_name,
                    error=stream_err,
                )
                return

            if sse_event.get("_done"):
                received_valid_completion = True
                if not received_visible_content:
                    yield StreamDelta(
                        content="",
                        finish_reason="error",
                        provider=self.provider_name,
                        model_name=model_name,
                        error=ModelStreamError(
                            code="EMPTY_RESPONSE",
                            category="RESPONSE_ERROR",
                            safe_message=f"EMPTY_RESPONSE: Provider '{self.provider_name}' completed stream without emitting visible assistant content.",
                            retryable=True,
                            http_status=None,
                        ),
                    )
                else:
                    yield StreamDelta(
                        content="",
                        finish_reason="stop",
                        provider=self.provider_name,
                        model_name=model_name,
                        error=None,
                    )
                return

            choices = sse_event.get("choices")
            if choices is None:
                continue
            if not isinstance(choices, list):
                yield self._stream_provider_response_error(
                    model_name,
                    "Streaming provider field 'choices' must be a list.",
                )
                return
            if not choices:
                continue

            choice = choices[0]
            if not isinstance(choice, dict):
                yield self._stream_provider_response_error(
                    model_name,
                    "Streaming provider first choice must be a JSON object.",
                )
                return

            delta_raw = choice.get("delta")
            if delta_raw is None:
                delta = {}
            elif isinstance(delta_raw, dict):
                delta = delta_raw
            else:
                yield self._stream_provider_response_error(
                    model_name,
                    "Streaming provider choice.delta must be a JSON object or null.",
                )
                return

            finish_reason_raw = choice.get("finish_reason")
            if finish_reason_raw is not None and not isinstance(finish_reason_raw, str):
                yield self._stream_provider_response_error(
                    model_name,
                    "Streaming provider choice.finish_reason must be a string or null.",
                )
                return
            finish_reason = finish_reason_raw

            content_raw = delta.get("content")
            if content_raw is None:
                content = ""
            elif isinstance(content_raw, str):
                content = content_raw
            else:
                yield self._stream_provider_response_error(
                    model_name,
                    "Streaming provider delta.content must be a string or null.",
                )
                return

            provider_model = sse_event.get("model")
            if not isinstance(provider_model, str) or not provider_model.strip():
                provider_model = model_name

            if content:
                received_visible_content = True
                yield StreamDelta(
                    content=content,
                    finish_reason=None,
                    provider=self.provider_name,
                    model_name=provider_model,
                )

            if finish_reason:
                received_valid_completion = True
                if finish_reason == "error":
                    yield StreamDelta(
                        content="",
                        finish_reason="error",
                        provider=self.provider_name,
                        model_name=provider_model,
                        error=ModelStreamError(
                            code="PROVIDER_RESPONSE_ERROR",
                            category="RESPONSE_ERROR",
                            safe_message=f"PROVIDER_RESPONSE_ERROR: Provider '{self.provider_name}' returned finish_reason='error'.",
                            retryable=False,
                            http_status=None,
                        ),
                    )
                elif not received_visible_content:
                    yield StreamDelta(
                        content="",
                        finish_reason="error",
                        provider=self.provider_name,
                        model_name=provider_model,
                        error=ModelStreamError(
                            code="EMPTY_RESPONSE",
                            category="RESPONSE_ERROR",
                            safe_message=f"EMPTY_RESPONSE: Provider '{self.provider_name}' returned finish_reason='{finish_reason}' without emitting visible assistant content.",
                            retryable=True,
                            http_status=None,
                        ),
                    )
                else:
                    yield StreamDelta(
                        content="",
                        finish_reason=finish_reason,
                        provider=self.provider_name,
                        model_name=provider_model,
                        error=None,
                    )
                return

        if not received_valid_completion:
            if not received_visible_content:
                yield StreamDelta(
                    content="",
                    finish_reason="error",
                    provider=self.provider_name,
                    model_name=model_name,
                    error=ModelStreamError(
                        code="STREAM_TRUNCATED",
                        category="STREAM_PROTOCOL",
                        safe_message=f"STREAM_TRUNCATED: Provider '{self.provider_name}' stream closed unexpectedly without completion signal.",
                        retryable=True,
                        http_status=None,
                    ),
                )
            else:
                yield StreamDelta(
                    content="",
                    finish_reason="error",
                    provider=self.provider_name,
                    model_name=model_name,
                    error=ModelStreamError(
                        code="STREAM_TRUNCATED",
                        category="STREAM_PROTOCOL",
                        safe_message=f"STREAM_TRUNCATED: Provider '{self.provider_name}' stream truncated after partial output.",
                        retryable=False,
                        http_status=None,
                    ),
                )
