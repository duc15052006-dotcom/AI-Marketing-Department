"""TheSparkDaily Third-Party OpenAI-Compatible Provider Adapter.

Executes completions against TheSparkDaily endpoint (https://llm.thesparkdaily.com/v1).
Explicitly marks provider provenance as THIRD_PARTY and model provenance as UNVERIFIED_THIRD_PARTY_CLAIM.
Preserves secret safety: never logs or leaks API keys.
Handles provider-specific constraints (e.g. temperature=1.0 requirement for underlying Azure reasoning endpoints).
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


class TheSparkProviderAdapter(BaseModelAdapter):
    """Third-party OpenAI-compatible provider adapter for TheSparkDaily."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("THESPARK_API_KEY")
        self._base_url = (
            base_url
            if base_url is not None
            else os.environ.get("THESPARK_BASE_URL", "https://llm.thesparkdaily.com/v1")
        ).rstrip("/")
        self._default_model = (
            default_model
            if default_model is not None
            else os.environ.get("THESPARK_MODEL", "gpt-5.6-sol")
        )

    @property
    def provider_name(self) -> str:
        return "thespark"

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.PAID

    @property
    def automatic_fallback_allowed(self) -> bool:
        return False

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def default_model(self) -> str:
        return self._default_model

    def is_configured(self) -> bool:
        """Check if API key is present without exposing it."""
        return bool(self._api_key and len(self._api_key.strip()) > 0)

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute completion via TheSparkDaily OpenAI-compatible REST API."""
        start_time = time.perf_counter()

        model_name = (
            request.model_name
            if (request.model_name and request.model_name != "default")
            else self._default_model
        )

        if not self.is_configured():
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=model_name,
                status=ModelResponseStatus.ERROR,
                error="MISSING_API_KEY: THESPARK_API_KEY is not configured in the environment.",
                latency_ms=latency_ms,
                provider_type="third_party_openai_compatible",
                provider_provenance="THIRD_PARTY",
                model_provenance="UNVERIFIED_THIRD_PARTY_CLAIM",
                trust_status="UNVERIFIED",
            )

        messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in request.messages
        ]

        payload: dict = {
            "model": model_name,
            "messages": messages,
            # Note: TheSpark / underlying Azure reasoning endpoint requires temperature=1 (or omitted)
            "temperature": 1.0,
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
                    error="No choices returned by TheSparkDaily endpoint.",
                    latency_ms=latency_ms,
                    provider_type="third_party_openai_compatible",
                    provider_provenance="THIRD_PARTY",
                    model_provenance="UNVERIFIED_THIRD_PARTY_CLAIM",
                    trust_status="UNVERIFIED",
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
                provider_type="third_party_openai_compatible",
                provider_provenance="THIRD_PARTY",
                model_provenance="UNVERIFIED_THIRD_PARTY_CLAIM",
                trust_status="UNVERIFIED",
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
                error=f"TheSpark HTTP {e.code}: {e.reason}. Detail: {error_body[:300]}",
                latency_ms=latency_ms,
                provider_type="third_party_openai_compatible",
                provider_provenance="THIRD_PARTY",
                model_provenance="UNVERIFIED_THIRD_PARTY_CLAIM",
                trust_status="UNVERIFIED",
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=model_name,
                status=ModelResponseStatus.ERROR,
                error=f"TheSpark Request Failed: {type(e).__name__}: {str(e)}",
                latency_ms=latency_ms,
                provider_type="third_party_openai_compatible",
                provider_provenance="THIRD_PARTY",
                model_provenance="UNVERIFIED_THIRD_PARTY_CLAIM",
                trust_status="UNVERIFIED",
            )
