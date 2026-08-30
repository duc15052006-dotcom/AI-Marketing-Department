"""Authoritative Model Settings Manager (PROD-MODEL-SETTINGS-01).

Guarantees:
- Single authoritative persisted state for Model & Provider Settings.
- Zero plaintext secret serialization (persists only safe credential_ref).
- Concurrency & optimistic locking via monotonic settings_revision.
- Direct compilation into certified ProviderRegistry, ModelPolicy, and UniversalModelGateway.
- Atomic multi-field transactions with fail-closed rollback.
- Non-mutating transient connection testing.
- Adapter cache invalidation on credential rotation.
- Versioned opaque credential references (STORE:<provider_id>:<version>): key
  rotation issues a NEW version while retaining prior versions (bounded) so
  active runs continue resolving their run-start credential. Plaintext keys
  never enter RuntimeContext, ModelPolicy, snapshots, artifacts, or logs.
- Enforcement of exactly 5 permanent logical agent override identities.
- Active run snapshot isolation preserved.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from governance.redaction import sanitize_sensitive_text
from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    normalize_model_request,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.local_openai_compatible_adapter import LocalNoAuthOpenAICompatibleProviderAdapter
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.provider_auth import provider_requires_api_key
from integrations.models.registry import (
    AgentId,
    ModelPolicy,
    ModelTarget,
    ProviderDefinition,
    ProviderRegistry,
    normalize_agent_id,
    validate_base_url,
    validate_strict_bool,
)
from integrations.models.secret_store import GLOBAL_SECRET_STORE, SecureSecretStore
from schemas.base import BaseModel, Field

logger = logging.getLogger("settings_manager")


class StaleSettingsRevisionError(Exception):
    """Raised when an update is attempted with a stale settings_revision."""
    def __init__(self, current_revision: int, expected_revision: Optional[int]) -> None:
        super().__init__(
            f"STALE_SETTINGS_REVISION: Current revision is {current_revision}, "
            f"but request expected {expected_revision}."
        )
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class ModelSettingsValidationError(ValueError):
    """Raised when model settings validation fails."""
    pass


class PersistedSettingsCorruptionError(ModelSettingsValidationError):
    """Raised when an EXISTING persisted model_settings.json cannot be parsed or
    validated. Fail-closed: user configuration is never silently replaced by
    defaults; the original file is preserved for diagnostics/recovery."""


class ModelSettings(BaseModel):
    """Authoritative persisted Model Settings state."""

    # Adapter types a user/API caller may persist via Model Settings.
    # CUSTOM_INJECTED is an internal deterministic-DI harness type and is
    # deliberately NOT user-configurable; direct Registry DI remains supported.
    USER_CONFIGURABLE_ADAPTER_TYPES = {
        "OPENAI_COMPATIBLE",
        "OPENAI",
        "GEMINI_NATIVE",
        "GEMINI",
    }

    settings_revision: int = 1
    free_only_mode: bool = True
    global_target: ModelTarget = Field(
        default_factory=lambda: ModelTarget(provider_id="gemini", model_id="gemini-flash-latest")
    )
    agent_overrides: Dict[str, ModelTarget] = Field(default_factory=dict)
    fallback_chain: List[ModelTarget] = Field(default_factory=list)
    providers: Dict[str, ProviderDefinition] = Field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.free_only_mode = validate_strict_bool(
            self.free_only_mode,
            "ModelSettings.free_only_mode",
        )
        # Normalize global target
        if isinstance(self.global_target, dict):
            self.global_target = ModelTarget(**self.global_target)

        # Normalize agent overrides: strictly 5 logical agents
        norm_overrides: Dict[str, ModelTarget] = {}
        for agent_key, target in self.agent_overrides.items():
            k_upper = str(agent_key).strip().upper()
            if k_upper == "FINAL_CMO":
                raise ModelSettingsValidationError("INVALID_AGENT_OVERRIDE: FINAL_CMO is not a separate agent; configure CMO.")
            try:
                norm_agent = normalize_agent_id(agent_key)
            except Exception as e:
                raise ModelSettingsValidationError(f"INVALID_AGENT_OVERRIDE: Unknown agent '{agent_key}': {str(e)}")

            if isinstance(target, dict):
                norm_overrides[norm_agent] = ModelTarget(**target)
            elif isinstance(target, ModelTarget):
                norm_overrides[norm_agent] = target
            else:
                raise ModelSettingsValidationError(f"INVALID_MODEL_TARGET: Invalid target for agent '{agent_key}'.")
        self.agent_overrides = norm_overrides

        # Normalize fallback chain
        norm_fallbacks: List[ModelTarget] = []
        seen_targets: Set[Tuple[str, str]] = set()
        for fb in self.fallback_chain:
            fb_target = ModelTarget(**fb) if isinstance(fb, dict) else fb
            target_tuple = (fb_target.provider_id.lower(), fb_target.model_id.strip())
            if target_tuple in seen_targets:
                raise ModelSettingsValidationError(f"DUPLICATE_FALLBACK_TARGET: '{target_tuple[0]}::{target_tuple[1]}' appears multiple times in fallback chain.")
            seen_targets.add(target_tuple)
            norm_fallbacks.append(fb_target)
        self.fallback_chain = norm_fallbacks

        # Normalize providers
        norm_providers: Dict[str, ProviderDefinition] = {}
        for pid, pdef in self.providers.items():
            if isinstance(pdef, dict):
                p_obj = ProviderDefinition(**pdef)
            elif isinstance(pdef, ProviderDefinition):
                p_obj = pdef
            else:
                raise ModelSettingsValidationError(f"INVALID_PROVIDER_DEFINITION: Invalid definition for '{pid}'.")
            adapter_val = str(p_obj.adapter_type).upper()
            if adapter_val == "CUSTOM_INJECTED":
                raise ModelSettingsValidationError(
                    "INVALID_ADAPTER_TYPE: CUSTOM_INJECTED is an internal deterministic-DI "
                    "harness type and is not user-configurable via Model Settings."
                )
            if adapter_val not in ModelSettings.USER_CONFIGURABLE_ADAPTER_TYPES:
                raise ModelSettingsValidationError(
                    f"INVALID_ADAPTER_TYPE: '{p_obj.adapter_type}' is not a user-configurable "
                    f"adapter type (allowed: {', '.join(sorted(ModelSettings.USER_CONFIGURABLE_ADAPTER_TYPES))})."
                )
            norm_providers[p_obj.provider_id.lower()] = p_obj
        self.providers = norm_providers


class ModelSettingsManager:
    """Thread-safe authoritative manager for persisted model settings."""

    def __init__(
        self,
        settings_file_path: Optional[Path] = None,
        secret_store: Optional[SecureSecretStore] = None,
        provider_registry: Optional[ProviderRegistry] = None,
        gateway: Optional[UniversalModelGateway] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._secret_store = secret_store or GLOBAL_SECRET_STORE
        self._file_path = settings_file_path or self._default_settings_path()

        # SINGLE authoritative ProviderRegistry ownership:
        # an explicitly injected registry wins; otherwise reuse the Gateway's
        # existing registry (preserving any runtime-installed state such as the
        # credential usage authority); only create one when neither exists.
        if provider_registry is not None:
            self._provider_registry = provider_registry
        elif gateway is not None and getattr(gateway, "provider_registry", None) is not None:
            self._provider_registry = gateway.provider_registry
        else:
            self._provider_registry = ProviderRegistry()
        self._gateway = gateway

        self._settings = self._load_or_initialize()
        self._compile_to_registry()
        # Startup garbage collection: no runs exist in a fresh process, so any
        # version that is not the committed reference is safely reclaimable.
        try:
            self.reclaim_obsolete_credential_versions()
        except Exception as e:
            logger.warning(f"Startup credential GC deferred: {e}")

    def _default_settings_path(self) -> Path:
        """Resolve OS user-level settings file path."""
        if os.environ.get("AI_MARKETING_CONFIG_DIR"):
            base = Path(os.environ["AI_MARKETING_CONFIG_DIR"])
        elif sys.platform == "win32" and (os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")):
            app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            base = Path(app_data) / "AI-Marketing-Department"
        else:
            base = Path.home() / ".ai_marketing_department"

        base.mkdir(parents=True, exist_ok=True)
        return base / "model_settings.json"

    def _load_or_initialize(self) -> ModelSettings:
        """Load settings from disk or initialize defaults.

        MISSING file -> initialize defaults (existing product semantics).
        EXISTING but corrupt/unparsable/invalid-schema file -> FAIL CLOSED with
        PersistedSettingsCorruptionError. The damaged file is preserved
        untouched and live routing authority is never built from a partial parse.
        """
        with self._lock:
            if self._file_path.exists():
                try:
                    raw_text = self._file_path.read_text(encoding="utf-8")
                    raw = json.loads(raw_text)
                    if not isinstance(raw, dict):
                        raise ValueError("top-level JSON value is not an object.")
                    return ModelSettings(**raw)
                except Exception as e:
                    raise PersistedSettingsCorruptionError(
                        f"CORRUPT_MODEL_SETTINGS_FILE: Existing persisted settings at "
                        f"'{self._file_path}' could not be parsed/validated ({e}). "
                        f"Refusing to fall back to defaults; the original file was "
                        f"preserved for manual recovery."
                    ) from e

            # Initialize from default ProviderRegistry definitions
            default_providers: Dict[str, ProviderDefinition] = {}
            for p in self._provider_registry.list_provider_definitions(include_disabled=True):
                default_providers[p.provider_id.lower()] = p

            settings = ModelSettings(
                settings_revision=1,
                free_only_mode=True,
                global_target=ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
                fallback_chain=[
                    ModelTarget(provider_id="thespark", model_id="spark-default"),
                    ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
                ],
                providers=default_providers,
            )
            self._save_to_disk(settings)
            return settings

    def _save_to_disk(self, settings: ModelSettings) -> None:
        """Atomically persist settings to disk with zero plaintext secrets."""
        self._write_disk_payload(json.dumps(settings.model_dump(), indent=2).encode("utf-8"))

    def _write_disk_payload(self, payload: bytes) -> None:
        """Atomically publish a serialized settings payload to disk."""
        with self._lock:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self._file_path.with_suffix(".tmp")
            tmp_file.write_bytes(payload)
            tmp_file.replace(self._file_path)

    def _capture_runtime_state(self) -> Dict[str, Any]:
        """Capture a safe (secret-free) snapshot of the LIVE runtime authority:
        ProviderRegistry configuration set + Gateway ModelPolicy + free-only
        mode. Used to restore the complete previous live state if applying a
        candidate fails midway."""
        gateway = self._gateway
        return {
            "providers": dict(self._provider_registry.snapshot().providers),
            "policy": gateway.model_policy.model_dump() if gateway else None,
            "free_only_mode": getattr(gateway, "_free_only_mode", None) if gateway else None,
            "has_explicit_policy": getattr(gateway, "_has_explicit_policy", None) if gateway else None,
        }

    def _restore_runtime_state(self, state: Dict[str, Any]) -> None:
        """Restore the complete previous live registry/policy state. No guessing:
        the exact captured definitions are reinstalled and extras removed."""
        with self._lock:
            self._provider_registry.restore_provider_configs(state["providers"])
            gateway = self._gateway
            if gateway is not None and state.get("policy") is not None:
                gateway.model_policy = ModelPolicy(**state["policy"])
                if state.get("free_only_mode") is not None:
                    gateway.set_free_only_mode(bool(state["free_only_mode"]))
                if state.get("has_explicit_policy") is not None:
                    gateway._has_explicit_policy = bool(state["has_explicit_policy"])

    def _apply_candidate_to_runtime(self, candidate: ModelSettings) -> None:
        """Apply a candidate atomically to the live runtime authority; any
        failure mid-apply restores the complete previous live state."""
        runtime_state = self._capture_runtime_state()
        try:
            self._compile_to_registry(settings=candidate)
        except Exception:
            self._restore_runtime_state(runtime_state)
            raise

    def _compile_to_registry(self, settings: Optional[ModelSettings] = None) -> None:
        """Compile ModelSettings into ProviderRegistry and ModelPolicy.

        Accepts an explicit candidate so a transaction can apply registry/policy
        state for validation before committing in-memory authoritative state.
        """
        with self._lock:
            s = settings if settings is not None else self._settings

            # 1. Reconcile ProviderRegistry to the complete committed Settings
            #    state: register/update everything present, and REMOVE anything
            #    absent so deleted providers cannot resurrect (e.g. builtins
            #    after restart). Injected DI adapters are preserved.
            self._provider_registry.bind_secret_store(self._secret_store)
            for pid, pdef in s.providers.items():
                self._provider_registry.register_provider(pdef)
            self._provider_registry.reconcile_provider_configs(set(s.providers.keys()))

            # 2. Build ModelPolicy
            policy = ModelPolicy(
                global_target=s.global_target,
                agent_overrides=dict(s.agent_overrides),
                fallback_chain=list(s.fallback_chain),
                configuration_version=f"rev_{s.settings_revision}",
            )

            # 3. Update gateway if attached
            if self._gateway:
                self._gateway.model_policy = policy
                self._gateway.free_only_mode = s.free_only_mode
                self._gateway.provider_registry = self._provider_registry

    def _is_credential_ref_reclaimable(self, credential_ref: str, committed_refs: Set[str]) -> bool:
        """A credential version may be reclaimed only when it is neither a
        currently committed reference nor reported in-use by an active run."""
        if credential_ref in committed_refs:
            return False
        return not self._provider_registry._is_credential_ref_active(credential_ref)

    def reclaim_obsolete_credential_versions(self, provider_ids: Optional[List[str]] = None) -> List[str]:
        """Garbage-collect credential versions that are neither the current
        committed reference of any provider nor pinned by an active run.

        Returns list of reclaimed opaque refs. Failures are recorded as
        residuals (logged) and retried on the next invocation; reclamation is
        post-commit maintenance and never breaks settings coherence.
        """
        with self._lock:
            committed: Set[str] = set()
            pids = provider_ids or list(self._settings.providers.keys())
            for pid in pids:
                pdef = self._settings.providers.get(pid)
                if pdef and str(pdef.credential_ref or "").startswith("STORE:"):
                    committed.add(pdef.credential_ref)

            reclaimed: List[str] = []
            for pid in pids:
                try:
                    refs = self._secret_store.list_provider_version_refs(pid)
                except Exception as e:
                    logger.warning(f"Credential GC skipped for '{pid}': {e}")
                    continue
                for ref in refs:
                    if ref in reclaimed:
                        continue
                    if self._is_credential_ref_reclaimable(ref, committed):
                        try:
                            if self._secret_store.delete_secret_ref(ref):
                                self._provider_registry.evict_pinned_adapter(ref)
                                reclaimed.append(ref)
                        except Exception as e:
                            # Residual: encrypted version temporarily retained.
                            logger.warning(f"Deferred credential reclamation for {ref}: {e}")
            return reclaimed

    def get_settings(self) -> ModelSettings:
        """Get current in-memory ModelSettings copy."""
        with self._lock:
            return copy.deepcopy(self._settings)

    # Keys that must never cross the API/browser serialization boundary.
    UNSAFE_PROVIDER_RESPONSE_KEYS = (
        "credential_ref",   # internal secret-store locator
        "api_key",          # plaintext secret (defense in depth)
        "api_key_env",      # environment credential reference
    )

    @classmethod
    def sanitize_provider_response(cls, pdef: Any) -> Dict[str, Any]:
        """Browser-safe provider object: necessary metadata only. Never includes
        credential_ref, secret-store locators, vault identifiers, or secrets."""
        if isinstance(pdef, dict):
            data = dict(pdef)
        else:
            data = pdef.model_dump()
        for key in cls.UNSAFE_PROVIDER_RESPONSE_KEYS:
            data.pop(key, None)
        return data

    def get_safe_settings_dict(self) -> Dict[str, Any]:
        """Expose safe dictionary for UI/API clients with zero secret leakage
        and zero internal secret-store locators."""
        with self._lock:
            s = self._settings
            safe_providers: List[Dict[str, Any]] = []

            for pid, pdef in s.providers.items():
                has_cred = self._secret_store.has_secret(pdef.credential_ref)
                requires_key = provider_requires_api_key(pdef.adapter_type, pdef.base_url)
                p_dict = self.sanitize_provider_response(pdef)
                p_dict["has_credential"] = has_cred
                p_dict["requires_api_key"] = requires_key
                p_dict["is_configured"] = (
                    pdef.enabled
                    and bool(pdef.default_model)
                    and (has_cred or not requires_key)
                )
                safe_providers.append(p_dict)

            return {
                "settings_revision": s.settings_revision,
                "free_only_mode": s.free_only_mode,
                "global_target": s.global_target.model_dump(),
                "agent_overrides": {k: v.model_dump() for k, v in s.agent_overrides.items()},
                "fallback_chain": [fb.model_dump() for fb in s.fallback_chain],
                "providers": safe_providers,
                "allowed_agents": [a.value for a in AgentId],
            }

    def update_settings(
        self,
        updates: Dict[str, Any],
        expected_revision: Optional[int] = None,
    ) -> ModelSettings:
        """Atomically update settings with optimistic concurrency locking and
        staged transaction semantics.

        Transaction stages:
          1. Read committed state + optimistic revision check.
          2. Build candidate (pure merge; no external mutation).
          3. Stage secret writes (new credential versions); recorded for
             rollback so a later failure cannot leave usable orphans.
          4. Validate the COMPLETE candidate fail-closed.
          5. Atomically publish persistent settings (tmp+replace).
          6. Apply registry/policy from the explicit candidate.
          7. Commit in-memory authoritative state.
          8. Finalize: evict rotated live adapters, reclaim obsolete versions.
        Any failure before stage 7 rolls back staged secrets and restores the
        previously persisted payload; one coherent authoritative state remains.
        """
        with self._lock:
            # ---- Stage 1: read committed state + concurrency check
            if expected_revision is not None and expected_revision != self._settings.settings_revision:
                raise StaleSettingsRevisionError(
                    current_revision=self._settings.settings_revision,
                    expected_revision=expected_revision,
                )

            old_settings = self._settings
            old_payload = json.dumps(old_settings.model_dump(), indent=2).encode("utf-8")

            # ---- Stage 2: pure candidate merge (no side effects)
            current_dict = old_settings.model_dump()

            if "free_only_mode" in updates:
                current_dict["free_only_mode"] = validate_strict_bool(
                    updates["free_only_mode"],
                    "ModelSettings.free_only_mode",
                )

            if "global_target" in updates and updates["global_target"]:
                current_dict["global_target"] = updates["global_target"]

            if "agent_overrides" in updates and updates["agent_overrides"] is not None:
                current_dict["agent_overrides"] = updates["agent_overrides"]

            if "fallback_chain" in updates and updates["fallback_chain"] is not None:
                current_dict["fallback_chain"] = updates["fallback_chain"]

            rotated_pids: List[str] = []
            pending_secrets: List[Tuple[str, str]] = []
            staged_refs: List[str] = []
            disk_published = False

            if "providers" in updates and updates["providers"] is not None:
                prov_list = updates["providers"]
                if isinstance(prov_list, list):
                    prov_dict = {p["provider_id"].lower(): p for p in prov_list if "provider_id" in p}
                else:
                    prov_dict = prov_list

                for pid, pdata in prov_dict.items():
                    pid_clean = str(pid).strip().lower()
                    existing_pdef = current_dict["providers"].get(pid_clean, {})

                    api_key = pdata.get("api_key")
                    if api_key and str(api_key).strip():
                        # Rotation intent recorded; actual secret staging (the
                        # only vault write) happens in Stage 3.
                        pdata.pop("credential_ref", None)
                        rotated_pids.append(pid_clean)
                        pending_secrets.append((pid_clean, str(api_key).strip()))
                    elif not pdata.get("credential_ref") and existing_pdef.get("credential_ref"):
                        # Preserve existing credential_ref when no new key given
                        pdata["credential_ref"] = existing_pdef["credential_ref"]

                    pdata.pop("api_key", None)
                    pdata.pop("has_credential", None)
                    pdata.pop("requires_api_key", None)
                    pdata.pop("is_configured", None)

                    merged_p = dict(existing_pdef)
                    merged_p.update(pdata)
                    current_dict["providers"][pid_clean] = merged_p

            try:
                # ---- Stage 3: stage secret writes (rollback-able)
                for pid_clean, raw_key in pending_secrets:
                    cred_ref = self._secret_store.set_secret(pid_clean, raw_key)
                    staged_refs.append(cred_ref)
                    current_dict["providers"][pid_clean]["credential_ref"] = cred_ref

                # ---- Stage 4: validate complete candidate (fail-closed)
                current_dict["settings_revision"] = old_settings.settings_revision + 1
                new_settings = ModelSettings(**current_dict)

                # ---- Stage 5: atomically publish persistent settings
                self._save_to_disk(new_settings)
                disk_published = True

                # ---- Stage 6: apply registry/policy from explicit candidate
                self._apply_candidate_to_runtime(new_settings)

            except Exception:
                # ---- Rollback before commit boundary
                if disk_published:
                    try:
                        self._write_disk_payload(old_payload)
                    except Exception as restore_err:
                        logger.error(
                            f"CRITICAL: settings file rollback failed: {restore_err}; "
                            f"in-memory authoritative state retained."
                        )
                for ref in staged_refs:
                    try:
                        self._secret_store.delete_secret_ref(ref)
                    except Exception as e:
                        logger.error(f"ORPHAN_CREDENTIAL_ROLLBACK_FAILED for staged ref: {e}")
                raise

            # ---- Stage 7: commit in-memory authoritative state
            self._settings = new_settings

            # ---- Stage 8: finalize cache transition + obsolete reclamation
            for pid_clean in rotated_pids:
                self._provider_registry.evict_adapter(pid_clean)
            try:
                self.reclaim_obsolete_credential_versions(provider_ids=rotated_pids or None)
            except Exception as e:
                logger.warning(f"Post-commit credential GC deferred: {e}")

            logger.info(f"Model settings updated to revision {new_settings.settings_revision}")
            return new_settings

    def upsert_provider(
        self,
        provider_data: Dict[str, Any],
        secret: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> ProviderDefinition:
        """Add or update a single provider atomically."""
        with self._lock:
            pid = str(provider_data.get("provider_id", "")).strip().lower()
            if not pid:
                raise ModelSettingsValidationError("INVALID_PROVIDER_ID: provider_id is required.")

            clean_data = dict(provider_data)
            if secret and str(secret).strip():
                clean_data["api_key"] = str(secret).strip()

            current_providers = [p.model_dump() for p in self._settings.providers.values()]
            # Replace or append
            found = False
            for i, p in enumerate(current_providers):
                if p["provider_id"] == pid:
                    current_providers[i].update(clean_data)
                    found = True
                    break
            if not found:
                current_providers.append(clean_data)

            new_settings = self.update_settings(
                updates={"providers": current_providers},
                expected_revision=expected_revision,
            )
            return new_settings.providers[pid]

    def enable_provider(self, provider_id: str, expected_revision: Optional[int] = None) -> ProviderDefinition:
        """Enable provider."""
        with self._lock:
            pid = provider_id.strip().lower()
            if pid not in self._settings.providers:
                raise ModelSettingsValidationError(f"PROVIDER_NOT_FOUND: '{provider_id}' is not registered.")
            pdef = self._settings.providers[pid].model_dump()
            pdef["enabled"] = True
            self.update_settings(updates={"providers": [pdef]}, expected_revision=expected_revision)
            return self._settings.providers[pid]

    def disable_provider(self, provider_id: str, expected_revision: Optional[int] = None) -> ProviderDefinition:
        """Disable provider (applies to new runs)."""
        with self._lock:
            pid = provider_id.strip().lower()
            if pid not in self._settings.providers:
                raise ModelSettingsValidationError(f"PROVIDER_NOT_FOUND: '{provider_id}' is not registered.")
            pdef = self._settings.providers[pid].model_dump()
            pdef["enabled"] = False
            self.update_settings(updates={"providers": [pdef]}, expected_revision=expected_revision)
            return self._settings.providers[pid]

    def delete_provider(self, provider_id: str, expected_revision: Optional[int] = None) -> bool:
        """Delete a provider with full revision authority and active-run safety.

        Semantics (ordinary Settings change, not an emergency revocation):
        - Honors optimistic concurrency via expected_revision.
        - Fails closed if the provider is referenced by committed routing
          (global target / agent overrides / fallback chain).
        - Removes the provider from new-run Settings, registry configuration,
          and the live adapter cache so new runs cannot select it.
        - Physical credential versions are reclaimed ONLY when no active run
          still pins them; versions pinned by active runs are retained
          (encrypted) until their references terminate, then GC'd lazily.
        """
        with self._lock:
            # ---- Revision authority (same authority as every other mutation)
            if expected_revision is not None and expected_revision != self._settings.settings_revision:
                raise StaleSettingsRevisionError(
                    current_revision=self._settings.settings_revision,
                    expected_revision=expected_revision,
                )

            pid = provider_id.strip().lower()
            if pid not in self._settings.providers:
                raise ModelSettingsValidationError(f"PROVIDER_NOT_FOUND: '{provider_id}' is not registered.")

            # ---- Committed-routing reference checks (fail closed)
            if self._settings.global_target.provider_id == pid:
                raise ModelSettingsValidationError(
                    f"CANNOT_DELETE_REFERENCED_PROVIDER: '{provider_id}' is currently the global target."
                )
            for ag, tgt in self._settings.agent_overrides.items():
                if tgt.provider_id == pid:
                    raise ModelSettingsValidationError(
                        f"CANNOT_DELETE_REFERENCED_PROVIDER: '{provider_id}' is referenced by agent override '{ag}'."
                    )
            for fb in self._settings.fallback_chain:
                if fb.provider_id == pid:
                    raise ModelSettingsValidationError(
                        f"CANNOT_DELETE_REFERENCED_PROVIDER: '{provider_id}' is referenced in the fallback chain."
                    )

            old_settings = self._settings
            old_payload = json.dumps(old_settings.model_dump(), indent=2).encode("utf-8")

            # ---- Build + validate candidate without the provider
            current_dict = old_settings.model_dump()
            del current_dict["providers"][pid]
            current_dict["settings_revision"] = old_settings.settings_revision + 1
            new_settings = ModelSettings(**current_dict)

            disk_published = False
            try:
                # ---- Publish persistent settings atomically
                self._save_to_disk(new_settings)
                disk_published = True

                # ---- Apply registry/policy from explicit candidate
                self._apply_candidate_to_runtime(new_settings)
            except Exception:
                if disk_published:
                    try:
                        self._write_disk_payload(old_payload)
                    except Exception as restore_err:
                        logger.error(f"CRITICAL: settings file rollback failed: {restore_err}")
                raise

            # ---- Commit in-memory state
            self._settings = new_settings

            # ---- Finalize: remove config + cached adapters for NEW runs
            self._provider_registry.remove_provider_config(pid)

            # ---- Deferred physical credential cleanup (active-run aware)
            try:
                self.reclaim_obsolete_credential_versions(provider_ids=[pid])
            except Exception as e:
                logger.warning(f"Deferred credential reclamation after delete of '{pid}': {e}")

            logger.info(f"Provider '{pid}' deleted at revision {new_settings.settings_revision}")
            return True

    def test_connection(self, test_config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a non-mutating connection test against a saved or transient provider configuration."""
        start_time = time.perf_counter()
        pid = str(test_config.get("provider_id", "")).strip().lower()
        model_id = str(test_config.get("model_id", test_config.get("default_model", "default"))).strip()
        transient_api_key = test_config.get("api_key")
        adapter_type = str(test_config.get("adapter_type", "OPENAI_COMPATIBLE")).upper()
        base_url = test_config.get("base_url")

        # Resolve secret: use transient key if provided, else resolve from store
        secret: Optional[str] = None
        if transient_api_key and str(transient_api_key).strip():
            secret = str(transient_api_key).strip()
        elif pid in self._settings.providers:
            existing_def = self._settings.providers[pid]
            secret = self._secret_store.get_secret(existing_def.credential_ref)
            if not base_url:
                base_url = existing_def.base_url
            if not model_id or model_id == "default":
                model_id = existing_def.default_model

        # Validate URL before deciding credential policy. No-auth is allowed only
        # for explicit loopback OpenAI-compatible endpoints that pass validation.
        try:
            validated_url = validate_base_url(base_url)
        except Exception as e:
            safe_error = sanitize_sensitive_text(str(e), secret=secret)
            return {
                "status": "INVALID_CONFIGURATION",
                "latency_ms": (time.perf_counter() - start_time) * 1000.0,
                "error": f"INVALID_BASE_URL: {safe_error}",
            }

        requires_key = provider_requires_api_key(adapter_type, validated_url)
        if requires_key and not secret:
            return {
                "status": "AUTH_FAILED",
                "latency_ms": (time.perf_counter() - start_time) * 1000.0,
                "error": "MISSING_CREDENTIAL: No API key provided or stored for test.",
            }

        # Construct transient adapter for non-mutating execution
        try:
            adapter: BaseModelAdapter
            if adapter_type in ("GEMINI_NATIVE", "GEMINI"):
                adapter = GeminiProviderAdapter(default_model=model_id, api_key=secret)
            else:
                adapter_cls = (
                    OpenAICompatibleProviderAdapter
                    if requires_key
                    else LocalNoAuthOpenAICompatibleProviderAdapter
                )
                adapter = adapter_cls(
                    provider_id=pid or "custom",
                    base_url=validated_url or "https://api.openai.com/v1",
                    api_key_env="",
                    default_model=model_id,
                    api_key=secret,
                    timeout_seconds=10.0,
                )

            # Minimal ping request
            test_req = ModelRequest(
                request_id=f"TEST-CONN-{int(time.time()*1000)}",
                messages=[ModelMessage(role=ModelRole.USER, content="Ping")],
                model_name=model_id,
                timeout_seconds=10.0,
            )

            resp: ModelResponse = adapter.generate(test_req)
            latency = (time.perf_counter() - start_time) * 1000.0
            safe_response_error = sanitize_sensitive_text(resp.error or "", secret=secret)

            if resp.status == ModelResponseStatus.SUCCESS:
                return {
                    "status": "CONNECTED",
                    "latency_ms": latency,
                    "model_used": resp.model_name or model_id,
                    "details": "Connection successful.",
                }
            elif resp.status == ModelResponseStatus.TIMEOUT:
                return {
                    "status": "TIMEOUT",
                    "latency_ms": latency,
                    "error": safe_response_error or "Provider timed out.",
                }
            else:
                err_text = safe_response_error.upper()
                if "401" in err_text or "AUTH" in err_text or "UNAUTHORIZED" in err_text or "KEY" in err_text:
                    status_code = "AUTH_FAILED"
                elif "429" in err_text or "RATE" in err_text or "QUOTA" in err_text:
                    status_code = "RATE_LIMIT"
                elif "404" in err_text or "NOT FOUND" in err_text or "MODEL" in err_text:
                    status_code = "MODEL_NOT_FOUND"
                else:
                    status_code = "UNAVAILABLE"

                return {
                    "status": status_code,
                    "latency_ms": latency,
                    "error": safe_response_error,
                }
        except Exception as e:
            safe_error = sanitize_sensitive_text(str(e), secret=secret)
            return {
                "status": "UNAVAILABLE",
                "latency_ms": (time.perf_counter() - start_time) * 1000.0,
                "error": f"CONNECTION_EXCEPTION: {safe_error}",
            }
        finally:
            # Best-effort release of local references only. Python strings are
            # immutable and cannot be guaranteed to be zeroized in memory by del.
            del secret
            del transient_api_key
