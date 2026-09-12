"""Dynamic Tool Gateway platform extension.

This package keeps the existing governed ToolGateway intact while adding a
composite capability registry and trusted adapters for plugin/MCP sources.
"""

from tools.dynamic_gateway.adapters import McpRegistryAdapter, PluginRegistryAdapter
from tools.dynamic_gateway.gateway import DynamicGatewaySyncReport, DynamicToolGateway
from tools.dynamic_gateway.registry import CompositeCapabilityRegistry, DynamicCapabilityCollisionError

__all__ = [
    "CompositeCapabilityRegistry",
    "DynamicCapabilityCollisionError",
    "DynamicGatewaySyncReport",
    "DynamicToolGateway",
    "McpRegistryAdapter",
    "PluginRegistryAdapter",
]
