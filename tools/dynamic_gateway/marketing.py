"""Sandbox-only DynamicToolGateway adapter for governed marketing connectors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping

from connectors.marketing import (
    ExternalMarketingContractError,
    ExternalMarketingRequest,
    MarketingConnectionNotReadyError,
    MarketingConnectorRegistry,
    MarketingConnectorRegistryError,
    MarketingExecutionMode,
)
from governance.redaction import sanitize_sensitive_text
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


@dataclass(frozen=True)
class MarketingGatewayRoute:
    dynamic_capability_id: str
    connector_id: str
    base_capability_id: str


class MarketingRegistrySandboxAdapter(BaseCapabilityAdapter):
    """Prepare and simulate marketing actions after ToolGateway governance.

    This adapter is intentionally SANDBOX-only. It does not resolve credentials,
    perform network I/O, or call a provider SDK. Approval/intent/receipt handling
    therefore remains entirely in ToolGateway before this adapter is invoked.
    """

    _TRUSTED_SCOPE_KEYS = {
        "business_id",
        "project_id",
        "brand_id",
        "run_id",
        "request_id",
        "approval_token",
    }
    _ALLOWED_PARAMETERS = {
        "connection_id",
        "action",
        "resource_type",
        "resource_id",
        "idempotency_key",
        "payload",
    }

    def __init__(self, registry: MarketingConnectorRegistry) -> None:
        self.registry = registry
        self._routes: Dict[str, MarketingGatewayRoute] = {}

    @property
    def adapter_name(self) -> str:
        return "marketing_registry_sandbox_adapter"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return ExecutionMode.SANDBOX

    def replace_routes(self, routes: Mapping[str, MarketingGatewayRoute]) -> None:
        self._routes = {str(key).strip().lower(): value for key, value in routes.items()}

    def list_routes(self) -> Dict[str, MarketingGatewayRoute]:
        return dict(self._routes)

    @staticmethod
    def _request_id(
        capability_id: str,
        parameters: Dict[str, Any],
        run_id: str,
        business_id: str,
        project_id: str,
        brand_id: str,
    ) -> str:
        encoded = json.dumps(
            {
                "capability_id": capability_id,
                "parameters": parameters,
                "run_id": run_id,
                "business_id": business_id,
                "project_id": project_id,
                "brand_id": brand_id,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"mkt-{hashlib.sha256(encoded).hexdigest()[:24]}"

    @staticmethod
    def _error(code: str, message: str) -> AdapterResult:
        return AdapterResult(
            success=False,
            error_code=code,
            error_message=sanitize_sensitive_text(message),
            execution_mode=ExecutionMode.SANDBOX,
        )

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
        """Legacy adapter contract delegates with no trusted brand scope."""
        return self.execute_with_trusted_scope(
            capability_id=capability_id,
            parameters=parameters,
            timeout_seconds=timeout_seconds,
            run_id=run_id,
            business_id=business_id,
            project_id=project_id,
            brand_id="",
        )

    def execute_with_trusted_scope(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
        brand_id: str = "",
    ) -> AdapterResult:
        """Execute after ToolGateway supplies trusted tenant/project/brand scope."""
        route = self._routes.get(str(capability_id or "").strip().lower())
        if route is None:
            return self._error("MARKETING_ROUTE_NOT_FOUND", "Marketing gateway route is not active.")

        supplied = set(parameters)
        untrusted_scope = sorted(supplied & self._TRUSTED_SCOPE_KEYS)
        if untrusted_scope:
            return self._error(
                "UNTRUSTED_SCOPE_PARAMETER",
                "Trusted execution scope must come from ToolRequest fields, not model-controlled parameters: "
                + ", ".join(untrusted_scope),
            )
        unexpected = sorted(supplied - self._ALLOWED_PARAMETERS)
        if unexpected:
            return self._error(
                "UNSUPPORTED_MARKETING_PARAMETERS",
                "Unsupported marketing parameters: " + ", ".join(unexpected),
            )
        if not business_id:
            return self._error(
                "BUSINESS_SCOPE_REQUIRED",
                "External marketing execution requires trusted ToolRequest.business_id.",
            )

        payload = parameters.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            return self._error("INVALID_MARKETING_PAYLOAD", "payload must be an object/map.")

        try:
            request = ExternalMarketingRequest(
                request_id=self._request_id(
                    capability_id,
                    dict(parameters),
                    run_id,
                    business_id,
                    project_id,
                    brand_id,
                ),
                run_id=run_id,
                connector_id=route.connector_id,
                connection_id=str(parameters.get("connection_id") or ""),
                capability_id=route.base_capability_id,
                action=str(parameters.get("action") or ""),
                resource_type=str(parameters.get("resource_type") or ""),
                resource_id=parameters.get("resource_id"),
                business_id=business_id,
                project_id=project_id or None,
                brand_id=brand_id or None,
                idempotency_key=parameters.get("idempotency_key"),
                payload=dict(payload),
            )
            prepared = self.registry.prepare(request)
        except (ExternalMarketingContractError, MarketingConnectorRegistryError) as exc:
            code = (
                "MARKETING_CONNECTION_NOT_READY"
                if isinstance(exc, MarketingConnectionNotReadyError)
                else "MARKETING_CONTRACT_REJECTED"
            )
            return self._error(code, str(exc))
        except Exception as exc:
            return self._error("MARKETING_PREPARATION_ERROR", str(exc))

        if prepared.execution_mode is not MarketingExecutionMode.SANDBOX:
            return self._error(
                "MARKETING_SANDBOX_ONLY",
                "Only SANDBOX marketing specs may execute through this adapter version.",
            )

        data = prepared.to_safe_dict()
        data["timeout_seconds"] = float(timeout_seconds)
        if request.policy.is_write:
            data.update(
                {
                    "status": "SANDBOX_SIMULATED_WRITE",
                    "external_side_effect": False,
                    "provider_network_called": False,
                    "message": "Marketing write validated and simulated; no external account was changed.",
                }
            )
        else:
            data.update(
                {
                    "status": "SANDBOX_NO_OBSERVED_DATA",
                    "analysis_available": False,
                    "provider_network_called": False,
                    "message": "Sandbox route is valid but no provider telemetry was fetched or fabricated.",
                }
            )
        return AdapterResult(success=True, data=data, execution_mode=ExecutionMode.SANDBOX)
