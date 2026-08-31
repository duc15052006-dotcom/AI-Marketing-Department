"""Trusted dynamic adapters for PluginRegistry and McpServerRegistry."""

from __future__ import annotations

from typing import Any, Dict

from integrations.mcp.registry import (
    McpRegistryError,
    McpServerDisabledError,
    McpServerNotFoundError,
    McpServerRegistry,
)
from plugins.registry import (
    PluginDisabledError,
    PluginExecutorNotBoundError,
    PluginNotFoundError,
    PluginRegistry,
    PluginRegistryError,
)
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


def _normalize_plugin_output(value: Any) -> AdapterResult:
    if isinstance(value, AdapterResult):
        return value
    if isinstance(value, dict):
        return AdapterResult(success=True, data=dict(value), execution_mode=ExecutionMode.SANDBOX)
    return AdapterResult(
        success=True,
        data={"result": value},
        execution_mode=ExecutionMode.SANDBOX,
    )


class PluginRegistryAdapter(BaseCapabilityAdapter):
    """Routes namespaced plugin capabilities through an explicitly trusted registry."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry

    @property
    def adapter_name(self) -> str:
        return "plugin_registry_adapter"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        # Raw plugin executors are treated as sandbox/extension code unless the
        # executor returns an explicit AdapterResult with stronger provenance.
        return ExecutionMode.SANDBOX

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        trusted_context = {
            "run_id": run_id,
            "business_id": business_id,
            "project_id": project_id,
            "timeout_seconds": timeout_seconds,
        }
        try:
            value = self.registry.execute(capability_id, dict(parameters), trusted_context)
            return _normalize_plugin_output(value)
        except TimeoutError as exc:
            return AdapterResult(
                success=False,
                error_code="TIMEOUT",
                error_message=str(exc) or "Plugin execution timed out.",
                execution_mode=ExecutionMode.SANDBOX,
            )
        except ConnectionError as exc:
            return AdapterResult(
                success=False,
                error_code="NETWORK_ERROR",
                error_message=str(exc) or "Plugin network operation failed.",
                execution_mode=ExecutionMode.SANDBOX,
            )
        except PluginDisabledError as exc:
            return AdapterResult(success=False, error_code="PLUGIN_DISABLED", error_message=str(exc), execution_mode=ExecutionMode.SANDBOX)
        except PluginExecutorNotBoundError as exc:
            return AdapterResult(success=False, error_code="PLUGIN_EXECUTOR_NOT_BOUND", error_message=str(exc), execution_mode=ExecutionMode.SANDBOX)
        except PluginNotFoundError as exc:
            return AdapterResult(success=False, error_code="PLUGIN_NOT_FOUND", error_message=str(exc), execution_mode=ExecutionMode.SANDBOX)
        except PluginRegistryError as exc:
            return AdapterResult(success=False, error_code="PLUGIN_REGISTRY_ERROR", error_message=str(exc), execution_mode=ExecutionMode.SANDBOX)
        except Exception as exc:
            return AdapterResult(success=False, error_code="PLUGIN_EXECUTION_ERROR", error_message=str(exc), execution_mode=ExecutionMode.SANDBOX)


class McpRegistryAdapter(BaseCapabilityAdapter):
    """Routes discovered MCP tools while preserving the internal adapter contract."""

    def __init__(self, registry: McpServerRegistry) -> None:
        self.registry = registry

    @property
    def adapter_name(self) -> str:
        return "mcp_registry_adapter"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return ExecutionMode.REAL

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        # Scope fields are intentionally not injected into MCP tool arguments.
        # They stay in trusted gateway context/receipts rather than becoming
        # model-controlled remote parameters.
        try:
            result = self.registry.execute(capability_id, dict(parameters))
        except TimeoutError as exc:
            return AdapterResult(success=False, error_code="TIMEOUT", error_message=str(exc) or "MCP tool timed out.", execution_mode=ExecutionMode.REAL)
        except ConnectionError as exc:
            return AdapterResult(success=False, error_code="NETWORK_ERROR", error_message=str(exc) or "MCP transport failed.", execution_mode=ExecutionMode.REAL)
        except McpServerDisabledError as exc:
            return AdapterResult(success=False, error_code="MCP_SERVER_DISABLED", error_message=str(exc), execution_mode=ExecutionMode.REAL)
        except McpServerNotFoundError as exc:
            return AdapterResult(success=False, error_code="MCP_SERVER_NOT_FOUND", error_message=str(exc), execution_mode=ExecutionMode.REAL)
        except McpRegistryError as exc:
            return AdapterResult(success=False, error_code="MCP_REGISTRY_ERROR", error_message=str(exc), execution_mode=ExecutionMode.REAL)
        except Exception as exc:
            return AdapterResult(success=False, error_code="MCP_EXECUTION_ERROR", error_message=str(exc), execution_mode=ExecutionMode.REAL)

        data: Dict[str, Any] = {
            "content": list(result.content),
            "structured_content": result.structured_content,
        }
        if result.is_error:
            return AdapterResult(
                success=False,
                data=data,
                error_code="MCP_TOOL_ERROR",
                error_message="MCP tool returned isError=true.",
                execution_mode=ExecutionMode.REAL,
            )
        return AdapterResult(success=True, data=data, execution_mode=ExecutionMode.REAL)
