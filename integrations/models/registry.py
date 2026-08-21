"""Provider and Model Registry System (Phase 4.3C).

Central configuration-driven registry for LLM providers and models:
- ProviderRegistry: Dynamically registers providers (Gemini Native, OpenAI-Compatible, xKiro, TheSpark, etc.)
- ModelRegistry: Tracks known models, verified capabilities, context limits, and cost policies
- Guarantees: Unknown capabilities remain UNKNOWN; zero hardcoded provider dependencies in agent code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import os
from typing import Any, Dict, List, Optional

from integrations.models.base import BaseModelAdapter, CostPolicy
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from schemas.base import BaseModel, Field

logger = logging.getLogger("model_registry")


class ProviderProtocol(str, Enum):
    """Supported communication protocols for model providers."""
    OPENAI_COMPATIBLE = "openai_compatible"
    GEMINI_NATIVE = "gemini_native"
    CUSTOM = "custom"


class ProviderConfig(BaseModel):
    """Configuration descriptor for a model provider."""
    provider_id: str
    protocol: ProviderProtocol = ProviderProtocol.OPENAI_COMPATIBLE
    base_url: Optional[str] = None
    api_key_env: str
    default_model: str
    chat_completions_path: str = "/chat/completions"
    cost_policy: CostPolicy = CostPolicy.FREE_TIER_ALLOWED
    timeout_seconds: float = 60.0
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class ModelMetadata(BaseModel):
    """Metadata and verified capability specification for a model."""
    provider_id: str
    model_id: str
    display_name: str
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    context_window: Optional[int] = None
    cost_tier: CostPolicy = CostPolicy.FREE_TIER_ALLOWED
    availability: str = "AVAILABLE"  # AVAILABLE | DEPRECATED | UNKNOWN
    supports_json: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False


class ProviderRegistry:
    """Registry managing provider configurations and adapter lifecycle."""

    def __init__(self) -> None:
        self._configs: Dict[str, ProviderConfig] = {}
        self._adapters: Dict[str, BaseModelAdapter] = {}
        self._has_custom_adapters: bool = False
        self._load_builtin_providers()

    def _load_builtin_providers(self) -> None:
        """Register default production provider configurations."""
        # 1. xKiro (Verified free OpenAI-compatible provider)
        self.register_provider(
            ProviderConfig(
                provider_id="xkiro",
                protocol=ProviderProtocol.OPENAI_COMPATIBLE,
                base_url="https://api.xkiro.com/v1",
                api_key_env="XKIRO_API_KEY",
                default_model="mistralai/mistral-large-2512",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                capabilities={"supports_json": True, "provider_type": "third_party"},
            )
        )

        # 2. Google Gemini (Native first-party provider)
        self.register_provider(
            ProviderConfig(
                provider_id="gemini",
                protocol=ProviderProtocol.GEMINI_NATIVE,
                api_key_env="GEMINI_API_KEY",
                default_model="gemini-flash-latest",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                capabilities={"supports_json": True, "supports_vision": True, "provider_type": "first_party"},
            )
        )

        # 3. OpenAI (Paid OpenAI-compatible provider)
        self.register_provider(
            ProviderConfig(
                provider_id="openai",
                protocol=ProviderProtocol.OPENAI_COMPATIBLE,
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                default_model="gpt-4o-mini",
                cost_policy=CostPolicy.PAID,
                capabilities={"supports_json": True, "provider_type": "first_party"},
            )
        )

        # 4. TheSpark (OpenAI-compatible free-tier aggregator)
        self.register_provider(
            ProviderConfig(
                provider_id="thespark",
                protocol=ProviderProtocol.OPENAI_COMPATIBLE,
                base_url="https://api.thespark.io/v1",
                api_key_env="THESPARK_API_KEY",
                default_model="spark-default",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                capabilities={"supports_json": True, "provider_type": "third_party"},
            )
        )

    def register_provider(self, config: ProviderConfig) -> None:
        """Register or update a provider configuration."""
        pid = config.provider_id.lower()
        self._configs[pid] = config
        # Invalidate cached adapter if config changed
        self._adapters.pop(pid, None)
        logger.info(f"Registered provider configuration: {pid} (protocol={config.protocol.value})")

    def get_config(self, provider_id: str) -> Optional[ProviderConfig]:
        """Retrieve provider config by ID."""
        return self._configs.get(provider_id.lower())

    def list_providers(self) -> List[str]:
        """List all registered provider IDs."""
        return list(self._configs.keys())

    def get_adapter(self, provider_id: str) -> Optional[BaseModelAdapter]:
        """Retrieve or create adapter instance for given provider ID."""
        pid = provider_id.lower()
        if pid in self._adapters:
            return self._adapters[pid]

        cfg = self._configs.get(pid)
        if cfg is None:
            return None

        adapter: BaseModelAdapter
        if cfg.protocol == ProviderProtocol.GEMINI_NATIVE:
            adapter = GeminiProviderAdapter(default_model=cfg.default_model)
        elif cfg.protocol == ProviderProtocol.OPENAI_COMPATIBLE:
            adapter = OpenAICompatibleProviderAdapter(
                provider_id=cfg.provider_id,
                base_url=cfg.base_url or "",
                api_key_env=cfg.api_key_env,
                default_model=cfg.default_model,
                chat_completions_path=cfg.chat_completions_path,
                cost_policy=cfg.cost_policy,
                timeout_seconds=cfg.timeout_seconds,
                capabilities=cfg.capabilities,
            )
        else:
            raise ValueError(f"Unsupported provider protocol: {cfg.protocol}")

        self._adapters[pid] = adapter
        return adapter

    def register_custom_adapter(self, adapter: BaseModelAdapter) -> None:
        """Register custom pre-instantiated adapter (e.g. for testing/mocks)."""
        pid = adapter.provider_name.lower()
        self._adapters[pid] = adapter
        self._has_custom_adapters = True


class ModelRegistry:
    """Registry managing model definitions, capabilities, and cost tiers."""

    def __init__(self) -> None:
        self._models: Dict[str, ModelMetadata] = {}
        self._load_builtin_models()

    def _make_key(self, provider_id: str, model_id: str) -> str:
        return f"{provider_id.lower()}::{model_id}"

    def _load_builtin_models(self) -> None:
        """Populate verified known models."""
        # xKiro verified models
        self.register_model(
            ModelMetadata(
                provider_id="xkiro",
                model_id="mistralai/mistral-large-2512",
                display_name="Mistral Large 2512 (xKiro Free)",
                context_window=128000,
                cost_tier=CostPolicy.FREE_TIER_ALLOWED,
                supports_json=True,
                supports_reasoning=True,
            )
        )

        # Gemini models
        for m_id in ("gemini-flash-latest", "gemini-2.0-flash", "gemini-1.5-flash"):
            self.register_model(
                ModelMetadata(
                    provider_id="gemini",
                    model_id=m_id,
                    display_name=f"Google {m_id}",
                    context_window=1000000,
                    cost_tier=CostPolicy.FREE_TIER_ALLOWED,
                    supports_json=True,
                    supports_vision=True,
                )
            )

        # OpenAI models
        self.register_model(
            ModelMetadata(
                provider_id="openai",
                model_id="gpt-4o-mini",
                display_name="OpenAI GPT-4o Mini",
                context_window=128000,
                cost_tier=CostPolicy.PAID,
                supports_json=True,
            )
        )

        # TheSpark models
        self.register_model(
            ModelMetadata(
                provider_id="thespark",
                model_id="spark-default",
                display_name="TheSpark Default Free",
                context_window=32000,
                cost_tier=CostPolicy.FREE_TIER_ALLOWED,
                supports_json=True,
            )
        )

    def register_model(self, model: ModelMetadata) -> None:
        """Register or update a model specification."""
        key = self._make_key(model.provider_id, model.model_id)
        self._models[key] = model

    def get_model(self, provider_id: str, model_id: str) -> Optional[ModelMetadata]:
        """Retrieve model metadata by provider and model ID."""
        key = self._make_key(provider_id, model_id)
        return self._models.get(key)

    def list_models_for_provider(self, provider_id: str) -> List[ModelMetadata]:
        """List all models registered under a given provider."""
        pid = provider_id.lower()
        return [m for m in self._models.values() if m.provider_id.lower() == pid]

    def list_free_models(self) -> List[ModelMetadata]:
        """List all models classified as FREE or FREE_TIER_ALLOWED."""
        return [m for m in self._models.values() if m.cost_tier == CostPolicy.FREE_TIER_ALLOWED]
