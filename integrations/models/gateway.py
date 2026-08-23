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
from typing import Any, Dict, List, Optional, Tuple

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
    normalize_model_message,
    normalize_model_request,
)
from integrations.models.config_service import GLOBAL_PROVIDER_CONFIG, ProviderConfigService, ProviderErrorCode
from integrations.models.profiles import ModelProfile, ProfileManager
from integrations.models.registry import ModelMetadata, ModelRegistry, ProviderConfig, ProviderProtocol, ProviderRegistry

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
    if "CONFIG" in err_upper:
        return ProviderErrorCode.CONFIG_ERROR
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

        # Provider health tracking
        self._health_state: Dict[str, Dict[str, Any]] = {}

    @property
    def free_only_mode(self) -> bool:
        return self._free_only_mode

    def set_free_only_mode(self, enabled: bool) -> None:
        """Toggle strict free-only cost governance."""
        self._free_only_mode = enabled

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

        if getattr(self.provider_registry, "_has_custom_adapters", False) and not profile and not provider_id:
            return [
                (pid, getattr(adapter, "default_model", "default"))
                for pid, adapter in self.provider_registry._adapters.items()
            ]

        # Default fallback chain
        return [
            ("xkiro", "mistralai/mistral-large-2512"),
            ("gemini", "gemini-flash-latest"),
        ]

    def generate(
        self,
        request: ModelRequest,
        profile: Optional[str] = None,
        provider_id: Optional[str] = None,
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

        for cand_provider, cand_model in candidates:
            elapsed = time.perf_counter() - start_time
            remaining_timeout = total_timeout - elapsed
            if remaining_timeout <= 0.001 and attempt_count > 0:
                logger.warning("Gateway timeout budget exhausted across fallback candidates.")
                break

            attempt_count += 1

            # 1. Cost Policy & FREE_ONLY_MODE Gate
            adapter = self.provider_registry.get_adapter(cand_provider)
            model_meta = self.model_registry.get_model(cand_provider, cand_model)
            cost_tier = model_meta.cost_tier if model_meta else (adapter.cost_policy if adapter else CostPolicy.UNKNOWN)

            if self._free_only_mode and not allow_paid:
                if cost_tier == CostPolicy.PAID:
                    logger.warning(
                        f"Skipping paid model {cand_provider}::{cand_model} under FREE_ONLY_MODE (allow_paid=False)."
                    )
                    if strict_model_pin or len(candidates) == 1:
                        latency_ms = (time.perf_counter() - start_time) * 1000.0
                        return ModelResponse(
                            request_id=norm_req.request_id,
                            provider=cand_provider,
                            model_name=cand_model,
                            status=ModelResponseStatus.ERROR,
                            error=f"FREE_ONLY_POLICY_VIOLATION: Requesting paid model {cand_provider}::{cand_model} is blocked when FREE_ONLY_MODE=True.",
                            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                            latency_ms=latency_ms,
                        )
                    continue

                if cost_tier == CostPolicy.UNKNOWN and cand_provider not in ("gemini", "thespark", "xkiro"):
                    logger.warning(
                        f"Skipping unverified cost model {cand_provider}::{cand_model} under FREE_ONLY_MODE."
                    )
                    continue

            # 2. Retrieve Adapter
            adapter = self.provider_registry.get_adapter(cand_provider)
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
                if strict_model_pin:
                    return last_error_resp

            # 3. Construct Request Copy with Targeted Model and Remaining Timeout Budget
            cand_cfg_timeout = self.config_service.get_timeout(cand_provider) if self.config_service else 30.0
            adapter_timeout = min(cand_cfg_timeout, remaining_timeout) if norm_req.timeout_seconds is None else remaining_timeout
            req_copy = normalize_model_request(norm_req)
            req_copy.model_name = cand_model
            req_copy.timeout_seconds = max(adapter_timeout, 0.001)

            # 4. Execute Invocation
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
        return ModelResponse(
            request_id=request.request_id,
            provider="gateway",
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="ALL_CANDIDATES_EXHAUSTED: All candidate providers failed or were unavailable.",
            latency_ms=latency_ms,
        )
