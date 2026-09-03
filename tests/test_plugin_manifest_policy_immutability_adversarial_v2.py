from __future__ import annotations

import unittest

from plugins.models import PluginManifest, PluginToolDeclaration
from plugins.registry import PluginRegistry
from tools.dynamic_gateway.gateway import DynamicToolGateway
from tools.receipts import ExecutionStatus
from tools.tool_gateway import ToolRequest


class PluginManifestPolicyImmutabilityAdversarialV2Tests(unittest.TestCase):
    @staticmethod
    def _manifest(plugin_id: str) -> PluginManifest:
        return PluginManifest(
            plugin_id=plugin_id,
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

    @staticmethod
    def _downgrade(tool: PluginToolDeclaration) -> None:
        tool.category = "OBSERVE"
        tool.evidence_role = "OBSERVATION"
        tool.required_permissions = ["READ_ONLY"]
        tool.risk_level = "LOW"
        tool.human_approval_required = False

    def _assert_gateway_policy_still_authoritative(self, registry: PluginRegistry, plugin_id: str) -> None:
        external_effects = {"count": 0}

        def executor(parameters, context):
            external_effects["count"] += 1
            return {"external_side_effect": True, "count": external_effects["count"]}

        registry.bind_executor(plugin_id, "external_publish", executor)
        gateway = DynamicToolGateway(plugin_registry=registry)
        gateway.sync_plugins()
        capability_id = f"plugin.{plugin_id}.external_publish"
        exported = gateway.get_capability(capability_id)
        self.assertIsNotNone(exported)
        self.assertEqual("PUBLISH", exported.category.value)
        self.assertEqual("CRITICAL", exported.risk_level.value)
        self.assertTrue(exported.human_approval_required)

        result = gateway.execute(
            ToolRequest(
                run_id=f"RUN-{plugin_id.upper()}-001",
                agent_id="cmo",
                capability_id=capability_id,
                parameters={"payload": "must not execute without approval"},
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, result.status)
        self.assertEqual(0, external_effects["count"])

    def test_retained_manifest_reference_cannot_downgrade_registered_policy(self) -> None:
        registry = PluginRegistry()
        manifest = self._manifest("mutability_input")
        registry.register(manifest, enabled=True)

        # Caller retains the object passed through the validation boundary.
        self._downgrade(manifest.tools[0])

        self._assert_gateway_policy_still_authoritative(registry, "mutability_input")

    def test_register_return_value_cannot_mutate_internal_policy_authority(self) -> None:
        registry = PluginRegistry()
        returned = registry.register(self._manifest("mutability_return"), enabled=True)

        # A public return value is an observation, not mutable registry authority.
        self._downgrade(returned.manifest.tools[0])

        self._assert_gateway_policy_still_authoritative(registry, "mutability_return")

    def test_get_return_value_cannot_mutate_internal_policy_authority(self) -> None:
        registry = PluginRegistry()
        registry.register(self._manifest("mutability_get"), enabled=True)

        self._downgrade(registry.get("mutability_get").manifest.tools[0])

        self._assert_gateway_policy_still_authoritative(registry, "mutability_get")

    def test_list_plugins_return_value_cannot_mutate_internal_policy_authority(self) -> None:
        registry = PluginRegistry()
        registry.register(self._manifest("mutability_list"), enabled=True)

        exposed = registry.list_plugins()
        self.assertEqual(1, len(exposed))
        self._downgrade(exposed[0].manifest.tools[0])

        self._assert_gateway_policy_still_authoritative(registry, "mutability_list")


if __name__ == "__main__":
    unittest.main()
