"""Model Context Protocol integration contracts.

Targets MCP protocol revision 2026-07-28 for stateless HTTP requests. The
transport remains isolated from agent code so future MCP revisions can be
introduced behind this contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from schemas.base import BaseModel, Field


MCP_PROTOCOL_VERSION = "2026-07-28"


class McpServerState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"


class McpServerConfig(BaseModel):
    server_id: str = Field(..., min_length=2, max_length=64)
    endpoint: str = Field(..., min_length=1, max_length=2048)
    protocol_version: str = MCP_PROTOCOL_VERSION
    timeout_seconds: float = Field(default=20.0, gt=0.0, le=300.0)
    headers: Dict[str, str] = Field(default_factory=dict)
    client_name: str = "ai-marketing-department"
    client_version: str = "1.0.0"
    allow_insecure_http: bool = False
    enabled: bool = True


class McpToolDescriptor(BaseModel):
    server_id: str
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    annotations: Dict[str, Any] = Field(default_factory=dict)


class McpCallResult(BaseModel):
    content: List[Dict[str, Any]] = Field(default_factory=list)
    structured_content: Optional[Any] = None
    is_error: bool = False
    raw_result: Dict[str, Any] = Field(default_factory=dict)
