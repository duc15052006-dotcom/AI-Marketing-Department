"""Real read-only web connector with SSRF protection and safe errors."""
from __future__ import annotations

import ipaddress
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


class RealWebConnector(BaseCapabilityAdapter):
    def __init__(self, timeout_seconds: float = 15.0, user_agent: str = "AI-Marketing-Department/1.0") -> None:
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent

    @property
    def adapter_name(self) -> str:
        return "system_http_reader"

    @staticmethod
    def _is_forbidden_ip(raw: str) -> bool:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return True
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    @classmethod
    def _validate_public_url(cls, url: str) -> tuple[bool, str]:
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            return False, "INVALID_URL"
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False, "INVALID_URL"
        if parsed.username or parsed.password:
            return False, "URL_CREDENTIALS_FORBIDDEN"
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
            return False, "SSRF_BLOCKED"
        try:
            infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror:
            return False, "DNS_RESOLUTION_FAILED"
        addresses = {info[4][0] for info in infos if info and info[4]}
        if not addresses or any(cls._is_forbidden_ip(addr) for addr in addresses):
            return False, "SSRF_BLOCKED"
        return True, ""

    @staticmethod
    def _failure(start: float, code: str, message: str) -> AdapterResult:
        return AdapterResult(
            success=False,
            error_code=code,
            error_message=message,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.REAL,
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
        start = time.perf_counter()
        cap = capability_id.lower()

        if cap in ("read_page", "analyze_url"):
            url = str(parameters.get("url") or "").strip()
            if not url:
                return self._failure(start, "INVALID_URL", "A public http(s) URL is required.")
            allowed, reason = self._validate_public_url(url)
            if not allowed:
                return self._failure(start, reason, "The URL is invalid, unavailable, or targets a non-public network address.")

            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": self._user_agent, "Accept": "text/html,application/xhtml+xml,text/plain"},
                )
                # Redirects are validated by checking the final URL too.  This
                # blocks public->private redirect chains at the application boundary.
                with urllib.request.urlopen(req, timeout=min(timeout_seconds, self._timeout_seconds)) as resp:
                    final_url = resp.geturl()
                    final_allowed, final_reason = self._validate_public_url(final_url)
                    if not final_allowed:
                        return self._failure(start, final_reason, "A redirect targeted a non-public network address.")
                    content_type = str(resp.headers.get("Content-Type", ""))[:200]
                    if not any(t in content_type.lower() for t in ("text/", "html", "json", "xml")):
                        return self._failure(start, "UNSUPPORTED_CONTENT_TYPE", "The page did not return a supported textual content type.")
                    raw_bytes = resp.read(500_000)
                    text_body = raw_bytes.decode("utf-8", errors="replace")

                clean = re.sub(r"<script\b.*?</script>", " ", text_body, flags=re.DOTALL | re.IGNORECASE)
                clean = re.sub(r"<style\b.*?</style>", " ", clean, flags=re.DOTALL | re.IGNORECASE)
                clean = re.sub(r"<[^>]+>", " ", clean)
                clean = " ".join(clean.split())
                return AdapterResult(
                    success=True,
                    data={
                        "url": final_url,
                        "content_type": content_type,
                        "raw_length": len(text_body),
                        "extracted_text": clean[:20_000],
                        "truncated": len(clean) > 20_000,
                    },
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                    execution_mode=ExecutionMode.REAL,
                )
            except urllib.error.HTTPError as exc:
                return self._failure(start, f"HTTP_{exc.code}", f"The remote page returned HTTP {exc.code}.")
            except urllib.error.URLError:
                return self._failure(start, "NETWORK_ERROR", "The remote page could not be reached.")
            except (TimeoutError, socket.timeout):
                return self._failure(start, "TIMEOUT", "The remote page request timed out.")
            except Exception:
                return self._failure(start, "NETWORK_ERROR", "The remote page could not be read safely.")

        if cap == "web_search":
            # Real search is provided by ObservationSearchAdapter.  Never
            # fabricate an example.com result when that backend is absent.
            return self._failure(start, "SEARCH_BACKEND_NOT_CONFIGURED", "Web search must use the configured observation search backend.")

        return self._failure(start, "UNSUPPORTED_CAPABILITY", f"Capability '{capability_id}' is not handled by this connector.")
