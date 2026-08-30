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
    observation_record: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Canonical serialized ObservationRecord from observation execution path, if available.",
    )


class BaseCapabilityAdapter(abc.ABC):
    """Abstract interface for all capability provider backends."""

    @property
    @abc.abstractmethod
    def adapter_name(self) -> str:
        """Name of the adapter backend."""
        pass

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
        """Execute the capability against the underlying backend.

        Trusted scope parameters (run_id, business_id, project_id) are sourced
        from ToolRequest fields, NOT from model-controlled parameters.
        """
        pass


class SearchAdapter(BaseCapabilityAdapter):
    """Observational search adapter for public web intelligence."""

    @property
    def adapter_name(self) -> str:
        return "search_adapter"

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
        query = parameters.get("query", "")
        if not query:
            return AdapterResult(
                success=False,
                error_code="INVALID_PARAMETERS",
                error_message="Missing required parameter 'query'.",
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )
        return AdapterResult(
            success=False,
            error_code="SEARCH_PROVIDER_NOT_CONFIGURED",
            error_message="No real search provider is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )



class HttpAdapter(BaseCapabilityAdapter):
    """Web content reading and URL inspection adapter."""

    @property
    def adapter_name(self) -> str:
        return "http_adapter"

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
            success=False,
            error_code="HTTP_PROVIDER_NOT_CONFIGURED",
            error_message="No real webpage reader is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )



class CreativeTextAdapter(BaseCapabilityAdapter):
    """Creative copy and script generation support adapter."""

    @property
    def adapter_name(self) -> str:
        return "creative_text_adapter"

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
        prompt = parameters.get("prompt", "")
        return AdapterResult(
            success=False,
            error_code="TEXT_TOOL_NOT_CONFIGURED",
            error_message="No executable text-generation tool is bound to this adapter.",
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
        asset_type = "video" if "video" in capability_id else "image"
        return AdapterResult(
            success=False,
            data={"asset_type": asset_type, "status": "NOT_EXECUTED"},
            error_code="MEDIA_PROVIDER_NOT_CONFIGURED",
            error_message="No real media renderer is bound. A creative specification may be produced, but no asset was rendered.",
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
        return AdapterResult(
            success=False,
            error_code="PUBLISH_PROVIDER_NOT_CONFIGURED",
            error_message="No publishing connector is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )



class AnalyticsAdapter(BaseCapabilityAdapter):
    """Analytics, KPI calculation, attribution, and statistical testing adapter."""

    def __init__(self, name: str = "analytics_adapter") -> None:
        self._name = name

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
        return AdapterResult(
            success=False,
            error_code="ANALYTICS_PROVIDER_NOT_CONFIGURED",
            error_message="No real analytics dataset/provider is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )



class FileStorageAdapter(BaseCapabilityAdapter):
    """Local file I/O, database querying, and export adapter."""

    @property
    def adapter_name(self) -> str:
        return "file_io_adapter"

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
        return AdapterResult(
            success=False,
            error_code="FILE_PROVIDER_NOT_CONFIGURED",
            error_message="No real file connector is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )



class ObservationSearchAdapter(BaseCapabilityAdapter):
    """Production search adapter delegating to the observation SearchManager.

    Bridges the production ToolGateway to the certified observation backends
    (DuckDuckGo, SearXNG, Wikipedia) without bypassing capability authority.
    """

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
        query = parameters.get("query", "")
        if not query:
            return AdapterResult(
                success=False,
                error_code="INVALID_PARAMETERS",
                error_message="Missing required parameter 'query'.",
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )

        context = ToolExecutionContext(
            agent_id=parameters.get("agent_id", "intelligence"),
            product_id=parameters.get("product_id", ""),
            brand_id=parameters.get("brand_id", ""),
            run_id=run_id,
            business_id=business_id,
            project_id=project_id,
            timeout_seconds=min(timeout_seconds, 15.0),
        )
        req = CapabilityRequest(
            capability="search_web",
            parameters={
                "query": query,
                "language": parameters.get("language") or ("vi" if any(ch in query.lower() for ch in "ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ") else "en"),
                "max_results": parameters.get("max_results", 10),
                "safe_search": parameters.get("safe_search", True),
            },
            context=context,
        )

        try:
            result = self._gateway.execute(req)
        except Exception as exc:
            return AdapterResult(
                success=False,
                error_code="OBSERVATION_GATEWAY_ERROR",
                error_message=f"Observation gateway failed ({type(exc).__name__}).",
                latency_ms=(time.perf_counter() - start) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )

        latency_ms = (time.perf_counter() - start) * 1000.0

        if result.status != "SUCCESS":
            return AdapterResult(
                success=False,
                error_code=result.error.error_code if result.error else "OBSERVATION_ERROR",
                error_message=result.error.message if result.error else "Unknown observation error",
                latency_ms=latency_ms,
                execution_mode=ExecutionMode.MOCK,
            )

        exec_mode = ExecutionMode.REAL if result.backend_used and result.backend_used != "mock" else ExecutionMode.MOCK
        return AdapterResult(
            success=True,
            data=result.data,
            latency_ms=latency_ms,
            execution_mode=exec_mode,
            observation_record=getattr(result, "observation_record", None),
        )
