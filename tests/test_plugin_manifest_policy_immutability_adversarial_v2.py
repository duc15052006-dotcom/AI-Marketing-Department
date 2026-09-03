from __future__ import annotations

import unittest

from plugins.models import PluginManifest, PluginToolDeclaration
from plugins.registry import PluginRegistry
from tools.dynamic_gateway.gateway import DynamicToolGateway
from tools.receipts import ExecutionStatus
from tools.tool_gateway import ToolRequest


class PluginManifestPolicyImmutabilityAdversarialV2Tests(unittest.TestCase):
    def test_retained_manifest_reference_cannot_downgrade_registered_policy(self) -> None:
        registry = PluginRegistry()
        manifest = PluginManifest(
            plugin_id="mutability_probe",
            name="Mutability Probe",
            version="1.0.0",
            tools=[
                PluginToolDeclaration(
                    name="external_publish",
                    description="A trusted-bound executor representing an external publish side effect.",
                    category="PUBLISH",
                    evidence_role="ACTION",
                    required_permissions=["PUBLISH", "EXTERNAL_WRITE"],
                    risk_level="CRITICAL",
                    human_approval_required=True,
                    supported_agents=["cmo"],
                )
            ],
        )
        registry.register(manifest, enabled=True)

        external_effects = {"count": 0}

        def executor(parameters, context):
            external_effects["count"] += 1
            return {"external_side_effect": True, "count": external_effects["count"]}

        registry.bind_executor("mutability_probe", "external_publish", executor)

        # Attack the trust boundary after successful validation/registration.
        # A caller that retained the input object must not be able to rewrite the
        # policy authority that DynamicToolGateway later synchronizes.
        tool = manifest.tools[0]
        tool.category = "OBSERVE"
        tool.evidence_role = "OBSERVATION"
        tool.required_permissions = ["READ_ONLY"]
        tool.risk_level = "LOW"
        tool.human_approval_required = False

        gateway = DynamicToolGateway(plugin_registry=registry)
        gateway.sync_plugins()
        capability_id = "plugin.mutability_probe.external_publish"
        exported = gateway.get_capability(capability_id)
        self.assertIsNotNone(exported)

        # The validated registration snapshot remains authoritative, or the
        # tampered manifest must fail closed before execution becomes possible.
        self.assertEqual("PUBLISH", exported.category.value)
        self.assertEqual("CRITICAL", exported.risk_level.value)
        self.assertTrue(exported.human_approval_required)

        result = gateway.execute(
            ToolRequest(
                run_id="RUN-PLUGIN-MUTABILITY-V2-001",
                agent_id="cmo",
                capability_id=capability_id,
                parameters={"payload": "must not execute without approval"},
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, result.status)
        self.assertEqual(0, external_effects["count"])


if __name__ == "__main__":
    unittest.main()
