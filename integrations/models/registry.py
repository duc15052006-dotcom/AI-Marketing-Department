"""Provider and Model Registry System (Phase 4.3C / Phase PROD-MODEL-GATEWAY-01).

Central configuration-driven registry for LLM providers and models:
- ProviderDefinition & ProviderRegistry: Dynamically registers, validates, enables, disables,
  and tests providers (Gemini Native, OpenAI-Compatible, xKiro, TheSpark, Local Ollama/vLLM, etc.)
- ModelTarget: Generic (provider_id, model_id) routing tuple.
- ModelPolicy: Five-Agent policy supporting global targets, per-agent overrides, and deterministic fallback chains.
- ModelRegistry: Tracks known models, verified capabilities, context limits, and cost policies.
- Guarantees: Zero hardcoded provider dependencies in agent code; zero plaintext secret exposure in serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.parse

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.transport import sanitize_secrets
from schemas.base import BaseModel, Field

logger = logging.getLogger("model_registry")


class ProviderProtocol(str, Enum):
    """Supported communication protocols for model providers."""
    OPENAI_COMPATIBLE = "openai_compatible"
    GEMINI_NATIVE = "gemini_native"
    CUSTOM = "custom"


def validate_base_url(url: Optional[str]) -> Optional[str]:
    """Validate and canonicalize a provider base URL.

    Security & normalization rules:
    - Must use http:// or https://. Rejects file://, ftp://, javascript:, data:, etc.
    - Rejects embedded userinfo/credentials (https://user:pass@example.com).
    - Plain HTTP (http://) is strictly restricted to local loopback hosts (127.0.0.1, localhost, ::1, [::1], 0.0.0.0).
    - Canonicalizes duplicate slashes and redundant trailing paths (/v1/v1, /chat/completions).
    """
    if url is None:
        return None
    cleaned = str(url).strip()
    if not cleaned:
        return None

    parsed = urllib.parse.urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"INVALID_URL_SCHEME: Unsupported scheme '{parsed.scheme}'. Base URL must use https:// or http:// loopback.")

    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise ValueError("INVALID_URL_CREDENTIALS: Base URL must not contain embedded username or password.")

    hostname = (parsed.hostname or "").lower()
    if scheme == "http":
        is_loopback = hostname in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "local") or hostname.endswith(".localhost")
        if not is_loopback:
            raise ValueError(f"INSECURE_HTTP_URL: Plain HTTP is restricted to local loopback addresses (127.0.0.1, localhost). Found '{hostname}'.")

    # Canonicalize path: remove trailing /chat/completions or duplicate /v1/v1
    path = parsed.path or ""
    path = re.sub(r"/+", "/", path)
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    while path.endswith("/v1/v1"):
        path = path[:-3]
    path = path.rstrip("/")

    port_str = f":{parsed.port}" if parsed.port else ""
    canonical_url = f"{scheme}://{parsed.hostname}{port_str}{path}"
    return canonical_url


class ProviderDefinition(BaseModel):
    """Configuration and capability descriptor for a model provider."""
    provider_id: str
    adapter_type: str = "OPENAI_COMPATIBLE"
    display_name: str = ""
    base_url: Optional[str] = None
    enabled: bool = True
    supported_capabilities: Dict[str, Any] = Field(default_factory=dict)
    credential_ref: Optional[str] = None
    default_model: str = "default"
    chat_completions_path: str = "/chat/completions"
    cost_policy: CostPolicy = CostPolicy.FREE_TIER_ALLOWED
    timeout_seconds: float = 60.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Legacy / Compatibility fields
    protocol: Optional[ProviderProtocol] = None
    api_key_env: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        # Validate machine provider ID
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("INVALID_PROVIDER_ID: provider_id cannot be empty.")
        self.provider_id = str(self.provider_id).strip().lower()

        # Default display name
        if not self.display_name:
            self.display_name = self.provider_id.capitalize()

        # Handle backward compatibility fields
        if self.protocol is not None:
            if isinstance(self.protocol, str):
                try:
                    self.protocol = ProviderProtocol(self.protocol.lower())
                except Exception:
                    pass
            val = self.protocol.value if hasattr(self.protocol, "value") else str(self.protocol)
            self.adapter_type = val.upper()
        elif self.adapter_type:
            try:
                self.protocol = ProviderProtocol(self.adapter_type.lower())
            except Exception:
                pass

        if self.api_key_env and not self.credential_ref:
            self.credential_ref = f"ENV:{self.api_key_env}"
        elif self.credential_ref and not self.api_key_env and self.credential_ref.startswith("ENV:"):
            self.api_key_env = self.credential_ref[4:]

        if self.capabilities and not self.supported_capabilities:
            self.supported_capabilities = self.capabilities
        elif self.supported_capabilities and not self.capabilities:
            self.capabilities = self.supported_capabilities

        # Validate base_url if present
        if self.base_url:
            self.base_url = validate_base_url(self.base_url)


# Backward compatibility alias
class ProviderConfig(ProviderDefinition):
    """Legacy alias for ProviderDefinition."""
    pass


class ModelTarget(BaseModel):
    """Target pairing a specific provider machine ID and model identifier."""
    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.provider_id or not str(self.provider_id).strip():
            raise ValueError("INVALID_MODEL_TARGET: provider_id cannot be empty.")
        if not self.model_id or not str(self.model_id).strip():
            raise ValueError("INVALID_MODEL_TARGET: model_id cannot be empty.")
        self.provider_id = str(self.provider_id).strip().lower()
        self.model_id = str(self.model_id).strip()


class AgentId(str, Enum):
    """The exactly five permanent logical agents in the AI Marketing Department."""
    CMO = "CMO"
    INTELLIGENCE = "INTELLIGENCE"
    STRATEGIST = "STRATEGIST"
    CREATIVE = "CREATIVE"
    PERFORMANCE = "PERFORMANCE"


def normalize_agent_id(agent_name: str) -> str:
    """Normalize agent identity to one of the 5 permanent logical agents.

    Mapping:
    - 'cmo', 'CMO', 'final_cmo', 'FINAL_CMO' -> 'CMO'
    - 'intelligence', 'INTELLIGENCE' -> 'INTELLIGENCE'
    - 'strategist', 'STRATEGIST' -> 'STRATEGIST'
    - 'creative', 'CREATIVE' -> 'CREATIVE'
    - 'performance', 'PERFORMANCE' -> 'PERFORMANCE'

    Rejects 'agent_6', 'UNKNOWN', or any unauthorized agent key.
    """
    if not agent_name or not str(agent_name).strip():
        raise ValueError("INVALID_AGENT_ID: Agent identifier cannot be empty.")
    norm = str(agent_name).strip().upper()
    if norm in ("CMO", "FINAL_CMO", "STAGE_1_CMO", "STAGE_6_FINAL_CMO"):
        return AgentId.CMO.value
    if norm in ("INTELLIGENCE", "INTEL"):
        return AgentId.INTELLIGENCE.value
    if norm in ("STRATEGIST", "STRATEGY"):
        return AgentId.STRATEGIST.value
    if norm in ("CREATIVE", "COPYWRITER"):
        return AgentId.CREATIVE.value
    if norm in ("PERFORMANCE", "ANALYTICS"):
        return AgentId.PERFORMANCE.value

    raise ValueError(
        f"INVALID_AGENT_OVERRIDE_KEY: Unknown agent identifier '{agent_name}'. "
        "Must be one of exactly 5 permanent logical agents: CMO, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE."
    )


class ModelPolicy(BaseModel):
    """Governance and routing policy for model invocations across the five agents."""
    global_target: ModelTarget = Field(
        default_factory=lambda: ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512")
    )
    agent_overrides: Dict[str, ModelTarget] = Field(default_factory=dict)
    fallback_chain: List[ModelTarget] = Field(
        default_factory=lambda: [
            ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
            ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
        ]
    )
    timeout_seconds: float = 60.0
    free_only_mode: bool = True
    configuration_version: str = "v1"

    def __post_init__(self) -> None:
        super().__post_init__()
        # Validate and normalize all agent override keys
        normalized_overrides: Dict[str, ModelTarget] = {}
        for k, target in self.agent_overrides.items():
            norm_key = normalize_agent_id(k)
            if isinstance(target, dict):
                target = ModelTarget(**target)
            normalized_overrides[norm_key] = target
        self.agent_overrides = normalized_overrides

        normalized_chain: List[ModelTarget] = []
        for t in self.fallback_chain:
            if isinstance(t, dict):
                normalized_chain.append(ModelTarget(**t))
            else:
                normalized_chain.append(t)
        self.fallback_chain = normalized_chain

        if isinstance(self.global_target, dict):
            self.global_target = ModelTarget(**self.global_target)

    def resolve_target_for_agent(self, agent_name: Optional[str] = None) -> ModelTarget:
        """Resolve authoritative ModelTarget for a given agent or global fallback."""
        if agent_name:
            norm_key = normalize_agent_id(agent_name)
            if norm_key in self.agent_overrides:
                return self.agent_overrides[norm_key]
        return self.global_target

    def get_candidate_chain_for_agent(self, agent_name: Optional[str] = None) -> List[ModelTarget]:
        """Resolve ordered list of candidate ModelTargets for an agent execution."""
        primary = self.resolve_target_for_agent(agent_name)
        candidates = [primary]
        for fb in self.fallback_chain:
            if isinstance(fb, dict):
                fb = ModelTarget(**fb)
            if fb.provider_id != primary.provider_id or fb.model_id != primary.model_id:
                if fb not in candidates:
                    candidates.append(fb)
        return candidates


class ConnectionTestStatus(str, Enum):
    """Status of a model connection verification attempt."""
    CONNECTED = "CONNECTED"
    AUTH_FAILED = "AUTH_FAILED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    UNAVAILABLE = "UNAVAILABLE"


class ConnectionTestResult(BaseModel):
    """Result of testing connection to a model provider without saving configuration."""
    status: ConnectionTestStatus
    provider_id: str
    error: Optional[str] = None
    latency_ms: float = 0.0
    model_id: Optional[str] = None


class ProviderRegistrySnapshot(BaseModel):
    """Immutable snapshot of registered providers at a specific point in time."""
    providers: Dict[str, ProviderDefinition] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

    def get_provider(self, provider_id: str) -> Optional[ProviderDefinition]:
        """Retrieve provider definition from frozen snapshot."""
        return self.providers.get(provider_id.lower())


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
    """Registry managing provider configurations, custom adapters, and connection testing."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._configs: Dict[str, ProviderDefinition] = {}
        self._adapters: Dict[str, BaseModelAdapter] = {}
        self._secrets: Dict[str, str] = {}
        self._injected_adapters: Dict[str, BaseModelAdapter] = {}
        self._load_builtin_providers()

    def _load_builtin_providers(self) -> None:
        """Register default production provider configurations."""
        # 1. xKiro (Verified free OpenAI-compatible provider)
        self.register_provider(
            ProviderDefinition(
                provider_id="xkiro",
                adapter_type="OPENAI_COMPATIBLE",
                display_name="xKiro AI",
                base_url="https://api.xkiro.com/v1",
                credential_ref="ENV:XKIRO_API_KEY",
                default_model="mistralai/mistral-large-2512",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                supported_capabilities={"supports_json": True, "provider_type": "third_party"},
            )
        )

        # 2. Google Gemini (Native first-party provider)
        self.register_provider(
            ProviderDefinition(
                provider_id="gemini",
                adapter_type="GEMINI_NATIVE",
                display_name="Google Gemini",
                credential_ref="ENV:GEMINI_API_KEY",
                default_model="gemini-flash-latest",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                supported_capabilities={"supports_json": True, "supports_vision": True, "provider_type": "first_party"},
            )
        )

        # 3. OpenAI (Paid OpenAI-compatible provider)
        self.register_provider(
            ProviderDefinition(
                provider_id="openai",
                adapter_type="OPENAI_COMPATIBLE",
                display_name="OpenAI",
                base_url="https://api.openai.com/v1",
                credential_ref="ENV:OPENAI_API_KEY",
                default_model="gpt-4o-mini",
                cost_policy=CostPolicy.PAID,
                supported_capabilities={"supports_json": True, "provider_type": "first_party"},
            )
        )

        # 4. TheSpark (OpenAI-compatible free-tier aggregator)
        self.register_provider(
            ProviderDefinition(
                provider_id="thespark",
                adapter_type="OPENAI_COMPATIBLE",
                display_name="TheSpark",
                base_url="https://api.thespark.io/v1",
                credential_ref="ENV:THESPARK_API_KEY",
                default_model="spark-default",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
                supported_capabilities={"supports_json": True, "provider_type": "third_party"},
            )
        )

    def register_provider(self, config: Union[ProviderDefinition, ProviderConfig], secret: Optional[str] = None) -> None:
        """Register or update a provider configuration atomically."""
        if isinstance(config, dict):
            config = ProviderDefinition(**config)
        pid = config.provider_id.lower()
        with self._lock:
            self._configs[pid] = config
            if secret:
                self._secrets[pid] = secret
            self._adapters.pop(pid, None)
            logger.info(f"Registered provider configuration: {pid} (type={config.adapter_type})")

    def update_provider(self, provider_id: str, updates: Dict[str, Any]) -> ProviderDefinition:
        """Update fields on an existing registered provider."""
        pid = provider_id.lower()
        with self._lock:
            existing = self._configs.get(pid)
            if not existing:
                raise ValueError(f"PROVIDER_NOT_FOUND: Cannot update unregistered provider '{provider_id}'.")
            data = existing.model_dump()
            data.update(updates)
            updated = ProviderDefinition(**data)
            self._configs[pid] = updated
            self._adapters.pop(pid, None)
            return updated

    def enable_provider(self, provider_id: str) -> None:
        """Enable a registered provider."""
        pid = provider_id.lower()
        with self._lock:
            if pid not in self._configs:
                raise ValueError(f"PROVIDER_NOT_FOUND: Provider '{provider_id}' is not registered.")
            self._configs[pid].enabled = True
            self._adapters.pop(pid, None)

    def disable_provider(self, provider_id: str) -> None:
        """Disable a registered provider without deleting its metadata."""
        pid = provider_id.lower()
        with self._lock:
            if pid not in self._configs:
                raise ValueError(f"PROVIDER_NOT_FOUND: Provider '{provider_id}' is not registered.")
            self._configs[pid].enabled = False
            self._adapters.pop(pid, None)

    def get_provider(self, provider_id: str) -> Optional[ProviderDefinition]:
        """Retrieve provider definition by ID."""
        with self._lock:
            return self._configs.get(provider_id.lower())

    def get_config(self, provider_id: str) -> Optional[ProviderDefinition]:
        """Legacy compatibility alias for get_provider."""
        return self.get_provider(provider_id)

    def list_providers(self) -> List[str]:
        """List all registered provider IDs."""
        with self._lock:
            return list(self._configs.keys())

    def list_provider_definitions(self, include_disabled: bool = True) -> List[ProviderDefinition]:
        """List all registered provider definitions."""
        with self._lock:
            if include_disabled:
                return list(self._configs.values())
            return [p for p in self._configs.values() if p.enabled]

    def _resolve_secret(self, cfg: ProviderDefinition) -> Optional[str]:
        """Resolve API credential from secret storage or environment reference."""
        pid = cfg.provider_id.lower()
        if pid in self._secrets and self._secrets[pid]:
            return self._secrets[pid]
        ref = cfg.credential_ref or ""
        if ref.startswith("ENV:"):
            env_var = ref[4:].strip()
            return os.environ.get(env_var)
        if cfg.api_key_env:
            return os.environ.get(cfg.api_key_env)
        return None

    def get_adapter(self, provider_id: str, include_disabled: bool = False) -> Optional[BaseModelAdapter]:
        """Retrieve or create adapter instance for given provider ID."""
        pid = provider_id.lower()
        with self._lock:
            if pid in getattr(self, "_injected_adapters", {}):
                return self._injected_adapters[pid]

            cfg = self._configs.get(pid)
            if cfg is None:
                return None
            if not cfg.enabled and not include_disabled:
                return None

            if pid in self._adapters:
                return self._adapters[pid]

            secret = self._resolve_secret(cfg)
            adapter_type_upper = str(cfg.adapter_type).upper()

            adapter: BaseModelAdapter
            if adapter_type_upper in ("GEMINI_NATIVE", "GEMINI"):
                adapter = GeminiProviderAdapter(
                    default_model=cfg.default_model,
                    api_key=secret,
                )
            elif adapter_type_upper in ("OPENAI_COMPATIBLE", "OPENAI"):
                adapter = OpenAICompatibleProviderAdapter(
                    provider_id=cfg.provider_id,
                    base_url=cfg.base_url or "",
                    api_key_env=cfg.api_key_env or f"{cfg.provider_id.upper()}_API_KEY",
                    default_model=cfg.default_model,
                    api_key=secret,
                    chat_completions_path=cfg.chat_completions_path,
                    cost_policy=cfg.cost_policy,
                    timeout_seconds=cfg.timeout_seconds,
                    capabilities=cfg.supported_capabilities,
                )
            else:
                raise ValueError(f"UNSUPPORTED_ADAPTER_TYPE: '{cfg.adapter_type}' for provider '{pid}'.")

            self._adapters[pid] = adapter
            return adapter

    def register_custom_adapter(self, adapter: BaseModelAdapter) -> None:
        """Test/Mock Dependency Injection: register a pre-instantiated adapter object."""
        pid = adapter.provider_name.lower()
        with self._lock:
            self._adapters[pid] = adapter
            self._injected_adapters[pid] = adapter
            if pid not in self._configs:
                self._configs[pid] = ProviderDefinition(
                    provider_id=pid,
                    adapter_type="CUSTOM_INJECTED",
                    display_name=getattr(adapter, "provider_name", pid),
                    default_model=getattr(adapter, "default_model", "default"),
                    cost_policy=getattr(adapter, "cost_policy", CostPolicy.FREE_TIER_ALLOWED),
                )

    def snapshot(self) -> ProviderRegistrySnapshot:
        """Create an immutable snapshot of all provider definitions for execution run pinning."""
        with self._lock:
            copied = {pid: ProviderDefinition(**cfg.model_dump()) for pid, cfg in self._configs.items()}
            return ProviderRegistrySnapshot(providers=copied)

    def test_connection(
        self,
        definition: ProviderDefinition,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> ConnectionTestResult:
        """Test connection to a provider without saving or mutating the active registry."""
        start_time = time.perf_counter()
        pid = definition.provider_id.lower()
        model_id = definition.default_model or "default"
        resolved_key = api_key or self._resolve_secret(definition)

        try:
            adapter_type_upper = str(definition.adapter_type).upper()
            temp_adapter: BaseModelAdapter
            if adapter_type_upper in ("GEMINI_NATIVE", "GEMINI"):
                temp_adapter = GeminiProviderAdapter(
                    default_model=model_id,
                    api_key=resolved_key,
                    timeout_seconds=timeout_seconds,
                )
            else:
                temp_adapter = OpenAICompatibleProviderAdapter(
                    provider_id=definition.provider_id,
                    base_url=definition.base_url or "",
                    api_key_env="TEMP_KEY",
                    default_model=model_id,
                    api_key=resolved_key,
                    chat_completions_path=definition.chat_completions_path,
                    cost_policy=definition.cost_policy,
                    timeout_seconds=timeout_seconds,
                    capabilities=definition.supported_capabilities,
                )

            req = ModelRequest(
                model_name=model_id,
                messages=[ModelMessage(role=ModelRole.USER, content="ping")],
                max_tokens=5,
                timeout_seconds=timeout_seconds,
            )
            resp = temp_adapter.generate(req)
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            if resp.status == ModelResponseStatus.SUCCESS:
                return ConnectionTestResult(
                    status=ConnectionTestStatus.CONNECTED,
                    provider_id=pid,
                    model_id=model_id,
                    latency_ms=latency_ms,
                )
            if resp.status == ModelResponseStatus.RATE_LIMITED:
                return ConnectionTestResult(
                    status=ConnectionTestStatus.RATE_LIMIT,
                    provider_id=pid,
                    model_id=model_id,
                    error=sanitize_secrets(resp.error or "Rate limit exceeded", secret=resolved_key),
                    latency_ms=latency_ms,
                )
            if resp.status == ModelResponseStatus.TIMEOUT:
                return ConnectionTestResult(
                    status=ConnectionTestStatus.TIMEOUT,
                    provider_id=pid,
                    model_id=model_id,
                    error=sanitize_secrets(resp.error or "Request timed out", secret=resolved_key),
                    latency_ms=latency_ms,
                )

            err_str = str(resp.error or "").upper()
            sanitized_err = sanitize_secrets(resp.error or "Provider error", secret=resolved_key)
            if any(k in err_str for k in ("401", "UNAUTHORIZED", "AUTH", "API_KEY", "MISSING_API_KEY")):
                status = ConnectionTestStatus.AUTH_FAILED
            elif any(k in err_str for k in ("404", "NOT_FOUND", "MODEL_NOT_FOUND")):
                status = ConnectionTestStatus.MODEL_NOT_FOUND
            elif any(k in err_str for k in ("CONFIG", "URL", "SCHEME", "INVALID")):
                status = ConnectionTestStatus.INVALID_CONFIGURATION
            else:
                status = ConnectionTestStatus.UNAVAILABLE

            return ConnectionTestResult(
                status=status,
                provider_id=pid,
                model_id=model_id,
                error=sanitized_err,
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            sanitized = sanitize_secrets(str(e), secret=resolved_key)
            return ConnectionTestResult(
                status=ConnectionTestStatus.INVALID_CONFIGURATION if "INVALID" in sanitized.upper() else ConnectionTestStatus.UNAVAILABLE,
                provider_id=pid,
                model_id=model_id,
                error=sanitized,
                latency_ms=latency_ms,
            )


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
