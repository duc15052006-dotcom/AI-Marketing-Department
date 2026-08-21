"""OpenAI Provider Adapter.

Executes completions against OpenAI / compatible API using native standard library HTTP requests.
Preserves secret safety: never logs or leaks API keys.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional
from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelUsage,
)


class OpenAIProviderAdapter(BaseModelAdapter):
    """Provider adapter for OpenAI and compatible endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gpt-4o-mini",
        api_base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self._default_model = default_model
        self._api_base_url = api_base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.PAID

    @property
    def automatic_fallback_allowed(self) -> bool:
        return False

    def is_configured(self) -> bool:
        """Check if API key is present without exposing it."""
        return bool(self._api_key and len(self._api_key.strip()) > 0)

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute completion via OpenAI REST API."""
        start_time = time.perf_counter()

        if not self.is_configured():
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=request.model_name or self._default_model,
                status=ModelResponseStatus.ERROR,
                error="MISSING_API_KEY: OPENAI_API_KEY is not configured in the environment.",
                latency_ms=latency_ms,
            )

        model_name = request.model_name if request.model_name != "default" else self._default_model

        messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in request.messages
        ]

        payload: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": request.temperature,
        }

        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        if request.response_schema:
            payload["response_format"] = {"type": "json_object"}

        endpoint_url = f"{self._base_url}/chat/completions"

        try:
            req_data = json.dumps(payload).encode("utf-8")
            http_req = urllib.request.Request(
                endpoint_url,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )

            with urllib.request.urlopen(http_req, timeout=request.timeout_seconds) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))

            latency_ms = (time.perf_counter() - start_time) * 1000.0

            choices = resp_data.get("choices", [])
            if not choices:
                return ModelResponse(
                    request_id=request.request_id,
                    provider=self.provider_name,
                    model_name=model_name,
                    status=ModelResponseStatus.ERROR,
                    error="No choices returned by OpenAI API.",
                    latency_ms=latency_ms,
                )

            first_choice = choices[0]
            text_content = first_choice.get("message", {}).get("content", "")
            finish_reason = first_choice.get("finish_reason", "stop")

            usage_meta = resp_data.get("usage", {})
            usage = ModelUsage(
                prompt_tokens=usage_meta.get("prompt_tokens", 0),
                completion_tokens=usage_meta.get("completion_tokens", 0),
                total_tokens=usage_meta.get("total_tokens", 0),
            )

            structured = None
            if request.response_schema or text_content.strip().startswith("{"):
                try:
                    structured = json.loads(text_content)
                except Exception:
                    structured = None

            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=model_name,
                status=ModelResponseStatus.SUCCESS,
                content=text_content,
                structured_output=structured,
                usage=usage,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
            )

        except urllib.error.HTTPError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=model_name,
                status=ModelResponseStatus.ERROR,
                error=f"OpenAI HTTP {e.code}: {e.reason}. Detail: {error_body[:300]}",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=model_name,
                status=ModelResponseStatus.ERROR,
                error=f"OpenAI Request Failed: {type(e).__name__}: {str(e)}",
                latency_ms=latency_ms,
            )
