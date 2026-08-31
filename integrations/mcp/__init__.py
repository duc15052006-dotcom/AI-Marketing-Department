"""Public API for Model Context Protocol integrations."""

from integrations.mcp.client import McpError, McpHttpClient, McpProtocolError, McpTransportError
from integrations.mcp.models import (
    MCP_PROTOCOL_VERSION,
    McpCallResult,
    McpServerConfig,
    McpServerState,
    McpToolDescriptor,
)
from integrations.mcp.registry import (
    McpCapabilityCollisionError,
    McpRegistryError,
    McpServerDisabledError,
    McpServerNotFoundError,
    McpServerRegistry,
)

__all__ = [
    "MCP_PROTOCOL_VERSION",
    "McpCallResult",
    "McpServerConfig",
    "McpServerState",
    "McpToolDescriptor",
    "McpHttpClient",
    "McpError",
    "McpTransportError",
    "McpProtocolError",
    "McpServerRegistry",
    "McpRegistryError",
    "McpCapabilityCollisionError",
    "McpServerDisabledError",
    "McpServerNotFoundError",
]
