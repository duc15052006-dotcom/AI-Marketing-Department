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

import errno
import http.client
import json
import logging
import re
import socket
import time
from typing import Any, Dict, Generator, Optional, Tuple
import urllib.error
import urllib.request

from integrations.models.base import ModelResponseStatus, ModelStreamError

logger = logging.getLogger("openai_compatible_transport")

DEFAULT_USER_AGENT = "AI-Marketing-Department/1.0 (OpenAI-Compatible-Client)"

NETWORK_ERRNOS = {
    errno.ECONNRESET,
    errno.ECONNREFUSED,
    errno.ECONNABORTED,
    errno.ENETUNREACH,
    errno.EHOSTUNREACH,
    errno.ETIMEDOUT,
    errno.EPIPE,
    errno.ENETDOWN,
    errno.ENETRESET,
    errno.ESHUTDOWN,
    errno.EHOSTDOWN,
}
for wsa_code in (10051, 10052, 10053, 10054, 10057, 10058, 10060, 10061, 10064, 10065):
    NETWORK_ERRNOS.add(wsa_code)

NON_NETWORK_OS_ERRORS = (
    PermissionError,
    FileNotFoundError,
    IsADirectoryError,
    FileExistsError,
    NotADirectoryError,
    ProcessLookupError,
    InterruptedError,
)


def is_timeout_exception(exc: BaseException) -> bool:
    """Return True only if exc is a true timeout exception."""
    if isinstance(exc, NON_NETWORK_OS_ERRORS):
        return False
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return True
        if isinstance(reason, BaseException):
            return is_timeout_exception(reason)
        return False
    if isinstance(exc, (socket.error, OSError)):
        err_no = getattr(exc, "errno", None) or getattr(exc, "winerror", None)
        if err_no in (errno.ETIMEDOUT, 10060):
            return True
    return False


def is_network_exception(exc: BaseException) -> bool:
    """Return True only if exc is a true network/socket/transport exception."""
    if isinstance(exc, NON_NETWORK_OS_ERRORS):
        return False
    if is_timeout_exception(exc):
        return False
    if isinstance(exc, (ConnectionError, BrokenPipeError, ConnectionResetError, ConnectionRefusedError, ConnectionAbortedError, http.client.RemoteDisconnected, http.client.IncompleteRead, http.client.HTTPException)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if reason is not None:
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return False
            if isinstance(reason, BaseException):
                return is_network_exception(reason)
            # Plain string reason on URLError is generic transport network failure
            if isinstance(reason, str):
                return True
        return True
    if isinstance(exc, (socket.gaierror, socket.herror)):
        return True
    if isinstance(exc, (socket.error, OSError)):
        err_no = getattr(exc, "errno", None) or getattr(exc, "winerror", None)
        if err_no in NETWORK_ERRNOS:
            return True
    return False


def sanitize_secrets(text: str, secret: Optional[str] = None) -> str:
    """Sanitize secret API keys, tokens, and credentials from text/logs."""
    if not text:
        return ""
    sanitized = str(text)
    if secret and len(secret.strip()) > 0:
        sanitized = sanitized.replace(secret.strip(), "[REDACTED_API_KEY]")

    # 1. Bearer and Basic Authorization headers / tokens (no minimum length requirement)
    sanitized = re.sub(
        r"""((?:Authorization\s*:\s*)?Bearer\s+)[^\s,;}{"']+""",
        r"\1[REDACTED_TOKEN]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"""((?:Authorization\s*:\s*)?Basic\s+)[^\s,;}{"']+""",
        r"\1[REDACTED_BASIC_AUTH]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # 2. URL query parameters (?access_token=... / &api_key=... / ?token=...)
    sanitized = re.sub(
        r"([?&](?:api[_\-]?key|apiKey|access[_\-]?token|accessToken|token|secret|password)=)[^&\s]+",
        r"\1[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # 3. Quoted JSON / Dict / Config key-value pairs (e.g. {"api_key": "secret"} or 'password': 'foo' or key = "val")
    sanitized = re.sub(
        r"""(?i)(["']?(?:api[_\-]?key|apiKey|access[_\-]?token|accessToken|token|secret|password)["']?\s*[:=]\s*["'])([^"'\r\n]+)(["'])""",
        r"\1[REDACTED]\3",
        sanitized,
    )

    # 4. Unquoted key-value assignments (e.g. api_key=secret or password: foo or secret = foo)
    sanitized = re.sub(
        r"""(?i)(["']?(?:api[_\-]?key|apiKey|access[_\-]?token|accessToken|token|secret|password)["']?\s*[:=]\s*)([^\s,;}{"'&?]+)""",
        r"\1[REDACTED]",
        sanitized,
    )

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

        except Exception as e:
            if is_timeout_exception(e):
                return 408, {}, str(e)
            elif is_network_exception(e):
                return 599, {}, str(e)
            raise

    def post_json_stream(
        self,
        endpoint_path: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[float] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Execute HTTP POST with streaming SSE response.

        Yields parsed JSON objects from `data: {...}` lines.
        Handles `data: [DONE]` termination signal.
        Closes HTTP response on generator exhaustion or early termination.

        Does NOT use whole-body resp.read().
        """
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

        resp = None
        try:
            resp = urllib.request.urlopen(http_req, timeout=timeout)
            buffer = b""

            while True:
                try:
                    chunk = resp.read(1)
                except Exception as read_err:
                    if is_timeout_exception(read_err):
                        yield {
                            "_error": True,
                            "status_code": 408,
                            "headers": {},
                            "body": str(read_err),
                            "is_timeout": True,
                            "is_network": False,
                            "is_internal": False,
                        }
                    elif is_network_exception(read_err):
                        yield {
                            "_error": True,
                            "status_code": 599,
                            "headers": {},
                            "body": str(read_err),
                            "is_timeout": False,
                            "is_network": True,
                            "is_internal": False,
                        }
                    else:
                        yield {
                            "_error": True,
                            "status_code": None,
                            "headers": {},
                            "body": str(read_err),
                            "is_timeout": False,
                            "is_network": False,
                            "is_internal": True,
                        }
                    break

                if not chunk:
                    break

                buffer += chunk

                while b"\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")

                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:].strip()

                    if data_str == "[DONE]":
                        yield {"_done": True}
                        return

                    try:
                        parsed = json.loads(data_str)
                        yield parsed
                    except json.JSONDecodeError:
                        continue

            # Process any remaining unparsed buffer at EOF (e.g. [DONE] without trailing newline)
            if buffer:
                line = buffer.decode("utf-8", errors="replace").rstrip("\r")
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        yield {"_done": True}
                        return
                    try:
                        parsed = json.loads(data_str)
                        yield parsed
                    except json.JSONDecodeError:
                        pass

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            resp_headers = {k.lower(): v for k, v in e.headers.items()} if hasattr(e, "headers") and e.headers else {}
            yield {
                "_error": True,
                "status_code": e.code,
                "headers": resp_headers,
                "body": error_body,
                "is_timeout": False,
                "is_network": False,
                "is_internal": False,
            }

        except Exception as e:
            if is_timeout_exception(e):
                yield {
                    "_error": True,
                    "status_code": 408,
                    "headers": {},
                    "body": str(e),
                    "is_timeout": True,
                    "is_network": False,
                    "is_internal": False,
                }
            elif is_network_exception(e):
                yield {
                    "_error": True,
                    "status_code": 599,
                    "headers": {},
                    "body": str(e),
                    "is_timeout": False,
                    "is_network": True,
                    "is_internal": False,
                }
            else:
                yield {
                    "_error": True,
                    "status_code": None,
                    "headers": {},
                    "body": str(e),
                    "is_timeout": False,
                    "is_network": False,
                    "is_internal": True,
                }

        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass


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
            "code": "PROVIDER_ACCESS_DENIED",
            "category": "AUTHORIZATION",
            "safe_message": msg,
            "retryable": False,
            "http_status": 403,
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
            "code": "RATE_LIMITED",
            "category": "RATE_LIMIT",
            "safe_message": msg,
            "retryable": True,
            "http_status": 403,
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
            "code": "AUTH_ERROR",
            "category": "AUTHENTICATION",
            "safe_message": msg,
            "retryable": False,
            "http_status": 401,
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
                "code": "PROVIDER_ACCESS_DENIED",
                "category": "AUTHORIZATION",
                "safe_message": msg,
                "retryable": False,
                "http_status": 403,
                "metadata": {
                    "http_status": 403,
                    **cf_meta,
                },
            }
        msg = f"AUTHORIZATION_ERROR: {provider_name} HTTP 403 Forbidden (Permission Denied). Detail: {detail_snippet}"
        return {
            "status": ModelResponseStatus.ERROR,
            "error": msg,
            "code": "AUTHORIZATION_ERROR",
            "category": "AUTHORIZATION",
            "safe_message": msg,
            "retryable": False,
            "http_status": 403,
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
            "code": "RATE_LIMITED",
            "category": "RATE_LIMIT",
            "safe_message": msg,
            "retryable": True,
            "http_status": 429,
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
            "code": "TIMEOUT",
            "category": "TIMEOUT",
            "safe_message": msg,
            "retryable": True,
            "http_status": 408,
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
            "code": "PROVIDER_UNAVAILABLE",
            "category": "SERVER_ERROR",
            "safe_message": msg,
            "retryable": True,
            "http_status": status_code,
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
            "code": "INVALID_REQUEST",
            "category": "BAD_REQUEST",
            "safe_message": msg,
            "retryable": False,
            "http_status": 400,
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
        "code": "PROVIDER_RESPONSE_ERROR",
        "category": "RESPONSE_ERROR",
        "safe_message": msg,
        "retryable": False,
        "http_status": status_code,
        "metadata": {
            "http_status": status_code,
            "error_category": "response_error",
            "retryable": False,
        },
    }


def classify_transport_to_stream_error(
    status_code: Optional[int],
    headers: Dict[str, str],
    body_str: str,
    provider_name: str,
    secret_to_redact: Optional[str] = None,
    is_timeout: bool = False,
    is_network_err: bool = False,
    is_internal_err: bool = False,
) -> ModelStreamError:
    """Deterministic, machine-driven conversion of transport error evidence into ModelStreamError."""
    clean_detail = sanitize_secrets(str(body_str or ""), secret_to_redact)
    if len(clean_detail) > 200:
        clean_detail = clean_detail[:200] + "..."

    if is_timeout:
        return ModelStreamError(
            code="TIMEOUT",
            category="TIMEOUT",
            safe_message=f"TIMEOUT: {provider_name} request timed out.",
            retryable=True,
            http_status=408 if status_code == 408 else None,
        )

    if is_network_err:
        return ModelStreamError(
            code="NETWORK_ERROR",
            category="NETWORK",
            safe_message=f"NETWORK_ERROR: Failed to connect to {provider_name}. Detail: {clean_detail}",
            retryable=True,
            http_status=None,
        )

    if is_internal_err:
        return ModelStreamError(
            code="STREAM_INTERNAL_ERROR",
            category="INTERNAL",
            safe_message=f"STREAM_INTERNAL_ERROR: Internal streaming error on {provider_name}. Detail: {clean_detail}",
            retryable=False,
            http_status=None,
        )

    # HTTP error response
    classified = classify_transport_error(
        status_code=status_code or 500,
        headers=headers,
        body_str=body_str or "",
        provider_name=provider_name,
        secret_to_redact=secret_to_redact,
    )

    return ModelStreamError(
        code=classified["code"],
        category=classified["category"],
        safe_message=classified["safe_message"],
        retryable=classified["retryable"],
        http_status=classified["http_status"],
    )
