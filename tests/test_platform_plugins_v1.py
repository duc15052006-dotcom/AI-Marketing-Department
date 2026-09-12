"""Regression tests for the declarative plugin platform foundation."""

import unittest

from plugins import (
    PluginCollisionError,
    PluginDisabledError,
    PluginManifest,
    PluginRegistry,
    PluginToolDeclaration,
)


class PluginPlatformV1Tests(unittest.TestCase):
    def _manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="research_pack",
            name="Research Pack",
            version="1.0.0",
            tools=[
                PluginToolDeclaration(
                    name="lookup",
                    description="Look up a local research record.",
                    category="OBSERVE",
                    evidence_role="OBSERVATION",
                    required_permissions=["READ_ONLY"],
                    risk_level="LOW",
                    human_approval_required=False,
                    supported_agents=["intelligence"],
                )
            ],
        )

    def test_plugin_fails_closed_until_enabled_and_executor_bound(self) -> None:
        registry = PluginRegistry()
        record = registry.register(self._manifest())
        self.assertEqual(record.state.value, "DISABLED")
        self.assertEqual(registry.capability_descriptors(), [])

        capability_id = registry.bind_executor(
            "research_pack",
            "lookup",
            lambda params, context: {"query": params["q"], "context": context},
        )
        with self.assertRaises(PluginDisabledError):
            registry.execute(capability_id, {"q": "decor"})

        registry.set_enabled("research_pack", True)
        result = registry.execute(capability_id, {"q": "decor"}, context="ctx")
        self.assertEqual(result, {"query": "decor", "context": "ctx"})

        descriptors = registry.capability_descriptors()
        self.assertEqual(len(descriptors), 1)
        self.assertEqual(descriptors[0].capability_id, "plugin.research_pack.lookup")
        self.assertEqual(descriptors[0].risk_level.value, "LOW")
        self.assertFalse(descriptors[0].human_approval_required)

    def test_high_impact_plugin_tool_cannot_disable_approval(self) -> None:
        registry = PluginRegistry()
        manifest = PluginManifest(
            plugin_id="publisher",
            name="Publisher",
            version="1.0.0",
            tools=[
                PluginToolDeclaration(
                    name="publish",
                    description="Publish externally.",
                    category="PUBLISH",
                    evidence_role="ACTION",
                    required_permissions=["EXTERNAL_WRITE"],
                    risk_level="CRITICAL",
                    human_approval_required=False,
                )
            ],
        )
        with self.assertRaises(ValueError):
            registry.register(manifest)

    def test_duplicate_plugin_and_duplicate_tool_names_are_rejected(self) -> None:
        registry = PluginRegistry()
        registry.register(self._manifest())
        with self.assertRaises(PluginCollisionError):
            registry.register(self._manifest())

        duplicate_tool_manifest = PluginManifest(
            plugin_id="dup_tools",
            name="Duplicate tools",
            version="1.0.0",
            tools=[
                PluginToolDeclaration(name="read", description="First tool."),
                PluginToolDeclaration(name="read", description="Second tool."),
            ],
        )
        with self.assertRaises(PluginCollisionError):
            registry.register(duplicate_tool_manifest)

    def test_manifest_fingerprint_is_deterministic(self) -> None:
        a = PluginRegistry().register(self._manifest()).fingerprint
        b = PluginRegistry().register(self._manifest()).fingerprint
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)


if __name__ == "__main__":
    unittest.main()
