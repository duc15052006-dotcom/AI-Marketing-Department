"""OpenAI-Compatible Transport Layer (Phase 4.3C.3).

Provides a robust, provider-agnostic HTTP transport for OpenAI-compatible REST endpoints
with:
- Standardized API headers (Authorization, Content-Type, Accept, SDK User-Agent)
- Fine-grained HTTP error classification (401 Auth, 403 Permission vs Cloudflare 1010 Access Denied, 429 / 1015 Rate Limits, 5xx Unavailable)
- HTML / Problem+JSON / Plaintext Cloudflare edge error extraction (Error code, Ray ID)
- Strict secret sanitization (zero API key / Bearer token leakage)
- Clean testability via dependency injection or mock transport
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, Optional, Tuple
import urllib.error
import urllib.request

from integrations.models.base import ModelResponseStatus

logger = logging.getLogger("openai_compatible_transport")

DEFAULT_USER_AGENT = "AI-Marketing-Department/1.0 (OpenAI-Compatible-Client)"


def sanitize_secrets(text: str, secret: Optional[str] = None) -> str:
    """Sanitize secret API keys and Bearer tokens from text/logs."""
    if not text:
        return ""
    sanitized = text
    if secret and len(secret.strip()) > 0:
        sanitized = sanitized.replace(secret.strip(), "[REDACTED_API_KEY]")
    # Redact any Bearer tokens
    sanitized = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1[REDACTED_TOKEN]", sanitized, flags=re.IGNORECASE)
    return sanitized


class OpenAICompatibleTransport:
    """Standardized HTTP Transport for OpenAI-Compatible APIs."""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def build_headers(self) -> Dict[str, str]:
        """Construct standard API request headers."""
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.api_key and len(self.api_key.strip()) > 0:
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers

    def post_json(
        self,
        endpoint_path: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float] = None,
    ) -> Tuple[int, Dict[str, str], str]:
        """Execute HTTP POST and return (status_code, response_headers, response_body_text)."""
        url = f"{self.base_url}/{endpoint_path.lstrip('/')}"
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        req_bytes = json.dumps(payload).encode("utf-8")
        headers = self.build_headers()

        http_req = urllib.request.Request(
            url=url,
            data=req_bytes,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(http_req, timeout=timeout) as resp:
                status_code = getattr(resp, "status", None)
                if status_code is None or not isinstance(status_code, int):
                    status_code = getattr(resp, "code", None)
                if status_code is None or not isinstance(status_code, int):
                    if hasattr(resp, "getcode") and callable(resp.getcode):
                        try:
                            code_val = resp.getcode()
                            if isinstance(code_val, int):
                                status_code = code_val
                        except Exception:
                            pass
                if status_code is None or not isinstance(status_code, int):
                    status_code = 200

                if hasattr(resp, "headers") and hasattr(resp.headers, "items"):
                    resp_headers = {str(k).lower(): str(v) for k, v in resp.headers.items()}
                else:
                    resp_headers = {}

                body_bytes = resp.read()
                if isinstance(body_bytes, bytes):
                    body_str = body_bytes.decode("utf-8", errors="replace")
                else:
                    body_str = str(body_bytes)
                return status_code, resp_headers, body_str

        except urllib.error.HTTPError as e:
            status_code = e.code
            resp_headers = {k.lower(): v for k, v in e.headers.items()} if hasattr(e, "headers") else {}
            try:
                body_str = e.read().decode("utf-8", errors="replace")
            except Exception:
                body_str = ""
            return status_code, resp_headers, body_str

        except (TimeoutError, urllib.error.URLError) as e:
            is_timeout = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
            status_code = 408 if is_timeout else 599
            return status_code, {}, str(e)


def extract_cloudflare_error(status_code: int, headers: Dict[str, str], body_str: str) -> Optional[Dict[str, Any]]:
    """Inspect response for Cloudflare WAF/Edge error signatures (1010, 1015, 1020, etc.)."""
    lower_body = body_str.lower()
    is_cf = (
        "cloudflare" in lower_body
        or "cf-ray" in headers
        or "server" in headers and "cloudflare" in headers["server"].lower()
    )

    ray_id = headers.get("cf-ray")
    if not ray_id:
        ray_match = re.search(r"ray\s*id:\s*([a-f0-9]+)", body_str, flags=re.IGNORECASE)
        if ray_match:
            ray_id = ray_match.group(1)

    # Cloudflare 1010: Access Denied / User-Agent or IP block
    if "1010" in body_str or "error code: 1010" in lower_body or ("access denied" in lower_body and is_cf and status_code == 403):
        return {
            "edge_provider": "cloudflare",
            "edge_error_code": "1010",
            "error_category": "access_denied",
            "ray_id": ray_id,
            "retryable": False,
            "auth_error": False,
        }

    # Cloudflare 1015: Rate Limited
    if "1015" in body_str or "error code: 1015" in lower_body or ("rate limit" in lower_body and is_cf):
        return {
            "edge_provider": "cloudflare",
            "edge_error_code": "1015",
            "error_category": "rate_limited",
            "ray_id": ray_id,
            "retryable": True,
            "auth_error": False,
        }

    # Generic Cloudflare block
    if is_cf and status_code == 403:
        return {
            "edge_provider": "cloudflare",
            "edge_error_code": "generic_403",
            "error_category": "access_denied",
            "ray_id": ray_id,
            "retryable": False,
            "auth_error": False,
        }

    return None


def classify_transport_error(
    status_code: int,
    headers: Dict[str, str],
    body_str: str,
    provider_name: str,
    secret_to_redact: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize HTTP error responses into structured categories and standardized messages."""
    clean_body = sanitize_secrets(body_str, secret_to_redact)
    cf_meta = extract_cloudflare_error(status_code, headers, clean_body)

    # Try parsing JSON error body if available
    json_error_detail = None
    try:
        parsed = json.loads(clean_body)
        if isinstance(parsed, dict) and "error" in parsed:
            err_obj = parsed["error"]
            if isinstance(err_obj, dict):
                json_error_detail = err_obj.get("message") or err_obj.get("code")
            elif isinstance(err_obj, str):
                json_error_detail = err_obj
    except Exception:
        pass

    detail_snippet = json_error_detail or clean_body[:200]

    # 1. Cloudflare 1010 / Access Denied
    if cf_meta and cf_meta.get("edge_error_code") == "1010":
        msg = f"PROVIDER_ACCESS_DENIED: {provider_name} HTTP 403: Cloudflare Error 1010 (Access Denied). Ray ID: {cf_meta.get('ray_id') or 'N/A'}"
        return {
            "status": ModelResponseStatus.ERROR,
            "error": msg,
            "metadata": {
                "http_status": 403,
                **cf_meta,
            },
        }

    # 2. Cloudflare 1015 / Rate Limited
    if cf_meta and cf_meta.get("edge_error_code") == "1015":
        msg = f"RATE_LIMITED: {provider_name} HTTP 403: Cloudflare Error 1015 (Rate Limited). Ray ID: {cf_meta.get('ray_id') or 'N/A'}"
        return {
            "status": ModelResponseStatus.RATE_LIMITED,
            "error": msg,
            "metadata": {
                "http_status": 403,
                **cf_meta,
            },
        }

    # 3. HTTP 401 Unauthorized (Invalid API Key)
    if status_code == 401:
        msg = f"AUTH_ERROR: {provider_name} HTTP 401 Unauthorized. Detail: {detail_snippet}"
        return {
            "status": ModelResponseStatus.ERROR,
            "error": msg,
            "metadata": {
                "http_status": 401,
                "error_category": "invalid_credentials",
                "retryable": False,
                "auth_error": True,
            },
        }

    # 4. HTTP 403 Forbidden (Permission / Authorization Error)
    if status_code == 403:
        if cf_meta:
            msg = f"PROVIDER_ACCESS_DENIED: {provider_name} HTTP 403 Cloudflare Access Denied. Detail: {detail_snippet}"
            return {
                "status": ModelResponseStatus.ERROR,
                "error": msg,
                "metadata": {
                    "http_status": 403,
                    **cf_meta,
                },
            }
        msg = f"AUTHORIZATION_ERROR: {provider_name} HTTP 403 Forbidden (Permission Denied). Detail: {detail_snippet}"
        return {
            "status": ModelResponseStatus.ERROR,
            "error": msg,
            "metadata": {
                "http_status": 403,
                "error_category": "permission_denied",
                "retryable": False,
                "auth_error": False,
            },
        }

    # 5. HTTP 429 Rate Limited
    if status_code == 429:
        msg = f"RATE_LIMITED: {provider_name} HTTP 429 Too Many Requests. Detail: {detail_snippet}"
        return {
            "status": ModelResponseStatus.RATE_LIMITED,
            "error": msg,
            "metadata": {
                "http_status": 429,
                "error_category": "rate_limited",
                "retryable": True,
            },
        }

    # 6. HTTP 408 / Timeout
    if status_code == 408:
        msg = f"TIMEOUT: {provider_name} request timed out."
        return {
            "status": ModelResponseStatus.TIMEOUT,
            "error": msg,
            "metadata": {
                "http_status": 408,
                "error_category": "timeout",
                "retryable": True,
            },
        }

    # 7. HTTP 5xx Server Errors
    if status_code in (500, 502, 503, 504, 599):
        msg = f"PROVIDER_UNAVAILABLE: {provider_name} HTTP {status_code} Server Error. Detail: {detail_snippet}"
        return {
            "status": ModelResponseStatus.ERROR,
            "error": msg,
            "metadata": {
                "http_status": status_code,
                "error_category": "server_error",
                "retryable": True,
            },
        }

    # 8. HTTP 400 Bad Request
    if status_code == 400:
        msg = f"INVALID_REQUEST: {provider_name} HTTP 400 Bad Request. Detail: {detail_snippet}"
        return {
            "status": ModelResponseStatus.ERROR,
            "error": msg,
            "metadata": {
                "http_status": 400,
                "error_category": "bad_request",
                "retryable": False,
            },
        }

    # 9. Generic Fallback
    msg = f"PROVIDER_RESPONSE_ERROR: {provider_name} HTTP {status_code}. Detail: {detail_snippet}"
    return {
        "status": ModelResponseStatus.ERROR,
        "error": msg,
        "metadata": {
            "http_status": status_code,
            "error_category": "response_error",
            "retryable": False,
        },
    }
