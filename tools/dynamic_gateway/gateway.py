"""Governed dynamic gateway for built-in, Plugin, and MCP capabilities.

This is intentionally an additive composition layer. It does not modify agent
runtime call sites. Later integration can swap construction from ToolGateway to
DynamicToolGateway while preserving the existing ToolRequest/ExecutionReceipt
contract.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from integrations.mcp.registry import McpServerRegistry
from plugins.registry import PluginRegistry
from schemas.base import BaseModel, Field
from tools.capabilities import CapabilityDescriptor, CapabilityRegistry
from tools.dynamic_gateway.adapters import McpRegistryAdapter, PluginRegistryAdapter
from tools.dynamic_gateway.registry import CompositeCapabilityRegistry
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class DynamicGatewaySyncReport(BaseModel):
    """Result of one runtime discovery/synchronization pass."""

    plugin_capabilities: int = 0
    mcp_capabilities: int = 0
    removed_sources: List[str] = Field(default_factory=list)
    errors: Dict[str, str] = Field(default_factory=dict)

    @property
    def success(self) -> bool:
        return not self.errors


class DynamicToolGateway:
    """Composition root for dynamic capability discovery and governed execution."""

    def __init__(
        self,
        *,
        base_registry: Optional[CapabilityRegistry] = None,
        plugin_registry: Optional[PluginRegistry] = None,
        mcp_registry: Optional[McpServerRegistry] = None,
        policy_engine: Optional[PolicyEngine] = None,
        receipt_repository: Optional[ExecutionReceiptRepository] = None,
    ) -> None:
        self.plugin_registry = plugin_registry or PluginRegistry()
        self.mcp_registry = mcp_registry or McpServerRegistry()
        self.registry = CompositeCapabilityRegistry(base_registry or CapabilityRegistry())

        self._plugin_adapter = PluginRegistryAdapter(self.plugin_registry)
        self._mcp_adapter = McpRegistryAdapter(self.mcp_registry)

        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=policy_engine,
            receipt_repository=receipt_repository,
        )
        self.gateway.register_adapter(self._plugin_adapter)
        self.gateway.register_adapter(self._mcp_adapter)

    def _bind_provider_aliases(self, descriptors: List[CapabilityDescriptor]) -> None:
        for descriptor in descriptors:
            provider = descriptor.provider.lower()
            if provider.startswith("plugin:"):
                self.gateway.bind_adapter_alias(provider, self._plugin_adapter)
            elif provider.startswith("mcp:"):
                self.gateway.bind_adapter_alias(provider, self._mcp_adapter)

    def sync_plugins(self) -> int:
        """Refresh enabled plugin declarations into the dynamic capability overlay."""
        descriptors = self.plugin_registry.capability_descriptors(enabled_only=True)
        count = self.registry.replace_dynamic_source("plugins", descriptors)
        self._bind_provider_aliases(descriptors)
        return count

    def sync_mcp(self) -> DynamicGatewaySyncReport:
        """Refresh all enabled MCP servers independently and fail closed per server."""
        report = DynamicGatewaySyncReport()
        configured_sources = set()

        for config in self.mcp_registry.list_servers():
            source = f"mcp:{config.server_id}"
            configured_sources.add(source)
            if not config.enabled:
                if self.registry.remove_dynamic_source(source):
                    report.removed_sources.append(source)
                continue

            try:
                descriptors = self.mcp_registry.refresh_tools(config.server_id)
                report.mcp_capabilities += self.registry.replace_dynamic_source(source, descriptors)
                self._bind_provider_aliases(descriptors)
            except Exception as exc:
                # Discovery failure must not leave stale remote tools executable.
                if self.registry.remove_dynamic_source(source):
                    report.removed_sources.append(source)
                report.errors[source] = str(exc)

        for source in self.registry.list_dynamic_sources():
            if source.startswith("mcp:") and source not in configured_sources:
                if self.registry.remove_dynamic_source(source):
                    report.removed_sources.append(source)
        return report

    def sync_all(self) -> DynamicGatewaySyncReport:
        """Synchronize all dynamic capability authorities without touching built-ins."""
        report = DynamicGatewaySyncReport()
        try:
            report.plugin_capabilities = self.sync_plugins()
        except Exception as exc:
            self.registry.remove_dynamic_source("plugins")
            report.errors["plugins"] = str(exc)

        mcp_report = self.sync_mcp()
        report.mcp_capabilities = mcp_report.mcp_capabilities
        report.removed_sources.extend(mcp_report.removed_sources)
        report.errors.update(mcp_report.errors)
        report.removed_sources = sorted(set(report.removed_sources))
        return report

    def execute(self, request: ToolRequest) -> ExecutionReceipt:
        """Execute through the existing policy/approval/retry/receipt pipeline."""
        return self.gateway.execute(request)

    def get_capability(self, capability_id: str) -> Optional[CapabilityDescriptor]:
        return self.registry.get_capability(capability_id)

    def list_capabilities(self) -> List[CapabilityDescriptor]:
        return self.registry.list_capabilities()

    def close(self) -> None:
        self.mcp_registry.close()
