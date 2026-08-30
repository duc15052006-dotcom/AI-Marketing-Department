"""Universal Model Gateway (Phase 4.3C).

The single unified access point for all model inferences across the Five-Agent Department:
- Decouples agents from all LLM providers (Gemini, xKiro, OpenAI, TheSpark, etc.)
- Configuration-driven provider & model routing
- Profile-based task delegation (MARKETING_REASONING, RESEARCH, CREATIVE, etc.)
- Strict cost governance (FREE_ONLY_MODE)
- Configurable production fallback with benchmark strict-pin isolation
- Secure secret management (environment variables only, zero secret leakage)
"""

from __future__ import annotations

from enum import Enum
import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelStreamError,
    ModelUsage,
    StreamDelta,
    normalize_model_message,
    normalize_model_request,
)
from integrations.models.config_service import GLOBAL_PROVIDER_CONFIG, ProviderConfigService, ProviderErrorCode
from integrations.models.profiles import ModelProfile, ProfileManager
from integrations.models.registry import (
    ModelMetadata,
    ModelPolicy,
    ModelRegistry,
    ModelTarget,
    ProviderConfig,
    ProviderDefinition,
    ProviderProtocol,
    ProviderRegistry,
    normalize_agent_id,
)
from integrations.models.transport import is_network_exception, is_timeout_exception, sanitize_secrets

logger = logging.getLogger("universal_model_gateway")


def classify_error(err_str: Optional[str]) -> ProviderErrorCode:
    """Classify provider raw error string into standardized ProviderErrorCode."""
    if not err_str:
        return ProviderErrorCode.OTHER
    err_upper = str(err_str).upper()
    if "401" in err_upper or "UNAUTHORIZED" in err_upper or "INVALID_API_KEY" in err_upper:
        return ProviderErrorCode.AUTH_401
    if "403" in err_upper or "FORBIDDEN" in err_upper or "PERMISSION" in err_upper:
        return ProviderErrorCode.PERMISSION_403
    if "429" in err_upper or "RATE_LIMIT" in err_upper or "QUOTA" in err_upper:
        return ProviderErrorCode.RATE_LIMIT_429
    if "TIMEOUT" in err_upper or "TIMED OUT" in err_upper:
        return ProviderErrorCode.TIMEOUT
    if "NO_CREDENTIAL" in err_upper or "MISSING_API_KEY" in err_upper or "NOT CONFIGURED" in err_upper:
        return ProviderErrorCode.NO_CREDENTIAL
    if "NOT_FOUND" in err_upper or "404" in err_upper or "MODEL_NOT_FOUND" in err_upper:
        return ProviderErrorCode.MODEL_NOT_FOUND
    if "NETWORK" in err_upper or "CONNECTION" in err_upper or "ECONNREFUSED" in err_upper:
        return ProviderErrorCode.NETWORK_ERROR
    if "CONFIG" in err_upper or "SCHEME" in err_upper or "URL" in err_upper:
        return ProviderErrorCode.CONFIG_ERROR
    if "DISABLED" in err_upper:
        return ProviderErrorCode.PROVIDER_DISABLED
    return ProviderErrorCode.OTHER


def provider_error_code_to_stream_error(
    err_code: ProviderErrorCode,
    raw_error: Optional[str] = None,
    provider_name: str = "provider",
) -> ModelStreamError:
    """Explicit deterministic conversion from internal ProviderErrorCode to public ModelStreamError."""
    clean_msg = sanitize_secrets(raw_error or f"Error on {provider_name}")
    if len(clean_msg) > 500:
        clean_msg = clean_msg[:500] + "..."

    if err_code == ProviderErrorCode.RATE_LIMIT_429:
        return ModelStreamError(
            code="RATE_LIMITED",
            category="RATE_LIMIT",
            safe_message=clean_msg,
            retryable=True,
            http_status=429,
        )
    elif err_code == ProviderErrorCode.AUTH_401:
        return ModelStreamError(
            code="AUTH_ERROR",
            category="AUTHENTICATION",
            safe_message=clean_msg,
            retryable=False,
            http_status=401,
        )
    elif err_code == ProviderErrorCode.PERMISSION_403:
        return ModelStreamError(
            code="AUTHORIZATION_ERROR",
            category="AUTHORIZATION",
            safe_message=clean_msg,
            retryable=False,
            http_status=403,
        )
    elif err_code == ProviderErrorCode.TIMEOUT:
        return ModelStreamError(
            code="TIMEOUT",
            category="TIMEOUT",
            safe_message=clean_msg,
            retryable=True,
            http_status=408,
        )
    elif err_code == ProviderErrorCode.NETWORK_ERROR:
        return ModelStreamError(
            code="NETWORK_ERROR",
            category="NETWORK",
            safe_message=clean_msg,
            retryable=True,
            http_status=None,
        )
    elif err_code == ProviderErrorCode.NO_CREDENTIAL:
        return ModelStreamError(
            code="NO_CREDENTIAL",
            category="CONFIGURATION",
            safe_message=clean_msg,
            retryable=False,
            http_status=None,
        )
    elif err_code == ProviderErrorCode.PROVIDER_DISABLED:
        return ModelStreamError(
            code="PROVIDER_DISABLED",
            category="CONFIGURATION",
            safe_message=clean_msg,
            retryable=False,
            http_status=None,
        )
    elif err_code == ProviderErrorCode.MODEL_NOT_FOUND:
        return ModelStreamError(
            code="MODEL_NOT_FOUND",
            category="ROUTING",
            safe_message=clean_msg,
            retryable=False,
            http_status=404,
        )
    elif err_code == ProviderErrorCode.CONFIG_ERROR:
        return ModelStreamError(
            code="INVALID_REQUEST",
            category="BAD_REQUEST",
            safe_message=clean_msg,
            retryable=False,
            http_status=400,
        )
    else:
        return ModelStreamError(
            code="PROVIDER_UNAVAILABLE",
            category="SERVER_ERROR",
            safe_message=clean_msg,
            retryable=True,
            http_status=None,
        )


def stream_error_to_provider_error_code(stream_err: ModelStreamError) -> ProviderErrorCode:
    """Explicit deterministic conversion from public ModelStreamError to internal ProviderErrorCode."""
    code = getattr(stream_err, "code", "")
    if code == "RATE_LIMITED":
        return ProviderErrorCode.RATE_LIMIT_429
    elif code in ("AUTH_ERROR", "INVALID_CREDENTIAL"):
        return ProviderErrorCode.AUTH_401
    elif code in ("AUTHORIZATION_ERROR", "PROVIDER_ACCESS_DENIED"):
        return ProviderErrorCode.PERMISSION_403
    elif code == "TIMEOUT":
        return ProviderErrorCode.TIMEOUT
    elif code == "NETWORK_ERROR":
        return ProviderErrorCode.NETWORK_ERROR
    elif code == "NO_CREDENTIAL":
        return ProviderErrorCode.NO_CREDENTIAL
    elif code == "PROVIDER_DISABLED":
        return ProviderErrorCode.PROVIDER_DISABLED
    elif code == "MODEL_NOT_FOUND":
        return ProviderErrorCode.MODEL_NOT_FOUND
    elif code in ("REQUEST_SCHEMA_ERROR", "INVALID_REQUEST"):
        return ProviderErrorCode.CONFIG_ERROR
    return ProviderErrorCode.OTHER


def model_response_to_stream_error(
    response: ModelResponse,
    provider_name: str = "provider",
) -> ModelStreamError:
    """Deterministic, machine-driven conversion of synchronous ModelResponse to public ModelStreamError.

    Prefers structured machine metadata in response.metadata over any human error text.
    Never parses human strings to guess public stream error codes.
    """
    meta = getattr(response, "metadata", {}) or {}

    # 1. Trusted machine error metadata
    if "error_code" in meta and meta["error_code"]:
        code = str(meta["error_code"])
        category = str(meta.get("error_category", "PROVIDER_ERROR"))
        safe_msg = meta.get("safe_message") or sanitize_secrets(response.error or f"Error from {provider_name}")
        raw_retryable = meta.get("retryable", False)
        retryable = raw_retryable if type(raw_retryable) is bool else False
        http_status = meta.get("http_status")
        return ModelStreamError(
            code=code,
            category=category,
            safe_message=safe_msg,
            retryable=retryable,
            http_status=http_status,
        )

    # 2. Structural status signal
    status = getattr(response, "status", None)
    clean_err = sanitize_secrets(response.error or f"Error from {provider_name}")

    if status == ModelResponseStatus.RATE_LIMITED:
        return ModelStreamError(
            code="RATE_LIMITED",
            category="RATE_LIMIT",
            safe_message=clean_err,
            retryable=True,
            http_status=429,
        )
    elif status == ModelResponseStatus.TIMEOUT:
        return ModelStreamError(
            code="TIMEOUT",
            category="TIMEOUT",
            safe_message=clean_err,
            retryable=True,
            http_status=408,
        )
    elif status == ModelResponseStatus.STREAM_UNSUPPORTED:
        return ModelStreamError(
            code="STREAM_UNSUPPORTED",
            category="CAPABILITY",
            safe_message=clean_err,
            retryable=False,
            http_status=None,
        )
    else:
        # Conservative canonical provider error without string guessing
        return ModelStreamError(
            code="PROVIDER_RESPONSE_ERROR",
            category="RESPONSE_ERROR",
            safe_message=clean_err,
            retryable=False,
            http_status=None,
        )


CANONICAL_STREAM_ERROR_CODES = {
    "AUTH_ERROR",
    "AUTHORIZATION_ERROR",
    "PROVIDER_ACCESS_DENIED",
    "RATE_LIMITED",
    "TIMEOUT",
    "NETWORK_ERROR",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_RESPONSE_ERROR",
    "INVALID_REQUEST",
    "REQUEST_SCHEMA_ERROR",
    "NO_CREDENTIAL",
    "PROVIDER_DISABLED",
    "NO_AVAILABLE_PROVIDER",
    "NO_CANDIDATE_MODELS",
    "MODEL_NOT_FOUND",
    "FREE_ONLY_POLICY_VIOLATION",
    "STREAM_INTERNAL_ERROR",
    "STREAM_TRUNCATED",
    "EMPTY_RESPONSE",
    "STREAM_UNSUPPORTED",
    "ALL_CANDIDATES_EXHAUSTED",
}

CANONICAL_STREAM_ERROR_CATEGORIES = {
    "AUTHENTICATION",
    "AUTHORIZATION",
    "BAD_REQUEST",
    "RATE_LIMIT",
    "TIMEOUT",
    "NETWORK",
    "SERVER_ERROR",
    "RESPONSE_ERROR",
    "VALIDATION",
    "CONFIGURATION",
    "ROUTING",
    "POLICY",
    "INTERNAL",
    "STREAM_PROTOCOL",
    "CAPABILITY",
}


def normalize_public_stream_error(
    error: Optional[ModelStreamError],
    default_provider: str = "gateway",
    default_code: str = "PROVIDER_RESPONSE_ERROR",
) -> ModelStreamError:
    """Normalize and sanitize any ModelStreamError crossing the public gateway boundary.

    Validates machine fields against canonical public vocabulary (fails closed to safe defaults).
    Validates http_status to integer in range [100, 599] or None.
    Sanitizes credentials and bounds safe_message to <= MAX_SAFE_MESSAGE_LEN.
    Guarantees that error is never None.
    """
    if error is None:
        code = default_code if default_code in CANONICAL_STREAM_ERROR_CODES else "PROVIDER_RESPONSE_ERROR"
        return ModelStreamError(
            code=code,
            category="RESPONSE_ERROR",
            safe_message=f"Stream error on {default_provider}",
            retryable=False,
            http_status=None,
        )

    # 1. Validate code against canonical vocabulary
    raw_code = getattr(error, "code", None)
    if isinstance(raw_code, str) and raw_code in CANONICAL_STREAM_ERROR_CODES:
        code = raw_code
    else:
        code = "PROVIDER_RESPONSE_ERROR"

    # 2. Validate category against canonical vocabulary
    raw_category = getattr(error, "category", None)
    if isinstance(raw_category, str) and raw_category in CANONICAL_STREAM_ERROR_CATEGORIES:
        category = raw_category
    else:
        category = "RESPONSE_ERROR"

    # 3. Validate retryable (strict Python bool only; fails closed to False for non-bool)
    raw_retryable = getattr(error, "retryable", False)
    if type(raw_retryable) is bool:
        retryable: bool = raw_retryable
    else:
        retryable = False

    # 4. Validate http_status
    raw_status = getattr(error, "http_status", None)
    if isinstance(raw_status, int) and 100 <= raw_status <= 599:
        http_status: Optional[int] = raw_status
    else:
        http_status = None

    # 5. Sanitize and bound safe_message
    raw_msg = getattr(error, "safe_message", None) or f"Error on {default_provider}"
    clean_msg = sanitize_secrets(str(raw_msg))

    return ModelStreamError(
        code=code,
        category=category,
        safe_message=clean_msg,
        retryable=retryable,
        http_status=http_status,
    )


def normalize_public_stream_delta(
    delta: StreamDelta,
    cand_provider: str,
    cand_model: str,
) -> StreamDelta:
    """Enforce gateway candidate provenance, bidirectional error terminal invariant, and safety."""
    is_error = (delta.finish_reason == "error")
    norm_error = normalize_public_stream_error(delta.error, default_provider=cand_provider) if is_error else None

    return StreamDelta(
        content=delta.content,
        finish_reason=delta.finish_reason,
        provider=cand_provider,
        model_name=cand_model,
        error=norm_error,
    )


class ProviderHealth(str, Enum):
    """Runtime health status of a provider."""
    AVAILABLE = "AVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_ERROR = "AUTH_ERROR"
    UNKNOWN = "UNKNOWN"


class UniversalModelGateway:
    """Central universal gateway orchestrating all model requests."""

    def __init__(
        self,
        provider_registry: Optional[ProviderRegistry] = None,
        model_registry: Optional[ModelRegistry] = None,
        profile_manager: Optional[ProfileManager] = None,
        config_service: Optional[ProviderConfigService] = None,
        model_policy: Optional[ModelPolicy] = None,
        free_only_mode: Optional[bool] = None,
        default_provider: Optional[str] = None,
    ) -> None:
        self.config_service = config_service or GLOBAL_PROVIDER_CONFIG
        self.provider_registry = provider_registry or ProviderRegistry()
        self.model_registry = model_registry or ModelRegistry()
        self.profile_manager = profile_manager or ProfileManager()

        from config.authority import get_runtime_config
        runtime = get_runtime_config()
        resolved_free_only = free_only_mode if free_only_mode is not None else runtime.free_only_mode
        if type(resolved_free_only) is not bool:
            raise ValueError("INVALID_FREE_ONLY_MODE: free_only_mode must be a strict boolean.")
        self._free_only_mode: bool = resolved_free_only
        self._default_provider = (default_provider or runtime.default_provider).lower()

        # Authoritative Model Policy
        self._has_explicit_policy: bool = model_policy is not None
        self._model_policy = model_policy or ModelPolicy(
            global_target=ModelTarget(provider_id=default_provider or "xkiro", model_id="mistralai/mistral-large-2512"),
            fallback_chain=[
                ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
                ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
            ],
            free_only_mode=self._free_only_mode,
        )

        # Provider health tracking
        self._health_state: Dict[str, Dict[str, Any]] = {}

    @property
    def model_policy(self) -> ModelPolicy:
        return self._model_policy

    @model_policy.setter
    def model_policy(self, policy: ModelPolicy) -> None:
        self._model_policy = policy
        self._has_explicit_policy = True

    @property
    def free_only_mode(self) -> bool:
        return self._free_only_mode

    @free_only_mode.setter
    def free_only_mode(self, enabled: bool) -> None:
        self.set_free_only_mode(enabled)

    def set_free_only_mode(self, enabled: bool) -> None:
        """Toggle strict free-only cost governance."""
        if type(enabled) is not bool:
            raise ValueError("INVALID_FREE_ONLY_MODE: enabled must be a strict boolean.")
        self._free_only_mode = enabled
        self._model_policy.free_only_mode = enabled

    def get_provider_health(self, provider_id: str) -> ProviderHealth:
        """Get current health state for a provider."""
        state_data = self._health_state.get(provider_id.lower(), {})
        return state_data.get("health", ProviderHealth.AVAILABLE)

    def update_provider_health(self, provider_id: str, health: ProviderHealth, detail: Optional[str] = None) -> None:
        """Update provider health with timestamp."""
        pid = provider_id.lower()
        self._health_state[pid] = {
            "health": health,
            "last_update": time.time(),
            "detail": detail,
        }

    def resolve_candidate_chain(
        self,
        profile: Optional[str] = None,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model_policy: Optional[ModelPolicy] = None,
    ) -> List[Tuple[str, str]]:
        """Resolve ordered list of (provider_id, model_id) candidates."""
        if provider_id and model_id:
            return [(provider_id.lower(), model_id)]

        if profile:
            return self.profile_manager.get_models_for_profile(profile)

        if provider_id:
            cfg = self.provider_registry.get_config(provider_id)
            m_id = model_id or (cfg.default_model if cfg else "default")
            return [(provider_id.lower(), m_id)]

        effective_policy = model_policy or self.model_policy

        # Explicit Injected Adapter Chain (Generic DI Mode):
        # When adapters are explicitly injected and no explicit policy override exists,
        # route through the injected adapter chain.
        has_injected = getattr(self.provider_registry, "_has_custom_adapters", False) or bool(getattr(self.provider_registry, "_injected_adapters", None))
        if has_injected and not profile and not provider_id and not self._has_explicit_policy:
            adapters = getattr(self.provider_registry, "_injected_adapters", {}) or getattr(self.provider_registry, "_adapters", {})
            if adapters:
                return [
                    (pid, getattr(adapter, "default_model", "default"))
                    for pid, adapter in adapters.items()
                ]

        # Explicit Policy Authority (Production / Governed Policy):
        targets = effective_policy.get_candidate_chain_for_agent(agent_id)
        return [(t.provider_id, t.model_id) for t in targets]

    def generate(
        self,
        request: ModelRequest,
        profile: Optional[str] = None,
        provider_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model_policy: Optional[ModelPolicy] = None,
        provider_snapshot: Optional[Any] = None,
        strict_model_pin: bool = False,
        allow_paid: bool = False,
    ) -> ModelResponse:
        """Execute model generation with cost policy enforcement and production fallback."""
        start_time = time.perf_counter()

        if type(allow_paid) is not bool:
            return ModelResponse(
                request_id=getattr(request, "request_id", "REQ-UNKNOWN"),
                provider=provider_id or "gateway",
                model_name=getattr(request, "model_name", "unknown"),
                status=ModelResponseStatus.ERROR,
                error="REQUEST_SCHEMA_ERROR: allow_paid must be a strict boolean.",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        # Canonical request normalization
        try:
            norm_req = normalize_model_request(request)
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=getattr(request, "request_id", "REQ-UNKNOWN"),
                provider=provider_id or "gateway",
                model_name=getattr(request, "model_name", "unknown"),
                status=ModelResponseStatus.ERROR,
                error=f"REQUEST_SCHEMA_ERROR: {str(e)}",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=latency_ms,
            )

        candidates = self.resolve_candidate_chain(
            profile=profile,
            provider_id=provider_id,
            model_id=norm_req.model_name if norm_req.model_name not in ("default", "", None) else None,
            agent_id=agent_id,
            model_policy=model_policy,
        )

        if not candidates:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ModelResponse(
                request_id=norm_req.request_id,
                provider="gateway",
                model_name=norm_req.model_name,
                status=ModelResponseStatus.ERROR,
                error="NO_CANDIDATE_MODELS: No candidate models resolved for request.",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=latency_ms,
            )

        if norm_req.timeout_seconds is not None:
            total_timeout = norm_req.timeout_seconds
        else:
            total_timeout = 180.0
        last_error_resp: Optional[ModelResponse] = None
        attempt_count = 0
        policy_blocked_count = 0
        executed_any = False

        for cand_provider, cand_model in candidates:
            elapsed = time.perf_counter() - start_time
            remaining_timeout = total_timeout - elapsed
            if remaining_timeout <= 0.001 and attempt_count > 0:
                logger.warning("Gateway timeout budget exhausted across fallback candidates.")
                break

            attempt_count += 1

            # 1. Retrieve / Check Provider & Adapter Definition
            if provider_snapshot is not None:
                prov_def = provider_snapshot.get_provider(cand_provider) if hasattr(provider_snapshot, "get_provider") else provider_snapshot.get(cand_provider)
            else:
                prov_def = self.provider_registry.get_provider(cand_provider)

            if prov_def is not None and (not prov_def.enabled or prov_def.cost_policy == CostPolicy.DISABLED):
                err_msg = f"PROVIDER_DISABLED: Provider '{cand_provider}' is disabled."
                last_error_resp = ModelResponse(
                    request_id=norm_req.request_id,
                    provider=cand_provider,
                    model_name=cand_model,
                    status=ModelResponseStatus.ERROR,
                    error=err_msg,
                    usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )
                if strict_model_pin or len(candidates) == 1:
                    return last_error_resp
                continue

            # 2. Active-run adapter binding + Cost Policy & FREE_ONLY_MODE Gate
            # When executing under a run-scoped snapshot, resolve the adapter
            # PINNED to the snapshot's provider definition (full execution
            # fingerprint) so mid-run settings changes cannot drift an active
            # run onto a new credential or endpoint.
            if provider_snapshot is not None and prov_def is not None:
                adapter = self.provider_registry.get_pinned_adapter(prov_def)
            else:
                adapter = self.provider_registry.get_adapter(cand_provider)
            model_meta = self.model_registry.get_model(cand_provider, cand_model)
            # ProviderDefinition-declared cost policy is authoritative when a
            # definition exists (including explicit UNKNOWN = unverified);
            # model metadata is only a fallback for undefined providers.
            if prov_def is not None:
                cost_tier = prov_def.cost_policy
            else:
                cost_tier = (
                    model_meta.cost_tier if model_meta
                    else (adapter.cost_policy if adapter else CostPolicy.UNKNOWN)
                )

            # Effective cost-governance authority: an explicitly supplied
            # run-scoped ModelPolicy governs its own runs; live gateway state
            # applies only when no pinned policy exists. No second authority.
            effective_free_only = (
                bool(model_policy.free_only_mode)
                if model_policy is not None and getattr(model_policy, "free_only_mode", None) is not None
                else self._free_only_mode
            )

            if effective_free_only and not allow_paid:
                if cost_tier == CostPolicy.PAID or cost_tier == CostPolicy.UNKNOWN:
                    policy_reason = (
                        f"Requesting paid model {cand_provider}::{cand_model} is blocked when FREE_ONLY_MODE=True."
                        if cost_tier == CostPolicy.PAID
                        else f"Unverified cost model {cand_provider}::{cand_model} is blocked when FREE_ONLY_MODE=True."
                    )
                    logger.warning(
                        f"Skipping {'paid' if cost_tier == CostPolicy.PAID else 'unverified cost'} model "
                        f"{cand_provider}::{cand_model} under FREE_ONLY_MODE (allow_paid=False)."
                    )
                    policy_blocked_count += 1
                    if strict_model_pin or len(candidates) == 1:
                        latency_ms = (time.perf_counter() - start_time) * 1000.0
                        return ModelResponse(
                            request_id=norm_req.request_id,
                            provider=cand_provider,
                            model_name=cand_model,
                            status=ModelResponseStatus.ERROR,
                            error=f"FREE_ONLY_POLICY_VIOLATION: {policy_reason}",
                            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                            latency_ms=latency_ms,
                        )
                    continue

            if adapter is None:
                err_msg = f"PROVIDER_NOT_CONFIGURED: Provider '{cand_provider}' is not registered."
                last_error_resp = ModelResponse(
                    request_id=norm_req.request_id,
                    provider=cand_provider,
                    model_name=cand_model,
                    status=ModelResponseStatus.ERROR,
                    error=err_msg,
                    usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )
                if strict_model_pin or len(candidates) == 1:
                    return last_error_resp
                continue

            # 3. Construct Request Copy with Targeted Model and Remaining Timeout Budget
            # Timeout authority: the ProviderDefinition (run-pinned snapshot def
            # for active runs, live definition otherwise) bounds the execution
            # timeout, always capped by the overall request/gateway budget.
            # The legacy GLOBAL_PROVIDER_CONFIG does not override Model Settings.
            if provider_snapshot is not None and prov_def is not None and prov_def.timeout_seconds:
                definition_timeout = float(prov_def.timeout_seconds)
            elif prov_def is not None and prov_def.timeout_seconds:
                definition_timeout = float(prov_def.timeout_seconds)
            else:
                definition_timeout = None

            request_budget = (
                float(norm_req.timeout_seconds)
                if getattr(norm_req, "timeout_seconds", None)
                else float(total_timeout)
            )
            if definition_timeout is not None:
                adapter_timeout = min(definition_timeout, request_budget, remaining_timeout)
            else:
                adapter_timeout = min(request_budget, remaining_timeout)
            req_copy = normalize_model_request(norm_req)
            req_copy.model_name = cand_model
            req_copy.timeout_seconds = max(adapter_timeout, 0.001)

            # 4. Execute Invocation
            executed_any = True
            try:
                resp = adapter.generate(req_copy)
            except Exception as e:
                resp = ModelResponse(
                    request_id=norm_req.request_id,
                    provider=cand_provider,
                    model_name=cand_model,
                    status=ModelResponseStatus.ERROR,
                    error=f"ADAPTER_INVOCATION_EXCEPTION: {str(e)[:200]}",
                    usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            # Record fallback and resolution metadata
            resp.metadata["resolved_provider"] = cand_provider
            resp.metadata["resolved_model"] = cand_model
            resp.metadata["attempt_count"] = attempt_count

            # 5. Success Path
            if resp.status == ModelResponseStatus.SUCCESS:
                self.update_provider_health(cand_provider, ProviderHealth.AVAILABLE)
                return resp

            # 6. Failure Path Handling
            last_error_resp = resp
            err_code = classify_error(resp.error)
            self.config_service.record_error(cand_provider, err_code)

            if resp.status == ModelResponseStatus.RATE_LIMITED:
                self.update_provider_health(cand_provider, ProviderHealth.RATE_LIMITED, detail=resp.error)
            elif "AUTH_ERROR" in str(resp.error) or err_code == ProviderErrorCode.AUTH_401:
                self.update_provider_health(cand_provider, ProviderHealth.AUTH_ERROR, detail=resp.error)
            else:
                self.update_provider_health(cand_provider, ProviderHealth.UNAVAILABLE, detail=resp.error)

            # Strict Benchmark Mode blocks any fallback
            if strict_model_pin:
                logger.info(
                    f"Benchmark strict mode active: stopping immediately on failure of {cand_provider}::{cand_model} without fallback."
                )
                return resp

            logger.warning(
                f"Model call to {cand_provider}::{cand_model} failed ({resp.status.value}: {resp.error}). Attempting next candidate in profile chain..."
            )

        # All candidates exhausted
        if last_error_resp is not None:
            return last_error_resp

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        if policy_blocked_count >= len(candidates) and not executed_any:
            # Every candidate was rejected by cost policy and none executed:
            # report a truthful policy violation, never fake success.
            return ModelResponse(
                request_id=norm_req.request_id,
                provider="gateway",
                model_name=request.model_name,
                status=ModelResponseStatus.ERROR,
                error="FREE_ONLY_POLICY_VIOLATION: All candidate models are blocked under FREE_ONLY_MODE (allow_paid=False).",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=latency_ms,
            )
        return ModelResponse(
            request_id=request.request_id,
            provider="gateway",
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="ALL_CANDIDATES_EXHAUSTED: All candidate providers failed or were unavailable.",
            latency_ms=latency_ms,
        )

    def generate_stream(
        self,
        request: ModelRequest,
        profile: Optional[str] = None,
        provider_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model_policy: Optional[ModelPolicy] = None,
        provider_snapshot: Optional[Any] = None,
        strict_model_pin: bool = False,
        allow_paid: bool = False,
    ) -> Generator[StreamDelta, None, None]:
        """Execute model generation with streaming and production fallback.

        Fallback semantics:
        - BEFORE first visible content delta: fallback is safe (try next candidate).
        - AFTER first visible content delta: fallback is FORBIDDEN (provider committed).

        Non-streaming providers are handled via synchronous generate() degradation:
        the complete response is emitted as a single StreamDelta.
        """
        if type(allow_paid) is not bool:
            yield normalize_public_stream_delta(
                StreamDelta(
                    content="",
                    finish_reason="error",
                    error=ModelStreamError(
                        code="REQUEST_SCHEMA_ERROR",
                        category="VALIDATION",
                        safe_message="REQUEST_SCHEMA_ERROR: allow_paid must be a strict boolean.",
                        retryable=False,
                        http_status=None,
                    ),
                ),
                "gateway",
                getattr(request, "model_name", "unknown"),
            )
            return

        try:
            norm_req = normalize_model_request(request)
        except Exception as e:
            clean_err = sanitize_secrets(str(e))
            yield normalize_public_stream_delta(
                StreamDelta(
                    content="",
                    finish_reason="error",
                    error=ModelStreamError(
                        code="REQUEST_SCHEMA_ERROR",
                        category="VALIDATION",
                        safe_message=clean_err,
                        retryable=False,
                        http_status=None,
                    ),
                ),
                "gateway",
                getattr(request, "model_name", "unknown"),
            )
            return

        candidates = self.resolve_candidate_chain(
            profile=profile,
            provider_id=provider_id,
            model_id=norm_req.model_name if norm_req.model_name not in ("default", "", None) else None,
            agent_id=agent_id,
            model_policy=model_policy,
        )

        if not candidates:
            yield normalize_public_stream_delta(
                StreamDelta(
                    content="",
                    finish_reason="error",
                    error=ModelStreamError(
                        code="NO_CANDIDATE_MODELS",
                        category="ROUTING",
                        safe_message=f"NO_CANDIDATE_MODELS: No candidate models available for request '{norm_req.model_name}'.",
                        retryable=False,
                        http_status=None,
                    ),
                ),
                "gateway",
                norm_req.model_name,
            )
            return

        if norm_req.timeout_seconds is not None:
            total_timeout = norm_req.timeout_seconds
        else:
            total_timeout = 180.0

        start_time = time.perf_counter()
        has_emitted_visible_content = False
        last_error: Optional[ModelStreamError] = None
        last_error_provider: Optional[str] = None
        last_error_model: Optional[str] = None

        for cand_idx, (cand_provider, cand_model) in enumerate(candidates):
            if has_emitted_visible_content:
                break

            elapsed = time.perf_counter() - start_time
            remaining_timeout = total_timeout - elapsed

            # 1. Retrieve Provider Definition
            if provider_snapshot is not None:
                prov_def = provider_snapshot.get_provider(cand_provider) if hasattr(provider_snapshot, "get_provider") else provider_snapshot.get(cand_provider)
            else:
                prov_def = self.provider_registry.get_provider(cand_provider)

            if prov_def is not None and (not prov_def.enabled or prov_def.cost_policy == CostPolicy.DISABLED):
                err = ModelStreamError(
                    code="PROVIDER_DISABLED",
                    category="CONFIGURATION",
                    safe_message=f"PROVIDER_DISABLED: Provider '{cand_provider}' is disabled.",
                    retryable=False,
                    http_status=None,
                )
                last_error = err
                last_error_provider = cand_provider
                last_error_model = cand_model
                if strict_model_pin or len(candidates) == 1:
                    yield normalize_public_stream_delta(
                        StreamDelta(content="", finish_reason="error", error=err),
                        cand_provider,
                        cand_model,
                    )
                    return
                continue

            # 2. Adapter Resolution
            if provider_snapshot is not None and prov_def is not None:
                adapter = self.provider_registry.get_pinned_adapter(prov_def)
            else:
                adapter = self.provider_registry.get_adapter(cand_provider)

            if adapter is None:
                err = ModelStreamError(
                    code="NO_AVAILABLE_PROVIDER",
                    category="CONFIGURATION",
                    safe_message=f"NO_AVAILABLE_PROVIDER: No adapter available for provider '{cand_provider}'.",
                    retryable=False,
                    http_status=None,
                )
                last_error = err
                last_error_provider = cand_provider
                last_error_model = cand_model
                if strict_model_pin or len(candidates) == 1:
                    yield normalize_public_stream_delta(
                        StreamDelta(content="", finish_reason="error", error=err),
                        cand_provider,
                        cand_model,
                    )
                    return
                continue

            # 3. Cost Policy Gate
            if prov_def is not None:
                cost_tier = prov_def.cost_policy
            else:
                cost_tier = adapter.cost_policy

            effective_free_only = (
                bool(model_policy.free_only_mode)
                if model_policy is not None and getattr(model_policy, "free_only_mode", None) is not None
                else self._free_only_mode
            )

            if effective_free_only and not allow_paid:
                if cost_tier == CostPolicy.PAID:
                    err = ModelStreamError(
                        code="FREE_ONLY_POLICY_VIOLATION",
                        category="POLICY",
                        safe_message=f"FREE_ONLY_POLICY_VIOLATION: Provider '{cand_provider}' model '{cand_model}' requires paid tier but free_only mode is active.",
                        retryable=False,
                        http_status=None,
                    )
                    last_error = err
                    last_error_provider = cand_provider
                    last_error_model = cand_model
                    if strict_model_pin or len(candidates) == 1:
                        yield normalize_public_stream_delta(
                            StreamDelta(content="", finish_reason="error", error=err),
                            cand_provider,
                            cand_model,
                        )
                        return
                    continue
                elif cost_tier == CostPolicy.UNKNOWN:
                    err = ModelStreamError(
                        code="FREE_ONLY_POLICY_VIOLATION",
                        category="POLICY",
                        safe_message=f"FREE_ONLY_POLICY_VIOLATION: Provider '{cand_provider}' model '{cand_model}' has unverified/unknown cost policy and is blocked fail-closed under free_only mode.",
                        retryable=False,
                        http_status=None,
                    )
                    last_error = err
                    last_error_provider = cand_provider
                    last_error_model = cand_model
                    if strict_model_pin or len(candidates) == 1:
                        yield normalize_public_stream_delta(
                            StreamDelta(content="", finish_reason="error", error=err),
                            cand_provider,
                            cand_model,
                        )
                        return
                    continue

            # 4. Construct Request
            if provider_snapshot is not None and prov_def is not None and prov_def.timeout_seconds:
                definition_timeout = float(prov_def.timeout_seconds)
            elif prov_def is not None and prov_def.timeout_seconds:
                definition_timeout = float(prov_def.timeout_seconds)
            else:
                definition_timeout = None

            request_budget = float(norm_req.timeout_seconds) if getattr(norm_req, "timeout_seconds", None) else float(total_timeout)
            if definition_timeout is not None:
                adapter_timeout = min(definition_timeout, request_budget, remaining_timeout)
            else:
                adapter_timeout = min(request_budget, remaining_timeout)

            req_copy = normalize_model_request(norm_req)
            req_copy.model_name = cand_model
            req_copy.timeout_seconds = max(adapter_timeout, 0.001)

            # 5. Execute Streaming with Fallback Semantics
            candidate_visible_content = False
            candidate_terminal_seen = False

            try:
                stream_gen = adapter.generate_stream(req_copy)
                first_delta = next(stream_gen, None)

                if first_delta is None:
                    err = ModelStreamError(
                        code="STREAM_TRUNCATED",
                        category="STREAM_PROTOCOL",
                        safe_message=f"STREAM_TRUNCATED: Provider '{cand_provider}' stream closed unexpectedly without yielding deltas.",
                        retryable=True,
                        http_status=None,
                    )
                    last_error = err
                    last_error_provider = cand_provider
                    last_error_model = cand_model
                    if strict_model_pin or len(candidates) == 1:
                        yield normalize_public_stream_delta(
                            StreamDelta(content="", finish_reason="error", error=err),
                            cand_provider,
                            cand_model,
                        )
                        return
                    continue

                # 1. Check for stream_unsupported degradation
                if first_delta.finish_reason == "stream_unsupported" and first_delta.content == "" and not candidate_visible_content:
                    try:
                        sync_resp = adapter.generate(req_copy)
                        if sync_resp.status == ModelResponseStatus.SUCCESS:
                            if sync_resp.finish_reason == "error":
                                sync_err = ModelStreamError(
                                    code="PROVIDER_RESPONSE_ERROR",
                                    category="RESPONSE_ERROR",
                                    safe_message=f"PROVIDER_RESPONSE_ERROR: Provider '{cand_provider}' returned finish_reason='error'.",
                                    retryable=False,
                                    http_status=None,
                                )
                                last_error = sync_err
                                last_error_provider = cand_provider
                                last_error_model = cand_model
                                if strict_model_pin or len(candidates) == 1:
                                    yield normalize_public_stream_delta(
                                        StreamDelta(content="", finish_reason="error", error=sync_err),
                                        cand_provider,
                                        cand_model,
                                    )
                                    return
                                continue

                            if not sync_resp.content:
                                empty_err = ModelStreamError(
                                    code="EMPTY_RESPONSE",
                                    category="RESPONSE_ERROR",
                                    safe_message=f"EMPTY_RESPONSE: Provider '{cand_provider}' returned empty content.",
                                    retryable=True,
                                    http_status=None,
                                )
                                last_error = empty_err
                                last_error_provider = cand_provider
                                last_error_model = cand_model
                                if strict_model_pin or len(candidates) == 1:
                                    yield normalize_public_stream_delta(
                                        StreamDelta(content="", finish_reason="error", error=empty_err),
                                        cand_provider,
                                        cand_model,
                                    )
                                    return
                                continue

                            self.update_provider_health(cand_provider, ProviderHealth.AVAILABLE)
                            yield normalize_public_stream_delta(
                                StreamDelta(
                                    content=sync_resp.content,
                                    finish_reason=sync_resp.finish_reason or "stop",
                                ),
                                cand_provider,
                                cand_model,
                            )
                            return
                        else:
                            sync_err = normalize_public_stream_error(
                                model_response_to_stream_error(sync_resp, provider_name=cand_provider),
                                default_provider=cand_provider,
                            )
                            internal_code = stream_error_to_provider_error_code(sync_err)
                            self.config_service.record_error(cand_provider, internal_code)
                            if internal_code == ProviderErrorCode.RATE_LIMIT_429:
                                self.update_provider_health(cand_provider, ProviderHealth.RATE_LIMITED)
                            elif internal_code == ProviderErrorCode.AUTH_401:
                                self.update_provider_health(cand_provider, ProviderHealth.AUTH_ERROR)
                            elif internal_code in (ProviderErrorCode.TIMEOUT, ProviderErrorCode.NETWORK_ERROR):
                                self.update_provider_health(cand_provider, ProviderHealth.UNAVAILABLE)

                            last_error = sync_err
                            last_error_provider = cand_provider
                            last_error_model = cand_model
                            if strict_model_pin or len(candidates) == 1:
                                yield normalize_public_stream_delta(
                                    StreamDelta(content="", finish_reason="error", error=sync_err),
                                    cand_provider,
                                    cand_model,
                                )
                                return
                            continue
                    except Exception as sync_e:
                        sync_err = ModelStreamError(
                            code="STREAM_INTERNAL_ERROR",
                            category="INTERNAL",
                            safe_message=f"STREAM_INTERNAL_ERROR: Internal model invocation failure on '{cand_provider}'.",
                            retryable=False,
                            http_status=None,
                        )
                        last_error = sync_err
                        last_error_provider = cand_provider
                        last_error_model = cand_model
                        if strict_model_pin or len(candidates) == 1:
                            yield normalize_public_stream_delta(
                                StreamDelta(content="", finish_reason="error", error=sync_err),
                                cand_provider,
                                cand_model,
                            )
                            return
                        continue

                # 2. First delta is an explicit error with no content
                if first_delta.finish_reason == "error" and first_delta.content == "" and not candidate_visible_content:
                    candidate_terminal_seen = True
                    cand_err = normalize_public_stream_error(first_delta.error, default_provider=cand_provider)
                    last_error = cand_err
                    last_error_provider = cand_provider
                    last_error_model = cand_model

                    internal_code = stream_error_to_provider_error_code(cand_err)
                    self.config_service.record_error(cand_provider, internal_code)
                    if internal_code == ProviderErrorCode.RATE_LIMIT_429:
                        self.update_provider_health(cand_provider, ProviderHealth.RATE_LIMITED)
                    elif internal_code == ProviderErrorCode.AUTH_401:
                        self.update_provider_health(cand_provider, ProviderHealth.AUTH_ERROR)
                    elif internal_code in (ProviderErrorCode.TIMEOUT, ProviderErrorCode.NETWORK_ERROR):
                        self.update_provider_health(cand_provider, ProviderHealth.UNAVAILABLE)

                    if strict_model_pin or len(candidates) == 1:
                        yield normalize_public_stream_delta(first_delta, cand_provider, cand_model)
                        return
                    continue

                # 3. First delta is a non-error finish_reason (e.g. "stop") with NO content
                if first_delta.finish_reason and not first_delta.content and not candidate_visible_content:
                    candidate_terminal_seen = True
                    empty_err = ModelStreamError(
                        code="EMPTY_RESPONSE",
                        category="RESPONSE_ERROR",
                        safe_message=f"EMPTY_RESPONSE: Provider '{cand_provider}' completed without emitting visible assistant content.",
                        retryable=True,
                        http_status=None,
                    )
                    last_error = empty_err
                    last_error_provider = cand_provider
                    last_error_model = cand_model
                    if strict_model_pin or len(candidates) == 1:
                        yield normalize_public_stream_delta(
                            StreamDelta(content="", finish_reason="error", error=empty_err),
                            cand_provider,
                            cand_model,
                        )
                        return
                    continue

                # 4. First delta has visible content
                if first_delta.content:
                    candidate_visible_content = True
                    has_emitted_visible_content = True
                    if first_delta.finish_reason == "error":
                        candidate_terminal_seen = True
                        yield normalize_public_stream_delta(
                            StreamDelta(content=first_delta.content, finish_reason=None),
                            cand_provider,
                            cand_model,
                        )
                        yield normalize_public_stream_delta(
                            StreamDelta(
                                content="",
                                finish_reason="error",
                                error=normalize_public_stream_error(first_delta.error, default_provider=cand_provider),
                            ),
                            cand_provider,
                            cand_model,
                        )
                        return
                    else:
                        yield normalize_public_stream_delta(first_delta, cand_provider, cand_model)
                        if first_delta.finish_reason:
                            candidate_terminal_seen = True
                            return

                # 5. Process remaining deltas from stream_gen
                for delta in stream_gen:
                    if delta.content:
                        candidate_visible_content = True
                        has_emitted_visible_content = True

                    if delta.finish_reason:
                        candidate_terminal_seen = True
                        if delta.finish_reason == "error":
                            if delta.content:
                                yield normalize_public_stream_delta(
                                    StreamDelta(content=delta.content, finish_reason=None),
                                    cand_provider,
                                    cand_model,
                                )
                            yield normalize_public_stream_delta(
                                StreamDelta(
                                    content="",
                                    finish_reason="error",
                                    error=normalize_public_stream_error(delta.error, default_provider=cand_provider),
                                ),
                                cand_provider,
                                cand_model,
                            )
                            return
                        else:
                            yield normalize_public_stream_delta(delta, cand_provider, cand_model)
                            return
                    else:
                        yield normalize_public_stream_delta(delta, cand_provider, cand_model)

                # 6. Generator finished. Check if candidate finished without a terminal delta (Silent EOF)!
                if not candidate_terminal_seen:
                    if candidate_visible_content:
                        # Visible content was emitted, but stream dropped without finish_reason -> STREAM_TRUNCATED (NO fallback)
                        yield normalize_public_stream_delta(
                            StreamDelta(
                                content="",
                                finish_reason="error",
                                error=ModelStreamError(
                                    code="STREAM_TRUNCATED",
                                    category="STREAM_PROTOCOL",
                                    safe_message=f"STREAM_TRUNCATED: Provider '{cand_provider}' stream closed unexpectedly after partial output.",
                                    retryable=False,
                                    http_status=None,
                                ),
                            ),
                            cand_provider,
                            cand_model,
                        )
                        return
                    else:
                        # No visible content and no finish_reason -> STREAM_TRUNCATED (fallback allowed)
                        trunc_err = ModelStreamError(
                            code="STREAM_TRUNCATED",
                            category="STREAM_PROTOCOL",
                            safe_message=f"STREAM_TRUNCATED: Provider '{cand_provider}' stream closed unexpectedly without completion signal.",
                            retryable=True,
                            http_status=None,
                        )
                        last_error = trunc_err
                        last_error_provider = cand_provider
                        last_error_model = cand_model
                        if strict_model_pin or len(candidates) == 1:
                            yield normalize_public_stream_delta(
                                StreamDelta(content="", finish_reason="error", error=trunc_err),
                                cand_provider,
                                cand_model,
                            )
                            return
                        continue

                return

            except Exception as e:
                is_timeout = is_timeout_exception(e)
                is_net = is_network_exception(e)

                if is_timeout:
                    err_code = "TIMEOUT"
                    err_cat = "TIMEOUT"
                    safe_msg = f"TIMEOUT: Model call to '{cand_provider}' timed out."
                    ret = True
                    st = 408
                elif is_net:
                    err_code = "NETWORK_ERROR"
                    err_cat = "NETWORK"
                    safe_msg = f"NETWORK_ERROR: Network connection failure communicating with '{cand_provider}'."
                    ret = True
                    st = None
                else:
                    err_code = "STREAM_INTERNAL_ERROR"
                    err_cat = "INTERNAL"
                    safe_msg = f"STREAM_INTERNAL_ERROR: Internal model streaming failure on '{cand_provider}'."
                    ret = False
                    st = None

                err = ModelStreamError(
                    code=err_code,
                    category=err_cat,
                    safe_message=safe_msg,
                    retryable=ret,
                    http_status=st,
                )
                last_error = err
                last_error_provider = cand_provider
                last_error_model = cand_model
                if candidate_visible_content or has_emitted_visible_content:
                    yield normalize_public_stream_delta(
                        StreamDelta(content="", finish_reason="error", error=err),
                        cand_provider,
                        cand_model,
                    )
                    return
                if strict_model_pin or len(candidates) == 1:
                    yield normalize_public_stream_delta(
                        StreamDelta(content="", finish_reason="error", error=err),
                        cand_provider,
                        cand_model,
                    )
                    return
                continue

        # All candidates exhausted without visible content
        if not has_emitted_visible_content:
            if last_error is not None and last_error_provider is not None:
                yield normalize_public_stream_delta(
                    StreamDelta(
                        content="",
                        finish_reason="error",
                        error=last_error,
                    ),
                    last_error_provider,
                    last_error_model or norm_req.model_name,
                )
            else:
                yield normalize_public_stream_delta(
                    StreamDelta(
                        content="",
                        finish_reason="error",
                        error=ModelStreamError(
                            code="ALL_CANDIDATES_EXHAUSTED",
                            category="ROUTING",
                            safe_message=f"ALL_CANDIDATES_EXHAUSTED: All {len(candidates)} candidate models exhausted without successful completion.",
                            retryable=False,
                            http_status=None,
                        ),
                    ),
                    "gateway",
                    norm_req.model_name,
                )
