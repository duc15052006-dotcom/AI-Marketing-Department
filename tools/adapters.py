"""Provider-neutral tool adapter contracts.

Production capabilities are bound to explicit real/sandbox connectors by the
application composition root.  Generic defaults in this module MUST fail
closed: they are architectural placeholders, never simulated successful
executions.  Explicit test doubles belong in ``MockToolAdapter`` only.
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
    observation_record: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Canonical serialized ObservationRecord from observation execution path, if available.",
    )


class BaseCapabilityAdapter(abc.ABC):
    @property
    @abc.abstractmethod
    def adapter_name(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        raise NotImplementedError


def _unconfigured(adapter_name: str, capability_id: str, start: float) -> AdapterResult:
    """Canonical fail-closed response for architectural placeholder adapters."""
    return AdapterResult(
        success=False,
        error_code="PROVIDER_NOT_CONFIGURED",
        error_message=(
            f"Capability '{capability_id}' has no configured production connector "
            f"for adapter '{adapter_name}'."
        ),
        latency_ms=(time.perf_counter() - start) * 1000.0,
        execution_mode=ExecutionMode.MOCK,
    )


class SearchAdapter(BaseCapabilityAdapter):
    @property
    def adapter_name(self) -> str:
        return "search_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return _unconfigured(self.adapter_name, capability_id, time.perf_counter())


class HttpAdapter(BaseCapabilityAdapter):
    @property
    def adapter_name(self) -> str:
        return "http_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return _unconfigured(self.adapter_name, capability_id, time.perf_counter())


class CreativeTextAdapter(BaseCapabilityAdapter):
    @property
    def adapter_name(self) -> str:
        return "creative_text_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return _unconfigured(self.adapter_name, capability_id, time.perf_counter())


class MediaCreationAdapter(BaseCapabilityAdapter):
    """Placeholder for image/video backends; never pretends a render occurred."""
    def __init__(self, name: str = "image_gen_adapter") -> None:
        self._name = name

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return _unconfigured(self.adapter_name, capability_id, time.perf_counter())


class PublishingAdapter(BaseCapabilityAdapter):
    """Placeholder for consequential write connectors; never reports publication."""
    def __init__(self, name: str = "social_publish_adapter") -> None:
        self._name = name

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return _unconfigured(self.adapter_name, capability_id, time.perf_counter())


class AnalyticsAdapter(BaseCapabilityAdapter):
    """Placeholder analytics adapter; never invents telemetry/statistics."""
    def __init__(self, name: str = "analytics_adapter") -> None:
        self._name = name

    @property
    def adapter_name(self) -> str:
        return self._name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return _unconfigured(self.adapter_name, capability_id, time.perf_counter())


class FileStorageAdapter(BaseCapabilityAdapter):
    """Placeholder file adapter; never reports a write/read that did not happen."""
    @property
    def adapter_name(self) -> str:
        return "file_io_adapter"

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return _unconfigured(self.adapter_name, capability_id, time.perf_counter())


class MockToolAdapter(BaseCapabilityAdapter):
    """Explicit test-only configurable adapter for deterministic fault/success injection."""
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

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        start = time.perf_counter()
        self._current_attempts += 1
        if self._delay_seconds > 0:
            time.sleep(min(self._delay_seconds, timeout_seconds))
            if self._delay_seconds > timeout_seconds:
                return AdapterResult(
                    success=False,
                    error_code="TIMEOUT",
                    error_message="Mock timeout",
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


class ObservationSearchAdapter(BaseCapabilityAdapter):
    """Production search bridge to the certified observation SearchManager."""
    def __init__(self) -> None:
        from tools.gateway.gateway import ToolGateway as ObservationToolGateway
        self._gateway = ObservationToolGateway()

    @property
    def adapter_name(self) -> str:
        return "observation_search_adapter"

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
        from tools.gateway.contracts import CapabilityRequest, ToolExecutionContext

        start = time.perf_counter()
        query = str(parameters.get("query") or "").strip()
        if not query:
            return AdapterResult(
                success=False,
                error_code="INVALID_PARAMETERS",
                error_message="Missing required parameter 'query'.",
                latency_ms=(time.perf_counter() - start) * 1000.0,
                execution_mode=ExecutionMode.REAL,
            )

        context = ToolExecutionContext(
            agent_id=str(parameters.get("agent_id") or "intelligence"),
            product_id=str(parameters.get("product_id") or ""),
            brand_id=str(parameters.get("brand_id") or ""),
            run_id=run_id,
            business_id=business_id,
            project_id=project_id,
            timeout_seconds=min(timeout_seconds, 15.0),
        )
        req = CapabilityRequest(
            capability="search_web",
            parameters={
                "query": query,
                "language": str(parameters.get("language") or "en"),
                "max_results": parameters.get("max_results", 10),
                "safe_search": parameters.get("safe_search", True),
            },
            context=context,
        )

        try:
            result = self._gateway.execute(req)
        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception as exc:
            return AdapterResult(
                success=False,
                error_code="OBSERVATION_GATEWAY_ERROR",
                error_message=f"Observation search failed internally ({type(exc).__name__}).",
                latency_ms=(time.perf_counter() - start) * 1000.0,
                execution_mode=ExecutionMode.REAL,
            )

        latency_ms = (time.perf_counter() - start) * 1000.0
        if result.status != "SUCCESS":
            return AdapterResult(
                success=False,
                error_code=result.error.error_code if result.error else "OBSERVATION_ERROR",
                error_message=(result.error.message if result.error else "Observation search could not be completed."),
                latency_ms=latency_ms,
                execution_mode=ExecutionMode.REAL,
            )

        exec_mode = ExecutionMode.REAL if result.backend_used and result.backend_used != "mock" else ExecutionMode.MOCK
        return AdapterResult(
            success=True,
            data=result.data,
            latency_ms=latency_ms,
            execution_mode=exec_mode,
            observation_record=getattr(result, "observation_record", None),
        )
