"""Connection registry and fail-closed scoped secret resolution."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from connections.models import ConnectionProfile
from connections.secrets import SecretProvider, SecretValue, UnsupportedSecretReferenceError


class ConnectionManagerError(RuntimeError):
    """Base runtime error for connection management."""


class ConnectionAlreadyExistsError(ConnectionManagerError):
    """Raised when duplicate registration is attempted without explicit replace."""


class ConnectionNotFoundError(ConnectionManagerError):
    """Raised when a connection id is unknown."""


class ConnectionDisabledError(ConnectionManagerError):
    """Raised when a disabled connection is requested."""


class ConnectionScopeDeniedError(ConnectionManagerError):
    """Raised when caller context does not match the profile scope."""


class ConnectionStoreIntegrityError(ConnectionManagerError):
    """Raised when durable metadata or its indexed identity was altered."""


class ConnectionStoreClosedError(ConnectionManagerError):
    """Raised when a closed durable manager is used."""


@dataclass(frozen=True, repr=False)
class ResolvedConnection:
    """Execution-boundary connection containing a redaction-safe secret wrapper."""

    profile: ConnectionProfile
    secret: SecretValue

    def __repr__(self) -> str:
        return f"ResolvedConnection(profile={self.profile!r}, secret=***)"


class ConnectionManager:
    """Own connection metadata and resolve credentials only after scope checks."""

    def __init__(
        self,
        secret_provider: SecretProvider,
        database_path: Optional[str | Path] = None,
    ) -> None:
        self._secret_provider = secret_provider
        self._profiles: Dict[str, ConnectionProfile] = {}
        self._lock = threading.RLock()
        self._closed = False
        self.database_path = (
            Path(database_path).expanduser().resolve() if database_path else None
        )
        self._conn: Optional[sqlite3.Connection] = None
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.database_path), timeout=5.0, check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            with self._conn:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=FULL")
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS connection_profiles (
                        connection_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_hash TEXT NOT NULL
                    )
                    """
                )
            self._load_profiles()

    @property
    def durable(self) -> bool:
        return self._conn is not None

    def _ensure_open(self) -> None:
        if self._closed:
            raise ConnectionStoreClosedError("CONNECTION_STORE_CLOSED")

    @staticmethod
    def _serialize(profile: ConnectionProfile) -> tuple[str, str]:
        payload = json.dumps(
            profile.to_safe_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _deserialize(row: sqlite3.Row) -> ConnectionProfile:
        payload_json = str(row["payload_json"])
        expected_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if expected_hash != row["payload_hash"]:
            raise ConnectionStoreIntegrityError("CONNECTION_PROFILE_HASH_MISMATCH")
        try:
            payload = json.loads(payload_json)
            profile = ConnectionProfile(
                connection_id=payload["connection_id"],
                provider=payload["provider"],
                display_name=payload["display_name"],
                secret_ref=payload["secret_ref"],
                endpoint=payload.get("endpoint"),
                enabled=payload.get("enabled", True),
                business_id=payload.get("business_id"),
                project_ids=tuple(payload.get("project_ids") or ()),
                brand_ids=tuple(payload.get("brand_ids") or ()),
                metadata=payload.get("metadata") or {},
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionStoreIntegrityError("CONNECTION_PROFILE_PAYLOAD_INVALID") from exc
        if profile.connection_id != row["connection_id"] or profile.provider != row["provider"]:
            raise ConnectionStoreIntegrityError("CONNECTION_PROFILE_INDEX_MISMATCH")
        return profile

    def _load_profiles(self) -> None:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT connection_id, provider, payload_json, payload_hash FROM connection_profiles"
        ).fetchall()
        for row in rows:
            profile = self._deserialize(row)
            if not self._secret_provider.can_resolve(profile.secret_ref):
                raise ConnectionStoreIntegrityError(
                    "CONNECTION_PROFILE_SECRET_REFERENCE_UNSUPPORTED"
                )
            self._profiles[profile.connection_id] = profile

    def _persist(self, profile: ConnectionProfile) -> None:
        if self._conn is None:
            return
        payload_json, payload_hash = self._serialize(profile)
        self._conn.execute(
            """
            INSERT INTO connection_profiles(connection_id, provider, payload_json, payload_hash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(connection_id) DO UPDATE SET
                provider=excluded.provider,
                payload_json=excluded.payload_json,
                payload_hash=excluded.payload_hash
            """,
            (profile.connection_id, profile.provider, payload_json, payload_hash),
        )

    def register(self, profile: ConnectionProfile, *, replace: bool = False) -> ConnectionProfile:
        self._ensure_open()
        if not self._secret_provider.can_resolve(profile.secret_ref):
            raise UnsupportedSecretReferenceError(
                f"No configured SecretProvider accepts reference '{profile.secret_ref}'."
            )
        with self._lock:
            existing = self._profiles.get(profile.connection_id)
            if existing is not None and not replace:
                raise ConnectionAlreadyExistsError(
                    f"Connection '{profile.connection_id}' already exists; pass replace=True for an explicit replacement."
                )
            if self._conn is None:
                self._profiles[profile.connection_id] = profile
            else:
                with self._conn:
                    self._persist(profile)
                self._profiles[profile.connection_id] = profile
        return profile

    def get(self, connection_id: str) -> ConnectionProfile:
        self._ensure_open()
        try:
            return self._profiles[connection_id]
        except KeyError as exc:
            raise ConnectionNotFoundError(f"Connection '{connection_id}' is not registered.") from exc

    def list_profiles(self, *, include_disabled: bool = True) -> List[ConnectionProfile]:
        self._ensure_open()
        profiles = list(self._profiles.values())
        if not include_disabled:
            profiles = [profile for profile in profiles if profile.enabled]
        return sorted(profiles, key=lambda profile: profile.connection_id)

    def disable(self, connection_id: str) -> ConnectionProfile:
        profile = self.get(connection_id).with_updates(enabled=False)
        with self._lock:
            if self._conn is not None:
                with self._conn:
                    self._persist(profile)
            self._profiles[connection_id] = profile
        return profile

    def enable(self, connection_id: str) -> ConnectionProfile:
        profile = self.get(connection_id).with_updates(enabled=True)
        with self._lock:
            if self._conn is not None:
                with self._conn:
                    self._persist(profile)
            self._profiles[connection_id] = profile
        return profile

    def remove(self, connection_id: str) -> ConnectionProfile:
        profile = self.get(connection_id)
        with self._lock:
            if self._conn is not None:
                with self._conn:
                    self._conn.execute(
                        "DELETE FROM connection_profiles WHERE connection_id=?",
                        (connection_id,),
                    )
            del self._profiles[connection_id]
        return profile

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._conn is not None:
                self._conn.close()
            self._closed = True

    @staticmethod
    def _enforce_scope(
        profile: ConnectionProfile,
        *,
        business_id: Optional[str],
        project_id: Optional[str],
        brand_id: Optional[str],
    ) -> None:
        if profile.business_id is not None and business_id != profile.business_id:
            raise ConnectionScopeDeniedError(
                f"Connection '{profile.connection_id}' is not available in the requested business scope."
            )
        if profile.project_ids and project_id not in profile.project_ids:
            raise ConnectionScopeDeniedError(
                f"Connection '{profile.connection_id}' is not available in the requested project scope."
            )
        if profile.brand_ids and brand_id not in profile.brand_ids:
            raise ConnectionScopeDeniedError(
                f"Connection '{profile.connection_id}' is not available in the requested brand scope."
            )

    def authorize_profile(
        self,
        connection_id: str,
        *,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> ConnectionProfile:
        """Authorize profile metadata without resolving credential material.

        Health/control-plane code can use this method to enforce the exact same
        enabled/scope policy as ``resolve`` while proving that no SecretProvider
        lookup occurs merely to render status or choose an account.
        """
        profile = self.get(connection_id)
        if not profile.enabled:
            raise ConnectionDisabledError(f"Connection '{connection_id}' is disabled.")
        self._enforce_scope(
            profile,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        return profile

    def resolve(
        self,
        connection_id: str,
        *,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> ResolvedConnection:
        """Resolve a connection after enabled/scope checks, never before them."""
        profile = self.authorize_profile(
            connection_id,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        secret = self._secret_provider.get(profile.secret_ref)
        return ResolvedConnection(profile=profile, secret=secret)
