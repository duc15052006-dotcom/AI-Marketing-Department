"""Trusted LIVE execution boundary for governed external marketing connectors.

This module intentionally contains no provider SDK implementation. Runtime code
must explicitly bind a trusted executor object for an exact connector. Secret
material is resolved only after DynamicToolGateway approval/intent governance has
already admitted the request and entered adapter dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple

from connections.secrets import SecretValue
from connectors.marketing import (
    ExternalMarketingContractError,
    ExternalMarketingRequest,
    MarketingConnectionNotReadyError,
    MarketingConnectorRegistry,
    MarketingConnectorRegistryError,
    MarketingExecutionMode,
    PreparedMarketingAction,
)
from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.dynamic_gateway.marketing import MarketingGatewayRoute, MarketingRegistrySandboxAdapter
from tools.receipts import ExecutionMode


class MarketingLiveExecutorError(RuntimeError):
    """Base error for trusted marketing LIVE executor registration."""


class MarketingLiveExecutorNotBoundError(MarketingLiveExecutorError):
    pass


class MarketingLiveExecutorProviderMismatchError(MarketingLiveExecutorError):
    pass


@dataclass(frozen=True)
class MarketingLiveExecutorResult:
    """Normalized result returned by a trusted provider executor.

    ``success=False`` is only valid when the executor can prove the provider did
    not create the intended side effect. Any uncertain post-dispatch outcome must
    be raised as an exception so ToolGateway can classify consequential writes as
    AMBIGUOUS_EXTERNAL_ACTION_OUTCOME and suppress replay.
    """

    success: bool
    data: Mapping[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    cost_or_tokens: Mapping[str, Any] = field(default_factory=dict)
    artifact_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError("MarketingLiveExecutorResult.success must be bool.")
        if self.success and (self.error_code or self.error_message):
            raise ValueError("Successful LIVE executor results cannot carry error metadata.")
        if not self.success and not self.error_code:
            raise ValueError("Failed LIVE executor results require a stable error_code.")
        object.__setattr__(self, "data", dict(self.data or {}))
        object.__setattr__(self, "cost_or_tokens", dict(self.cost_or_tokens or {}))
        object.__setattr__(self, "artifact_refs", tuple(str(item) for item in self.artifact_refs or ()))


class MarketingLiveExecutor(Protocol):
    """Trusted runtime provider executor contract.

    The executor receives a redaction-safe ``SecretValue`` wrapper, not a raw
    credential string. Provider-specific code must explicitly call ``reveal()``
    at its transport boundary.
    """

    @property
    def executor_name(self) -> str:
        ...

    @property
    def provider(self) -> str:
        ...

    def execute(
        self,
        *,
        prepared: PreparedMarketingAction,
        request: ExternalMarketingRequest,
        credential: Optional[SecretValue],
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        ...


class MarketingLiveExecutorRegistry:
    """Explicit trusted binding from connector id to provider executor object."""

    def __init__(self, marketing_registry: MarketingConnectorRegistry) -> None:
        self.marketing_registry = marketing_registry
        self._executors: Dict[str, MarketingLiveExecutor] = {}

    @staticmethod
    def _key(connector_id: str) -> str:
        key = str(connector_id or "").strip().lower()
        if not key:
            raise MarketingLiveExecutorError("connector_id is required for LIVE executor binding.")
        return key

    def bind(
        self,
        connector_id: str,
        executor: MarketingLiveExecutor,
        *,
        replace: bool = False,
    ) -> None:
        key = self._key(connector_id)
        spec = self.marketing_registry.get(connector_id)
        if spec.execution_mode is not MarketingExecutionMode.LIVE:
            raise MarketingLiveExecutorError(
                f"Connector '{spec.connector_id}' is not registered for LIVE marketing execution."
            )
        executor_provider = str(getattr(executor, "provider", "") or "").strip().lower()
        executor_name = str(getattr(executor, "executor_name", "") or "").strip()
        if not executor_name:
            raise MarketingLiveExecutorError("Trusted LIVE executor must declare executor_name.")
        if executor_provider != spec.provider:
            raise MarketingLiveExecutorProviderMismatchError(
                f"Executor provider does not match connector '{spec.connector_id}' provider."
            )
        if key in self._executors and not replace:
            raise MarketingLiveExecutorError(
                f"LIVE executor for connector '{spec.connector_id}' is already bound; use replace=True explicitly."
            )
        self._executors[key] = executor

    def unbind(self, connector_id: str) -> bool:
        return self._executors.pop(self._key(connector_id), None) is not None

    def is_bound(self, connector_id: str) -> bool:
        return self._key(connector_id) in self._executors

    def get(self, connector_id: str) -> MarketingLiveExecutor:
        key = self._key(connector_id)
        try:
            return self._executors[key]
        except KeyError as exc:
            raise MarketingLiveExecutorNotBoundError(
                f"LIVE executor for connector '{connector_id}' is not bound."
            ) from exc

    def list_bindings(self) -> Dict[str, str]:
        return {
            connector_id: str(getattr(executor, "executor_name", "trusted_executor"))
            for connector_id, executor in sorted(self._executors.items())
        }


def _sanitize_with_exact_secret(value: Any, secret: Optional[str]) -> Any:
    """Recursively remove the exact transient credential plus generic secrets."""
    if isinstance(value, dict):
        value = {key: _sanitize_with_exact_secret(item, secret) for key, item in value.items()}
    elif isinstance(value, list):
        value = [_sanitize_with_exact_secret(item, secret) for item in value]
    elif isinstance(value, tuple):
        value = tuple(_sanitize_with_exact_secret(item, secret) for item in value)
    elif isinstance(value, str):
        value = sanitize_sensitive_text(value, secret=secret)
    return sanitize_sensitive_payload(value)


class MarketingRegistryLiveAdapter(BaseCapabilityAdapter):
    """LIVE adapter boundary guarded by explicit runtime opt-in and executor binding."""

    _TRUSTED_SCOPE_KEYS = MarketingRegistrySandboxAdapter._TRUSTED_SCOPE_KEYS
    _ALLOWED_PARAMETERS = MarketingRegistrySandboxAdapter._ALLOWED_PARAMETERS

    def __init__(
        self,
        marketing_registry: MarketingConnectorRegistry,
        executor_registry: MarketingLiveExecutorRegistry,
        *,
        allow_live_execution: bool = False,
    ) -> None:
        self.marketing_registry = marketing_registry
        self.executor_registry = executor_registry
        self.allow_live_execution = bool(allow_live_execution)
        self._routes: Dict[str, MarketingGatewayRoute] = {}

    @property
    def adapter_name(self) -> str:
        return "marketing_registry_live_adapter"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return ExecutionMode.REAL

    def replace_routes(self, routes: Mapping[str, MarketingGatewayRoute]) -> None:
        self._routes = {str(key).strip().lower(): value for key, value in routes.items()}

    def list_routes(self) -> Dict[str, MarketingGatewayRoute]:
        return dict(self._routes)

    @staticmethod
    def _error(code: str, message: str) -> AdapterResult:
        return AdapterResult(
            success=False,
            error_code=code,
            error_message=sanitize_sensitive_text(message),
            execution_mode=ExecutionMode.REAL,
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
        if not self.allow_live_execution:
            return self._error(
                "LIVE_MARKETING_EXECUTION_DISABLED",
                "LIVE marketing execution is disabled at the trusted runtime boundary.",
            )

        route = self._routes.get(str(capability_id or "").strip().lower())
        if route is None:
            return self._error("MARKETING_LIVE_ROUTE_NOT_FOUND", "LIVE marketing gateway route is not active.")

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
                "External marketing LIVE execution requires trusted ToolRequest.business_id.",
            )

        payload = parameters.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            return self._error("INVALID_MARKETING_PAYLOAD", "payload must be an object/map.")

        try:
            request = ExternalMarketingRequest(
                request_id=MarketingRegistrySandboxAdapter._request_id(
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
            prepared = self.marketing_registry.prepare(request)
        except (ExternalMarketingContractError, MarketingConnectorRegistryError) as exc:
            code = (
                "MARKETING_CONNECTION_NOT_READY"
                if isinstance(exc, MarketingConnectionNotReadyError)
                else "MARKETING_CONTRACT_REJECTED"
            )
            return self._error(code, str(exc))
        except Exception as exc:
            return self._error("MARKETING_PREPARATION_ERROR", str(exc))

        if prepared.execution_mode is not MarketingExecutionMode.LIVE:
            return self._error(
                "MARKETING_LIVE_SPEC_REQUIRED",
                "Only LIVE marketing specs may execute through the trusted LIVE adapter.",
            )

        try:
            executor = self.executor_registry.get(route.connector_id)
        except MarketingLiveExecutorError as exc:
            return self._error("LIVE_MARKETING_EXECUTOR_NOT_BOUND", str(exc))

        # Secret resolution is deliberately after request preparation. For
        # consequential capabilities ToolGateway has already claimed approval and
        # persisted DISPATCHING intent before entering this adapter method.
        try:
            access = self.marketing_registry.control_plane.resolve_for_execution(
                route.connector_id,
                business_id=business_id,
                project_id=project_id or None,
                brand_id=brand_id or None,
                connection_id=request.connection_id,
            )
        except Exception as exc:
            # No provider executor has run yet, so this is a definite pre-side-
            # effect failure and may safely return a normal AdapterResult error.
            return self._error("LIVE_CREDENTIAL_RESOLUTION_FAILED", str(exc))

        credential = access.connection.secret if access.connection is not None else None
        exact_secret: Optional[str] = None
        try:
            result = executor.execute(
                prepared=prepared,
                request=request,
                credential=credential,
                timeout_seconds=float(timeout_seconds),
            )
            if credential is not None:
                exact_secret = credential.reveal()
            if not isinstance(result, MarketingLiveExecutorResult):
                raise RuntimeError(
                    "LIVE_EXECUTOR_INVALID_RESULT: trusted executor must return MarketingLiveExecutorResult."
                )
        except Exception as exc:
            if exact_secret is None and credential is not None:
                exact_secret = credential.reveal()
            safe_message = sanitize_sensitive_text(str(exc), secret=exact_secret)
            # Once the provider executor has been invoked, uncertainty must reach
            # ToolGateway. Consequential writes will be marked AMBIGUOUS and are
            # never automatically replayed.
            if isinstance(exc, TimeoutError):
                raise TimeoutError(safe_message) from exc
            if isinstance(exc, ConnectionError):
                raise ConnectionError(safe_message) from exc
            raise RuntimeError(safe_message) from exc

        safe_data = _sanitize_with_exact_secret(dict(result.data), exact_secret)
        safe_cost = _sanitize_with_exact_secret(dict(result.cost_or_tokens), exact_secret)
        safe_artifacts = [sanitize_sensitive_text(item, secret=exact_secret) for item in result.artifact_refs]
        if result.success:
            return AdapterResult(
                success=True,
                data=safe_data,
                cost_or_tokens=safe_cost,
                artifact_refs=safe_artifacts,
                execution_mode=ExecutionMode.REAL,
            )

        safe_error = sanitize_sensitive_text(result.error_message or "LIVE provider execution failed.", secret=exact_secret)
        safe_code = sanitize_sensitive_text(result.error_code or "LIVE_EXECUTION_ERROR", secret=exact_secret)
        return AdapterResult(
            success=False,
            data=safe_data,
            error_code=safe_code,
            error_message=safe_error,
            cost_or_tokens=safe_cost,
            artifact_refs=safe_artifacts,
            execution_mode=ExecutionMode.REAL,
        )
