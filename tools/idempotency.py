"""Durable idempotency reservations for real consequential tool actions.

The ledger is intentionally provider-neutral. It stores only hashes of the raw
idempotency key and semantic request payload. When the Tool Gateway uses a
file-backed ExecutionReceiptRepository, this ledger creates its table in the
same SQLite database file so idempotency evidence survives process restarts.

A reservation is conservative: once a key is reserved for an exact trusted
scope/capability/connection namespace, automatic replay with that key is
blocked even if a later crash happened before the provider result was known.
Operators may choose a new key after inspecting durable execution evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from governance.redaction import sanitize_sensitive_text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _hash(payload: Any) -> str:
    raw = payload if isinstance(payload, str) else _canonical_json(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IdempotencyStoreError(RuntimeError):
    """Base failure for idempotency persistence or state transitions."""


class IdempotencyConflictError(IdempotencyStoreError):
    """Stable conflict raised when a reserved key is presented again."""

    def __init__(self, code: str, message: str, record: "IdempotencyRecord") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.record = record


class IdempotencyState(str, Enum):
    RESERVED = "RESERVED"
    DISPATCHING = "DISPATCHING"
    FINALIZED = "FINALIZED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class IdempotencyRecord:
    reservation_id: str
    namespace_hash: str
    key_hash: str
    request_fingerprint: str
    state: IdempotencyState = IdempotencyState.RESERVED
    created_at: str = ""
    updated_at: str = ""

    def normalized(self) -> "IdempotencyRecord":
        state = self.state
        if not isinstance(state, IdempotencyState):
            state = IdempotencyState(str(state).strip().upper())
        required = {
            "reservation_id": self.reservation_id,
            "namespace_hash": self.namespace_hash,
            "key_hash": self.key_hash,
            "request_fingerprint": self.request_fingerprint,
        }
        for name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise IdempotencyStoreError(f"IDEMPOTENCY_{name.upper()}_REQUIRED")
        created_at = self.created_at or _utc_now_iso()
        return replace(
            self,
            reservation_id=self.reservation_id.strip(),
            namespace_hash=self.namespace_hash.strip().lower(),
            key_hash=self.key_hash.strip().lower(),
            request_fingerprint=self.request_fingerprint.strip().lower(),
            state=state,
            created_at=created_at,
            updated_at=self.updated_at or created_at,
        )


class IdempotencyLedger:
    """Fail-closed idempotency ledger with in-memory and SQLite modes."""

    def __init__(self, database_path: Optional[str | Path] = None) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, IdempotencyRecord] = {}
        self.database_path = (
            Path(database_path).expanduser().resolve() if database_path is not None else None
        )
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize_schema()

    @property
    def durable(self) -> bool:
        return self.database_path is not None

    def _connect(self) -> sqlite3.Connection:
        if self.database_path is None:
            raise IdempotencyStoreError("IDEMPOTENCY_LEDGER_NOT_DURABLE")
        conn = sqlite3.connect(str(self.database_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize_schema(self) -> None:
        try:
            with closing(self._connect()) as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS idempotency_ledger (
                            reservation_id TEXT PRIMARY KEY,
                            namespace_hash TEXT NOT NULL,
                            key_hash TEXT NOT NULL,
                            request_fingerprint TEXT NOT NULL,
                            state TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_idempotency_state "
                        "ON idempotency_ledger(state, reservation_id)"
                    )
        except sqlite3.Error as exc:
            raise IdempotencyStoreError(
                "IDEMPOTENCY_STORE_INIT_FAILED: " + sanitize_sensitive_text(str(exc))
            ) from exc

    @staticmethod
    def semantic_fingerprint(
        *,
        capability_id: str,
        provider: str,
        parameters: Dict[str, Any],
        business_id: Optional[str],
        project_id: Optional[str],
        brand_id: Optional[str],
    ) -> str:
        """Hash logical action content while deliberately excluding run/agent/request ids."""
        return _hash(
            {
                "schema_version": 1,
                "capability_id": str(capability_id or "").strip().lower(),
                "provider": str(provider or "").strip().lower(),
                "business_id": str(business_id or "").strip(),
                "project_id": str(project_id or "").strip(),
                "brand_id": str(brand_id or "").strip(),
                "parameters": parameters,
            }
        )

    @staticmethod
    def reservation_identity(
        *,
        capability_id: str,
        provider: str,
        idempotency_key: str,
        connection_id: Optional[str],
        business_id: Optional[str],
        project_id: Optional[str],
        brand_id: Optional[str],
    ) -> tuple[str, str, str]:
        """Return opaque reservation id, namespace hash, and key hash.

        The raw key is never persisted or embedded in the reservation id.
        Run/agent/request identifiers are intentionally excluded so replay from a
        new run or newly-approved request collides with the existing reservation.
        """
        key = str(idempotency_key or "").strip()
        if not key:
            raise IdempotencyStoreError("IDEMPOTENCY_KEY_REQUIRED")
        key_hash = _hash(key)
        namespace = {
            "schema_version": 1,
            "capability_id": str(capability_id or "").strip().lower(),
            "provider": str(provider or "").strip().lower(),
            "connection_id": str(connection_id or "").strip().lower(),
            "business_id": str(business_id or "").strip(),
            "project_id": str(project_id or "").strip(),
            "brand_id": str(brand_id or "").strip(),
            "key_hash": key_hash,
        }
        namespace_hash = _hash(namespace)
        reservation_id = f"IDEM-{namespace_hash[:32].upper()}"
        return reservation_id, namespace_hash, key_hash

    @staticmethod
    def _from_row(row: sqlite3.Row) -> IdempotencyRecord:
        return IdempotencyRecord(
            reservation_id=row["reservation_id"],
            namespace_hash=row["namespace_hash"],
            key_hash=row["key_hash"],
            request_fingerprint=row["request_fingerprint"],
            state=IdempotencyState(row["state"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        ).normalized()

    def _conflict(self, existing: IdempotencyRecord, request_fingerprint: str) -> None:
        if existing.request_fingerprint == request_fingerprint:
            raise IdempotencyConflictError(
                "IDEMPOTENCY_REPLAY_BLOCKED",
                "This idempotency key is already reserved for the same governed action; automatic replay is forbidden.",
                copy.deepcopy(existing),
            )
        raise IdempotencyConflictError(
            "IDEMPOTENCY_KEY_CONFLICT",
            "This idempotency key is already reserved for a different governed action in the same trusted namespace.",
            copy.deepcopy(existing),
        )

    def reserve(
        self,
        *,
        capability_id: str,
        provider: str,
        idempotency_key: str,
        connection_id: Optional[str],
        parameters: Dict[str, Any],
        business_id: Optional[str],
        project_id: Optional[str],
        brand_id: Optional[str],
    ) -> IdempotencyRecord:
        reservation_id, namespace_hash, key_hash = self.reservation_identity(
            capability_id=capability_id,
            provider=provider,
            idempotency_key=idempotency_key,
            connection_id=connection_id,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        fingerprint = self.semantic_fingerprint(
            capability_id=capability_id,
            provider=provider,
            parameters=parameters,
            business_id=business_id,
            project_id=project_id,
            brand_id=brand_id,
        )
        record = IdempotencyRecord(
            reservation_id=reservation_id,
            namespace_hash=namespace_hash,
            key_hash=key_hash,
            request_fingerprint=fingerprint,
        ).normalized()

        with self._lock:
            if self.database_path is None:
                existing = self._records.get(reservation_id)
                if existing is not None:
                    self._conflict(existing, fingerprint)
                self._records[reservation_id] = record
                return copy.deepcopy(record)

            try:
                with closing(self._connect()) as conn:
                    with conn:
                        existing_row = conn.execute(
                            "SELECT * FROM idempotency_ledger WHERE reservation_id=?",
                            (reservation_id,),
                        ).fetchone()
                        if existing_row is not None:
                            self._conflict(self._from_row(existing_row), fingerprint)
                        conn.execute(
                            """
                            INSERT INTO idempotency_ledger(
                                reservation_id, namespace_hash, key_hash,
                                request_fingerprint, state, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record.reservation_id,
                                record.namespace_hash,
                                record.key_hash,
                                record.request_fingerprint,
                                record.state.value,
                                record.created_at,
                                record.updated_at,
                            ),
                        )
                return record
            except IdempotencyConflictError:
                raise
            except sqlite3.IntegrityError:
                # A concurrent writer may have won after the SELECT. Re-read and
                # classify without ever allowing a second reservation.
                existing = self.get(reservation_id)
                if existing is not None:
                    self._conflict(existing, fingerprint)
                raise IdempotencyStoreError("IDEMPOTENCY_RESERVATION_CONFLICT")
            except sqlite3.Error as exc:
                raise IdempotencyStoreError(
                    "IDEMPOTENCY_RESERVE_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc

    def get(self, reservation_id: str) -> Optional[IdempotencyRecord]:
        key = str(reservation_id or "").strip()
        if not key:
            return None
        with self._lock:
            if self.database_path is None:
                record = self._records.get(key)
                return copy.deepcopy(record) if record is not None else None
            try:
                with closing(self._connect()) as conn:
                    row = conn.execute(
                        "SELECT * FROM idempotency_ledger WHERE reservation_id=?",
                        (key,),
                    ).fetchone()
                return self._from_row(row) if row is not None else None
            except sqlite3.Error as exc:
                raise IdempotencyStoreError(
                    "IDEMPOTENCY_GET_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc

    def list_records(self) -> List[IdempotencyRecord]:
        with self._lock:
            if self.database_path is None:
                return copy.deepcopy(list(self._records.values()))
            try:
                with closing(self._connect()) as conn:
                    rows = conn.execute(
                        "SELECT * FROM idempotency_ledger ORDER BY rowid"
                    ).fetchall()
                return [self._from_row(row) for row in rows]
            except sqlite3.Error as exc:
                raise IdempotencyStoreError(
                    "IDEMPOTENCY_LIST_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc

    def release_reserved(self, reservation_id: str) -> None:
        """Release a reservation only while dispatch is provably not started."""
        key = str(reservation_id or "").strip()
        if not key:
            raise IdempotencyStoreError("IDEMPOTENCY_RESERVATION_ID_REQUIRED")

        with self._lock:
            if self.database_path is None:
                current = self._records.get(key)
                if current is None:
                    raise IdempotencyStoreError(
                        f"IDEMPOTENCY_RESERVATION_NOT_FOUND: reservation_id={key}"
                    )
                if current.state != IdempotencyState.RESERVED:
                    raise IdempotencyStoreError(
                        "IDEMPOTENCY_RELEASE_FORBIDDEN: "
                        f"reservation_id={key} state={current.state.value}"
                    )
                del self._records[key]
                return

            try:
                with closing(self._connect()) as conn:
                    with conn:
                        cur = conn.execute(
                            "DELETE FROM idempotency_ledger "
                            "WHERE reservation_id=? AND state=?",
                            (key, IdempotencyState.RESERVED.value),
                        )
                        if cur.rowcount == 1:
                            return
                        row = conn.execute(
                            "SELECT state FROM idempotency_ledger WHERE reservation_id=?",
                            (key,),
                        ).fetchone()
                        if row is None:
                            raise IdempotencyStoreError(
                                f"IDEMPOTENCY_RESERVATION_NOT_FOUND: reservation_id={key}"
                            )
                        raise IdempotencyStoreError(
                            "IDEMPOTENCY_RELEASE_FORBIDDEN: "
                            f"reservation_id={key} state={row['state']}"
                        )
            except IdempotencyStoreError:
                raise
            except sqlite3.Error as exc:
                raise IdempotencyStoreError(
                    "IDEMPOTENCY_RELEASE_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc

    def _transition(self, reservation_id: str, target: IdempotencyState) -> IdempotencyRecord:
        with self._lock:
            current = self.get(reservation_id)
            if current is None:
                raise IdempotencyStoreError(
                    f"IDEMPOTENCY_RESERVATION_NOT_FOUND: reservation_id={reservation_id}"
                )
            if current.state == target:
                return current
            allowed = {
                IdempotencyState.RESERVED: {IdempotencyState.DISPATCHING},
                IdempotencyState.DISPATCHING: {
                    IdempotencyState.FINALIZED,
                    IdempotencyState.AMBIGUOUS,
                },
            }
            if target not in allowed.get(current.state, set()):
                raise IdempotencyStoreError(
                    "IDEMPOTENCY_INVALID_TRANSITION: "
                    f"reservation_id={reservation_id} state={current.state.value} target={target.value}"
                )
            updated = replace(current, state=target, updated_at=_utc_now_iso()).normalized()

            if self.database_path is None:
                self._records[reservation_id] = updated
                return copy.deepcopy(updated)
            try:
                with closing(self._connect()) as conn:
                    with conn:
                        cur = conn.execute(
                            "UPDATE idempotency_ledger SET state=?, updated_at=? "
                            "WHERE reservation_id=? AND state=?",
                            (
                                updated.state.value,
                                updated.updated_at,
                                reservation_id,
                                current.state.value,
                            ),
                        )
                        if cur.rowcount != 1:
                            raise IdempotencyStoreError(
                                "IDEMPOTENCY_CONCURRENT_TRANSITION_CONFLICT: "
                                f"reservation_id={reservation_id}"
                            )
                return updated
            except IdempotencyStoreError:
                raise
            except sqlite3.Error as exc:
                raise IdempotencyStoreError(
                    "IDEMPOTENCY_TRANSITION_FAILED: " + sanitize_sensitive_text(str(exc))
                ) from exc

    def mark_dispatching(self, reservation_id: str) -> IdempotencyRecord:
        return self._transition(reservation_id, IdempotencyState.DISPATCHING)

    def settle(self, reservation_id: str, *, ambiguous: bool = False) -> IdempotencyRecord:
        return self._transition(
            reservation_id,
            IdempotencyState.AMBIGUOUS if ambiguous else IdempotencyState.FINALIZED,
        )
