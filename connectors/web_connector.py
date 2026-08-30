"""Real Web and Observation Connector (Phase 6.1).

Implements real read-oriented HTTP fetching, HTML text extraction,
and search querying with SSRF protection and sanitized error handling.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


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

            # Validate URL format & block local network SSRF
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return AdapterResult(
                    success=False,
                    error_code="INVALID_SCHEME",
                    error_message=f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed.",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            if parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"):
                return AdapterResult(
                    success=False,
                    error_code="SSRF_BLOCKED",
                    error_message="Targeting internal loopback and cloud metadata addresses is strictly forbidden.",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": self._user_agent, "Accept": "text/html,application/xhtml+xml,text/plain"},
                )
                with urllib.request.urlopen(req, timeout=min(timeout_seconds, self._timeout_seconds)) as resp:
                    raw_bytes = resp.read(250000)  # Max 250KB
                    content_type = resp.headers.get("Content-Type", "text/html")
                    text_body = raw_bytes.decode("utf-8", errors="replace")

                # Basic HTML stripping
                clean_text = re.sub(r"<script.*?</script>", "", text_body, flags=re.DOTALL | re.IGNORECASE)
                clean_text = re.sub(r"<style.*?</style>", "", clean_text, flags=re.DOTALL | re.IGNORECASE)
                clean_text = re.sub(r"<[^>]+>", " ", clean_text)
                clean_text = " ".join(clean_text.split())

                return AdapterResult(
                    success=True,
                    data={
                        "url": url,
                        "content_type": content_type,
                        "raw_length": len(text_body),
                        "extracted_text": clean_text[:4000],
                    },
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.REAL,
                )
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
