"""Adversarial contract for production DynamicToolGateway composition.

The platform-level dynamic gateway tests prove Plugin/MCP discovery and governed
execution in isolation.  This contract guards the production composition root:
the singleton API backend, runtime, and context compiler must all share that
same dynamic registry and governed ToolGateway instance.
"""

from __future__ import annotations

import unittest

from app_api.server import APP_BACKEND
from plugins.models import PluginManifest, PluginToolDeclaration
from tools.receipts import ExecutionStatus
from tools.tool_gateway import ToolRequest


class ProductionDynamicToolGatewayWiringAdversarialV1Tests(unittest.TestCase):
    def test_production_backend_discovers_and_routes_trusted_plugin(self) -> None:
        dynamic = APP_BACKEND.dynamic_tool_gateway

        self.assertIs(
            APP_BACKEND.tool_gateway,
            dynamic.gateway,
            "Production runtime must execute through the governed dynamic gateway.",
        )
        self.assertIs(
            APP_BACKEND.cap_registry,
            dynamic.registry,
            "Production capability reads must include the dynamic overlay.",
        )
        self.assertIs(APP_BACKEND.runtime.tool_gateway, APP_BACKEND.tool_gateway)
        self.assertIs(
            APP_BACKEND.context_compiler.capability_registry,
            dynamic.registry,
            "Agent context compilation must see the same discovered capabilities.",
        )

        manifest = PluginManifest(
            plugin_id="prodwire",
            name="Production Wiring Probe",
            version="1.0.0",
            tools=[
                PluginToolDeclaration(
                    name="echo",
                    description="Return trusted production-composition context.",
                    category="OBSERVE",
                    evidence_role="COMPUTATION",
                    required_permissions=["READ_ONLY"],
                    risk_level="LOW",
                    human_approval_required=False,
                    supported_agents=["intelligence"],
                )
            ],
        )

        registry = dynamic.plugin_registry
        registry.register(manifest, enabled=True)
        registry.bind_executor(
            "prodwire",
            "echo",
            lambda parameters, context: {
                "echo": parameters.get("text"),
                "trusted_run_id": context["run_id"],
            },
        )
        try:
            self.assertEqual(dynamic.sync_plugins(), 1)
            self.assertIsNotNone(APP_BACKEND.cap_registry.get_capability("plugin.prodwire.echo"))

            receipt = APP_BACKEND.runtime.tool_gateway.execute(
                ToolRequest(
                    run_id="RUN-PRODUCTION-DYNAMIC-WIRING-V1",
                    agent_id="intelligence",
                    capability_id="plugin.prodwire.echo",
                    parameters={"text": "connected"},
                )
            )

            self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
            self.assertEqual(receipt.data["echo"], "connected")
            self.assertEqual(
                receipt.data["trusted_run_id"],
                "RUN-PRODUCTION-DYNAMIC-WIRING-V1",
            )
        finally:
            registry.unregister("prodwire")
            dynamic.sync_plugins()


if __name__ == "__main__":
    unittest.main()
