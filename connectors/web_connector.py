"""Real Web and Observation Connector (Phase 6.1).

Implements real read-oriented HTTP fetching, HTML text extraction,
and search querying with SSRF protection and sanitized error handling.
"""

from __future__ import annotations

import http.client
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.gateway.security import SecurityValidationError, SecurityValidator
from tools.receipts import ExecutionMode


def _safe_create_connection(
    address,
    timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
    source_address=None,
    *,
    all_errors: bool = False,
):
    """Connect only to an IP address resolved and validated in the same operation.

    ``socket.create_connection`` resolves a hostname internally.  Doing a separate
    SSRF DNS pre-check and then calling it would create a DNS-rebinding race.  This
    helper resolves once, validates every returned address, and connects directly
    to a validated sockaddr without resolving the hostname again.
    """
    host, port = address
    addr_info = SecurityValidator.resolve_public_addresses(host, port)
    errors: list[OSError] = []

    for family, socktype, proto, _canonname, sockaddr in addr_info:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            errors.append(exc)
            if sock is not None:
                sock.close()

    if errors:
        if all_errors and len(errors) > 1:
            raise ExceptionGroup("create_connection failed", errors)
        raise errors[-1]
    raise OSError("No validated address was available for connection.")


class _SafeHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection whose actual socket connect is SSRF-safe and DNS-pinned."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _safe_create_connection


class _SafeHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection retaining hostname/SNI while pinning the validated IP."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _safe_create_connection


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # type: ignore[override]
        return self.do_open(_SafeHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # type: ignore[override]
        return self.do_open(
            _SafeHTTPSConnection,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target before urllib is allowed to follow it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        safe_url = SecurityValidator.validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


class RealWebConnector(BaseCapabilityAdapter):
    """Real HTTP reading and observation connector with strict read-only safety."""

    def __init__(self, timeout_seconds: float = 15.0, user_agent: str = "AI-Marketing-Department/1.0") -> None:
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent

    @property
    def adapter_name(self) -> str:
        return "system_http_reader"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        """Declare the backend mode selected for receipt provenance."""
        cap = capability_id.lower()
        return ExecutionMode.REAL if cap in ("read_page", "analyze_url") else ExecutionMode.MOCK

    @staticmethod
    def _security_failure(
        error: SecurityValidationError,
        start_time: float,
    ) -> AdapterResult:
        # Preserve the legacy generic SSRF code for callers while retaining the
        # specific validator code in the sanitized message for diagnostics.
        code = "SSRF_BLOCKED" if error.code.startswith("SSRF_") else error.code
        return AdapterResult(
            success=False,
            error_code=code,
            error_message=f"Outbound URL blocked ({error.code}): {error.message}",
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 15.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        start_time = time.perf_counter()
        cap = capability_id.lower()

        if cap in ("read_page", "analyze_url"):
            url = parameters.get("url", "")
            if not url:
                return AdapterResult(
                    success=False,
                    error_code="INVALID_URL",
                    error_message="Missing required parameter 'url'.",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            # Keep the existing scheme contract, then delegate all hostname/IP/DNS
            # SSRF decisions to the shared security authority used by observation.
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return AdapterResult(
                    success=False,
                    error_code="INVALID_SCHEME",
                    error_message=f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed.",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            try:
                safe_url = SecurityValidator.validate_url(url)
            except SecurityValidationError as error:
                return self._security_failure(error, start_time)

            try:
                req = urllib.request.Request(
                    safe_url,
                    headers={"User-Agent": self._user_agent, "Accept": "text/html,application/xhtml+xml,text/plain"},
                )
                # Disable environment proxies for this connector: otherwise the
                # actual network destination could bypass the validated direct
                # connection path.  Custom HTTP(S) handlers pin each connection to
                # one of the public IPs validated by _safe_create_connection.
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}),
                    _SafeHTTPHandler(),
                    _SafeHTTPSHandler(),
                    _SafeRedirectHandler(),
                )
                with opener.open(req, timeout=min(timeout_seconds, self._timeout_seconds)) as resp:
                    raw_bytes = resp.read(250000)  # Max 250KB
                    content_type = resp.headers.get("Content-Type", "text/html")
                    text_body = raw_bytes.decode("utf-8", errors="replace")
                    final_url = resp.geturl() if hasattr(resp, "geturl") else safe_url

                # Basic HTML stripping
                clean_text = re.sub(r"<script.*?</script>", "", text_body, flags=re.DOTALL | re.IGNORECASE)
                clean_text = re.sub(r"<style.*?</style>", "", clean_text, flags=re.DOTALL | re.IGNORECASE)
                clean_text = re.sub(r"<[^>]+>", " ", clean_text)
                clean_text = " ".join(clean_text.split())

                return AdapterResult(
                    success=True,
                    data={
                        "url": final_url,
                        "content_type": content_type,
                        "raw_length": len(text_body),
                        "extracted_text": clean_text[:4000],
                    },
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.REAL,
                )
            except SecurityValidationError as error:
                # Raised by redirect validation or by the DNS-pinned connection
                # path before an unsafe destination can receive a request.
                return self._security_failure(error, start_time)
            except urllib.error.HTTPError as e:
                return AdapterResult(
                    success=False,
                    error_code=f"HTTP_{e.code}",
                    error_message=f"HTTP request failed with status {e.code}: {e.reason}",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )
            except Exception as e:
                return AdapterResult(
                    success=False,
                    error_code="NETWORK_ERROR",
                    error_message=str(e),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

        elif cap == "web_search":
            query = parameters.get("query", "")
            if not query:
                return AdapterResult(
                    success=False,
                    error_code="INVALID_PARAMETERS",
                    error_message="Missing query parameter.",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )
            # Simulated search mock (live search backend unconfigured in local sandbox)
            results = [
                {
                    "title": f"Industry Research: {query}",
                    "snippet": f"Simulated market telemetry and analysis for '{query}'.",
                    "url": f"https://mock-search.example.com/topic?q={urllib.parse.quote(query)}",
                }
            ]
            return AdapterResult(
                success=True,
                data={"query": query, "results": results, "count": len(results)},
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )

        return AdapterResult(
            success=False,
            error_code="UNSUPPORTED_CAPABILITY",
            error_message=f"Capability '{capability_id}' not handled by RealWebConnector.",
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
