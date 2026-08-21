# Tool Gateway Specification (TOOL_GATEWAY_SPEC.md)

**Status**: SPECIFICATION & ARCHITECTURAL BLUEPRINT — PHASE 3B.1  
**Target Milestone**: Tool Gateway Core Protocol & Security Gates  
**Purpose**: Multi-transport execution engine abstracting Native Python, REST API, MCP, CLI, and Browser tools behind a unified security envelope.

---

## 1. Gateway Architecture & Supported Transports

The **Tool Gateway** serves as the security boundary and protocol translation layer between marketing agents and all underlying operating system tools, web services, and external APIs.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        AGENT INTELLIGENCE LAYER                        │
│                (CMO, Intelligence, Strategist, Creative)               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Typed ToolCallRequest)
┌───────────────────────────────────▼────────────────────────────────────┐
│                              TOOL GATEWAY                              │
│  ┌─────────────────────────┐ ┌───────────────────┐ ┌─────────────────┐ │
│  │ Security & Auth Sandbox │ │ Input Validation  │ │ Rate Limiting   │ │
│  └─────────────────────────┘ └───────────────────┘ └─────────────────┘ │
└─┬──────────────┬──────────────────┬─────────────────┬────────────────┬─┘
  │              │                  │                 │                │
┌─▼────────────┐ ┌▼───────────────┐ ┌▼──────────────┐ ┌▼─────────────┐ ┌▼───────────────┐
│ TRANSPORT 1: │ │ TRANSPORT 2:   │ │ TRANSPORT 3:   │ │ TRANSPORT 4:│ │ TRANSPORT 5:    │
│ Native Python│ │ REST API       │ │ Official MCP   │ │ Local CLI   │ │ Headless Browser│
│ (trafilatura,│ │ (SearXNG,      │ │ (Apify, Brave, │ │ (xreach,    │ │ (Playwright,    │
│  yt-dlp)     │ │  DuckDuckGo)   │ │  Filesystem)   │ │  subprocess)│ │  Browser Use)   │
└──────────────┘└─────────────────┘└────────────────┘└───────────────┘└─────────────────┘
```

---

## 2. MCP Version Pinning & Transport Configuration

To prevent breaking protocol shifts, the Gateway pins the official Model Context Protocol Python SDK:

```python
class MCPGatewayConfig(BaseModel):
    """Configuration and version pinning for MCP client bridges."""
    mcp_sdk_major: int = Field(default=2, description="Target major SDK version")
    mcp_sdk_version_range: str = Field(default=">=2,<3", description="Constrained dependency range")
    mcp_protocol_version: str = Field(default="2026-07-28", description="Target MCP specification")
    sdk_supported_transports: List[str] = Field(
        default_factory=lambda: ["stdio", "sse", "streamable_http"],
        description="Transports supported by the official SDK",
    )
    gateway_enabled_transports: List[str] = Field(
        default_factory=lambda: ["stdio", "sse"],
        description="Transports enabled within the Tool Gateway",
    )
    heartbeat_interval_seconds: float = Field(default=15.0)
    process_timeout_seconds: float = Field(default=30.0)
```

---

## 3. Disallowed Upstream Capabilities Enforcement

In accordance with `TOOL_SECURITY_POLICY.md`, the Gateway strictly intercepts and rejects all requests attempting to invoke:
- `CAPTCHA_BYPASS`
- `FINGERPRINT_EVASION`
- `STEALTH_BYPASS`
- `BAN_AVOIDANCE`
- `RATE_LIMIT_CIRCUMVENTION`
- `AUTOMATED_MEDIA_BUYING`
- `UNAUTHORIZED_CREDENTIAL_STORAGE`

---

## 4. Execution Lifecycle & Result Normalization

```python
class ToolCallRequest(BaseModel):
    """Standardized invocation request passed to the Tool Gateway."""
    call_id: str = Field(..., description="Unique tool call ID")
    agent_id: str = Field(..., description="Calling agent, e.g. 'intelligence'")
    capability_name: str = Field(..., description="Target capability, e.g. 'read_page'")
    product_id: str = Field(..., description="Product isolation partition")
    brand_id: str = Field(..., description="Brand partition")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0)


class ToolCallResponse(BaseModel):
    """Standardized response returned by the Tool Gateway."""
    call_id: str
    capability_name: str
    status: str = Field(default="SUCCESS", description="SUCCESS | ERROR | TIMEOUT | NO_PERMISSION")
    observation_record: Optional[ObservationRecord] = None
    raw_payload: Optional[Dict[str, Any]] = None
    latency_ms: float = 0.0
    backend_used: str = ""
    error: Optional[str] = None
```
