"""Provider Configuration Service (ProviderConfigService).

Single source of truth for all LLM provider configurations, credentials,
endpoints, and sanitized health diagnostics across the AI Marketing Department runtime.

Guarantees:
- Deterministic production configuration root resolution (OS app data, explicit path, or project root)
- Secure credential management (zero secret exposure in logs, APIs, or UI)
- Sourcing from Windows User Environment (HKCU\\Environment), app config, and OS environment
- Standardized error classification
- Zero Five-Agent Brain DNA modification
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("provider_config_service")


class ProviderErrorCode(str, Enum):
    """Standardized error categories for model provider interactions."""
    NO_CREDENTIAL = "NO_CREDENTIAL"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    AUTH_401 = "AUTH_401"
    PERMISSION_403 = "PERMISSION_403"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    RATE_LIMIT_429 = "RATE_LIMIT_429"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    NO_AVAILABLE_PROVIDER = "NO_AVAILABLE_PROVIDER"
    STALE_BACKEND = "STALE_BACKEND"
    OTHER = "OTHER"


@dataclass
class ResolvedProviderConfig:
    """Resolved, validated configuration for a single provider."""
    provider_id: str
    enabled: bool = True
    base_url: Optional[str] = None
    default_model: str = ""
    api_key: Optional[str] = None  # Internal use only — NEVER serialized or logged
    timeout_seconds: float = 30.0
    cost_policy: str = "FREE_TIER_ALLOWED"
    last_error_category: Optional[ProviderErrorCode] = None

    @property
    def has_credential(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 0)

    @property
    def is_configured(self) -> bool:
        return self.enabled and self.has_credential and bool(self.default_model)


class ProviderConfigService:
    """Central configuration service and single source of truth for all LLM providers."""

    APP_BACKEND_VERSION = "1.0.0"
    BUILD_ID = "20260820-RELEASE-V1"

    def __init__(self, config_dir: Optional[str] = None, override_env: Optional[Dict[str, str]] = None) -> None:
        self._config_dir = self._resolve_config_dir(config_dir)
        self._override_env = override_env or {}
        self._providers: Dict[str, ResolvedProviderConfig] = {}
        self._bootstrap_environment()
        self._load_provider_configurations()

    def _resolve_config_dir(self, explicit_dir: Optional[str]) -> Path:
        """Resolve deterministic configuration directory.

        Priority:
        1. Explicitly supplied path / CLI argument
        2. AI_MARKETING_CONFIG_DIR environment variable
        3. Windows AppData / OS user configuration directory
        4. Application root directory fallback
        """
        if explicit_dir and os.path.exists(explicit_dir):
            return Path(explicit_dir).resolve()

        env_dir = os.environ.get("AI_MARKETING_CONFIG_DIR")
        if env_dir and os.path.exists(env_dir):
            return Path(env_dir).resolve()

        # Windows AppData / LocalAppData
        app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if app_data:
            prod_dir = Path(app_data) / "AI-Marketing-Department"
            try:
                prod_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            return prod_dir

        # Application root fallback
        return Path(__file__).resolve().parent.parent.parent

    def _bootstrap_environment(self) -> None:
        """Bootstrap environment variables from Windows registry, config files, and .env."""
        # 1. Windows HKCU\Environment (Active user credentials on Windows)
        if sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                    idx = 0
                    while True:
                        try:
                            name, val, _ = winreg.EnumValue(key, idx)
                            if name not in os.environ and val:
                                os.environ[name] = str(val)
                            idx += 1
                        except OSError:
                            break
            except Exception as e:
                logger.debug(f"Windows registry bootstrap note: {e}")

        # 2. Config file in config_dir (ai_marketing_config.json)
        cfg_file = self._config_dir / "ai_marketing_config.json"
        if cfg_file.is_file():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.get("environment", {}).items():
                        if k not in os.environ:
                            os.environ[k] = str(v)
            except Exception as e:
                logger.debug(f"Config file read note: {e}")

        # 3. Development .env fallback (managed via single ConfigurationAuthority)
        from config.authority import get_runtime_config
        try:
            get_runtime_config()
        except Exception as e:
            logger.debug(f"ConfigurationAuthority bootstrap note: {e}")

    def _get_env_val(self, key: str) -> Optional[str]:
        """Retrieve key value prioritizing overrides then OS environment."""
        if key in self._override_env:
            return self._override_env[key]
        return os.environ.get(key)

    def _load_provider_configurations(self) -> None:
        """Construct the resolved provider configurations."""
        from config.authority import get_runtime_config
        runtime = get_runtime_config()

        # 1. xKiro
        xkiro_key = self._get_env_val("XKIRO_API_KEY")
        self._providers["xkiro"] = ResolvedProviderConfig(
            provider_id="xkiro",
            enabled=True,
            base_url=self._get_env_val("XKIRO_BASE_URL") or runtime.xkiro_base_url,
            default_model=self._get_env_val("XKIRO_MODEL") or runtime.xkiro_model,
            api_key=xkiro_key,
            timeout_seconds=float(self._get_env_val("XKIRO_TIMEOUT") or runtime.xkiro_timeout),
            cost_policy="FREE_TIER_ALLOWED",
        )

        # 2. Google Gemini
        gemini_key = self._get_env_val("GEMINI_API_KEY") or self._get_env_val("GOOGLE_API_KEY")
        self._providers["gemini"] = ResolvedProviderConfig(
            provider_id="gemini",
            enabled=True,
            base_url=None,  # Google native SDK
            default_model=self._get_env_val("GEMINI_MODEL") or "gemini-flash-latest",
            api_key=gemini_key,
            timeout_seconds=float(self._get_env_val("GEMINI_TIMEOUT") or "30.0"),
            cost_policy="FREE_TIER_ALLOWED",
        )

        # 3. TheSpark
        thespark_key = self._get_env_val("THESPARK_API_KEY")
        self._providers["thespark"] = ResolvedProviderConfig(
            provider_id="thespark",
            enabled=True,
            base_url=self._get_env_val("THESPARK_BASE_URL") or runtime.thespark_base_url,
            default_model=self._get_env_val("THESPARK_MODEL") or runtime.thespark_model,
            api_key=thespark_key,
            timeout_seconds=float(self._get_env_val("THESPARK_TIMEOUT") or runtime.thespark_timeout),
            cost_policy="FREE_TIER_ALLOWED",
        )

        # 4. OpenAI
        openai_key = self._get_env_val("OPENAI_API_KEY")
        self._providers["openai"] = ResolvedProviderConfig(
            provider_id="openai",
            enabled=True,
            base_url=self._get_env_val("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            default_model=self._get_env_val("OPENAI_MODEL") or "gpt-4o-mini",
            api_key=openai_key,
            timeout_seconds=float(self._get_env_val("OPENAI_TIMEOUT") or "60.0"),
            cost_policy="PAID",
        )

    # =========================================================================
    # Public Accessors & Sanitized Health Reporting
    # =========================================================================

    def get_provider(self, provider_id: str) -> Optional[ResolvedProviderConfig]:
        """Get resolved provider configuration."""
        return self._providers.get(provider_id.lower())

    def is_provider_enabled(self, provider_id: str) -> bool:
        cfg = self.get_provider(provider_id)
        return bool(cfg and cfg.enabled)

    def has_credential(self, provider_id: str) -> bool:
        """Check if credential is present without revealing it."""
        cfg = self.get_provider(provider_id)
        return bool(cfg and cfg.has_credential)

    def get_credential(self, provider_id: str) -> Optional[str]:
        """Internal adapter access only — NEVER expose externally."""
        cfg = self.get_provider(provider_id)
        return cfg.api_key if cfg else None

    def get_base_url(self, provider_id: str) -> Optional[str]:
        cfg = self.get_provider(provider_id)
        return cfg.base_url if cfg else None

    def get_default_model(self, provider_id: str) -> str:
        cfg = self.get_provider(provider_id)
        return cfg.default_model if cfg else ""

    def get_timeout(self, provider_id: str) -> float:
        cfg = self.get_provider(provider_id)
        return cfg.timeout_seconds if cfg else 60.0

    def record_error(self, provider_id: str, error_code: ProviderErrorCode) -> None:
        """Record last error category for a provider."""
        cfg = self.get_provider(provider_id)
        if cfg:
            cfg.last_error_category = error_code

    def get_sanitized_health_report(self) -> List[Dict[str, Any]]:
        """Generate sanitized provider status report for HTTP API (0 secrets)."""
        report = []
        for pid, cfg in self._providers.items():
            health_val = "AVAILABLE" if cfg.is_configured else ("NO_CREDENTIAL" if not cfg.has_credential else "DISABLED")
            report.append({
                "provider": pid,
                "enabled": cfg.enabled,
                "credential_present": cfg.has_credential,
                "configured": cfg.is_configured,
                "health": health_val,
                "model": cfg.default_model,
                "cost_policy": cfg.cost_policy,
                "last_error_category": cfg.last_error_category.value if cfg.last_error_category else None,
            })
        return report

    def get_boot_diagnostics(self) -> Dict[str, Any]:
        """Generate sanitized boot diagnostics."""
        diag = {
            "app_backend_version": self.APP_BACKEND_VERSION,
            "build_id": self.BUILD_ID,
            "config_root_resolved": str(self._config_dir),
            "providers": {},
        }
        for pid, cfg in self._providers.items():
            diag["providers"][pid] = {
                "registered": True,
                "enabled": cfg.enabled,
                "credential_present": cfg.has_credential,
                "model_present": bool(cfg.default_model),
                "endpoint_present": bool(cfg.base_url) or (pid == "gemini"),
            }
        return diag


# Global singleton instance
GLOBAL_PROVIDER_CONFIG = ProviderConfigService()
