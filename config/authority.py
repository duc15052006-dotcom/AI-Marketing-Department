"""Runtime Configuration Authority & Immutable Snapshot (PROD-CONFIG-01 / PROD-CONFIG-01R).

Provides an immutable, validated snapshot of runtime configuration settings
with complete provenance tracking and safe diagnostic exposure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

from config.env_loader import (
    CONFIG_RELOAD_REQUIRES_RESTART,
    ConfigSource,
    KNOWN_SECRET_ENV_KEYS,
    REPO_ROOT,
    load_env_file,
    parse_bool,
    parse_env_file,
    parse_float,
    parse_int,
    redact_secret_value,
    sanitize_config_dict,
    validate_loopback_host,
)


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    """Immutable, validated runtime configuration snapshot with provenance tracking."""

    api_host: str = "127.0.0.1"
    api_port: int = 8765
    environment: str = "development"
    autonomy_mode: str = "SUPERVISED"
    free_only_mode: bool = True
    default_provider: str = "gemini"
    max_auto_budget_usd: float = 100.0
    max_daily_budget_change_pct: float = 15.0
    department_db_path: str = "chat_sessions.db"
    searxng_base_url: str = "http://127.0.0.1:8080"
    xkiro_base_url: str = "https://api.xkiro.com/v1"
    xkiro_model: str = "mistralai/mistral-large-2512"
    xkiro_timeout: float = 30.0
    thespark_base_url: str = "https://api.thespark.io/v1"
    thespark_model: str = "thespark-v1"
    thespark_timeout: float = 30.0
    verifier_python_executable: str = ""
    verifier_worker_startup_timeout_s: float = 20.0
    verifier_claim_timeout_s: float = 30.0
    verifier_gate_timeout_s: float = 120.0
    verifier_max_claim_chars: int = 4000
    verifier_max_evidence_chars: int = 24000
    verifier_ipc_frame_limit_bytes: int = 1048576
    verifier_max_claims_per_gate: int = 64
    verifier_model_network_mode: str = "LOCAL_ONLY"
    verifier_cache_root: str = ""
    verifier_manifest_required: bool = True
    # PROD-VERIFIER-02E CERTIFIED BASELINE (real-model acceptance 02E):
    # frozen from the actual isolated-worker acceptance run. Production
    # handshakes are validated against this map; mismatch fails closed.
    verifier_expected_dependency_versions: str = (
        '{"torch": "2.13.0+cpu", "transformers": "4.57.6", "numpy": "2.5.2", '
        '"huggingface_hub": "0.36.2", "tokenizers": "0.22.2", "safetensors": "0.8.0"}'
    )
    repo_root: Path = REPO_ROOT
    secrets_configured: Dict[str, str] = field(default_factory=dict)
    provenance: Dict[str, ConfigSource] = field(default_factory=dict)

    def to_diagnostics_dict(self) -> Dict[str, Any]:
        """Expose safe diagnostics dictionary derived strictly from immutable snapshot."""
        return {
            "api_host": self.api_host,
            "api_port": self.api_port,
            "environment": self.environment,
            "autonomy_mode": self.autonomy_mode,
            "free_only_mode": self.free_only_mode,
            "default_provider": self.default_provider,
            "max_auto_budget_usd": self.max_auto_budget_usd,
            "max_daily_budget_change_pct": self.max_daily_budget_change_pct,
            "department_db_path": self.department_db_path,
            "searxng_base_url": self.searxng_base_url,
            "xkiro_base_url": self.xkiro_base_url,
            "xkiro_model": self.xkiro_model,
            "xkiro_timeout": self.xkiro_timeout,
            "thespark_base_url": self.thespark_base_url,
            "thespark_model": self.thespark_model,
            "thespark_timeout": self.thespark_timeout,
            "verifier_python_configured": bool(self.verifier_python_executable),
            "verifier_worker_startup_timeout_s": self.verifier_worker_startup_timeout_s,
            "verifier_claim_timeout_s": self.verifier_claim_timeout_s,
            "verifier_gate_timeout_s": self.verifier_gate_timeout_s,
            "verifier_max_claim_chars": self.verifier_max_claim_chars,
            "verifier_max_evidence_chars": self.verifier_max_evidence_chars,
            "verifier_ipc_frame_limit_bytes": self.verifier_ipc_frame_limit_bytes,
            "verifier_max_claims_per_gate": self.verifier_max_claims_per_gate,
            "verifier_model_network_mode": self.verifier_model_network_mode,
            "verifier_cache_root_configured": bool(self.verifier_cache_root),
            "verifier_manifest_required": self.verifier_manifest_required,
            "verifier_expected_dependency_versions_configured": bool(self.verifier_expected_dependency_versions),
            "repo_root": str(self.repo_root),
            "secrets_configured": dict(self.secrets_configured),
            "provenance": {k: v.value for k, v in self.provenance.items()},
        }


class ConfigurationAuthority:
    """Central authority for resolving, validating, and snapshotting system configuration."""

    _instance: Optional[ConfigurationAuthority] = None
    _snapshot: Optional[RuntimeConfigSnapshot] = None

    @classmethod
    def get_instance(
        cls,
        env_file_path: Optional[Path] = None,
        explicit_overrides: Optional[Dict[str, Any]] = None,
    ) -> ConfigurationAuthority:
        if cls._instance is None:
            cls._instance = ConfigurationAuthority(
                env_file_path=env_file_path,
                explicit_overrides=explicit_overrides,
            )
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (used in testing)."""
        cls._instance = None
        cls._snapshot = None

    def __init__(
        self,
        env_file_path: Optional[Path] = None,
        explicit_overrides: Optional[Dict[str, Any]] = None,
        auto_load: bool = True,
    ) -> None:
        self._env_file_path = env_file_path or (REPO_ROOT / ".env")
        self._explicit_overrides = dict(explicit_overrides or {})
        self._process_env_at_boot: Dict[str, str] = dict(os.environ)
        self._parsed_env_file: Dict[str, str] = {}
        if ConfigurationAuthority._instance is None:
            ConfigurationAuthority._instance = self
        if auto_load:
            self._load_and_initialize()

    def _load_and_initialize(self) -> None:
        """Load .env without overwriting existing process env, then build snapshot."""
        # 1. Parse .env file without mutating process env yet
        self._parsed_env_file = parse_env_file(self._env_file_path)

        # 2. Build immutable snapshot with exact provenance
        self._snapshot = self._build_snapshot()
        ConfigurationAuthority._snapshot = self._snapshot

        # 3. Populate missing keys in os.environ for backwards compatibility with low-level libraries
        for k, v in self._parsed_env_file.items():
            if k not in os.environ:
                os.environ[k] = v

    def _get_with_provenance(
        self,
        key: str,
        default: Any,
        alias_key: Optional[str] = None,
    ) -> Tuple[Any, ConfigSource]:
        """Retrieve key value with strict provenance attribution and alias support."""
        # 1. Explicit override check
        if key in self._explicit_overrides:
            return self._explicit_overrides[key], ConfigSource.EXPLICIT
        if alias_key and alias_key in self._explicit_overrides:
            return self._explicit_overrides[alias_key], ConfigSource.EXPLICIT

        # 2. Process environment check (captured at boot)
        if key in self._process_env_at_boot:
            return self._process_env_at_boot[key], ConfigSource.PROCESS_ENV
        if alias_key and alias_key in self._process_env_at_boot:
            return self._process_env_at_boot[alias_key], ConfigSource.PROCESS_ENV

        # 3. .env file check
        if key in self._parsed_env_file:
            return self._parsed_env_file[key], ConfigSource.ENV_FILE
        if alias_key and alias_key in self._parsed_env_file:
            return self._parsed_env_file[alias_key], ConfigSource.ENV_FILE

        # 4. Code default
        return default, ConfigSource.DEFAULT

    def _build_snapshot(self) -> RuntimeConfigSnapshot:
        """Build validated immutable RuntimeConfigSnapshot."""
        prov: Dict[str, ConfigSource] = {}

        # 1. API Host
        raw_host, prov["API_HOST"] = self._get_with_provenance("API_HOST", "127.0.0.1")
        api_host = validate_loopback_host(str(raw_host), setting_name="API_HOST")

        # 2. API Port
        raw_port, prov["API_PORT"] = self._get_with_provenance("API_PORT", 8765)
        api_port = parse_int(raw_port, default=8765, min_val=1, max_val=65535, setting_name="API_PORT")

        # 3. Environment
        raw_env, prov["APP_ENV"] = self._get_with_provenance("APP_ENV", "development")
        environment = str(raw_env).strip()

        # 4. Autonomy Mode
        raw_autonomy, prov["AUTONOMY_MODE"] = self._get_with_provenance("AUTONOMY_MODE", "SUPERVISED")
        autonomy_mode = str(raw_autonomy).strip().upper()

        # 5. Free Only Mode
        raw_free, prov["FREE_ONLY_MODE"] = self._get_with_provenance("FREE_ONLY_MODE", True)
        free_only_mode = parse_bool(raw_free, default=True, setting_name="FREE_ONLY_MODE")

        # 6. Default Provider
        raw_provider, prov["DEFAULT_PROVIDER"] = self._get_with_provenance("DEFAULT_PROVIDER", "gemini")
        default_provider = str(raw_provider).strip().lower()

        # 7. Budgets
        raw_budget, prov["MAX_AUTO_BUDGET_USD"] = self._get_with_provenance("MAX_AUTO_BUDGET_USD", 100.0)
        max_budget = parse_float(raw_budget, default=100.0, min_val=0.0, max_val=1000000.0, setting_name="MAX_AUTO_BUDGET_USD")

        raw_pct, prov["MAX_DAILY_BUDGET_CHANGE_PCT"] = self._get_with_provenance("MAX_DAILY_BUDGET_CHANGE_PCT", 15.0)
        max_pct = parse_float(raw_pct, default=15.0, min_val=0.0, max_val=100.0, setting_name="MAX_DAILY_BUDGET_CHANGE_PCT")

        # 8. Database Path & Integrations
        raw_db, prov["DEPARTMENT_DB_PATH"] = self._get_with_provenance("DEPARTMENT_DB_PATH", "chat_sessions.db")
        department_db_path = str(raw_db).strip()

        raw_searxng, prov["SEARXNG_BASE_URL"] = self._get_with_provenance("SEARXNG_BASE_URL", "http://127.0.0.1:8080")
        searxng_base_url = str(raw_searxng).strip()

        # 9. XKiro Config
        raw_xkiro_url, prov["XKIRO_BASE_URL"] = self._get_with_provenance("XKIRO_BASE_URL", "https://api.xkiro.com/v1")
        xkiro_base_url = str(raw_xkiro_url).strip()

        raw_xkiro_model, prov["XKIRO_MODEL"] = self._get_with_provenance("XKIRO_MODEL", "mistralai/mistral-large-2512")
        xkiro_model = str(raw_xkiro_model).strip()

        raw_xkiro_timeout, prov["XKIRO_TIMEOUT"] = self._get_with_provenance("XKIRO_TIMEOUT", 30.0)
        xkiro_timeout = parse_float(raw_xkiro_timeout, default=30.0, min_val=0.1, setting_name="XKIRO_TIMEOUT")

        # 10. TheSpark Config
        raw_spark_url, prov["THESPARK_BASE_URL"] = self._get_with_provenance("THESPARK_BASE_URL", "https://api.thespark.io/v1")
        thespark_base_url = str(raw_spark_url).strip()

        raw_spark_model, prov["THESPARK_MODEL"] = self._get_with_provenance("THESPARK_MODEL", "thespark-v1")
        thespark_model = str(raw_spark_model).strip()

        raw_spark_timeout, prov["THESPARK_TIMEOUT"] = self._get_with_provenance("THESPARK_TIMEOUT", 30.0)
        thespark_timeout = parse_float(raw_spark_timeout, default=30.0, min_val=0.1, setting_name="THESPARK_TIMEOUT")

        # 11. Verifier Worker Interpreter (isolated NLI sidecar boundary)
        raw_vpy, prov["VERIFIER_PYTHON_EXECUTABLE"] = self._get_with_provenance("VERIFIER_PYTHON_EXECUTABLE", "")
        verifier_python_executable = str(raw_vpy).strip()

        # 11b. Verifier deadline & resource authority (all finite, >0, bounded).
        raw_vstart, prov["VERIFIER_WORKER_STARTUP_TIMEOUT_S"] = self._get_with_provenance("VERIFIER_WORKER_STARTUP_TIMEOUT_S", 20.0)
        verifier_worker_startup_timeout_s = parse_float(raw_vstart, default=20.0, min_val=0.5, max_val=120.0, setting_name="VERIFIER_WORKER_STARTUP_TIMEOUT_S")

        raw_vclaim, prov["VERIFIER_CLAIM_TIMEOUT_S"] = self._get_with_provenance("VERIFIER_CLAIM_TIMEOUT_S", 30.0)
        verifier_claim_timeout_s = parse_float(raw_vclaim, default=30.0, min_val=0.5, max_val=300.0, setting_name="VERIFIER_CLAIM_TIMEOUT_S")

        raw_vgate, prov["VERIFIER_GATE_TIMEOUT_S"] = self._get_with_provenance("VERIFIER_GATE_TIMEOUT_S", 120.0)
        verifier_gate_timeout_s = parse_float(raw_vgate, default=120.0, min_val=1.0, max_val=600.0, setting_name="VERIFIER_GATE_TIMEOUT_S")

        raw_vcc, prov["VERIFIER_MAX_CLAIM_CHARS"] = self._get_with_provenance("VERIFIER_MAX_CLAIM_CHARS", 4000)
        from .env_loader import parse_int as _parse_int
        verifier_max_claim_chars = _parse_int(raw_vcc, default=4000, min_val=64, max_val=100000, setting_name="VERIFIER_MAX_CLAIM_CHARS")

        raw_vec, prov["VERIFIER_MAX_EVIDENCE_CHARS"] = self._get_with_provenance("VERIFIER_MAX_EVIDENCE_CHARS", 24000)
        verifier_max_evidence_chars = _parse_int(raw_vec, default=24000, min_val=256, max_val=500000, setting_name="VERIFIER_MAX_EVIDENCE_CHARS")

        raw_vframe, prov["VERIFIER_IPC_FRAME_LIMIT_BYTES"] = self._get_with_provenance("VERIFIER_IPC_FRAME_LIMIT_BYTES", 1048576)
        verifier_ipc_frame_limit_bytes = _parse_int(raw_vframe, default=1048576, min_val=4096, max_val=16777216, setting_name="VERIFIER_IPC_FRAME_LIMIT_BYTES")

        raw_vmc, prov["VERIFIER_MAX_CLAIMS_PER_GATE"] = self._get_with_provenance("VERIFIER_MAX_CLAIMS_PER_GATE", 64)
        verifier_max_claims_per_gate = _parse_int(raw_vmc, default=64, min_val=1, max_val=1024, setting_name="VERIFIER_MAX_CLAIMS_PER_GATE")

        # 11c. Verifier supply-chain authority (PROD-VERIFIER-02D / 02F-R2).
        # Normal production verification is IMMUTABLY:
        #   network_mode=LOCAL_ONLY + manifest REQUIRED + hash verified +
        #   safetensors-only. Configuration may never weaken these.
        # Provisioning (model download) exists ONLY as the explicit out-of-band
        # command `python -m runtime.verifier_worker.provision` and MUST NOT be
        # selected through normal runtime configuration -> fail closed loudly
        # instead of silently coercing (operator error must stay visible).
        raw_vnet, prov["VERIFIER_MODEL_NETWORK_MODE"] = self._get_with_provenance("VERIFIER_MODEL_NETWORK_MODE", "LOCAL_ONLY")
        verifier_model_network_mode = str(raw_vnet).strip().upper()
        if verifier_model_network_mode != "LOCAL_ONLY":
            raise ValueError(
                f"INSECURE_VERIFIER_NETWORK_MODE: VERIFIER_MODEL_NETWORK_MODE "
                f"must be 'LOCAL_ONLY' for the normal production verifier "
                f"(got '{verifier_model_network_mode}'). Provisioning is a "
                f"separate explicit command "
                f"(python -m runtime.verifier_worker.provision) and cannot be "
                f"selected through configuration.")

        raw_vcroot, prov["VERIFIER_CACHE_ROOT"] = self._get_with_provenance("VERIFIER_CACHE_ROOT", "")
        verifier_cache_root = str(raw_vcroot).strip()

        raw_vman, prov["VERIFIER_MANIFEST_REQUIRED"] = self._get_with_provenance("VERIFIER_MANIFEST_REQUIRED", True)
        from .env_loader import parse_bool as _parse_bool
        verifier_manifest_required = _parse_bool(raw_vman, default=True, setting_name="VERIFIER_MANIFEST_REQUIRED")
        # No silent coercion: an explicitly insecure override fails closed.
        if not verifier_manifest_required:
            raise ValueError(
                "INSECURE_VERIFIER_CONFIGURATION: VERIFIER_MANIFEST_REQUIRED="
                "false is forbidden; production claim verification is ALWAYS "
                "integrity-manifest hash verified. Remove this override.")

        raw_vdeps, prov["VERIFIER_EXPECTED_DEPENDENCY_VERSIONS"] = self._get_with_provenance("VERIFIER_EXPECTED_DEPENDENCY_VERSIONS", "")
        verifier_expected_dependency_versions = str(raw_vdeps).strip()

        # 12. Safe Secret Presence Status (Frozen at boot)
        raw_openai, _ = self._get_with_provenance("OPENAI_API_KEY", "")
        raw_anthropic, _ = self._get_with_provenance("ANTHROPIC_API_KEY", "")
        raw_gemini, _ = self._get_with_provenance("GEMINI_API_KEY", "", alias_key="GOOGLE_API_KEY")
        raw_xkiro, _ = self._get_with_provenance("XKIRO_API_KEY", "")
        raw_spark, _ = self._get_with_provenance("THESPARK_API_KEY", "")
        raw_reddit, _ = self._get_with_provenance("REDDIT_CLIENT_SECRET", "")

        secrets_configured = {
            "openai": redact_secret_value(raw_openai),
            "anthropic": redact_secret_value(raw_anthropic),
            "gemini": redact_secret_value(raw_gemini),
            "xkiro": redact_secret_value(raw_xkiro),
            "thespark": redact_secret_value(raw_spark),
            "reddit": redact_secret_value(raw_reddit),
        }

        return RuntimeConfigSnapshot(
            api_host=api_host,
            api_port=api_port,
            environment=environment,
            autonomy_mode=autonomy_mode,
            free_only_mode=free_only_mode,
            default_provider=default_provider,
            max_auto_budget_usd=max_budget,
            max_daily_budget_change_pct=max_pct,
            department_db_path=department_db_path,
            searxng_base_url=searxng_base_url,
            xkiro_base_url=xkiro_base_url,
            xkiro_model=xkiro_model,
            xkiro_timeout=xkiro_timeout,
            thespark_base_url=thespark_base_url,
            thespark_model=thespark_model,
            thespark_timeout=thespark_timeout,
            verifier_python_executable=verifier_python_executable,
            verifier_worker_startup_timeout_s=verifier_worker_startup_timeout_s,
            verifier_claim_timeout_s=verifier_claim_timeout_s,
            verifier_gate_timeout_s=verifier_gate_timeout_s,
            verifier_max_claim_chars=verifier_max_claim_chars,
            verifier_max_evidence_chars=verifier_max_evidence_chars,
            verifier_ipc_frame_limit_bytes=verifier_ipc_frame_limit_bytes,
            verifier_max_claims_per_gate=verifier_max_claims_per_gate,
            verifier_model_network_mode=verifier_model_network_mode,
            verifier_cache_root=verifier_cache_root,
            verifier_manifest_required=verifier_manifest_required,
            verifier_expected_dependency_versions=verifier_expected_dependency_versions,
            repo_root=REPO_ROOT,
            secrets_configured=secrets_configured,
            provenance=prov,
        )

    def get_snapshot(self) -> RuntimeConfigSnapshot:
        if self._snapshot is None:
            self._load_and_initialize()
        assert self._snapshot is not None
        return self._snapshot


def get_runtime_config() -> RuntimeConfigSnapshot:
    """Get the current immutable runtime configuration snapshot."""
    return ConfigurationAuthority.get_instance().get_snapshot()
