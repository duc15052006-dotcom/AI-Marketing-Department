"""Domain Contracts for Tool Gateway Execution Layer.

Defines backend-independent request, result, health, and error schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field


class CapabilityState(str, Enum):
    """Lifecycle and operational state of a capability backend."""
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    NO_PERMISSION = "NO_PERMISSION"


class CostClass(str, Enum):
    """Generic relative execution cost tier (not monetary estimation)."""
    COST_0_LIGHT = "COST_0_LIGHT"
    COST_1_LOCAL_PARSE = "COST_1_LOCAL_PARSE"
    COST_2_BROWSER = "COST_2_BROWSER"
    COST_3_AGENTIC_BROWSER = "COST_3_AGENTIC_BROWSER"
    COST_4_EXTERNAL_METERED = "COST_4_EXTERNAL_METERED"


class ToolExecutionContext(BaseModel):
    """Contextual metadata passed to every tool execution."""
    agent_id: str
    product_id: str
    brand_id: str
    timeout_seconds: float = Field(default=15.0)
    max_retries: int = Field(default=1)
    allowed_domains: List[str] = Field(default_factory=list)


class CapabilityRequest(BaseModel):
    """Standardized tool invocation envelope passed into the Tool Gateway."""
    request_id: str = Field(default_factory=lambda: f"REQ-{uuid.uuid4().hex[:12]}")
    capability: str = Field(..., description="Target capability name, e.g. 'read_page'")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    context: ToolExecutionContext


class ToolError(BaseModel):
    """Structured error payload for failed tool executions."""
    error_code: str = Field(..., description="e.g. 'SSRF_BLOCKED', 'TIMEOUT', 'HTTP_404'")
    message: str
    backend_used: str = ""
    retryable: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class BackendHealth(BaseModel):
    """Real-time operational health record for an individual backend."""
    backend_id: str
    state: CapabilityState = Field(default=CapabilityState.READY)
    cost_class: CostClass = Field(default=CostClass.COST_0_LIGHT)
    avg_latency_ms: float = 0.0
    consecutive_failures: int = 0
    last_success_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    last_error_message: Optional[str] = None


class CapabilityResult(BaseModel):
    """Normalized outcome of a tool execution returned by the Tool Gateway."""
    request_id: str
    capability: str
    status: str = Field(default="SUCCESS", description="SUCCESS | ERROR | BLOCKED | TIMEOUT")
    data: Optional[Dict[str, Any]] = None
    observation_record: Optional[Dict[str, Any]] = None
    backend_used: str = ""
    cost_class: CostClass = CostClass.COST_0_LIGHT
    latency_ms: float = 0.0
    error: Optional[ToolError] = None
