"""Tool Gateway Package.

Provides core execution, capability routing, security sandboxing,
and protocol abstractions for all external tools.
"""

from __future__ import annotations

from tools.gateway.contracts import (
    BackendHealth,
    CapabilityRequest,
    CapabilityResult,
    CapabilityState,
    CostClass,
    ToolError,
    ToolExecutionContext,
)
from tools.gateway.gateway import ToolGateway
from tools.gateway.security import SecurityValidator, SecurityValidationError

__all__ = [
    "BackendHealth",
    "CapabilityRequest",
    "CapabilityResult",
    "CapabilityState",
    "CostClass",
    "ToolError",
    "ToolExecutionContext",
    "ToolGateway",
    "SecurityValidator",
    "SecurityValidationError",
]
