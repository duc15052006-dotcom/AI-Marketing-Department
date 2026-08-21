"""Specification and Contract Tests for Tool Gateway & Eyes V0 (Phase 3B.1).

Validates architectural contracts, version pinning, security gate enforcement,
cost classification, and observation normalization without installing external packages.
"""

import unittest
from pathlib import Path


class TestToolGatewaySpec(unittest.TestCase):
    def setUp(self):
        self.workspace_root = Path(__file__).resolve().parent.parent
        self.audit_doc = (self.workspace_root / "OPEN_SOURCE_TOOL_AUDIT.md").read_text(encoding="utf-8")
        self.decision_matrix = (self.workspace_root / "TOOL_DECISION_MATRIX.md").read_text(encoding="utf-8")
        self.dependency_matrix = (self.workspace_root / "TOOL_DEPENDENCY_MATRIX.md").read_text(encoding="utf-8")
        self.security_policy = (self.workspace_root / "TOOL_SECURITY_POLICY.md").read_text(encoding="utf-8")
        self.registry_spec = (self.workspace_root / "CAPABILITY_REGISTRY_SPEC.md").read_text(encoding="utf-8")
        self.gateway_spec = (self.workspace_root / "TOOL_GATEWAY_SPEC.md").read_text(encoding="utf-8")
        self.v0_arch = (self.workspace_root / "OBSERVATION_V0_ARCHITECTURE.md").read_text(encoding="utf-8")

    def test_agent_reach_is_not_universal_backend(self):
        """Verify Agent-Reach is treated as bootstrap/diagnostic layer rather than universal social runtime."""
        self.assertIn("Panniantong", self.audit_doc)
        self.assertIn("installer, configuration/diagnostic layer", self.audit_doc)
        self.assertNotIn("universal runtime social backend", self.audit_doc.lower())
        self.assertIn("IMPLEMENT_NATIVE_ADAPTER", self.audit_doc)

    def test_mcp_major_version_explicitly_pinned(self):
        """Verify Model Context Protocol Python SDK includes explicit version constraints and protocol metadata."""
        self.assertIn("MCP_SDK_MAJOR", self.audit_doc)
        self.assertIn("MCP_SDK_VERSION_RANGE", self.audit_doc)
        self.assertIn(">=2,<3", self.gateway_spec)
        self.assertIn("2026-07-28", self.gateway_spec)
        self.assertIn("stdio", self.gateway_spec)
        self.assertIn("sse", self.gateway_spec)
        self.assertIn("SDK_SUPPORTED_TRANSPORTS", self.audit_doc)
        self.assertIn("GATEWAY_ENABLED_TRANSPORTS", self.audit_doc)

    def test_browser_dependencies_differ_from_pure_http_extraction(self):
        """Verify Crawl4AI and Playwright are classified as browser-assisted and separate from pure HTTP extractors."""
        self.assertIn("REQUIRES_BROWSER_BINARY", self.dependency_matrix)
        self.assertIn("COST_2_BROWSER", self.decision_matrix)
        self.assertIn("COST_0_LIGHT", self.decision_matrix)
        self.assertIn("LICENSE_CAVEAT = true", self.audit_doc)

    def test_browser_use_forbidden_capabilities_not_exposed(self):
        """Verify disallowed upstream capabilities (CAPTCHA bypass, fingerprint evasion) are explicitly prohibited."""
        for forbidden in [
            "CAPTCHA_BYPASS",
            "FINGERPRINT_EVASION",
            "STEALTH_BYPASS",
            "BAN_AVOIDANCE",
            "RATE_LIMIT_CIRCUMVENTION",
            "AUTOMATED_MEDIA_BUYING",
        ]:
            self.assertIn(forbidden, self.security_policy)
            self.assertIn(forbidden, self.gateway_spec)

    def test_provider_specific_objects_cannot_leak_into_observation_result(self):
        """Verify ObservationRecord schema is normalized, backend-independent, and includes product isolation."""
        for required_field in [
            "observation_id",
            "capability",
            "source_platform",
            "backend_used",
            "normalized_data",
            "evidence_class",
            "confidence",
            "product_id",
            "brand_id",
        ]:
            self.assertIn(required_field, self.v0_arch)

    def test_capability_routing_supports_interchangeable_backends(self):
        """Verify CapabilityRegistry supports primary and fallback execution chains across cost classes."""
        self.assertIn("primary_backend_id", self.registry_spec)
        self.assertIn("fallback_backend_ids", self.registry_spec)
        self.assertIn("COST_0_LIGHT", self.registry_spec)
        self.assertIn("COST_1_LOCAL_PARSE", self.registry_spec)
        self.assertIn("COST_2_BROWSER", self.registry_spec)
        self.assertIn("COST_3_AGENTIC_BROWSER", self.registry_spec)
        self.assertIn("COST_4_EXTERNAL_METERED", self.registry_spec)

    def test_managed_cloud_tools_marked_with_network_cost_privacy_metadata(self):
        """Verify Apify is defined as optional managed structured backend with explicit cost/auth boundaries."""
        self.assertIn("OPTIONAL_MANAGED_STRUCTURED_EXTRACTION_BACKEND", self.audit_doc)
        self.assertIn("COST_4_EXTERNAL_METERED", self.decision_matrix)
        self.assertIn("Hosted MCP", self.audit_doc)
        self.assertIn("Local Stdio MCP", self.audit_doc)


if __name__ == "__main__":
    unittest.main()
