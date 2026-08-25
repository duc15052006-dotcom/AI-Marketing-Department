"""Secure Secret Store for Provider API Credentials (PROD-MODEL-SETTINGS-01R1).

Source-of-truth semantics (matches implementation exactly):

- Windows production: secrets are encrypted with Windows DPAPI
  (CryptProtectData / CryptUnprotectData) bound to the logged-in user.
  Protection comes from DPAPI user-bound encryption. The optional entropy
  argument passed to DPAPI is a constant APPLICATION parameter, NOT a secret,
  and must never be described or relied upon as the protection mechanism.
  A DPAPI encrypt/decrypt failure FAILS CLOSED: the operation raises and no
  secret is persisted or recovered through any weaker mechanism.

- Non-Windows production: NO OS-backed secure persistent secret store is
  implemented in this codebase. Persistent storage therefore FAILS CLOSED by
  raising SecureSecretStoreUnavailableError ("SECURE_SECRET_STORE_UNAVAILABLE").
  There is intentionally NO XOR, base64, obfuscation, or other pseudo-encryption
  fallback anywhere in this module.

- Credential references are VERSIONED and opaque/non-secret:
      STORE:<provider_id>:<version>
  Rotation creates a NEW version. Retention/reclamation of old versions is NOT
  decided here by any fixed count: the caller (ModelSettingsManager) is the
  lifetime authority and reclaims a version only when it is neither the
  current committed reference nor reported in-use by an active run via its
  credential usage authority. This store only provides exact single-reference
  deletion primitives. Legacy unversioned references ("STORE:<provider_id>")
  remain readable for backward compatibility but are never newly issued.

- Vault corruption (failed decrypt, truncation, invalid JSON structure) FAILS
  CLOSED: raises VaultCorruptionError. A corrupted vault is never silently
  treated as empty and never "recovered" through any fallback decoding.

- Plaintext truth: decrypted secrets exist transiently in process memory when
  resolved for an authenticated request. This module does NOT keep a long-lived
  plaintext cache; the vault is read and decrypted per operation and only the
  requested value is returned. Python cannot securely erase memory; no fake
  zeroization is claimed.

- InMemorySecretStore exists purely as an explicitly injected TEST double
  (dependency injection). It is never selected automatically at runtime.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import sys
import threading
import uuid
from typing import Dict, Optional

logger = logging.getLogger("secret_store")

_IS_WINDOWS = sys.platform == "win32"


class SecureSecretStoreError(Exception):
    """Base error for SecureSecretStore failures."""


class SecureSecretStoreUnavailableError(SecureSecretStoreError):
    """Raised when no secure OS-backed persistent secret storage is available."""


class VaultCorruptionError(SecureSecretStoreError):
    """Raised when the encrypted vault cannot be decrypted or parsed (fail closed)."""


# Windows DPAPI Structures
if _IS_WINDOWS:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]


def _win_dpapi_encrypt(data: bytes, entropy: Optional[bytes] = None) -> bytes:
    """Encrypt byte payload using Windows DPAPI CryptProtectData. Raises on failure."""
    if not _IS_WINDOWS:
        raise SecureSecretStoreUnavailableError("DPAPI is only available on Windows")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_blob = DATA_BLOB()
    in_blob.cbData = len(data)
    in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte))

    entropy_blob_ptr = None
    if entropy:
        entropy_blob = DATA_BLOB()
        entropy_blob.cbData = len(entropy)
        entropy_blob.pbData = ctypes.cast(ctypes.create_string_buffer(entropy, len(entropy)), ctypes.POINTER(ctypes.c_byte))
        entropy_blob_ptr = ctypes.byref(entropy_blob)

    out_blob = DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x1
    flags = 0x1

    res = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        entropy_blob_ptr,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    if not res:
        err = kernel32.GetLastError()
        raise OSError(f"CryptProtectData failed with error code {err}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _win_dpapi_decrypt(encrypted_data: bytes, entropy: Optional[bytes] = None) -> bytes:
    """Decrypt byte payload using Windows DPAPI CryptUnprotectData. Raises on failure."""
    if not _IS_WINDOWS:
        raise SecureSecretStoreUnavailableError("DPAPI is only available on Windows")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_blob = DATA_BLOB()
    in_blob.cbData = len(encrypted_data)
    in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_data, len(encrypted_data)), ctypes.POINTER(ctypes.c_byte))

    entropy_blob_ptr = None
    if entropy:
        entropy_blob = DATA_BLOB()
        entropy_blob.cbData = len(entropy)
        entropy_blob.pbData = ctypes.cast(ctypes.create_string_buffer(entropy, len(entropy)), ctypes.POINTER(ctypes.c_byte))
        entropy_blob_ptr = ctypes.byref(entropy_blob)

    out_blob = DATA_BLOB()
    flags = 0x1

    res = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        entropy_blob_ptr,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    if not res:
        err = kernel32.GetLastError()
        raise OSError(f"CryptUnprotectData failed with error code {err}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


class SecureSecretStore:
    """Thread-safe, DPAPI-encrypted credential vault. Fail-closed on all errors.

    No plaintext values are held longer than a single operation. There is no
    long-lived in-memory plaintext cache.
    """

    def __init__(self, vault_path: Optional[Path] = None) -> None:
        self._lock = threading.RLock()
        self._vault_path = vault_path or self._default_vault_path()

    def _default_vault_path(self) -> Path:
        """Resolve OS user-level secure vault directory."""
        if os.environ.get("AI_MARKETING_CONFIG_DIR"):
            base = Path(os.environ["AI_MARKETING_CONFIG_DIR"])
        elif _IS_WINDOWS and (os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")):
            app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            base = Path(app_data) / "AI-Marketing-Department"
        else:
            base = Path.home() / ".ai_marketing_department"

        base.mkdir(parents=True, exist_ok=True)
        return base / "secrets.vault"

    @staticmethod
    def _get_application_entropy() -> bytes:
        """Constant DPAPI application parameter. NOT a secret; protection comes
        exclusively from DPAPI user-bound encryption."""
        return b"AI-Marketing-Dept-Credential-Vault-v1"

    # ------------------------------------------------------------------
    # Vault I/O (fail-closed)
    # ------------------------------------------------------------------

    def _read_vault(self) -> Dict[str, str]:
        """Decrypt and parse vault contents. Raises fail-closed on any problem."""
        with self._lock:
            if not _IS_WINDOWS:
                raise SecureSecretStoreUnavailableError(
                    "SECURE_SECRET_STORE_UNAVAILABLE: No OS-backed secure secret "
                    "storage is implemented on this platform."
                )

            if not self._vault_path.exists():
                return {}

            raw_bytes = self._vault_path.read_bytes()
            if not raw_bytes:
                # An EXISTING empty file is not "no vault": it is a damaged or
                # truncated vault and must never be silently treated as an
                # empty credential store. Fail closed; the file is preserved.
                raise VaultCorruptionError(
                    "VAULT_CORRUPTION: Existing vault file is zero bytes; refusing to "
                    "interpret it as an empty credential store."
                )

            try:
                decrypted_bytes = _win_dpapi_decrypt(raw_bytes, self._get_application_entropy())
            except Exception as e:
                raise VaultCorruptionError(
                    f"VAULT_CORRUPTION: Vault could not be decrypted: {e}"
                ) from e

            try:
                data = json.loads(decrypted_bytes.decode("utf-8"))
            except Exception as e:
                raise VaultCorruptionError(
                    f"VAULT_CORRUPTION: Vault payload is not valid JSON: {e}"
                ) from e

            if not isinstance(data, dict):
                raise VaultCorruptionError(
                    "VAULT_CORRUPTION: Vault JSON structure is invalid (expected object)."
                )

            return {str(k): str(v) for k, v in data.items()}

    def _write_vault(self, data: Dict[str, str]) -> None:
        """Encrypt via DPAPI and atomically persist. Raises fail-closed."""
        with self._lock:
            if not _IS_WINDOWS:
                raise SecureSecretStoreUnavailableError(
                    "SECURE_SECRET_STORE_UNAVAILABLE: No OS-backed secure secret "
                    "storage is implemented on this platform."
                )

            payload = json.dumps(data).encode("utf-8")
            try:
                encrypted_bytes = _win_dpapi_encrypt(payload, self._get_application_entropy())
            except Exception as e:
                raise SecureSecretStoreUnavailableError(
                    f"SECRET_STORE_WRITE_FAILED: DPAPI encryption failed; "
                    f"secret NOT persisted (fail-closed): {e}"
                ) from e

            self._vault_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._vault_path.with_suffix(".tmp")
            tmp_path.write_bytes(encrypted_bytes)
            tmp_path.replace(self._vault_path)

    # ------------------------------------------------------------------
    # Versioned public interface
    # ------------------------------------------------------------------

    def set_secret(self, key_id: str, secret_value: str) -> str:
        """Persist secret under a NEW opaque versioned reference and return it.

        Format: 'STORE:<provider_id>:<version>'. Prior versions of the same
        provider_id are retained (bounded by MAX_CREDENTIAL_VERSIONS) so that
        active runs may continue resolving their pinned credential version.
        """
        if not key_id or not str(key_id).strip():
            raise ValueError("INVALID_KEY_ID: Secret key_id cannot be empty.")
        if secret_value is None:
            raise ValueError("INVALID_SECRET_VALUE: secret_value cannot be None.")

        clean_key = str(key_id).strip().lower()
        clean_secret = str(secret_value).strip()

        with self._lock:
            vault_data = self._read_vault()
            version = uuid.uuid4().hex[:12]
            vault_key = f"{clean_key}:{version}"
            vault_data[vault_key] = clean_secret
            self._write_vault(vault_data)
            return f"STORE:{vault_key}"

    @staticmethod
    def _is_version_key(provider_id: str, vault_key: str) -> bool:
        return (
            vault_key.startswith(f"{provider_id}:")
            and len(vault_key.split(":")) == 2
        )

    def list_provider_version_refs(self, provider_id: str) -> list:
        """Return all full opaque versioned refs (STORE:<pid>:<version>)
        currently persisted for a provider id."""
        clean_key = str(provider_id).strip().lower()
        with self._lock:
            vault_data = self._read_vault()
            return [
                f"STORE:{k}" for k in sorted(vault_data.keys())
                if self._is_version_key(clean_key, k)
            ]

    def get_secret(self, credential_ref: Optional[str]) -> Optional[str]:
        """Resolve a secret from a STORE: reference, ENV: reference, or legacy name.

        Raises fail-closed (VaultCorruptionError / availability) on vault problems;
        returns None only when the referenced credential simply does not exist.
        """
        if not credential_ref:
            return None

        ref = str(credential_ref).strip()
        if ref.startswith("STORE:"):
            vault_key = ref[6:].strip().lower()
            with self._lock:
                vault_data = self._read_vault()
                return vault_data.get(vault_key)
        elif ref.startswith("ENV:"):
            env_var = ref[4:].strip()
            return os.environ.get(env_var)
        else:
            # Legacy direct-name lookup (pre-versioning references), then ENV.
            with self._lock:
                vault_data = self._read_vault()
                val = vault_data.get(ref.lower())
            if val:
                return val
            return os.environ.get(ref)

    def list_credential_versions(self, key_id: str) -> int:
        """Return number of retained credential versions for a provider id."""
        return len(self.list_provider_version_refs(key_id))

    def delete_secret_ref(self, credential_ref: str) -> bool:
        """Delete EXACTLY one versioned vault entry identified by its full
        opaque ref (STORE:<pid>:<version>). Used for precise transactional
        rollback and lifetime-authority reclamation; never touches other
        versions of the same provider."""
        if not credential_ref:
            return False
        ref = str(credential_ref).strip()
        if not ref.startswith("STORE:"):
            return False
        vault_key = ref[6:].strip().lower()
        with self._lock:
            vault_data = self._read_vault()
            if vault_key not in vault_data:
                return False
            del vault_data[vault_key]
            self._write_vault(vault_data)
            return True

    def delete_secret(self, key_id: str) -> bool:
        """Remove ALL retained versions of a provider's credentials from the vault."""
        clean_key = str(key_id).strip().lower()
        with self._lock:
            vault_data = self._read_vault()
            doomed = [
                k for k in vault_data
                if k == clean_key
                or (k.startswith(f"{clean_key}:") and len(k.split(":")) == 2)
            ]
            if not doomed:
                return False
            for k in doomed:
                del vault_data[k]
            self._write_vault(vault_data)
            return True

    def has_secret(self, credential_ref: Optional[str]) -> bool:
        """Check whether a credential resolves to a non-empty value WITHOUT
        returning or logging the plaintext secret."""
        val = self.get_secret(credential_ref)
        return bool(val and len(val.strip()) > 0)


class InMemorySecretStore:
    """EXPLICIT dependency-injection test double ONLY.

    Implements the SecureSecretStore interface with in-memory storage. It must
    be injected explicitly by test code; it is NEVER selected automatically by
    production paths and provides no persistence or encryption.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: Dict[str, str] = {}

    def set_secret(self, key_id: str, secret_value: str) -> str:
        if not key_id or not str(key_id).strip():
            raise ValueError("INVALID_KEY_ID: Secret key_id cannot be empty.")
        if secret_value is None:
            raise ValueError("INVALID_SECRET_VALUE: secret_value cannot be None.")
        clean_key = str(key_id).strip().lower()
        version = uuid.uuid4().hex[:12]
        vault_key = f"{clean_key}:{version}"
        with self._lock:
            self._store[vault_key] = str(secret_value).strip()
        return f"STORE:{vault_key}"

    def get_secret(self, credential_ref: Optional[str]) -> Optional[str]:
        if not credential_ref:
            return None
        ref = str(credential_ref).strip()
        if ref.startswith("STORE:"):
            with self._lock:
                return self._store.get(ref[6:].strip().lower())
        if ref.startswith("ENV:"):
            return os.environ.get(ref[4:].strip())
        with self._lock:
            val = self._store.get(ref.lower())
        if val:
            return val
        return os.environ.get(ref)

    def list_credential_versions(self, key_id: str) -> int:
        clean_key = str(key_id).strip().lower()
        with self._lock:
            return sum(
                1 for k in self._store
                if k.startswith(f"{clean_key}:") and len(k.split(":")) == 2
            )

    def list_provider_version_refs(self, provider_id: str) -> list:
        clean_key = str(provider_id).strip().lower()
        with self._lock:
            return [
                f"STORE:{k}" for k in sorted(self._store.keys())
                if k.startswith(f"{clean_key}:") and len(k.split(":")) == 2
            ]

    def delete_secret_ref(self, credential_ref: str) -> bool:
        if not credential_ref or not str(credential_ref).startswith("STORE:"):
            return False
        vault_key = str(credential_ref).strip()[6:].strip().lower()
        with self._lock:
            if vault_key in self._store:
                del self._store[vault_key]
                return True
            return False

    def delete_secret(self, key_id: str) -> bool:
        clean_key = str(key_id).strip().lower()
        with self._lock:
            doomed = [
                k for k in self._store
                if k == clean_key
                or (k.startswith(f"{clean_key}:") and len(k.split(":")) == 2)
            ]
            for k in doomed:
                del self._store[k]
            return bool(doomed)

    def has_secret(self, credential_ref: Optional[str]) -> bool:
        val = self.get_secret(credential_ref)
        return bool(val and len(val.strip()) > 0)


# Global singleton instance
GLOBAL_SECRET_STORE = SecureSecretStore()
