# Dynamic Tool Gateway v1

## Status

Implementation branch: `platform/dynamic-tool-gateway-v1`

Dependency: Plugin + MCP foundation in PR #45 / branch `platform/plugin-mcp-foundation-v1`.

This batch is intentionally **not wired into the five-agent runtime yet**. It is a platform component prepared for a later dedicated Agent <-> Platform integration batch.

## Purpose

Extend the existing governed `tools.tool_gateway.ToolGateway` so runtime-discovered capabilities can use the same execution path as built-in capabilities without modifying the existing gateway's security/retry/receipt implementation.

## Architecture

```text
Built-in CapabilityRegistry
          |
          +-----------------------+
                                  v
                       CompositeCapabilityRegistry
                                  ^
                                  |
                 +----------------+----------------+
                 |                                 |
             Plugins                           MCP servers
                 |                                 |
         PluginRegistryAdapter              McpRegistryAdapter
                 |                                 |
                 +----------------+----------------+
                                  |
                           existing ToolGateway
                                  |
                  Policy / Approval / Retry / Receipt
```

## Security and correctness properties

- Built-in capability IDs cannot be overwritten by dynamic sources.
- Dynamic capabilities are namespaced (`plugin.*`, `mcp.*`).
- Dynamic refresh is replace-per-source so removed tools do not remain stale.
- Failed MCP discovery removes that server's previously discovered capabilities (fail closed).
- Disabled plugins disappear from the composite registry after synchronization.
- Plugin execution still requires an explicitly trusted executor binding from Plugin Registry v1.
- MCP workspace scope fields are not silently injected into remote model/tool arguments.
- Existing `PolicyEngine` remains authoritative for agent permissions and approval requirements.
- Existing `ToolGateway` remains authoritative for retry safety and execution receipts.
- Existing `ExecutionReceiptRepository` remains the audit sink.

## Execution provenance

- MCP adapter executions are classified `REAL` because they represent calls to an external MCP server.
- Plugin executions are conservatively classified `SANDBOX` by the dynamic adapter. A future trusted plugin-runtime provenance policy can make this more granular; arbitrary plugin code cannot self-upgrade its audit classification in v1.

## Runtime synchronization

`DynamicToolGateway.sync_all()` performs:

1. export of enabled plugin descriptors;
2. replacement of the plugin dynamic source;
3. discovery of enabled MCP server tools;
4. independent replacement for each `mcp:<server_id>` source;
5. removal of stale/disabled/failed sources;
6. provider alias binding to the appropriate trusted adapter.

## Deliberately deferred

- No agent constructor or orchestrator changes.
- No provider/account/secret profile management.
- No new approval implementation; the existing policy engine is reused.
- No background polling/discovery scheduler.
- No external marketing connector implementation.
- No UI.

## Validation

Focused regression target:

```text
python -m unittest -v tests.test_platform_dynamic_tool_gateway_v1
```

Before integration into `main`, run the repository's full offline regression workflow again against the then-current hardened core.
