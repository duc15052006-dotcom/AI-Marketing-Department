"""Provider-Neutral Tool Adapters (Phase 5.1).

Implements decoupled provider adapters for all capability categories:
OBSERVE, CREATE, PUBLISH, ANALYZE, and FILE_DATA.
"""

from __future__ import annotations

import abc
import time
from typing import Any, Dict, Optional
from schemas.base import BaseModel, Field
from tools.receipts import ExecutionMode


class AdapterResult(BaseModel):
    """Normalized payload returned by an underlying tool adapter."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    cost_or_tokens: Dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    execution_mode: ExecutionMode = Field(default=ExecutionMode.MOCK)


class BaseCapabilityAdapter(abc.ABC):
    """Abstract interface for all capability provider backends."""

    @property
    @abc.abstractmethod
    def adapter_name(self) -> str:
        """Name of the adapter backend."""
        pass

    @abc.abstractmethod
    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        """Execute the capability against the underlying backend."""
        pass


class SearchAdapter(BaseCapabilityAdapter):
    """Observational search adapter for public web intelligence."""

    @property
    def adapter_name(self) -> str:
        return "search_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        query = parameters.get("query", "")
        if not query:
            return AdapterResult(
                success=False,
                error_code="INVALID_PARAMETERS",
                error_message="Missing required parameter 'query'.",
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )
        # Mock / Provider-neutral search results
        results = [
            {"title": f"Market Research for {query}", "snippet": f"Verified qualitative insights regarding {query}", "url": f"https://example.com/research?q={query}"}
        ]
        return AdapterResult(
            success=True,
            data={"query": query, "results": results, "result_count": len(results)},
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )


class HttpAdapter(BaseCapabilityAdapter):
    """Web content reading and URL inspection adapter."""

    @property
    def adapter_name(self) -> str:
        return "http_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        url = parameters.get("url", "")
        if not url:
            return AdapterResult(
                success=False,
                error_code="INVALID_PARAMETERS",
                error_message="Missing required parameter 'url'.",
                latency_ms=(time.perf_counter() - start) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )
        return AdapterResult(
            success=True,
            data={
                "url": url,
                "content_type": "text/html",
                "extracted_text": f"Simulated content extracted from {url}",
                "headings": ["Overview", "Key Findings"],
            },
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )


class CreativeTextAdapter(BaseCapabilityAdapter):
    """Creative copy and script generation support adapter."""

    @property
    def adapter_name(self) -> str:
        return "creative_text_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        prompt = parameters.get("prompt", "")
        return AdapterResult(
            success=True,
            data={"generated_copy": f"Drafted copy for: {prompt[:60]}...", "word_count": 42},
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )


class MediaCreationAdapter(BaseCapabilityAdapter):
    """Image and video generation and editing adapter."""

    def __init__(self, name: str = "image_gen_adapter") -> None:
        self._name = name

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        asset_type = "video" if "video" in capability_id else "image"
        artifact_id = f"art-{asset_type}-{int(time.time())}"
        return AdapterResult(
            success=True,
            data={"asset_id": artifact_id, "asset_type": asset_type, "status": "RENDERED", "format": "png" if asset_type == "image" else "mp4"},
            artifact_refs=[artifact_id],
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )


class PublishingAdapter(BaseCapabilityAdapter):
    """Controlled social and ad platform publishing adapter."""

    def __init__(self, name: str = "social_publish_adapter") -> None:
        self._name = name

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        platform = parameters.get("platform", "generic")
        return AdapterResult(
            success=True,
            data={"publish_id": f"PUB-{int(time.time())}", "platform": platform, "status": "PUBLISHED_OR_QUEUED"},
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.SANDBOX,
        )


class AnalyticsAdapter(BaseCapabilityAdapter):
    """Analytics, KPI calculation, attribution, and statistical testing adapter."""

    def __init__(self, name: str = "analytics_adapter") -> None:
        self._name = name

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        metric_name = parameters.get("metric_name", "roas")
        return AdapterResult(
            success=True,
            data={
                "metric": metric_name,
                "value": 3.45,
                "confidence_interval": [3.12, 3.78],
                "sample_size": 14200,
                "p_value": 0.012,
            },
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )


class FileStorageAdapter(BaseCapabilityAdapter):
    """Local file I/O, database querying, and export adapter."""

    @property
    def adapter_name(self) -> str:
        return "file_io_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        action = "read" if "read" in capability_id else "write"
        path = parameters.get("path", "workspace/output.txt")
        return AdapterResult(
            success=True,
            data={"path": path, "action": action, "bytes_processed": 1024},
            artifact_refs=[path],
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )


class MockToolAdapter(BaseCapabilityAdapter):
    """Configurable mock adapter for error injection, timeouts, and retry testing."""

    def __init__(
        self,
        name: str = "mock_adapter",
        should_fail: bool = False,
        error_code: str = "INTERNAL_ERROR",
        error_message: str = "Mock error",
        delay_seconds: float = 0.0,
        fail_attempts: int = 0,
    ) -> None:
        self._name = name
        self._should_fail = should_fail
        self._error_code = error_code
        self._error_message = error_message
        self._delay_seconds = delay_seconds
        self._fail_attempts = fail_attempts
        self._current_attempts = 0

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        start = time.perf_counter()
        self._current_attempts += 1

        if self._delay_seconds > 0:
            time.sleep(min(self._delay_seconds, timeout_seconds))
            if self._delay_seconds > timeout_seconds:
                return AdapterResult(
                    success=False,
                    error_code="TIMEOUT",
                    error_message=f"Execution exceeded timeout limit of {timeout_seconds}s.",
                    latency_ms=timeout_seconds * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

        if self._current_attempts <= self._fail_attempts or self._should_fail:
            return AdapterResult(
                success=False,
                error_code=self._error_code,
                error_message=self._error_message,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )

        return AdapterResult(
            success=True,
            data={"mock_output": "SUCCESS_PAYLOAD", "attempts": self._current_attempts},
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
