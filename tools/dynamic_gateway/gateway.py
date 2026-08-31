"""Governed dynamic gateway for built-in, Plugin, MCP, and marketing capabilities.

This is intentionally an additive composition layer. It does not modify agent
runtime call sites. Later integration can swap construction from ToolGateway to
DynamicToolGateway while preserving the existing ToolRequest/ExecutionReceipt
contract.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from connectors.marketing import MarketingConnectorRegistry, MarketingExecutionMode, policy_for
from integrations.mcp.registry import McpServerRegistry
from plugins.registry import PluginRegistry
from schemas.base import BaseModel, Field
from tools.capabilities import CapabilityDescriptor, CapabilityRegistry
from tools.dynamic_gateway.adapters import McpRegistryAdapter, PluginRegistryAdapter
from tools.dynamic_gateway.marketing import MarketingGatewayRoute, MarketingRegistrySandboxAdapter
from tools.dynamic_gateway.registry import CompositeCapabilityRegistry
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class DynamicGatewaySyncReport(BaseModel):
    """Result of one runtime discovery/synchronization pass."""

    plugin_capabilities: int = 0
    mcp_capabilities: int = 0
    marketing_capabilities: int = 0
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
        marketing_registry: Optional[MarketingConnectorRegistry] = None,
        policy_engine: Optional[PolicyEngine] = None,
        receipt_repository: Optional[ExecutionReceiptRepository] = None,
    ) -> None:
        self.plugin_registry = plugin_registry or PluginRegistry()
        self.mcp_registry = mcp_registry or McpServerRegistry()
        self.marketing_registry = marketing_registry
        self.registry = CompositeCapabilityRegistry(base_registry or CapabilityRegistry())

        self._plugin_adapter = PluginRegistryAdapter(self.plugin_registry)
        self._mcp_adapter = McpRegistryAdapter(self.mcp_registry)
        self._marketing_adapter = (
            MarketingRegistrySandboxAdapter(marketing_registry)
            if marketing_registry is not None
            else None
        )

        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=policy_engine,
            receipt_repository=receipt_repository,
        )
        self.gateway.register_adapter(self._plugin_adapter)
        self.gateway.register_adapter(self._mcp_adapter)
        if self._marketing_adapter is not None:
            self.gateway.register_adapter(self._marketing_adapter)

    def _bind_provider_aliases(self, descriptors: List[CapabilityDescriptor]) -> None:
        for descriptor in descriptors:
            provider = descriptor.provider.lower()
            if provider.startswith("plugin:"):
                self.gateway.bind_adapter_alias(provider, self._plugin_adapter)
            elif provider.startswith("mcp:"):
                self.gateway.bind_adapter_alias(provider, self._mcp_adapter)
            elif provider.startswith("marketing:") and self._marketing_adapter is not None:
                self.gateway.bind_adapter_alias(provider, self._marketing_adapter)

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

    @staticmethod
    def _marketing_capability_id(connector_id: str, base_capability_id: str) -> str:
        return f"marketing.{connector_id.strip().lower()}.{base_capability_id.strip().lower()}"

    def _marketing_descriptor(
        self,
        *,
        connector_id: str,
        provider: str,
        base_capability_id: str,
    ) -> CapabilityDescriptor:
        base = self.registry.base_registry.get_capability(base_capability_id)
        if base is None:
            raise ValueError(
                f"Marketing connector '{connector_id}' references unknown base capability '{base_capability_id}'."
            )
        policy = policy_for(base_capability_id)
        required = ["connection_id", "action", "resource_type"]
        if policy.is_write:
            required.append("idempotency_key")
        dynamic_id = self._marketing_capability_id(connector_id, base_capability_id)
        return CapabilityDescriptor(
            capability_id=dynamic_id,
            name=f"{base.name} via {provider} [SANDBOX]",
            category=base.category,
            evidence_role=base.evidence_role,
            description=(
                f"Sandbox-governed external marketing route for connector '{connector_id}'. "
                "No provider network call or real external side effect is permitted in this version."
            ),
            input_schema={
                "type": "object",
                "required": required,
                "properties": {
                    "connection_id": {"type": "string"},
                    "action": {"type": "string"},
                    "resource_type": {"type": "string"},
                    "resource_id": {"type": ["string", "null"]},
                    "idempotency_key": {"type": ["string", "null"]},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "external_side_effect": {"type": "boolean"},
                    "provider_network_called": {"type": "boolean"},
                    "request_fingerprint": {"type": "string"},
                },
            },
            required_permissions=list(policy.required_permissions),
            risk_level=policy.risk_level,
            human_approval_required=policy.approval_required,
            supported_agents=list(base.supported_agents),
            provider=f"marketing:{connector_id.strip().lower()}",
            availability="MOCK_ONLY",
            cost_policy=base.cost_policy,
            timeout_policy=base.timeout_policy,
            retry_policy={"max_retries": 0, "backoff_seconds": 0.0, "retryable_errors": []},
            audit_policy={"log_payload": True, "redact_secrets": True, "emit_receipt": True},
        )

    def sync_marketing(self) -> DynamicGatewaySyncReport:
        """Expose only SANDBOX marketing specs as namespaced governed capabilities.

        CONTRACT_ONLY specs stay non-executable. LIVE specs are explicitly rejected
        by this adapter version even if their registry was created with live
        registration opt-in. Real provider execution requires a later dedicated
        driver boundary after approval and secret resolution are wired together.
        """
        report = DynamicGatewaySyncReport()
        if self.marketing_registry is None or self._marketing_adapter is None:
            return report

        configured_sources = set()
        routes: Dict[str, MarketingGatewayRoute] = {}

        for spec in self.marketing_registry.list_specs():
            source = f"marketing:{spec.connector_id.strip().lower()}"
            configured_sources.add(source)

            if spec.execution_mode is MarketingExecutionMode.CONTRACT_ONLY:
                if self.registry.remove_dynamic_source(source):
                    report.removed_sources.append(source)
                continue
            if spec.execution_mode is MarketingExecutionMode.LIVE:
                if self.registry.remove_dynamic_source(source):
                    report.removed_sources.append(source)
                report.errors[source] = (
                    "LIVE_MARKETING_EXECUTION_UNSUPPORTED: sandbox gateway adapter refuses LIVE specs."
                )
                continue

            try:
                descriptors: List[CapabilityDescriptor] = []
                staged_routes: Dict[str, MarketingGatewayRoute] = {}
                for base_capability_id in spec.supported_capabilities:
                    descriptor = self._marketing_descriptor(
                        connector_id=spec.connector_id,
                        provider=spec.provider,
                        base_capability_id=base_capability_id,
                    )
                    dynamic_id = descriptor.capability_id.lower()
                    if dynamic_id in routes or dynamic_id in staged_routes:
                        raise ValueError(f"Duplicate marketing capability route '{dynamic_id}'.")
                    descriptors.append(descriptor)
                    staged_routes[dynamic_id] = MarketingGatewayRoute(
                        dynamic_capability_id=dynamic_id,
                        connector_id=spec.connector_id,
                        base_capability_id=base_capability_id,
                    )

                report.marketing_capabilities += self.registry.replace_dynamic_source(source, descriptors)
                self._bind_provider_aliases(descriptors)
                routes.update(staged_routes)
            except Exception as exc:
                if self.registry.remove_dynamic_source(source):
                    report.removed_sources.append(source)
                report.errors[source] = str(exc)

        for source in self.registry.list_dynamic_sources():
            if source.startswith("marketing:") and source not in configured_sources:
                if self.registry.remove_dynamic_source(source):
                    report.removed_sources.append(source)

        self._marketing_adapter.replace_routes(routes)
        return report

    def sync_all(self) -> DynamicGatewaySyncReport:
        """Synchronize all dynamic capability authorities without touching built-ins."""
        report = DynamicGatewaySyncReport()
        try:
            report.plugin_capabilities = self.sync_plugins()
        except Exception as exc:
            self.registry.remove_dynamic_source("plugins")
            report.errors["plugins"] = str(exc)

        marketing_report = self.sync_marketing()
        report.marketing_capabilities = marketing_report.marketing_capabilities
        report.removed_sources.extend(marketing_report.removed_sources)
        report.errors.update(marketing_report.errors)

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
