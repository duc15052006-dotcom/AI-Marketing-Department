"""Durable provider preflight and user-choice consent authority.

Some external platforms require fresh provider metadata plus explicit user choices
before an external action may be submitted. This authority is separate from the
Approval Engine:

- Approval answers whether the governed action is authorized.
- Preflight proves provider-required human choices were captured from a trusted UI.

The repository stores no credentials and never performs provider network I/O.
Raw idempotency keys are hashed before persistence. Artifacts are short-lived,
exact-scope-bound, and one-shot once claimed for provider dispatch.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

from governance.redaction import REDACTED_SENSITIVE_KEYS, sanitize_sensitive_payload, sanitize_sensitive_text


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}$")
_SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "auth_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "credential",
    "private_key",
    "session_token",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: Optional[datetime] = None) -> str:
    return (value or _utc_now()).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload_hash(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _identifier(name: str, value: Optional[str], *, required: bool = True) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        if required:
            raise ValueError(f"{name} is required.")
        return None
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{name} contains unsupported characters.")
    return normalized


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in REDACTED_SENSITIVE_KEYS or any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def _validate_secret_free(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _is_sensitive_key(key):
                raise ValueError(f"PREFLIGHT_SECRET_FIELD_FORBIDDEN: {path}.{key}")
            _validate_secret_free(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            _validate_secret_free(child, f"{path}[{index}]")
        return
    if isinstance(value, str) and "://" in value:
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            raise ValueError(f"PREFLIGHT_CREDENTIAL_URL_FORBIDDEN: {path}")


def _safe_mapping(value: Optional[Mapping[str, Any]], *, path: str) -> Dict[str, Any]:
    raw = dict(value or {})
    _validate_secret_free(raw, path)
    safe = sanitize_sensitive_payload(raw)
    if not isinstance(safe, dict):
        raise ValueError(f"{path} must be an object/map.")
    return safe


class ProviderPreflightError(RuntimeError):
    pass


class ProviderPreflightConflictError(ProviderPreflightError):
    pass


class ProviderPreflightIntegrityError(ProviderPreflightError):
    pass


class ProviderPreflightState(str, Enum):
    ACTIVE = "ACTIVE"
    CLAIMED = "CLAIMED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ProviderPreflightArtifact:
    preflight_id: str
    provider: str
    connector_id: str
    connection_id: str
    business_id: str
    purpose: str
    idempotency_key_hash: str
    approved_payload: Mapping[str, Any]
    provider_snapshot: Mapping[str, Any]
    user_choices: Mapping[str, Any]
    project_id: Optional[str] = None
    brand_id: Optional[str] = None
    state: ProviderPreflightState = ProviderPreflightState.ACTIVE
    created_at: str = ""
    expires_at: str = ""
    claimed_at: Optional[str] = None
    consumed_at: Optional[str] = None
    schema_version: int = 1
    record_hash: str = ""

    def normalized(self) -> "ProviderPreflightArtifact":
        state = self.state if isinstance(self.state, ProviderPreflightState) else ProviderPreflightState(str(self.state).upper())
        created = self.created_at or _utc_iso()
        if not self.expires_at:
            raise ValueError("expires_at is required for provider preflight artifacts.")
        normalized = replace(
            self,
            preflight_id=_identifier("preflight_id", self.preflight_id) or "",
            provider=(_identifier("provider", self.provider) or "").lower(),
            connector_id=_identifier("connector_id", self.connector_id) or "",
            connection_id=_identifier("connection_id", self.connection_id) or "",
            business_id=_identifier("business_id", self.business_id) or "",
            project_id=_identifier("project_id", self.project_id, required=False),
            brand_id=_identifier("brand_id", self.brand_id, required=False),
            purpose=(_identifier("purpose", self.purpose) or "").lower(),
            idempotency_key_hash=str(self.idempotency_key_hash or "").strip().lower(),
            approved_payload=_safe_mapping(self.approved_payload, path="approved_payload"),
            provider_snapshot=_safe_mapping(self.provider_snapshot, path="provider_snapshot"),
            user_choices=_safe_mapping(self.user_choices, path="user_choices"),
            state=state,
            created_at=created,
            record_hash="",
        )
        if not re.fullmatch(r"[0-9a-f]{64}", normalized.idempotency_key_hash):
            raise ValueError("idempotency_key_hash must be a SHA-256 hex digest.")
        try:
            created_dt = datetime.fromisoformat(normalized.created_at)
            expiry_dt = datetime.fromisoformat(normalized.expires_at)
        except ValueError as exc:
            raise ValueError("Provider preflight timestamps must be ISO-8601.") from exc
        if created_dt.tzinfo is None or expiry_dt.tzinfo is None or expiry_dt <= created_dt:
            raise ValueError("Provider preflight expiry must be timezone-aware and later than creation.")
        return replace(normalized, record_hash=normalized.calculate_hash())

    def hash_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "preflight_id": self.preflight_id,
            "provider": self.provider,
            "connector_id": self.connector_id,
            "connection_id": self.connection_id,
            "business_id": self.business_id,
            "project_id": self.project_id,
            "brand_id": self.brand_id,
            "purpose": self.purpose,
            "idempotency_key_hash": self.idempotency_key_hash,
            "approved_payload": dict(self.approved_payload),
            "provider_snapshot": dict(self.provider_snapshot),
            "user_choices": dict(self.user_choices),
            "state": self.state.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "claimed_at": self.claimed_at,
            "consumed_at": self.consumed_at,
        }

    def calculate_hash(self) -> str:
        return _payload_hash(self.hash_payload())

    def verify_integrity(self) -> bool:
        return bool(self.record_hash) and self.record_hash == self.calculate_hash()

    def to_safe_dict(self) -> Dict[str, Any]:
        return sanitize_sensitive_payload(self.hash_payload() | {"record_hash": self.record_hash})


class ProviderPreflightRepository:
    """One-shot, scope-bound provider preflight repository with optional SQLite durability."""

    def __init__(self, database_path: Optional[str | Path] = None) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, ProviderPreflightArtifact] = {}
        self.database_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False
        if database_path is not None:
            raw = str(database_path)
            if raw == ":memory:":
                target = raw
            else:
                self.database_path = Path(database_path).expanduser().resolve()
                self.database_path.parent.mkdir(parents=True, exist_ok=True)
                target = str(self.database_path)
            self._conn = sqlite3.connect(target, timeout=5.0, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            with self._conn:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=FULL")
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS provider_preflights (
                        preflight_id TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_hash TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_provider_preflight_state ON provider_preflights(state, expires_at)"
                )

    @property
    def durable(self) -> bool:
        return self._conn is not None

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderPreflightError("PROVIDER_PREFLIGHT_STORE_CLOSED")

    @staticmethod
    def _serialize(record: ProviderPreflightArtifact) -> tuple[ProviderPreflightArtifact, str, str]:
        normalized = record.normalized()
        payload = normalized.to_safe_dict()
        encoded = _canonical_json(payload)
        return normalized, encoded, _sha256_text(encoded)

    @staticmethod
    def _decode(payload_json: str, payload_hash: str, *, state: str, expires_at: str) -> ProviderPreflightArtifact:
        if _sha256_text(payload_json) != payload_hash:
            raise ProviderPreflightIntegrityError("PROVIDER_PREFLIGHT_PAYLOAD_HASH_MISMATCH")
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ProviderPreflightIntegrityError("PROVIDER_PREFLIGHT_INVALID_JSON") from exc
        payload.pop("record_hash", None)
        payload["state"] = ProviderPreflightState(payload["state"])
        record = ProviderPreflightArtifact(**payload).normalized()
        if record.state.value != state or record.expires_at != expires_at or not record.verify_integrity():
            raise ProviderPreflightIntegrityError("PROVIDER_PREFLIGHT_INDEX_BINDING_MISMATCH")
        return record

    def create(
        self,
        *,
        provider: str,
        connector_id: str,
        connection_id: str,
        business_id: str,
        purpose: str,
        idempotency_key: str,
        approved_payload: Mapping[str, Any],
        provider_snapshot: Mapping[str, Any],
        user_choices: Mapping[str, Any],
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        ttl_seconds: int = 900,
    ) -> ProviderPreflightArtifact:
        self._ensure_open()
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 60 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be an integer from 60 to 3600.")
        raw_key = str(idempotency_key or "").strip()
        if len(raw_key) < 8:
            raise ValueError("idempotency_key must be at least 8 characters.")
        now = _utc_now()
        record = ProviderPreflightArtifact(
            preflight_id=f"PREF-{uuid.uuid4().hex[:20].upper()}",
            provider=provider,
            connector_id=connector_id,
            connection_id=connection_id,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
            purpose=purpose,
            idempotency_key_hash=_sha256_text(raw_key),
            approved_payload=approved_payload,
            provider_snapshot=provider_snapshot,
            user_choices=user_choices,
            created_at=_utc_iso(now),
            expires_at=_utc_iso(now + timedelta(seconds=ttl_seconds)),
        ).normalized()
        normalized, encoded, encoded_hash = self._serialize(record)
        with self._lock:
            if self._conn is None:
                self._records[normalized.preflight_id] = normalized
                return copy.deepcopy(normalized)
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO provider_preflights(preflight_id,state,expires_at,payload_json,payload_hash) VALUES(?,?,?,?,?)",
                        (normalized.preflight_id, normalized.state.value, normalized.expires_at, encoded, encoded_hash),
                    )
            except sqlite3.IntegrityError as exc:
                raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_ALREADY_EXISTS") from exc
            except sqlite3.Error as exc:
                raise ProviderPreflightError(
                    "PROVIDER_PREFLIGHT_CREATE_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc
        return copy.deepcopy(normalized)

    def get(self, preflight_id: str) -> Optional[ProviderPreflightArtifact]:
        self._ensure_open()
        key = str(preflight_id or "").strip()
        with self._lock:
            if self._conn is None:
                record = self._records.get(key)
                return copy.deepcopy(record) if record else None
            try:
                row = self._conn.execute(
                    "SELECT state,expires_at,payload_json,payload_hash FROM provider_preflights WHERE preflight_id=?",
                    (key,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise ProviderPreflightError(
                    "PROVIDER_PREFLIGHT_GET_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc
        if row is None:
            return None
        return self._decode(row["payload_json"], row["payload_hash"], state=row["state"], expires_at=row["expires_at"])

    def _store_replace(self, record: ProviderPreflightArtifact) -> ProviderPreflightArtifact:
        normalized, encoded, encoded_hash = self._serialize(record)
        if self._conn is None:
            if normalized.preflight_id not in self._records:
                raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_NOT_FOUND")
            self._records[normalized.preflight_id] = normalized
            return copy.deepcopy(normalized)
        cur = self._conn.execute(
            "UPDATE provider_preflights SET state=?,expires_at=?,payload_json=?,payload_hash=? WHERE preflight_id=?",
            (normalized.state.value, normalized.expires_at, encoded, encoded_hash, normalized.preflight_id),
        )
        if cur.rowcount != 1:
            raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_NOT_FOUND")
        return copy.deepcopy(normalized)

    @staticmethod
    def _assert_binding(
        record: ProviderPreflightArtifact,
        *,
        provider: str,
        connector_id: str,
        connection_id: str,
        business_id: str,
        project_id: Optional[str],
        brand_id: Optional[str],
        purpose: str,
        idempotency_key: str,
    ) -> None:
        expected = (
            str(provider or "").strip().lower(),
            str(connector_id or "").strip(),
            str(connection_id or "").strip(),
            str(business_id or "").strip(),
            str(project_id or "").strip() or None,
            str(brand_id or "").strip() or None,
            str(purpose or "").strip().lower(),
            _sha256_text(str(idempotency_key or "").strip()),
        )
        actual = (
            record.provider,
            record.connector_id,
            record.connection_id,
            record.business_id,
            record.project_id,
            record.brand_id,
            record.purpose,
            record.idempotency_key_hash,
        )
        if actual != expected:
            raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_BINDING_MISMATCH")

    def claim(
        self,
        preflight_id: str,
        *,
        provider: str,
        connector_id: str,
        connection_id: str,
        business_id: str,
        purpose: str,
        idempotency_key: str,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> ProviderPreflightArtifact:
        self._ensure_open()
        with self._lock:
            record = self.get(preflight_id)
            if record is None:
                raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_NOT_FOUND")
            self._assert_binding(
                record,
                provider=provider,
                connector_id=connector_id,
                connection_id=connection_id,
                business_id=business_id,
                project_id=project_id,
                brand_id=brand_id,
                purpose=purpose,
                idempotency_key=idempotency_key,
            )
            if record.state is not ProviderPreflightState.ACTIVE:
                raise ProviderPreflightConflictError(
                    f"PROVIDER_PREFLIGHT_NOT_ACTIVE: state={record.state.value}"
                )
            if datetime.fromisoformat(record.expires_at) <= _utc_now():
                expired = replace(
                    record,
                    state=ProviderPreflightState.EXPIRED,
                    record_hash="",
                )
                if self._conn is None:
                    self._store_replace(expired)
                else:
                    with self._conn:
                        self._store_replace(expired)
                raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_EXPIRED")
            claimed = replace(
                record,
                state=ProviderPreflightState.CLAIMED,
                claimed_at=_utc_iso(),
                record_hash="",
            )
            try:
                if self._conn is None:
                    return self._store_replace(claimed)
                with self._conn:
                    return self._store_replace(claimed)
            except sqlite3.Error as exc:
                raise ProviderPreflightError(
                    "PROVIDER_PREFLIGHT_CLAIM_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc

    def consume(self, preflight_id: str) -> ProviderPreflightArtifact:
        self._ensure_open()
        with self._lock:
            record = self.get(preflight_id)
            if record is None:
                raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_NOT_FOUND")
            if record.state is not ProviderPreflightState.CLAIMED:
                raise ProviderPreflightConflictError(
                    f"PROVIDER_PREFLIGHT_NOT_CLAIMED: state={record.state.value}"
                )
            consumed = replace(
                record,
                state=ProviderPreflightState.CONSUMED,
                consumed_at=_utc_iso(),
                record_hash="",
            )
            try:
                if self._conn is None:
                    return self._store_replace(consumed)
                with self._conn:
                    return self._store_replace(consumed)
            except sqlite3.Error as exc:
                raise ProviderPreflightError(
                    "PROVIDER_PREFLIGHT_CONSUME_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc

    def revoke(self, preflight_id: str) -> ProviderPreflightArtifact:
        self._ensure_open()
        with self._lock:
            record = self.get(preflight_id)
            if record is None:
                raise ProviderPreflightConflictError("PROVIDER_PREFLIGHT_NOT_FOUND")
            if record.state is not ProviderPreflightState.ACTIVE:
                raise ProviderPreflightConflictError(
                    f"PROVIDER_PREFLIGHT_NOT_REVOCABLE: state={record.state.value}"
                )
            revoked = replace(record, state=ProviderPreflightState.REVOKED, record_hash="")
            if self._conn is None:
                return self._store_replace(revoked)
            with self._conn:
                return self._store_replace(revoked)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._conn is not None:
                self._conn.close()
            self._closed = True
