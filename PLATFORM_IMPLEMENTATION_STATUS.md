# Platform / Infrastructure Implementation Status

This file tracks platform work separately from the five-agent core so parallel hardening work can continue without conflating missing product infrastructure with agent defects.

## Baseline already present before Platform Batch 1

The repository already contains meaningful foundations that should be extended rather than rewritten:

- `knowledge/`: ingestion, repository, models, conflict handling, plus domain folders.
- `memory/`: learning, promotion, operations, repository, success/failure learning folders.
- `tools/`: capability registry, security, receipts, evidence, observation backends, and a Tool Gateway.
- `connectors/`: file, web, analytics, publishing connectors and connector registry.
- `workspace/`: business/project/operator workspace primitives.
- `integrations/models/`: provider-agnostic model gateway and provider registry.

## Platform Batch 1 — Plugin + MCP Foundation

Branch: `platform/plugin-mcp-foundation-v1`

Implemented:

### Plugin platform

- Declarative `PluginManifest` and tool declarations.
- Strict plugin/tool identifier validation.
- Semantic-version-like manifest validation and deterministic fingerprints.
- Global namespace: `plugin.<plugin_id>.<tool_name>`.
- Enable / disable / quarantine lifecycle.
- Explicit executor binding; manifests cannot specify arbitrary Python import paths.
- Fail-closed validation for high-risk/external tools that try to bypass human approval.
- Export to the existing `tools.capabilities.CapabilityDescriptor` contract.

### MCP platform

- MCP server configuration and registry.
- MCP protocol revision pinned to `2026-07-28` for this adapter.
- Stateless HTTP JSON-RPC client with protocol routing headers.
- `server/discover`, paginated `tools/list`, and `tools/call` support.
- Global namespace: `mcp.<server_id>.<normalized_tool_name>`.
- Collision detection during normalized tool discovery.
- Conservative policy translation:
  - explicit read-only/non-destructive tools -> LOW + READ_ONLY + no approval;
  - destructive tools -> CRITICAL + EXTERNAL_WRITE + approval;
  - unknown tools -> HIGH + EXTERNAL_WRITE + approval (fail closed).
- Plaintext remote HTTP endpoints rejected by default; loopback HTTP remains available for local development.
- Secrets stay in server configuration headers and are not copied into capability descriptors.

### Regression coverage

- Plugin lifecycle, collision, fingerprint, and approval-policy tests.
- MCP namespace, risk classification, collision, protocol-header, and endpoint-security tests.

## Intentionally not wired into the five-agent core yet

Batch 1 does **not** modify agent prompts, orchestration, model routing, or the hard-coded dispatch path inside the current Tool Gateway. This keeps the platform branch merge-friendly while core hardening continues in parallel.

## Next platform batches

1. Dynamic Tool Gateway backend/provider dispatch for built-in + plugin + MCP capabilities.
2. Knowledge/File Manager lifecycle: source registry, versions, provenance, replace/retire/delete, indexing state, and workspace scope enforcement.
3. Memory scope + retention + conflict/supersession rules.
4. Connection/secret profiles separated from plugin manifests.
5. Approval engine integration and tool receipts for plugin/MCP executions.
6. Job queue / retry / cancellation / idempotency for long-running external tools.
7. Platform inspector endpoints/UI for plugin, MCP, knowledge, memory, and receipts.
