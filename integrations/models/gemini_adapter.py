"""Google Gemini Provider Adapter (Phase 3A / 3D.1.6).

Executes completions against official Google Gemini API using native standard library HTTP requests.
Preserves secret safety: never logs or leaks API keys.
Maps normalized ModelRequest/ModelResponse schemas and usageMetadata.
"""

from __future__ import annotations

import json
import logging
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
    ModelRole,
    ModelUsage,
    normalize_model_request,
)

logger = logging.getLogger("gemini_adapter")


class GeminiProviderAdapter(BaseModelAdapter):
    """Production Gemini Adapter using native REST API with zero external dependencies."""

    # Explicit Model Registry & Stable Routing Aliases
    MODEL_ALIASES: Dict[str, str] = {
        "gemini-flash-latest": "gemini-3.5-flash",
        "gemini-3.5-flash": "gemini-3.5-flash",
        "gemini-3.6-flash": "gemini-3.6-flash",
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-pro-latest": "gemini-2.5-pro",
        "gemini-2.0-flash": "gemini-3.5-flash",
        "gemini-1.5-flash": "gemini-3.5-flash",
        "gemini-1.5-pro": "gemini-2.5-pro",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gemini-flash-latest",
        api_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        self._api_key = (
            api_key
            if api_key is not None
            else (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        )
        self._default_model = default_model
        self._api_base_url = api_base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.FREE_TIER_ALLOWED

    @property
    def automatic_fallback_allowed(self) -> bool:
        return True

    def is_configured(self) -> bool:
        """Check if API key is present without exposing it."""
        return bool(self._api_key and len(self._api_key.strip()) > 0)

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute completion via Gemini REST API."""
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
                model_name=norm_req.model_name or self._default_model,
                status=ModelResponseStatus.ERROR,
                error="MISSING_API_KEY: Neither GEMINI_API_KEY nor GOOGLE_API_KEY is configured in the environment.",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=latency_ms,
            )

        raw_model = norm_req.model_name if norm_req.model_name not in ("default", "", None) else self._default_model
        # Map alias if applicable to guarantee stable operational endpoint
        model_name = self.MODEL_ALIASES.get(raw_model, raw_model)

        # Build contents payload
        system_instruction_text = ""
        contents: List[Dict[str, Any]] = []

        for msg in norm_req.messages:
            if msg.role == ModelRole.SYSTEM:
                system_instruction_text += f"{msg.content}\n"
            elif msg.role == ModelRole.USER:
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == ModelRole.ASSISTANT:
                contents.append({"role": "model", "parts": [{"text": msg.content}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
            },
        }

        if request.max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = request.max_tokens

        if system_instruction_text.strip():
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction_text.strip()}]
            }

        # If structured output JSON is requested
        if request.response_schema:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        try:
            endpoint_url = f"{self._api_base_url}/models/{model_name}:generateContent"
            max_http_retries = 5
            resp_data = None
            for attempt in range(max_http_retries):
                try:
                    req_data = json.dumps(payload).encode("utf-8")
                    http_req = urllib.request.Request(
                        endpoint_url,
                        data=req_data,
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": self._api_key,
                        },
                        method="POST",
                    )

                    with urllib.request.urlopen(http_req, timeout=request.timeout_seconds) as resp:
                        resp_data = json.loads(resp.read().decode("utf-8"))
                    break  # success
                except (urllib.error.HTTPError, TimeoutError, urllib.error.URLError) as e:
                    if attempt < max_http_retries - 1:
                        elapsed = time.perf_counter() - start_time
                        if elapsed >= request.timeout_seconds or request.timeout_seconds <= 5.0:
                            raise e
                        backoff = min(request.timeout_seconds - elapsed, 20.0 * (attempt + 1) if (isinstance(e, urllib.error.HTTPError) and e.code == 429) else 4.0 * (attempt + 1))
                        if backoff <= 0:
                            raise e
                        time.sleep(backoff)
                        continue
                    raise e

            if resp_data is None:
                raise RuntimeError("No response data received from Gemini API.")
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            candidates = resp_data.get("candidates", [])
            if not candidates:
                # Check for prompt feedback blocking
                block_reason = resp_data.get("promptFeedback", {}).get("blockReason")
                err_msg = f"CONTENT_BLOCKED: {block_reason}" if block_reason else "No candidates returned by Gemini API."
                return ModelResponse(
                    request_id=request.request_id,
                    provider=self.provider_name,
                    model_name=raw_model,
                    status=ModelResponseStatus.ERROR,
                    error=err_msg,
                    latency_ms=latency_ms,
                )

            first_candidate = candidates[0]
            content_parts = first_candidate.get("content", {}).get("parts", [])
            text_content = "".join(p.get("text", "") for p in content_parts)
            finish_reason = first_candidate.get("finishReason", "STOP")

            # Parse usage metadata
            usage_meta = resp_data.get("usageMetadata", {})
            thoughts_tokens = usage_meta.get("thoughtsTokenCount")
            if thoughts_tokens is None and "candidatesTokensDetails" in usage_meta:
                for detail in usage_meta.get("candidatesTokensDetails", []):
                    if detail.get("modality") == "THOUGHTS" or "thought" in str(detail).lower():
                        thoughts_tokens = detail.get("tokenCount")
                        break

            cached_tokens = usage_meta.get("cachedContentTokenCount")
            tool_tokens = usage_meta.get("toolUsePromptTokenCount")

            usage = ModelUsage(
                prompt_tokens=usage_meta.get("promptTokenCount", 0),
                completion_tokens=usage_meta.get("candidatesTokenCount", 0),
                thoughts_tokens=thoughts_tokens,
                cached_tokens=cached_tokens,
                tool_use_prompt_tokens=tool_tokens,
                total_tokens=usage_meta.get("totalTokenCount", 0),
                usage_source="PROVIDER_REPORTED" if usage_meta else "NOT_REPORTED",
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
                model_name=raw_model,
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
                # Redact any accidental credential echo
                if self._api_key and self._api_key in error_body:
                    error_body = error_body.replace(self._api_key, "[REDACTED_API_KEY]")
            except Exception:
                pass

            if e.code == 400:
                norm_err = f"INVALID_REQUEST: Gemini HTTP 400: {e.reason}. Detail: {error_body[:300]}"
            elif e.code in (401, 403):
                norm_err = f"AUTHENTICATION_ERROR: Gemini HTTP {e.code}: {e.reason}. Detail: {error_body[:300]}"
            elif e.code == 404:
                norm_err = f"MODEL_NOT_AVAILABLE: Gemini HTTP 404: {e.reason}. Detail: {error_body[:300]}"
            elif e.code == 429:
                norm_err = f"FREE_TIER_QUOTA_EXCEEDED: Gemini HTTP 429 Rate Limit. Detail: {error_body[:300]}"
            else:
                norm_err = f"PROVIDER_ERROR: Gemini HTTP {e.code}: {e.reason}. Detail: {error_body[:300]}"

            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=raw_model,
                status=ModelResponseStatus.ERROR,
                error=norm_err,
                latency_ms=latency_ms,
            )
        except urllib.error.URLError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            if "timed out" in str(e).lower():
                norm_err = f"TIMEOUT: Gemini request timed out after {request.timeout_seconds}s"
            else:
                norm_err = f"NETWORK_ERROR: Gemini network error: {str(e)}"
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=raw_model,
                status=ModelResponseStatus.ERROR,
                error=norm_err,
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=raw_model,
                status=ModelResponseStatus.ERROR,
                error=f"PROVIDER_ERROR: Gemini Request Failed: {type(e).__name__}: {str(e)}",
                latency_ms=latency_ms,
            )
