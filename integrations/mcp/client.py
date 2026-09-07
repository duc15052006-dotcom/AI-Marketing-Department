"""Minimal MCP 2026-07-28 stateless HTTP client.

This is deliberately a small transport adapter, not a second agent runtime.
It supports discovery, paginated tool listing, and tool calls. Secrets are
never logged or embedded in capability descriptors.
"""

from __future__ import annotations

import ipaddress
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from integrations.mcp.models import McpCallResult, McpServerConfig, McpToolDescriptor


class McpError(RuntimeError):
    pass


class McpTransportError(McpError):
    pass


class McpProtocolError(McpError):
    pass


def _is_loopback_host(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class McpHttpClient:
    """Synchronous MCP client for the stateless Streamable HTTP profile."""

    def __init__(self, config: McpServerConfig, *, http_client: Optional[httpx.Client] = None) -> None:
        self.config = config
        self._validate_endpoint(config)
        self._client = http_client or httpx.Client(timeout=config.timeout_seconds, follow_redirects=False)
        self._owns_client = http_client is None
        self._counter = 0
        self._counter_lock = threading.Lock()

    @staticmethod
    def _validate_endpoint(config: McpServerConfig) -> None:
        parsed = urlparse(config.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP endpoint must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("credentials in MCP endpoint URLs are not allowed; use headers")
        if parsed.scheme == "http" and not (config.allow_insecure_http or _is_loopback_host(parsed.hostname)):
            raise ValueError("plaintext HTTP MCP endpoints are allowed only for loopback unless explicitly enabled")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "McpHttpClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _next_id(self) -> int:
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def _meta(self) -> Dict[str, Any]:
        return {
            "io.modelcontextprotocol/clientInfo": {
                "name": self.config.client_name,
                "version": self.config.client_version,
            },
            "io.modelcontextprotocol/clientCapabilities": {},
        }

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None, *, tool_name: Optional[str] = None) -> Dict[str, Any]:
        if not self.config.enabled:
            raise McpTransportError(f"MCP server '{self.config.server_id}' is disabled")

        request_id = self._next_id()
        request_params = dict(params or {})
        request_params.setdefault("_meta", self._meta())
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": request_params}

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "MCP-Protocol-Version": self.config.protocol_version,
            "Mcp-Method": method,
        }
        if tool_name:
            headers["Mcp-Name"] = tool_name
        reserved = {key.lower() for key in headers}
        for key, value in self.config.headers.items():
            if key.lower() not in reserved:
                headers[key] = value

        try:
            response = self._client.post(
                self.config.endpoint,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise McpTransportError(f"MCP request failed for {method}: {type(exc).__name__}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise McpProtocolError("MCP server returned a non-JSON response") from exc
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            raise McpProtocolError("invalid JSON-RPC response envelope")
        if body.get("id") != request_id:
            raise McpProtocolError("MCP response id does not match request id")
        if "error" in body:
            error = body.get("error") or {}
            code = error.get("code", "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
            message = error.get("message", "MCP error") if isinstance(error, dict) else str(error)
            raise McpProtocolError(f"MCP error {code}: {message}")
        result = body.get("result")
        if not isinstance(result, dict):
            raise McpProtocolError("MCP response is missing an object result")
        return result

    def discover(self) -> Dict[str, Any]:
        return self._rpc("server/discover")

    def list_tools(self, *, max_pages: int = 20) -> List[McpToolDescriptor]:
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        tools: List[McpToolDescriptor] = []
        cursor: Optional[str] = None
        seen_cursors = set()
        for _ in range(max_pages):
            params: Dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self._rpc("tools/list", params)
            raw_tools = result.get("tools", [])
            if not isinstance(raw_tools, list):
                raise McpProtocolError("tools/list returned a non-list tools field")
            for raw in raw_tools:
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                    raise McpProtocolError("tools/list returned an invalid tool descriptor")
                output_schema = raw.get("outputSchema")
                tools.append(
                    McpToolDescriptor(
                        server_id=self.config.server_id,
                        name=raw["name"],
                        description=str(raw.get("description") or ""),
                        input_schema=raw.get("inputSchema") if isinstance(raw.get("inputSchema"), dict) else {},
                        output_schema=output_schema if isinstance(output_schema, dict) else {},
                        annotations=raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {},
                    )
                )
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)
            if cursor in seen_cursors:
                raise McpProtocolError("tools/list pagination cursor loop detected")
            seen_cursors.add(cursor)
        else:
            raise McpProtocolError("tools/list exceeded pagination safety limit")
        return tools

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> McpCallResult:
        result = self._rpc("tools/call", {"name": name, "arguments": dict(arguments or {})}, tool_name=name)
        content = result.get("content", [])
        if not isinstance(content, list):
            raise McpProtocolError("tools/call returned invalid content")
        normalized_content = [item for item in content if isinstance(item, dict)]
        return McpCallResult(
            content=normalized_content,
            structured_content=result.get("structuredContent"),
            is_error=bool(result.get("isError", False)),
            raw_result=result,
        )
