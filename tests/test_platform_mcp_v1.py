"""Regression tests for MCP registry, policy classification, and HTTP framing."""

import json
import unittest

import httpx

from integrations.mcp import (
    MCP_PROTOCOL_VERSION,
    McpCallResult,
    McpCapabilityCollisionError,
    McpHttpClient,
    McpServerConfig,
    McpServerRegistry,
    McpToolDescriptor,
)


class _FakeMcpClient:
    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self.calls = []

    def list_tools(self):
        return [
            McpToolDescriptor(
                server_id=self.config.server_id,
                name="search",
                description="Search a read-only source.",
                input_schema={"type": "object"},
                annotations={"readOnlyHint": True},
            ),
            McpToolDescriptor(
                server_id=self.config.server_id,
                name="publish/post",
                description="Unknown write-like tool.",
                input_schema={"type": "object"},
                annotations={},
            ),
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return McpCallResult(structured_content={"name": name, "arguments": arguments})

    def close(self):
        pass


class McpPlatformV1Tests(unittest.TestCase):
    def test_registry_namespaces_tools_and_defaults_unknown_tools_to_high_risk(self) -> None:
        registry = McpServerRegistry(client_factory=lambda config: _FakeMcpClient(config))
        registry.register_server(McpServerConfig(server_id="market", endpoint="https://example.invalid/mcp"))
        descriptors = registry.refresh_tools("market")

        by_id = {descriptor.capability_id: descriptor for descriptor in descriptors}
        read_cap = by_id["mcp.market.search"]
        self.assertEqual(read_cap.risk_level.value, "HIGH")
        self.assertTrue(read_cap.human_approval_required)
        self.assertEqual([p.value for p in read_cap.required_permissions], ["EXTERNAL_WRITE"])

        write_cap = by_id["mcp.market.publish_post"]
        self.assertEqual(write_cap.risk_level.value, "HIGH")
        self.assertTrue(write_cap.human_approval_required)
        self.assertEqual([p.value for p in write_cap.required_permissions], ["EXTERNAL_WRITE"])

        result = registry.execute("mcp.market.publish_post", {"text": "hello"})
        self.assertEqual(result.structured_content["name"], "publish/post")

    def test_normalized_tool_name_collision_fails_closed(self) -> None:
        class CollisionClient(_FakeMcpClient):
            def list_tools(self):
                return [
                    McpToolDescriptor(server_id=self.config.server_id, name="read/page"),
                    McpToolDescriptor(server_id=self.config.server_id, name="read page"),
                ]

        registry = McpServerRegistry(client_factory=lambda config: CollisionClient(config))
        registry.register_server(McpServerConfig(server_id="collision", endpoint="https://example.invalid/mcp"))
        with self.assertRaises(McpCapabilityCollisionError):
            registry.refresh_tools("collision")

    def test_http_client_pins_protocol_headers_and_tool_name(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            request_id = captured["payload"]["id"]
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [], "structuredContent": {"ok": True}},
                },
            )

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        config = McpServerConfig(server_id="mock", endpoint="https://mcp.example.test/api")
        client = McpHttpClient(config, http_client=http_client)
        result = client.call_tool("search", {"q": "decor"})

        headers = {key.lower(): value for key, value in captured["headers"].items()}
        self.assertEqual(headers["mcp-protocol-version"], MCP_PROTOCOL_VERSION)
        self.assertEqual(headers["mcp-method"], "tools/call")
        self.assertEqual(headers["mcp-name"], "search")
        self.assertEqual(captured["payload"]["method"], "tools/call")
        self.assertIn("_meta", captured["payload"]["params"])
        self.assertEqual(result.structured_content, {"ok": True})
        http_client.close()

    def test_plaintext_remote_http_is_rejected_by_default(self) -> None:
        with self.assertRaises(ValueError):
            McpHttpClient(McpServerConfig(server_id="remote", endpoint="http://example.com/mcp"))


if __name__ == "__main__":
    unittest.main()
