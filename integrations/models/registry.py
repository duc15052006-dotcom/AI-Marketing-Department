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
import hashlib
import json
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
    - Rejects scheme-relative URLs ('//host/...') and percent-encoded host tricks.
    - Plain HTTP (http://) is strictly restricted to explicit loopback hosts:
      exactly 127.0.0.1, localhost (incl. subdomains of localhost), and ::1.
      0.0.0.0, [::], other 127/8 addresses and all private/link-local ranges
      are NOT accepted for plain HTTP.
    - Canonicalizes duplicate slashes and redundant trailing paths (/v1/v1, /chat/completions).
    """
    if url is None:
        return None
    cleaned = str(url).strip()
    if not cleaned:
        return None

    if cleaned.startswith("//"):
        raise ValueError("INVALID_URL_SCHEME: Scheme-relative URLs are not allowed.")

    if any(ch in cleaned for ch in ("\x00", "\n", "\r", "\t")):
        raise ValueError("INVALID_URL_CHARACTERS: Control characters are not allowed in URLs.")

    parsed = urllib.parse.urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"INVALID_URL_SCHEME: Unsupported scheme '{parsed.scheme}'. Base URL must use https:// or http:// loopback.")

    netloc = parsed.netloc or ""
    if "%" in netloc:
        raise ValueError("INVALID_URL_HOST: Percent-encoded host components are not allowed.")

    if parsed.username or parsed.password or "@" in netloc:
        raise ValueError("INVALID_URL_CREDENTIALS: Base URL must not contain embedded username or password.")

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise ValueError("INVALID_URL_HOST: Base URL host is missing or malformed.")
    if any(ch in hostname for ch in (" ", "\\", "/")):
        raise ValueError("INVALID_URL_HOST: Host contains illegal characters.")

    if scheme == "http":
        # Exact parsed-host semantics only (never substring matching).
        is_loopback = (
            hostname == "127.0.0.1"
            or hostname == "::1"
            or hostname == "localhost"
            or hostname.endswith(".localhost")
        )
        if not is_loopback:
            raise ValueError(
                f"INSECURE_HTTP_URL: Plain HTTP is restricted to explicit loopback hosts "
                f"(127.0.0.1, localhost, ::1). Found '{hostname}'."
            )

    # Canonicalize path: remove trailing /chat/completions or duplicate /v1/v1
    path = parsed.path or ""
    path = re.sub(r"/+", "/", path).rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")].rstrip("/")
    while path.endswith("/v1/v1"):
        path = path[:-3].rstrip("/")

    try:
        port = parsed.port
    except ValueError:
        raise ValueError("INVALID_URL_PORT: Base URL port is malformed.")

    port_str = f":{port}" if port else ""
    host_for_url = f"[{hostname}]" if ":" in hostname else hostname  # re-bracket IPv6
    return f"{scheme}://{host_for_url}{port_str}{path}"


# Adapter types that may actually be constructed by this registry.
SUPPORTED_ADAPTER_TYPES = {
    "OPENAI_COMPATIBLE",
    "OPENAI",
    "GEMINI_NATIVE",
    "GEMINI",
    "CUSTOM_INJECTED",
}

# Sane execution upper bound consistent with gateway budgeting behavior.
MAX_PROVIDER_TIMEOUT_SECONDS = 600.0

_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MODEL_ID_RE = re.compile(r"^[^\x00-\x1f\x7f\\]{1,200}$")


def validate_provider_id(provider_id: str) -> str:
    """Canonical provider-id grammar: lowercase alnum start, then alnum/-/_ ,
    max 64 chars. Rejects empty/whitespace-only values, path traversal,
    slashes/backslashes, control characters, ':' (secret-ref delimiter),
    and unreasonably long identifiers."""
    pid = str(provider_id or "").strip().lower()
    if not pid:
        raise ValueError("INVALID_PROVIDER_ID: provider_id cannot be empty.")
    if len(pid) > 64:
        raise ValueError("INVALID_PROVIDER_ID: provider_id exceeds maximum length of 64 characters.")
    if not _PROVIDER_ID_RE.fullmatch(pid):
        raise ValueError(
            "INVALID_PROVIDER_ID: provider_id must match ^[a-z0-9][a-z0-9_-]{0,63}$ "
            "(no slashes, dots, colons, spaces, traversal or control characters)."
        )
    return pid


def validate_adapter_type(adapter_type: str) -> str:
    val = str(adapter_type or "").strip().upper()
    if val not in SUPPORTED_ADAPTER_TYPES:
        raise ValueError(
            f"UNSUPPORTED_ADAPTER_TYPE: '{adapter_type}' is not a supported adapter type "
            f"(allowed: {', '.join(sorted(SUPPORTED_ADAPTER_TYPES))})."
        )
    return val


def validate_timeout_seconds(timeout_seconds) -> float:
    try:
        value = float(timeout_seconds)
    except Exception:
        raise ValueError(f"INVALID_TIMEOUT_SECONDS: timeout_seconds must be numeric, got '{timeout_seconds!r}'.")
    import math
    if not math.isfinite(value):
        raise ValueError("INVALID_TIMEOUT_SECONDS: timeout_seconds must be finite (no NaN/Infinity).")
    if value <= 0:
        raise ValueError("INVALID_TIMEOUT_SECONDS: timeout_seconds must be > 0.")
    if value > MAX_PROVIDER_TIMEOUT_SECONDS:
        raise ValueError(
            f"INVALID_TIMEOUT_SECONDS: timeout_seconds exceeds the maximum allowed "
            f"{MAX_PROVIDER_TIMEOUT_SECONDS} seconds."
        )
    return value


def validate_default_model(default_model: str) -> str:
    mid = str(default_model or "").strip()
    if not mid:
        raise ValueError("INVALID_MODEL_ID: model id cannot be empty.")
    if not _MODEL_ID_RE.fullmatch(mid):
        raise ValueError("INVALID_MODEL_ID: model id contains control characters or is pathologically sized.")
    return mid


def validate_chat_completions_path(path: Optional[str]) -> Optional[str]:
    """Must be a relative HTTP path appropriate to the base URL. Absolute URLs,
    alternate origins, schemes and backslashes are rejected so the value can
    never become a second SSRF URL authority."""
    if path is None:
        return None
    cleaned = str(path).strip()
    if not cleaned:
        return None
    if "://" in cleaned or cleaned.startswith("//"):
        raise ValueError("INVALID_CHAT_COMPLETIONS_PATH: absolute origins/schemes are not allowed.")
    if not cleaned.startswith("/"):
        raise ValueError("INVALID_CHAT_COMPLETIONS_PATH: path must start with '/'.")
    if "\\" in cleaned or any(ch in cleaned for ch in "\x00\r\n\t"):
        raise ValueError("INVALID_CHAT_COMPLETIONS_PATH: illegal characters in path.")
    if len(cleaned) > 256:
        raise ValueError("INVALID_CHAT_COMPLETIONS_PATH: path exceeds maximum length of 256 characters.")
    return cleaned


def normalize_cost_policy(value: Any) -> CostPolicy:
    """Normalize cost governance to the canonical enum and reject malformed values.

    Cost policy is a security/governance boundary. Unknown spellings or non-string
    values must never silently behave like a free provider under FREE_ONLY_MODE.
    """
    if isinstance(value, CostPolicy):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        try:
            return CostPolicy(normalized)
        except ValueError as exc:
            raise ValueError(
                f"INVALID_COST_POLICY: '{value}' is not one of "
                f"{', '.join(policy.value for policy in CostPolicy)}."
            ) from exc
    raise ValueError(
        f"INVALID_COST_POLICY: cost policy must be a CostPolicy or string, got {type(value).__name__}."
    )


# Security floor for built-ins already classified as paid by this repository.
# Older persisted settings may say FREE_TIER_ALLOWED; such stale values must not
# downgrade a paid provider. Providers not listed here may still be made more
# restrictive (PAID/UNKNOWN/DISABLED) by settings without being forced back free.
BUILTIN_PROVIDER_COST_POLICIES: Dict[str, CostPolicy] = {
    "openai": CostPolicy.PAID,
    "thespark": CostPolicy.PAID,
}


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
        # Validate machine provider ID (canonical grammar; traversal/secret-ref safe)
        self.provider_id = validate_provider_id(self.provider_id)

        # Default display name
        if not self.display_name:
            self.display_name = self.provider_id.capitalize()

        # Adapter type must be an actually supported type (no silent coercion).
        if self.adapter_type:
            self.adapter_type = validate_adapter_type(self.adapter_type)

        # Cost governance must be canonical and fail closed on malformed input.
        self.cost_policy = normalize_cost_policy(self.cost_policy)

        # Execution timeout must be numeric, finite, > 0 and within sane bounds.
        if self.timeout_seconds is not None:
            self.timeout_seconds = validate_timeout_seconds(self.timeout_seconds)

        # Model id: free-form but sane (no control chars, bounded size).
        self.default_model = validate_default_model(self.default_model)

        # OpenAI-compatible request path must stay relative to the base URL.
        if self.chat_completions_path:
            self.chat_completions_path = validate_chat_completions_path(self.chat_completions_path)

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

    def get_target_for_agent(self, agent_name: Optional[str] = None) -> ModelTarget:
        """Alias for resolve_target_for_agent."""
        return self.resolve_target_for_agent(agent_name)

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

    def __post_init__(self) -> None:
        super().__post_init__()
        self.provider_id = validate_provider_id(self.provider_id)
        self.model_id = validate_default_model(self.model_id)
        self.cost_tier = normalize_cost_policy(self.cost_tier)


class ProviderRegistry:
    """Registry managing provider configurations, custom adapters, and connection testing."""

    def __init__(self, secret_store: Optional[Any] = None) -> None:
        self._lock = threading.RLock()
        self._configs: Dict[str, ProviderDefinition] = {}
        self._adapters: Dict[str, BaseModelAdapter] = {}
        self._secrets: Dict[str, str] = {}
        self._injected_adapters: Dict[str, BaseModelAdapter] = {}
        self._secret_store = secret_store
        self._credential_usage_authority: Optional[Any] = None
        self._load_builtin_providers()

    def bind_secret_store(self, secret_store: Any) -> None:
        """Explicit dependency binding for the secure credential store.
        Replaces direct private-attribute mutation by collaborators."""
        with self._lock:
            self._secret_store = secret_store

    def set_credential_usage_authority(self, authority: Optional[Any]) -> None:
        """Register a callback(ref: str) -> bool answering whether an opaque
        credential_ref is still referenced by any active execution run.
        Used as the lifetime authority for credential version reclamation."""
        with self._lock:
            self._credential_usage_authority = authority

    def _is_credential_ref_active(self, credential_ref: str) -> bool:
        authority = getattr(self, "_credential_usage_authority", None)
        if authority is None:
            return False
        try:
            return bool(authority(credential_ref))
        except Exception:
            # Fail safe: if the authority errors, treat the ref as in-use so an
            # actively pinned credential is never prematurely reclaimed.
            return True

    def remove_provider_config(self, provider_id: str) -> bool:
        """Remove a provider's configuration and its LIVE cached adapter so new
        runs can no longer select it.

        Credential-version-pinned adapters are also purged; they are safely
        rebuildable while their pinned secret remains retained for active runs.
        Returns True if a configuration existed and was removed.
        """
        pid = provider_id.lower()
        with self._lock:
            existed = self._configs.pop(pid, None) is not None
            doomed = [k for k in self._adapters if k == pid or k.startswith(f"{pid}@")]
            for k in doomed:
                del self._adapters[k]
            self._drop_pinned_index_entries(doomed)
            if hasattr(self, "_injected_adapters"):
                self._injected_adapters.pop(pid, None)
            return existed

    def restore_provider_configs(self, providers_map: Dict[str, "ProviderDefinition"]) -> None:
        """Restore registry configuration to an exact prior committed snapshot
        (transaction rollback). Non-injected providers absent from the map are
        removed; all mapped definitions are (re)installed; live adapter cache
        entries for restored/removed pids are evicted so subsequent requests
        rebuild from the restored state. Injected DI adapters are preserved.
        """
        with self._lock:
            injected = getattr(self, "_injected_adapters", {}) or {}
            for pid in [p for p in list(self._configs.keys()) if p not in providers_map]:
                if pid in injected:
                    continue
                del self._configs[pid]
                doomed = [k for k in self._adapters if k == pid or k.startswith(f"{pid}@")]
                for k in doomed:
                    del self._adapters[k]
                self._drop_pinned_index_entries(doomed)
            for pid, pdef in providers_map.items():
                if pid in injected:
                    continue
                self._configs[pid] = ProviderDefinition(**pdef.model_dump()) if not isinstance(pdef, ProviderDefinition) else pdef
                self._adapters.pop(pid, None)

    def reconcile_provider_configs(self, valid_provider_ids: set) -> None:
        """Reconcile registry configuration to the complete committed Settings
        state: provider configs (and their adapters) absent from the authoritative
        settings are removed. Explicitly injected DI adapters and their
        auto-registered config entries are preserved per the generic DI contract.
        """
        with self._lock:
            injected = getattr(self, "_injected_adapters", {}) or {}
            for pid in [p for p in list(self._configs.keys()) if p not in valid_provider_ids]:
                if pid in injected:
                    continue
                del self._configs[pid]
                doomed = [k for k in self._adapters if k == pid or k.startswith(f"{pid}@")]
                for k in doomed:
                    del self._adapters[k]
                self._drop_pinned_index_entries(doomed)
                self._injected_adapters.pop(pid, None)

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

        # 4. TheSpark (policy-classified paid third-party provider)
        self.register_provider(
            ProviderDefinition(
                provider_id="thespark",
                adapter_type="OPENAI_COMPATIBLE",
                display_name="TheSpark",
                base_url="https://api.thespark.io/v1",
                credential_ref="ENV:THESPARK_API_KEY",
                default_model="spark-default",
                cost_policy=CostPolicy.PAID,
                supported_capabilities={"supports_json": True, "provider_type": "third_party"},
            )
        )

    def register_provider(self, config: Union[ProviderDefinition, ProviderConfig], secret: Optional[str] = None) -> None:
        """Register or update a provider configuration atomically."""
        if isinstance(config, dict):
            config = ProviderDefinition(**config)
        pid = config.provider_id.lower()
        authoritative_cost = BUILTIN_PROVIDER_COST_POLICIES.get(pid)
        if authoritative_cost is not None and config.cost_policy != authoritative_cost:
            logger.warning(
                "Overriding stale/mismatched built-in cost policy for '%s': %s -> %s",
                pid,
                getattr(config.cost_policy, "value", config.cost_policy),
                authoritative_cost.value,
            )
            # Mutate the canonical definition so callers holding a persisted
            # settings object also observe the corrected governance value.
            config.cost_policy = authoritative_cost
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

    def evict_adapter(self, provider_id: str) -> None:
        """Evict the LIVE cached adapter for a provider, forcing re-instantiation
        with updated credentials/config.

        Deliberately does NOT purge credential-version-pinned adapters
        ('<pid>@<credential_ref>' keys) so active runs may continue resolving
        their run-start credential version. Use purge_provider_adapters() when
        the provider (and all its credential versions) is being removed.
        """
        pid = provider_id.lower()
        with self._lock:
            self._adapters.pop(pid, None)
            if hasattr(self, "_injected_adapters"):
                self._injected_adapters.pop(pid, None)

    def purge_provider_adapters(self, provider_id: str) -> None:
        """Purge ALL cached adapters for a provider: the live entry plus every
        pinned entry. Used on provider deletion."""
        pid = provider_id.lower()
        with self._lock:
            doomed = [k for k in self._adapters if k == pid or k.startswith(f"{pid}@")]
            for k in doomed:
                del self._adapters[k]
            self._drop_pinned_index_entries(doomed)
            if hasattr(self, "_injected_adapters"):
                self._injected_adapters.pop(pid, None)

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
        """Resolve API credential from secret storage, vault, or environment reference."""
        pid = cfg.provider_id.lower()
        if pid in self._secrets and self._secrets[pid]:
            return self._secrets[pid]
        ref = cfg.credential_ref or ""
        if ref:
            from integrations.models.secret_store import GLOBAL_SECRET_STORE
            store = getattr(self, "_secret_store", None) or GLOBAL_SECRET_STORE
            secret = store.get_secret(ref)
            if secret:
                return secret
        if cfg.api_key_env:
            return os.environ.get(cfg.api_key_env)
        return None

    def _build_adapter(self, cfg: ProviderDefinition, secret: Optional[str]) -> BaseModelAdapter:
        """Instantiate the correct adapter for a provider definition."""
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
            raise ValueError(f"UNSUPPORTED_ADAPTER_TYPE: '{cfg.adapter_type}' for provider '{cfg.provider_id.lower()}'.")
        return adapter

    def get_adapter(self, provider_id: str, include_disabled: bool = False) -> Optional[BaseModelAdapter]:
        """Retrieve or create adapter instance for given provider ID (live config)."""
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
            adapter = self._build_adapter(cfg, secret)

            self._adapters[pid] = adapter
            return adapter

    @staticmethod
    def _execution_fingerprint(cfg: ProviderDefinition) -> str:
        """Deterministic SHA-256 fingerprint of the SAFE execution-influencing
        ProviderDefinition fields. Contains no secret material (credential_ref
        is an opaque non-secret handle; api keys are never part of identity)."""
        payload = json.dumps({
            "provider_id": cfg.provider_id.lower(),
            "adapter_type": str(cfg.adapter_type).upper(),
            "base_url": cfg.base_url or "",
            "credential_ref": cfg.credential_ref or "",
            "default_model": cfg.default_model or "",
            "chat_completions_path": cfg.chat_completions_path or "",
            "timeout_seconds": float(cfg.timeout_seconds or 0.0),
            "cost_policy": str(getattr(cfg.cost_policy, "value", cfg.cost_policy)),
            "supported_capabilities": sorted((cfg.supported_capabilities or {}).items()),
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_pinned_adapter(self, cfg: ProviderDefinition) -> Optional[BaseModelAdapter]:
        """Retrieve or create an adapter PINNED to an exact provider definition.

        Used when executing under a run-scoped ProviderRegistrySnapshot: the
        cache key is provider_id + SHA-256 fingerprint over the complete safe
        execution configuration (endpoint, path, model, timeout, cost policy,
        credential version), so neither key rotation nor any other config
        mutation can alias one run's adapter onto another run's definition.
        No secret values ever appear in cache keys or the pin index.
        """
        pid = cfg.provider_id.lower()
        with self._lock:
            if pid in getattr(self, "_injected_adapters", {}):
                return self._injected_adapters[pid]

            fingerprint = self._execution_fingerprint(cfg)
            cache_key = f"{pid}@{fingerprint}"
            if cache_key in self._adapters:
                return self._adapters[cache_key]

            secret = self._resolve_secret(cfg)
            if not secret:
                # A pinned adapter cannot be constructed without its pinned
                # credential (e.g. reclaimed after run termination).
                return None
            adapter = self._build_adapter(cfg, secret)

            self._adapters[cache_key] = adapter
            # Pin index: credential_ref -> cache keys, enabling reclamation
            # eviction without depending on the key format itself.
            ref = cfg.credential_ref or ""
            if ref:
                index = getattr(self, "_pinned_adapter_index", None)
                if index is None:
                    index = {}
                    self._pinned_adapter_index = index
                index.setdefault(ref, set()).add(cache_key)
            return adapter

    def _drop_pinned_index_entries(self, cache_keys) -> None:
        index = getattr(self, "_pinned_adapter_index", None)
        if not index:
            return
        removed = set(cache_keys)
        for ref in list(index.keys()):
            remaining = index[ref] - removed
            if remaining:
                index[ref] = remaining
            else:
                del index[ref]

    def evict_pinned_adapter(self, credential_ref: str) -> None:
        """Evict cached adapters PINNED to a specific opaque credential_ref
        (across providers), e.g. after that credential version was reclaimed.
        Uses the pin index; independent of cache-key format."""
        if not credential_ref:
            return
        with self._lock:
            index = getattr(self, "_pinned_adapter_index", None)
            keys = list(index.get(credential_ref, set())) if index else []
            # Fallback scan for legacy entries created before the index existed.
            if not keys:
                suffix = f"@{credential_ref}"
                keys = [k for k in self._adapters if k.endswith(suffix)]
            for k in keys:
                self._adapters.pop(k, None)
            if index:
                index.pop(credential_ref, None)

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
                display_name="TheSpark Default",
                context_window=32000,
                cost_tier=CostPolicy.PAID,
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
