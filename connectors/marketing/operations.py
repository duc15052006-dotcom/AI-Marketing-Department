"""Durable provider-operation tracking for asynchronous marketing actions.

Provider APIs such as TikTok Direct Post may return an operation identifier long
before the final publish result is known. This repository keeps that state out of
agent context and makes it restart-safe, scope-aware, integrity-checked, and
secret-free.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlsplit

from governance.redaction import REDACTED_SENSITIVE_KEYS, sanitize_sensitive_payload


class ProviderOperationError(RuntimeError):
    """Base provider-operation tracker error."""


class ProviderOperationConflictError(ProviderOperationError):
    pass


class ProviderOperationNotFoundError(ProviderOperationError):
    pass


class ProviderOperationScopeError(ProviderOperationError):
    pass


class ProviderOperationIntegrityError(ProviderOperationError):
    pass


class ProviderOperationStoreError(ProviderOperationError):
    pass


class ProviderOperationState(str, Enum):
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    UNKNOWN = "UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

    @property
    def terminal(self) -> bool:
        return self in {ProviderOperationState.SUCCEEDED, ProviderOperationState.FAILED}


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/~-]{0,191}$")
_OPERATION_ID_RE = re.compile(r"^PROVOP-[A-F0-9]{24}$")
_SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "client_secret",
    "developer_token",
    "credential",
    "private_key",
    "session_token",
    "bearer",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_identifier(name: str, value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _IDENTIFIER_RE.fullmatch(normalized):
        raise ProviderOperationError(f"{name} is not a valid provider-operation identifier.")
    return normalized


def _optional_identifier(name: str, value: object) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return _required_identifier(name, normalized)


def _sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in REDACTED_SENSITIVE_KEYS or any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def _validate_safe_metadata(value: Any, path: str = "metadata") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _sensitive_key(key):
                raise ProviderOperationError(
                    f"Sensitive field '{path}.{key}' is forbidden in provider-operation metadata."
                )
            _validate_safe_metadata(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            _validate_safe_metadata(child, f"{path}[{index}]")
        return
    if isinstance(value, str) and "://" in value:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise ProviderOperationError(f"Credential-bearing URL is forbidden at {path}.")
        lowered = {key.lower() for key, _ in __import__("urllib.parse").parse.parse_qsl(parsed.query, keep_blank_values=True)}
        if any(_sensitive_key(key) for key in lowered):
            raise ProviderOperationError(f"Credential-bearing URL query is forbidden at {path}.")


def _safe_metadata(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    raw = dict(value or {})
    _validate_safe_metadata(raw)
    safe = sanitize_sensitive_payload(raw)
    if not isinstance(safe, dict):
        raise ProviderOperationError("Provider-operation metadata must serialize to an object.")
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise ProviderOperationError("Provider-operation metadata exceeds 64 KiB.")
    return safe


def _idempotency_hash(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_payload(record: "ProviderOperationRecord") -> Dict[str, Any]:
    return {
        "operation_id": record.operation_id,
        "provider": record.provider,
        "connector_id": record.connector_id,
        "connection_id": record.connection_id,
        "capability_id": record.capability_id,
        "action": record.action,
        "external_operation_id": record.external_operation_id,
        "business_id": record.business_id,
        "project_id": record.project_id,
        "brand_id": record.brand_id,
        "state": record.state.value,
        "provider_status": record.provider_status,
        "idempotency_key_hash": record.idempotency_key_hash,
        "metadata": record.metadata,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "last_polled_at": record.last_polled_at,
        "poll_count": record.poll_count,
    }


def _record_hash(record: "ProviderOperationRecord") -> str:
    encoded = json.dumps(
        _canonical_payload(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProviderOperationRecord:
    operation_id: str
    provider: str
    connector_id: str
    connection_id: str
    capability_id: str
    action: str
    external_operation_id: str
    business_id: str
    project_id: Optional[str]
    brand_id: Optional[str]
    state: ProviderOperationState
    provider_status: str
    idempotency_key_hash: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict, repr=False)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    last_polled_at: Optional[str] = None
    poll_count: int = 0
    record_hash: str = ""

    def __post_init__(self) -> None:
        if not _OPERATION_ID_RE.fullmatch(self.operation_id):
            raise ProviderOperationError("operation_id is invalid.")
        for name in (
            "provider",
            "connector_id",
            "connection_id",
            "capability_id",
            "action",
            "external_operation_id",
            "business_id",
        ):
            object.__setattr__(self, name, _required_identifier(name, getattr(self, name)))
        object.__setattr__(self, "provider", self.provider.lower())
        object.__setattr__(self, "connector_id", self.connector_id.lower())
        object.__setattr__(self, "capability_id", self.capability_id.lower())
        object.__setattr__(self, "action", self.action.lower())
        object.__setattr__(self, "project_id", _optional_identifier("project_id", self.project_id))
        object.__setattr__(self, "brand_id", _optional_identifier("brand_id", self.brand_id))
        if not isinstance(self.state, ProviderOperationState):
            object.__setattr__(self, "state", ProviderOperationState(str(self.state)))
        status = str(self.provider_status or "").strip().upper()
        if not status or not _IDENTIFIER_RE.fullmatch(status):
            raise ProviderOperationError("provider_status is invalid.")
        object.__setattr__(self, "provider_status", status)
        if self.idempotency_key_hash is not None and not re.fullmatch(r"[a-f0-9]{64}", self.idempotency_key_hash):
            raise ProviderOperationError("idempotency_key_hash is invalid.")
        if not isinstance(self.poll_count, int) or isinstance(self.poll_count, bool) or self.poll_count < 0:
            raise ProviderOperationError("poll_count must be a non-negative integer.")
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))

    def safe_dict(self) -> Dict[str, Any]:
        payload = _canonical_payload(self)
        payload["record_hash"] = self.record_hash
        return copy.deepcopy(payload)


class ProviderOperationRepository:
    """In-memory or SQLite-backed provider-operation authority."""

    def __init__(self, database_path: Optional[str | Path] = None) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, ProviderOperationRecord] = {}
        self._database_path = Path(database_path).expanduser().resolve() if database_path else None
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False
        if self._database_path is not None:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._conn = sqlite3.connect(str(self._database_path), check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=FULL")
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS provider_operations (
                        operation_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        connector_id TEXT NOT NULL,
                        connection_id TEXT NOT NULL,
                        external_operation_id TEXT NOT NULL,
                        business_id TEXT NOT NULL,
                        project_id TEXT,
                        brand_id TEXT,
                        payload_json TEXT NOT NULL,
                        record_hash TEXT NOT NULL,
                        UNIQUE(provider, connection_id, external_operation_id)
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_provider_ops_scope ON provider_operations(business_id, project_id, brand_id, provider)"
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                raise ProviderOperationStoreError("PROVIDER_OPERATION_STORE_INIT_FAILED") from exc

    @property
    def database_path(self) -> Optional[Path]:
        return self._database_path

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderOperationStoreError("PROVIDER_OPERATION_STORE_CLOSED")

    @staticmethod
    def _new_operation_id() -> str:
        return f"PROVOP-{uuid.uuid4().hex[:24].upper()}"

    @staticmethod
    def _with_hash(record: ProviderOperationRecord) -> ProviderOperationRecord:
        unhashed = replace(record, record_hash="")
        return replace(unhashed, record_hash=_record_hash(unhashed))

    @staticmethod
    def _verify(record: ProviderOperationRecord) -> ProviderOperationRecord:
        expected = _record_hash(replace(record, record_hash=""))
        if not record.record_hash or record.record_hash != expected:
            raise ProviderOperationIntegrityError(
                f"PROVIDER_OPERATION_INTEGRITY_MISMATCH: {record.operation_id}"
            )
        return record

    @staticmethod
    def _serialize(record: ProviderOperationRecord) -> str:
        return json.dumps(
            _canonical_payload(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def _deserialize(cls, payload_json: str, record_hash: str) -> ProviderOperationRecord:
        try:
            payload = json.loads(payload_json)
            record = ProviderOperationRecord(
                operation_id=payload["operation_id"],
                provider=payload["provider"],
                connector_id=payload["connector_id"],
                connection_id=payload["connection_id"],
                capability_id=payload["capability_id"],
                action=payload["action"],
                external_operation_id=payload["external_operation_id"],
                business_id=payload["business_id"],
                project_id=payload.get("project_id"),
                brand_id=payload.get("brand_id"),
                state=ProviderOperationState(payload["state"]),
                provider_status=payload["provider_status"],
                idempotency_key_hash=payload.get("idempotency_key_hash"),
                metadata=payload.get("metadata") or {},
                created_at=payload["created_at"],
                updated_at=payload["updated_at"],
                last_polled_at=payload.get("last_polled_at"),
                poll_count=int(payload.get("poll_count", 0)),
                record_hash=record_hash,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderOperationIntegrityError("PROVIDER_OPERATION_PAYLOAD_INVALID") from exc
        return cls._verify(record)

    @staticmethod
    def _verify_index(row: sqlite3.Row, record: ProviderOperationRecord) -> None:
        checks = {
            "operation_id": record.operation_id,
            "provider": record.provider,
            "connector_id": record.connector_id,
            "connection_id": record.connection_id,
            "external_operation_id": record.external_operation_id,
            "business_id": record.business_id,
            "project_id": record.project_id,
            "brand_id": record.brand_id,
        }
        for column, expected in checks.items():
            if row[column] != expected:
                raise ProviderOperationIntegrityError(
                    f"PROVIDER_OPERATION_INDEX_MISMATCH: {record.operation_id}:{column}"
                )

    def _row_record(self, row: sqlite3.Row) -> ProviderOperationRecord:
        record = self._deserialize(row["payload_json"], row["record_hash"])
        self._verify_index(row, record)
        return record

    def _insert_locked(self, record: ProviderOperationRecord) -> None:
        if self._conn is None:
            if record.operation_id in self._records:
                raise ProviderOperationConflictError("PROVIDER_OPERATION_ID_CONFLICT")
            if any(
                existing.provider == record.provider
                and existing.connection_id == record.connection_id
                and existing.external_operation_id == record.external_operation_id
                for existing in self._records.values()
            ):
                raise ProviderOperationConflictError("PROVIDER_EXTERNAL_OPERATION_CONFLICT")
            self._records[record.operation_id] = copy.deepcopy(record)
            return
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO provider_operations(
                        operation_id, provider, connector_id, connection_id,
                        external_operation_id, business_id, project_id, brand_id,
                        payload_json, record_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.operation_id,
                        record.provider,
                        record.connector_id,
                        record.connection_id,
                        record.external_operation_id,
                        record.business_id,
                        record.project_id,
                        record.brand_id,
                        self._serialize(record),
                        record.record_hash,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ProviderOperationConflictError("PROVIDER_OPERATION_CONFLICT") from exc
        except sqlite3.Error as exc:
            raise ProviderOperationStoreError("PROVIDER_OPERATION_INSERT_FAILED") from exc

    def _replace_locked(
        self,
        record: ProviderOperationRecord,
        *,
        expected_record_hash: Optional[str] = None,
    ) -> None:
        if self._conn is None:
            try:
                existing = self._records[record.operation_id]
            except KeyError as exc:
                raise ProviderOperationNotFoundError(record.operation_id) from exc
            if expected_record_hash is not None and existing.record_hash != expected_record_hash:
                raise ProviderOperationConflictError("PROVIDER_OPERATION_CONCURRENT_UPDATE")
            self._records[record.operation_id] = copy.deepcopy(record)
            return
        try:
            with self._conn:
                if expected_record_hash is None:
                    cursor = self._conn.execute(
                        """
                        UPDATE provider_operations
                        SET payload_json = ?, record_hash = ?
                        WHERE operation_id = ?
                        """,
                        (self._serialize(record), record.record_hash, record.operation_id),
                    )
                else:
                    cursor = self._conn.execute(
                        """
                        UPDATE provider_operations
                        SET payload_json = ?, record_hash = ?
                        WHERE operation_id = ? AND record_hash = ?
                        """,
                        (
                            self._serialize(record),
                            record.record_hash,
                            record.operation_id,
                            expected_record_hash,
                        ),
                    )
                if cursor.rowcount != 1:
                    if expected_record_hash is not None:
                        exists = self._conn.execute(
                            "SELECT 1 FROM provider_operations WHERE operation_id = ?",
                            (record.operation_id,),
                        ).fetchone()
                        if exists is not None:
                            raise ProviderOperationConflictError("PROVIDER_OPERATION_CONCURRENT_UPDATE")
                    raise ProviderOperationNotFoundError(record.operation_id)
        except (ProviderOperationNotFoundError, ProviderOperationConflictError):
            raise
        except sqlite3.Error as exc:
            raise ProviderOperationStoreError("PROVIDER_OPERATION_UPDATE_FAILED") from exc

    def create(
        self,
        *,
        provider: str,
        connector_id: str,
        connection_id: str,
        capability_id: str,
        action: str,
        external_operation_id: str,
        business_id: str,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        provider_status: str = "SUBMITTED",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ProviderOperationRecord:
        self._ensure_open()
        now = _now_iso()
        record = self._with_hash(
            ProviderOperationRecord(
                operation_id=self._new_operation_id(),
                provider=provider,
                connector_id=connector_id,
                connection_id=connection_id,
                capability_id=capability_id,
                action=action,
                external_operation_id=external_operation_id,
                business_id=business_id,
                project_id=project_id,
                brand_id=brand_id,
                state=ProviderOperationState.SUBMITTED,
                provider_status=provider_status,
                idempotency_key_hash=_idempotency_hash(idempotency_key),
                metadata=_safe_metadata(metadata),
                created_at=now,
                updated_at=now,
            )
        )
        with self._lock:
            self._insert_locked(record)
        return copy.deepcopy(record)

    def get(self, operation_id: str) -> ProviderOperationRecord:
        self._ensure_open()
        with self._lock:
            if self._conn is None:
                try:
                    return copy.deepcopy(self._verify(self._records[operation_id]))
                except KeyError as exc:
                    raise ProviderOperationNotFoundError(operation_id) from exc
            try:
                row = self._conn.execute(
                    "SELECT * FROM provider_operations WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise ProviderOperationStoreError("PROVIDER_OPERATION_READ_FAILED") from exc
            if row is None:
                raise ProviderOperationNotFoundError(operation_id)
            return copy.deepcopy(self._row_record(row))

    def find_external(
        self,
        *,
        provider: str,
        connection_id: str,
        external_operation_id: str,
        business_id: str,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> ProviderOperationRecord:
        self._ensure_open()
        provider_n = _required_identifier("provider", provider).lower()
        connection_n = _required_identifier("connection_id", connection_id)
        external_n = _required_identifier("external_operation_id", external_operation_id)
        business_n = _required_identifier("business_id", business_id)
        project_n = _optional_identifier("project_id", project_id)
        brand_n = _optional_identifier("brand_id", brand_id)
        with self._lock:
            if self._conn is None:
                candidates = [
                    copy.deepcopy(self._verify(item))
                    for item in self._records.values()
                    if item.provider == provider_n
                    and item.connection_id == connection_n
                    and item.external_operation_id == external_n
                ]
            else:
                try:
                    rows = self._conn.execute(
                        """
                        SELECT * FROM provider_operations
                        WHERE provider = ? AND connection_id = ? AND external_operation_id = ?
                        """,
                        (provider_n, connection_n, external_n),
                    ).fetchall()
                except sqlite3.Error as exc:
                    raise ProviderOperationStoreError("PROVIDER_OPERATION_LOOKUP_FAILED") from exc
                candidates = [self._row_record(row) for row in rows]
        if not candidates:
            raise ProviderOperationNotFoundError(external_n)
        if len(candidates) != 1:
            raise ProviderOperationIntegrityError("PROVIDER_OPERATION_DUPLICATE_EXTERNAL_ID")
        record = candidates[0]
        if (
            record.business_id != business_n
            or record.project_id != project_n
            or record.brand_id != brand_n
        ):
            raise ProviderOperationScopeError("PROVIDER_OPERATION_SCOPE_MISMATCH")
        return copy.deepcopy(record)

    @staticmethod
    def _validate_transition(current: ProviderOperationState, target: ProviderOperationState) -> None:
        if current.terminal:
            if target != current:
                raise ProviderOperationConflictError(
                    f"PROVIDER_OPERATION_TERMINAL_STATE: {current.value} -> {target.value}"
                )
            return
        allowed = {
            ProviderOperationState.SUBMITTED: {
                ProviderOperationState.SUBMITTED,
                ProviderOperationState.PROCESSING,
                ProviderOperationState.UNKNOWN,
                ProviderOperationState.SUCCEEDED,
                ProviderOperationState.FAILED,
            },
            ProviderOperationState.PROCESSING: {
                ProviderOperationState.PROCESSING,
                ProviderOperationState.UNKNOWN,
                ProviderOperationState.SUCCEEDED,
                ProviderOperationState.FAILED,
            },
            ProviderOperationState.UNKNOWN: {
                ProviderOperationState.UNKNOWN,
                ProviderOperationState.PROCESSING,
                ProviderOperationState.SUCCEEDED,
                ProviderOperationState.FAILED,
            },
        }
        if target not in allowed.get(current, set()):
            raise ProviderOperationConflictError(
                f"PROVIDER_OPERATION_INVALID_TRANSITION: {current.value} -> {target.value}"
            )

    def record_status(
        self,
        operation_id: str,
        *,
        state: ProviderOperationState,
        provider_status: str,
        metadata: Optional[Mapping[str, Any]] = None,
        polled: bool = True,
    ) -> ProviderOperationRecord:
        self._ensure_open()
        target = state if isinstance(state, ProviderOperationState) else ProviderOperationState(str(state))
        current = self.get(operation_id)
        self._validate_transition(current.state, target)
        now = _now_iso()
        merged_metadata = dict(current.metadata)
        merged_metadata.update(_safe_metadata(metadata))
        updated = self._with_hash(
            replace(
                current,
                state=target,
                provider_status=str(provider_status or "").strip().upper(),
                metadata=merged_metadata,
                updated_at=now,
                last_polled_at=now if polled else current.last_polled_at,
                poll_count=current.poll_count + (1 if polled else 0),
                record_hash="",
            )
        )
        with self._lock:
            # Re-read under the write lock to reject concurrent terminal/state changes.
            latest = self.get(operation_id)
            if latest.record_hash != current.record_hash:
                raise ProviderOperationConflictError("PROVIDER_OPERATION_CONCURRENT_UPDATE")
            self._replace_locked(updated, expected_record_hash=current.record_hash)
        return copy.deepcopy(updated)

    def list_scope(
        self,
        *,
        business_id: str,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> List[ProviderOperationRecord]:
        self._ensure_open()
        business_n = _required_identifier("business_id", business_id)
        project_n = _optional_identifier("project_id", project_id)
        brand_n = _optional_identifier("brand_id", brand_id)
        provider_n = _required_identifier("provider", provider).lower() if provider else None
        with self._lock:
            if self._conn is None:
                records = [copy.deepcopy(self._verify(item)) for item in self._records.values()]
            else:
                try:
                    rows = self._conn.execute(
                        "SELECT * FROM provider_operations ORDER BY rowid"
                    ).fetchall()
                except sqlite3.Error as exc:
                    raise ProviderOperationStoreError("PROVIDER_OPERATION_LIST_FAILED") from exc
                records = [self._row_record(row) for row in rows]
        return [
            copy.deepcopy(item)
            for item in records
            if item.business_id == business_n
            and item.project_id == project_n
            and item.brand_id == brand_n
            and (provider_n is None or item.provider == provider_n)
        ]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._conn is not None:
                self._conn.close()
            self._closed = True