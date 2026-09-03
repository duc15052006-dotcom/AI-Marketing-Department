"""MCP server registry and bridge into the internal capability system."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from integrations.mcp.client import McpHttpClient
from integrations.mcp.models import McpCallResult, McpServerConfig, McpServerState, McpToolDescriptor
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CostPolicy,
    EvidenceRole,
    PermissionLevel,
    RiskLevel,
)


_SERVER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SAFE_SEGMENT_RE = re.compile(r"[^a-z0-9_-]+")


class McpRegistryError(RuntimeError):
    pass


class McpServerNotFoundError(McpRegistryError):
    pass


class McpCapabilityCollisionError(McpRegistryError):
    pass


class McpServerDisabledError(McpRegistryError):
    pass


ClientFactory = Callable[[McpServerConfig], Any]


class McpServerRegistry:
    """Registers MCP servers and exposes their tools as namespaced capabilities."""

    def __init__(self, *, client_factory: Optional[ClientFactory] = None) -> None:
        self._configs: Dict[str, McpServerConfig] = {}
        self._states: Dict[str, McpServerState] = {}
        self._clients: Dict[str, Any] = {}
        self._tool_index: Dict[str, Tuple[str, str]] = {}
        self._client_factory: ClientFactory = client_factory or (lambda config: McpHttpClient(config))

    @staticmethod
    def _safe_tool_segment(tool_name: str) -> str:
        segment = _SAFE_SEGMENT_RE.sub("_", tool_name.lower()).strip("_")
        if not segment:
            raise ValueError(f"MCP tool name cannot be normalized safely: {tool_name!r}")
        return segment[:96]

    @classmethod
    def capability_id(cls, server_id: str, tool_name: str) -> str:
        return f"mcp.{server_id}.{cls._safe_tool_segment(tool_name)}"

    def register_server(self, config: McpServerConfig) -> None:
        if not _SERVER_ID_RE.fullmatch(config.server_id):
            raise ValueError("server_id must match ^[a-z][a-z0-9_-]{1,63}$")
        if config.server_id in self._configs:
            raise McpCapabilityCollisionError(f"MCP server '{config.server_id}' is already registered")
        self._configs[config.server_id] = config
        self._states[config.server_id] = McpServerState.ENABLED if config.enabled else McpServerState.DISABLED

    def unregister_server(self, server_id: str) -> None:
        if server_id not in self._configs:
            raise McpServerNotFoundError(server_id)
        client = self._clients.pop(server_id, None)
        if client is not None and hasattr(client, "close"):
            client.close()
        self._configs.pop(server_id, None)
        self._states.pop(server_id, None)
        for cid in [cid for cid, target in self._tool_index.items() if target[0] == server_id]:
            self._tool_index.pop(cid, None)

    def set_enabled(self, server_id: str, enabled: bool) -> None:
        config = self._configs.get(server_id)
        if config is None:
            raise McpServerNotFoundError(server_id)
        config.enabled = enabled
        self._states[server_id] = McpServerState.ENABLED if enabled else McpServerState.DISABLED

    def list_servers(self) -> List[McpServerConfig]:
        return [self._configs[key] for key in sorted(self._configs)]

    def _client_for(self, server_id: str) -> Any:
        config = self._configs.get(server_id)
        if config is None:
            raise McpServerNotFoundError(server_id)
        if self._states.get(server_id) != McpServerState.ENABLED or not config.enabled:
            raise McpServerDisabledError(server_id)
        client = self._clients.get(server_id)
        if client is None:
            client = self._client_factory(config)
            self._clients[server_id] = client
        return client

    @staticmethod
    def _policy_for(tool: McpToolDescriptor) -> Tuple[RiskLevel, List[PermissionLevel], bool]:
        annotations = tool.annotations
        destructive = annotations.get("destructiveHint") is True

        # MCP annotations are remote-controlled metadata. They may escalate local
        # policy, but they are never authority to lower the authorization floor.
        if destructive:
            return RiskLevel.CRITICAL, [PermissionLevel.EXTERNAL_WRITE], True
        return RiskLevel.HIGH, [PermissionLevel.EXTERNAL_WRITE], True

    def refresh_tools(self, server_id: str) -> List[CapabilityDescriptor]:
        client = self._client_for(server_id)
        tools = client.list_tools()
        staged: Dict[str, Tuple[str, str]] = {}
        descriptors: List[CapabilityDescriptor] = []

        for tool in tools:
            cid = self.capability_id(server_id, tool.name)
            if cid in staged or (cid in self._tool_index and self._tool_index[cid] != (server_id, tool.name)):
                raise McpCapabilityCollisionError(f"MCP capability collision: {cid}")
            staged[cid] = (server_id, tool.name)
            risk, permissions, approval = self._policy_for(tool)
            is_read_only = permissions == [PermissionLevel.READ_ONLY]
            descriptors.append(
                CapabilityDescriptor(
                    capability_id=cid,
                    name=f"MCP {server_id}: {tool.name}",
                    category=CapabilityCategory.OBSERVE if is_read_only else CapabilityCategory.PUBLISH,
                    evidence_role=EvidenceRole.OBSERVATION if is_read_only else EvidenceRole.ACTION,
                    description=tool.description or f"Tool '{tool.name}' exposed by MCP server '{server_id}'.",
                    input_schema=dict(tool.input_schema),
                    output_schema=dict(tool.output_schema),
                    required_permissions=permissions,
                    risk_level=risk,
                    human_approval_required=approval,
                    supported_agents=["all"],
                    provider=f"mcp:{server_id}",
                    availability="AVAILABLE",
                    cost_policy=CostPolicy.FREE_TIER_METERED,
                    timeout_policy=self._configs[server_id].timeout_seconds,
                )
            )

        for cid in [cid for cid, target in self._tool_index.items() if target[0] == server_id]:
            self._tool_index.pop(cid, None)
        self._tool_index.update(staged)
        return descriptors

    def execute(self, capability_id: str, arguments: Dict[str, Any]) -> McpCallResult:
        target = self._tool_index.get(capability_id)
        if target is None:
            raise McpRegistryError(f"unknown or undiscovered MCP capability: {capability_id}")
        server_id, original_tool_name = target
        client = self._client_for(server_id)
        return client.call_tool(original_tool_name, dict(arguments))

    def close(self) -> None:
        for client in list(self._clients.values()):
            if hasattr(client, "close"):
                client.close()
        self._clients.clear()
