from __future__ import annotations

import unittest

from integrations.mcp.models import McpCallResult, McpServerConfig, McpToolDescriptor
from integrations.mcp.registry import McpServerRegistry
from plugins.models import PluginManifest, PluginToolDeclaration
from plugins.registry import PluginRegistry
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    EvidenceRole,
    PermissionLevel,
    RiskLevel,
)
from tools.dynamic_gateway.gateway import DynamicToolGateway
from tools.dynamic_gateway.registry import CompositeCapabilityRegistry, DynamicCapabilityCollisionError
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolRequest


class FakeMcpClient:
    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self.fail_discovery = False
        self.calls = []

    def list_tools(self):
        if self.fail_discovery:
            raise ConnectionError("discovery unavailable")
        return [
            McpToolDescriptor(
                server_id=self.config.server_id,
                name="lookup_metrics",
                description="Read metrics",
                input_schema={"type": "object"},
                annotations={"readOnlyHint": True},
            ),
            McpToolDescriptor(
                server_id=self.config.server_id,
                name="publish_campaign",
                description="Publish campaign",
                input_schema={"type": "object"},
                annotations={"destructiveHint": True},
            ),
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return McpCallResult(
            content=[{"type": "text", "text": "ok"}],
            structured_content={"tool": name, "arguments": dict(arguments)},
            is_error=False,
        )

    def close(self):
        return None


class DynamicGatewayV1Tests(unittest.TestCase):
    def _plugin_registry(self) -> PluginRegistry:
        registry = PluginRegistry()
        manifest = PluginManifest(
            plugin_id="localdemo",
            name="Local Demo",
            version="1.0.0",
            tools=[
                PluginToolDeclaration(
                    name="echo",
                    description="Echo safe input",
                    category="OBSERVE",
                    evidence_role="COMPUTATION",
                    required_permissions=["READ_ONLY"],
                    risk_level="LOW",
                    human_approval_required=False,
                    supported_agents=["intelligence"],
                )
            ],
        )
        registry.register(manifest, enabled=True)
        registry.bind_executor(
            "localdemo",
            "echo",
            lambda parameters, context: {
                "echo": parameters.get("text"),
                "trusted_run_id": context["run_id"],
                "trusted_business_id": context["business_id"],
            },
        )
        return registry

    def test_composite_registry_preserves_builtin_and_rejects_collision(self):
        registry = CompositeCapabilityRegistry()
        self.assertIsNotNone(registry.get_capability("web_search"))

        colliding = CapabilityDescriptor(
            capability_id="web_search",
            name="Collision",
            category=CapabilityCategory.OBSERVE,
            evidence_role=EvidenceRole.NONE,
            description="Must not overwrite built-in capability.",
            required_permissions=[PermissionLevel.READ_ONLY],
            risk_level=RiskLevel.LOW,
        )
        with self.assertRaises(DynamicCapabilityCollisionError):
            registry.replace_dynamic_source("bad-source", [colliding])
        self.assertIsNotNone(registry.get_capability("web_search"))

    def test_plugin_sync_and_execution_use_existing_governed_gateway(self):
        plugin_registry = self._plugin_registry()
        gateway = DynamicToolGateway(plugin_registry=plugin_registry)
        report = gateway.sync_all()
        self.assertTrue(report.success)
        self.assertEqual(report.plugin_capabilities, 1)
        self.assertIsNotNone(gateway.get_capability("plugin.localdemo.echo"))

        receipt = gateway.execute(
            ToolRequest(
                run_id="RUN-DYN-1",
                agent_id="intelligence",
                capability_id="plugin.localdemo.echo",
                parameters={"text": "hello"},
                business_id="BIZ-1",
                project_id="PROJ-1",
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.SANDBOX)
        self.assertEqual(receipt.data["echo"], "hello")
        self.assertEqual(receipt.data["trusted_run_id"], "RUN-DYN-1")
        self.assertEqual(receipt.data["trusted_business_id"], "BIZ-1")
        self.assertEqual(receipt.business_id, "BIZ-1")
        self.assertEqual(receipt.project_id, "PROJ-1")

    def test_disabling_plugin_and_resync_removes_capability(self):
        plugin_registry = self._plugin_registry()
        gateway = DynamicToolGateway(plugin_registry=plugin_registry)
        gateway.sync_plugins()
        self.assertIsNotNone(gateway.get_capability("plugin.localdemo.echo"))

        plugin_registry.set_enabled("localdemo", False)
        gateway.sync_plugins()
        self.assertIsNone(gateway.get_capability("plugin.localdemo.echo"))

        receipt = gateway.execute(
            ToolRequest(
                run_id="RUN-DYN-2",
                agent_id="intelligence",
                capability_id="plugin.localdemo.echo",
                parameters={"text": "blocked"},
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "CAPABILITY_NOT_FOUND")

    def test_mcp_read_only_tool_routes_as_real_execution(self):
        clients = {}

        def factory(config):
            client = FakeMcpClient(config)
            clients[config.server_id] = client
            return client

        mcp_registry = McpServerRegistry(client_factory=factory)
        mcp_registry.register_server(
            McpServerConfig(server_id="metrics", endpoint="https://mcp.example.test")
        )
        gateway = DynamicToolGateway(mcp_registry=mcp_registry)
        report = gateway.sync_all()
        self.assertTrue(report.success)
        self.assertEqual(report.mcp_capabilities, 2)

        receipt = gateway.execute(
            ToolRequest(
                run_id="RUN-MCP-1",
                agent_id="intelligence",
                capability_id="mcp.metrics.lookup_metrics",
                parameters={"campaign_id": "C-1"},
                business_id="BIZ-9",
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertEqual(receipt.data["structured_content"]["tool"], "lookup_metrics")
        self.assertEqual(clients["metrics"].calls[0][1], {"campaign_id": "C-1"})
        self.assertNotIn("business_id", clients["metrics"].calls[0][1])

    def test_mcp_destructive_tool_still_hits_approval_gate(self):
        mcp_registry = McpServerRegistry(client_factory=lambda config: FakeMcpClient(config))
        mcp_registry.register_server(
            McpServerConfig(server_id="publisher", endpoint="https://mcp.example.test")
        )
        gateway = DynamicToolGateway(mcp_registry=mcp_registry)
        gateway.sync_all()

        receipt = gateway.execute(
            ToolRequest(
                run_id="RUN-MCP-2",
                agent_id="cmo",
                capability_id="mcp.publisher.publish_campaign",
                parameters={"campaign_id": "C-2"},
                business_id="BIZ-2",
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertIsNotNone(receipt.approval_reference)

    def test_failed_mcp_refresh_removes_stale_capabilities(self):
        clients = {}

        def factory(config):
            client = FakeMcpClient(config)
            clients[config.server_id] = client
            return client

        mcp_registry = McpServerRegistry(client_factory=factory)
        mcp_registry.register_server(
            McpServerConfig(server_id="unstable", endpoint="https://mcp.example.test")
        )
        gateway = DynamicToolGateway(mcp_registry=mcp_registry)
        first = gateway.sync_all()
        self.assertTrue(first.success)
        self.assertIsNotNone(gateway.get_capability("mcp.unstable.lookup_metrics"))

        clients["unstable"].fail_discovery = True
        second = gateway.sync_mcp()
        self.assertFalse(second.success)
        self.assertIn("mcp:unstable", second.errors)
        self.assertIsNone(gateway.get_capability("mcp.unstable.lookup_metrics"))


if __name__ == "__main__":
    unittest.main()
