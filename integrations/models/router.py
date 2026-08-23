"""Model Router and Central Dispatcher (Phase 3A / 3D.1.6 / 3D.2.1).

Routes LLM requests to appropriate provider adapters based on configuration,
availability, cost policy, and fallback priority.
Enforces FREE_ONLY_MODE (default True) to guarantee zero unexpected paid provider spend.
Paid providers require explicit user approval (allow_paid=True).
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional
from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
)
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.openai_adapter import OpenAIProviderAdapter
from integrations.models.thespark_adapter import TheSparkProviderAdapter

logger = logging.getLogger("model_router")


class ModelRouter:
    """Central registry and router for multi-provider LLMs with cost governance."""

    def __init__(
        self,
        default_provider: Optional[str] = None,
        free_only_mode: Optional[bool] = None,
    ) -> None:
        self._adapters: Dict[str, BaseModelAdapter] = {}
        from config.authority import get_runtime_config
        runtime = get_runtime_config()
        self._default_provider = (
            default_provider or runtime.default_provider
        ).lower()
        self._fallback_chain: List[str] = ["gemini", "thespark", "openai"]
        self._fallback_enabled: bool = True

        self._free_only_mode: bool = free_only_mode if free_only_mode is not None else runtime.free_only_mode

        # Auto-register available adapters
        self.register_adapter(GeminiProviderAdapter())
        self.register_adapter(TheSparkProviderAdapter())
        self.register_adapter(OpenAIProviderAdapter())

    @property
    def registered_providers(self) -> List[str]:
        return list(self._adapters.keys())

    @property
    def default_provider(self) -> str:
        return self._default_provider

    @property
    def fallback_enabled(self) -> bool:
        return self._fallback_enabled

    @property
    def free_only_mode(self) -> bool:
        return self._free_only_mode

    def set_free_only_mode(self, enabled: bool) -> None:
        """Enable or disable strict free-only mode."""
        self._free_only_mode = enabled

    def set_fallback_enabled(self, enabled: bool) -> None:
        """Enable or disable fallback chain (e.g. disable for strict benchmark mode)."""
        self._fallback_enabled = enabled

    def register_adapter(self, adapter: BaseModelAdapter) -> None:
        """Register a provider adapter."""
        self._adapters[adapter.provider_name.lower()] = adapter
        logger.info(f"Registered model adapter for provider: {adapter.provider_name}")

    def get_adapter(self, provider_name: str) -> Optional[BaseModelAdapter]:
        """Get registered adapter by provider name."""
        return self._adapters.get(provider_name.lower())

    def get_provider_cost_policy(self, provider_name: str) -> CostPolicy:
        """Get cost policy classification for a provider."""
        adapter = self._adapters.get(provider_name.lower())
        return adapter.cost_policy if adapter else CostPolicy.UNKNOWN

    def set_fallback_chain(self, provider_names: List[str]) -> None:
        """Set the priority chain for automated provider fallback."""
        self._fallback_chain = [p.lower() for p in provider_names]

    def set_default_provider(self, provider_name: str) -> None:
        """Set the default provider."""
        self._default_provider = provider_name.lower()

    def generate(
        self,
        request: ModelRequest,
        preferred_provider: Optional[str] = None,
        allow_fallback: Optional[bool] = None,
        allow_paid: bool = False,
    ) -> ModelResponse:
        """Route request to the preferred provider, with cost policy and configurable fallback."""
        target_provider = (
            preferred_provider.lower()
            if preferred_provider
            else self._default_provider
        )

        should_fallback = (
            self._fallback_enabled if allow_fallback is None else allow_fallback
        )

        # Check direct target provider cost policy in FREE_ONLY_MODE
        target_adapter = self._adapters.get(target_provider)
        if self._free_only_mode and not allow_paid:
            if target_adapter and target_adapter.cost_policy != CostPolicy.FREE_TIER_ALLOWED:
                return ModelResponse(
                    request_id=request.request_id,
                    provider=target_provider,
                    model_name=request.model_name,
                    status=ModelResponseStatus.ERROR,
                    error=f"PAID_PROVIDER_BLOCKED_IN_FREE_ONLY_MODE: Provider '{target_provider}' is classified as {target_adapter.cost_policy.value}. Set allow_paid=True or disable FREE_ONLY_MODE to invoke paid models.",
                )

        providers_to_try: List[str] = []
        if target_provider in self._adapters:
            providers_to_try.append(target_provider)

        if should_fallback:
            for p in self._fallback_chain:
                if p not in providers_to_try and p in self._adapters:
                    adapter = self._adapters[p]
                    # In FREE_ONLY_MODE, only fallback to free-tier allowed providers
                    if self._free_only_mode and not allow_paid:
                        if adapter.cost_policy != CostPolicy.FREE_TIER_ALLOWED:
                            continue
                    if not adapter.automatic_fallback_allowed:
                        continue
                    providers_to_try.append(p)

            if not providers_to_try:
                providers_to_try = [
                    p for p, a in self._adapters.items()
                    if not self._free_only_mode or allow_paid or a.cost_policy == CostPolicy.FREE_TIER_ALLOWED
                ]

        if not providers_to_try:
            return ModelResponse(
                request_id=request.request_id,
                provider=target_provider,
                model_name=request.model_name,
                status=ModelResponseStatus.ERROR,
                error=f"NO_ADAPTER_REGISTERED: No eligible provider available for '{target_provider}' under current cost and fallback policies.",
            )

        last_response: Optional[ModelResponse] = None
        for provider_name in providers_to_try:
            adapter = self._adapters[provider_name]
            response = adapter.generate(request)
            if response.status == ModelResponseStatus.SUCCESS:
                return response
            last_response = response
            logger.warning(
                f"Provider {provider_name} failed: {response.error}. "
                f"{'Trying next adapter...' if should_fallback else 'Fallback disabled for benchmark.'}"
            )
            if not should_fallback:
                # Benchmark mode: do not try other providers
                break

        return last_response or ModelResponse(
            request_id=request.request_id,
            provider=target_provider,
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="ALL_PROVIDERS_FAILED",
        )
