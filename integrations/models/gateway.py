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
        self._free_only_mode: bool = free_only_mode if free_only_mode is not None else runtime.free_only_mode
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

            if prov_def is not None and not prov_def.enabled:
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
        try:
            norm_req = normalize_model_request(request)
        except Exception as e:
            yield StreamDelta(
                content="",
                finish_reason="error",
                provider="gateway",
                model_name=getattr(request, "model_name", "unknown"),
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
            yield StreamDelta(
                content="",
                finish_reason="error",
                provider="gateway",
                model_name=norm_req.model_name,
            )
            return

        if norm_req.timeout_seconds is not None:
            total_timeout = norm_req.timeout_seconds
        else:
            total_timeout = 180.0

        start_time = time.perf_counter()
        has_emitted_visible_content = False

        for cand_provider, cand_model in candidates:
            if has_emitted_visible_content:
                break

            elapsed = time.perf_counter() - start_time
            remaining_timeout = total_timeout - elapsed

            # 1. Retrieve Provider Definition
            if provider_snapshot is not None:
                prov_def = provider_snapshot.get_provider(cand_provider) if hasattr(provider_snapshot, "get_provider") else provider_snapshot.get(cand_provider)
            else:
                prov_def = self.provider_registry.get_provider(cand_provider)

            if prov_def is not None and not prov_def.enabled:
                if strict_model_pin or len(candidates) == 1:
                    yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
                    return
                continue

            # 2. Adapter Resolution
            if provider_snapshot is not None and prov_def is not None:
                adapter = self.provider_registry.get_pinned_adapter(prov_def)
            else:
                adapter = self.provider_registry.get_adapter(cand_provider)

            if adapter is None:
                if strict_model_pin or len(candidates) == 1:
                    yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
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
                if cost_tier == CostPolicy.PAID or cost_tier == CostPolicy.UNKNOWN:
                    if strict_model_pin or len(candidates) == 1:
                        yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
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
            try:
                stream_gen = adapter.generate_stream(req_copy)
                first_delta = next(stream_gen, None)

                if first_delta is None:
                    if strict_model_pin or len(candidates) == 1:
                        yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
                        return
                    continue

                # Check for unsupported/error before first visible content
                if first_delta.finish_reason == "stream_unsupported" and first_delta.content == "" and not has_emitted_visible_content:
                    # Degradation for non-streaming adapters via synchronous generate()
                    try:
                        sync_resp = adapter.generate(req_copy)
                        if sync_resp.status == ModelResponseStatus.SUCCESS:
                            self.update_provider_health(cand_provider, ProviderHealth.AVAILABLE)
                            yield StreamDelta(
                                content=sync_resp.content,
                                finish_reason=sync_resp.finish_reason or "stop",
                                provider=cand_provider,
                                model_name=cand_model,
                            )
                            return
                        else:
                            err_code = classify_error(sync_resp.error)
                            self.config_service.record_error(cand_provider, err_code)
                            if strict_model_pin or len(candidates) == 1:
                                yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
                                return
                            continue
                    except Exception:
                        if strict_model_pin or len(candidates) == 1:
                            yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
                            return
                        continue

                if first_delta.finish_reason == "error" and first_delta.content == "" and not has_emitted_visible_content:
                    if strict_model_pin or len(candidates) == 1:
                        yield first_delta
                        return
                    continue

                # First delta has visible content — provider is committed
                if first_delta.content:
                    has_emitted_visible_content = True
                    yield first_delta
                elif first_delta.finish_reason:
                    # First delta is a finish_reason with no content
                    yield first_delta
                    return

                # Yield remaining deltas
                for delta in stream_gen:
                    if delta.content:
                        has_emitted_visible_content = True
                    yield delta
                    if delta.finish_reason:
                        return

                return

            except Exception as e:
                if has_emitted_visible_content:
                    yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
                    return
                if strict_model_pin or len(candidates) == 1:
                    yield StreamDelta(content="", finish_reason="error", provider=cand_provider, model_name=cand_model)
                    return
                continue

        # All candidates exhausted without visible content
        if not has_emitted_visible_content:
            yield StreamDelta(content="", finish_reason="error", provider="gateway", model_name=norm_req.model_name)
