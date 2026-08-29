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

        # Execute request through standardized transport
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
                return ModelResponse(
                    request_id=norm_req.request_id,
                    provider=self.provider_name,
                    model_name=model_name,
                    status=ModelResponseStatus.ERROR,
                    error=f"PROVIDER_RESPONSE_ERROR: Malformed JSON returned by {self.provider_name} (HTTP {status_code}). Detail: {str(e)[:100]}",
                    usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                    latency_ms=latency_ms,
                )

            choices = resp_data.get("choices", [])
            if not choices:
                return ModelResponse(
                    request_id=norm_req.request_id,
                    provider=self.provider_name,
                    model_name=model_name,
                    status=ModelResponseStatus.ERROR,
                    error=f"PROVIDER_RESPONSE_ERROR: No choices returned by {self.provider_name} API.",
                    usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                    latency_ms=latency_ms,
                )

            first_choice = choices[0]
            message_obj = first_choice.get("message", {})
            content = message_obj.get("content", "") or ""
            finish_reason = first_choice.get("finish_reason", "stop")

            # Parse usage
            usage_raw = resp_data.get("usage", {})
            prompt_tokens = usage_raw.get("prompt_tokens", 0)
            completion_tokens = usage_raw.get("completion_tokens", 0)
            total_tokens = usage_raw.get("total_tokens", prompt_tokens + completion_tokens)

            # Extract optional thought / reasoning tokens if provider returned them
            thoughts_tokens = None
            if "reasoning_tokens" in usage_raw:
                thoughts_tokens = usage_raw.get("reasoning_tokens")
            elif "completion_tokens_details" in usage_raw:
                details = usage_raw.get("completion_tokens_details", {})
                thoughts_tokens = details.get("reasoning_tokens")

            cached_tokens = None
            if "cached_tokens" in usage_raw:
                cached_tokens = usage_raw.get("cached_tokens")
            elif "prompt_tokens_details" in usage_raw:
                details = usage_raw.get("prompt_tokens_details", {})
                cached_tokens = details.get("cached_tokens")

            tool_tokens = usage_raw.get("tool_use_prompt_tokens")

            usage = ModelUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                thoughts_tokens=thoughts_tokens,
                cached_tokens=cached_tokens,
                tool_use_prompt_tokens=tool_tokens,
                total_tokens=total_tokens,
                usage_source="PROVIDER_REPORTED",
            )

            structured = None
            if norm_req.response_schema or content.strip().startswith("{"):
                try:
                    structured = json.loads(content.strip())
                except Exception:
                    structured = None

            return ModelResponse(
                request_id=norm_req.request_id,
                provider=self.provider_name,
                model_name=resp_data.get("model", model_name),
                status=ModelResponseStatus.SUCCESS,
                content=content,
                structured_output=structured,
                usage=usage,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
            )

        # Handle non-2xx HTTP errors via standardized classifier
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

            choices = sse_event.get("choices", [])
            if not choices:
                continue

            choice = choices[0]
            delta = choice.get("delta", {})
            finish_reason = choice.get("finish_reason")

            content = delta.get("content", "")
            if content:
                received_visible_content = True
                yield StreamDelta(
                    content=content,
                    finish_reason=None,
                    provider=self.provider_name,
                    model_name=sse_event.get("model", model_name),
                )

            if finish_reason:
                received_valid_completion = True
                if finish_reason == "error":
                    yield StreamDelta(
                        content="",
                        finish_reason="error",
                        provider=self.provider_name,
                        model_name=sse_event.get("model", model_name),
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
                        model_name=sse_event.get("model", model_name),
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
                        model_name=sse_event.get("model", model_name),
                        error=None,
                    )
                return

        # Handle unexpected stream truncation (EOF without [DONE] or finish_reason)
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
