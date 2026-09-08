"""Durable Mission-wide execution leases with monotonic fencing.

A wake lease says which worker owns one wake record.  A Mission lease is the
stronger control-plane authority: only one worker may own a long-lived Mission
execution cycle at a time, even when multiple wakes/events arrive concurrently.

The fencing token increases on every new acquisition.  Consumers must carry the
exact lease record forward and validate it before authoritative resume/handoff
operations so a worker that lost its lease cannot continue after a takeover.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Optional, Sequence

from runtime.mission import TERMINAL_MISSION_STATUSES
from runtime.mission_store import MissionStore


class MissionLeaseAuthorityError(RuntimeError):
    """Raised when lease access is not bound to canonical Mission scope."""


class MissionLeaseStateError(RuntimeError):
    """Raised when a new lease cannot be acquired for current Mission state."""


class MissionLeaseLostError(RuntimeError):
    """Raised when a caller no longer owns the exact live fenced lease."""


class MissionLeaseCorruptionError(RuntimeError):
    """Raised when durable lease authority cannot be decoded safely."""


@dataclass(frozen=True)
class MissionLeaseRecord:
    mission_id: str
    business_id: str
    project_id: Optional[str]
    lease_owner: Optional[str]
    lease_token: Optional[str]
    lease_expires_at: Optional[datetime]
    fencing_token: int
    created_at: datetime
    updated_at: datetime

    @property
    def leased(self) -> bool:
        return bool(self.lease_owner and self.lease_token and self.lease_expires_at)


def _aware_utc(value: object, *, code: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(code)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(code)
    return value.astimezone(timezone.utc)


def _encode_time(value: datetime) -> str:
    return _aware_utc(
        value,
        code="MISSION_LEASE_TIME_MUST_BE_TIMEZONE_AWARE",
    ).isoformat()


def _decode_time(value: Optional[str], *, nullable: bool = False) -> Optional[datetime]:
    if value is None:
        if nullable:
            return None
        raise MissionLeaseCorruptionError("MISSION_LEASE_TIMESTAMP_MISSING")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise MissionLeaseCorruptionError("MISSION_LEASE_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MissionLeaseCorruptionError(
            "MISSION_LEASE_TIMESTAMP_NOT_TIMEZONE_AWARE"
        )
    return parsed.astimezone(timezone.utc)


class DurableMissionLeaseStore:
    """SQLite authority for one fenced execution lease per Mission."""

    _COLUMNS = (
        "mission_id, business_id, project_id, lease_owner, lease_token, "
        "lease_expires_at, fencing_token, created_at, updated_at"
    )

    def __init__(self, *, database_path: str, mission_store: MissionStore) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("MISSION_LEASE_DATABASE_PATH_REQUIRED")
        if database_path == ":memory:":
            raise ValueError("MISSION_LEASE_REQUIRES_DURABLE_DATABASE_PATH")
        if not isinstance(mission_store, MissionStore):
            raise TypeError("MISSION_LEASE_REQUIRES_MISSION_STORE")

        self._database_path = str(Path(database_path).expanduser())
        Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
        self._mission_store = mission_store
        self._lock = RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self._database_path,
            timeout=30.0,
            check_same_thread=False,
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mission_leases (
                mission_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                project_id TEXT NULL,
                lease_owner TEXT NULL,
                lease_token TEXT NULL,
                lease_expires_at TEXT NULL,
                fencing_token INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mission_leases_scope "
            "ON mission_leases(business_id, project_id, mission_id)"
        )
        self._connection.commit()
        self._mission_store.bind_execution_lease_database(self._database_path)

    @property
    def durable(self) -> bool:
        return True

    @property
    def database_path(self) -> str:
        return self._database_path

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("MISSION_LEASE_STORE_CLOSED")

    @staticmethod
    def _row_to_record(row: Sequence[object]) -> MissionLeaseRecord:
        if len(row) != 9:
            raise MissionLeaseCorruptionError("MISSION_LEASE_ROW_SHAPE_INVALID")
        try:
            fencing_token = int(row[6])
            if fencing_token < 1:
                raise ValueError("fencing_token")
            created_at = _decode_time(str(row[7]))
            updated_at = _decode_time(str(row[8]))
            lease_expires_at = _decode_time(
                None if row[5] is None else str(row[5]),
                nullable=True,
            )
        except (TypeError, ValueError) as exc:
            raise MissionLeaseCorruptionError("MISSION_LEASE_ROW_INVALID") from exc

        assert created_at is not None
        assert updated_at is not None
        record = MissionLeaseRecord(
            mission_id=str(row[0]),
            business_id=str(row[1]),
            project_id=None if row[2] is None else str(row[2]),
            lease_owner=None if row[3] is None else str(row[3]),
            lease_token=None if row[4] is None else str(row[4]),
            lease_expires_at=lease_expires_at,
            fencing_token=fencing_token,
            created_at=created_at,
            updated_at=updated_at,
        )
        if not record.mission_id or not record.business_id:
            raise MissionLeaseCorruptionError("MISSION_LEASE_SCOPE_MISSING")
        populated = (
            record.lease_owner is not None,
            record.lease_token is not None,
            record.lease_expires_at is not None,
        )
        if any(populated) and not all(populated):
            raise MissionLeaseCorruptionError("MISSION_LEASE_AUTHORITY_INCOMPLETE")
        return record

    def _row_locked(self, mission_id: str) -> Optional[Sequence[object]]:
        return self._connection.execute(
            f"SELECT {self._COLUMNS} FROM mission_leases WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()

    def _require_mission_authority(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
        allow_terminal: bool = False,
    ) -> None:
        mission = self._mission_store.get_mission(
            mission_id,
            business_id=business_id,
            project_id=project_id,
        )
        if mission is None:
            raise MissionLeaseAuthorityError("MISSION_LEASE_SCOPE_NOT_AUTHORIZED")
        if not allow_terminal and mission.status in TERMINAL_MISSION_STATUSES:
            raise MissionLeaseStateError(
                f"MISSION_LEASE_TERMINAL_MISSION: {mission.status.value}"
            )

    @staticmethod
    def _validate_lease_seconds(value: object) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("MISSION_LEASE_SECONDS_INVALID")
        seconds = float(value)
        if seconds <= 0 or seconds > 86400:
            raise ValueError("MISSION_LEASE_SECONDS_INVALID")
        return seconds

    def acquire(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
        worker_id: str,
        lease_seconds: float = 60.0,
        now: Optional[datetime] = None,
    ) -> MissionLeaseRecord:
        """Acquire or crash-reclaim a Mission lease and advance its fence."""

        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("MISSION_LEASE_MISSION_ID_REQUIRED")
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("MISSION_LEASE_BUSINESS_ID_REQUIRED")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("MISSION_LEASE_WORKER_ID_REQUIRED")
        seconds = self._validate_lease_seconds(lease_seconds)
        reference = _aware_utc(
            now or datetime.now(timezone.utc),
            code="MISSION_LEASE_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        self._require_mission_authority(
            mission_id=mission_id,
            business_id=business_id,
            project_id=project_id,
        )

        encoded_now = _encode_time(reference)
        encoded_expiry = _encode_time(reference + timedelta(seconds=seconds))
        new_token = uuid.uuid4().hex

        with self._lock:
            self._require_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._row_locked(mission_id)
                if row is None:
                    self._connection.execute(
                        """
                        INSERT INTO mission_leases(
                            mission_id, business_id, project_id,
                            lease_owner, lease_token, lease_expires_at,
                            fencing_token, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            mission_id,
                            business_id,
                            project_id,
                            worker_id.strip(),
                            new_token,
                            encoded_expiry,
                            encoded_now,
                            encoded_now,
                        ),
                    )
                else:
                    current = self._row_to_record(row)
                    if (
                        current.business_id != business_id
                        or current.project_id != project_id
                    ):
                        raise MissionLeaseCorruptionError(
                            "MISSION_LEASE_PERSISTED_SCOPE_MISMATCH"
                        )
                    if (
                        current.leased
                        and current.lease_expires_at is not None
                        and current.lease_expires_at > reference
                    ):
                        raise MissionLeaseStateError("MISSION_LEASE_ALREADY_OWNED")
                    self._connection.execute(
                        """
                        UPDATE mission_leases
                        SET lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                            fencing_token = fencing_token + 1, updated_at = ?
                        WHERE mission_id = ?
                        """,
                        (
                            worker_id.strip(),
                            new_token,
                            encoded_expiry,
                            encoded_now,
                            mission_id,
                        ),
                    )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            acquired_row = self._row_locked(mission_id)
        assert acquired_row is not None
        return self._row_to_record(acquired_row)

    def get(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
    ) -> Optional[MissionLeaseRecord]:
        """Return a detached lease snapshot only for exact canonical scope."""

        if not mission_id or not business_id:
            return None
        with self._lock:
            self._require_open()
            row = self._connection.execute(
                f"""
                SELECT {self._COLUMNS}
                FROM mission_leases
                WHERE mission_id = ? AND business_id = ?
                  AND ((project_id IS NULL AND ? IS NULL) OR project_id = ?)
                """,
                (mission_id, business_id, project_id, project_id),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def _require_exact_live_lease_locked(
        self,
        lease: MissionLeaseRecord,
        *,
        now: datetime,
    ) -> MissionLeaseRecord:
        if not isinstance(lease, MissionLeaseRecord):
            raise MissionLeaseLostError("MISSION_LEASE_RECORD_REQUIRED")
        row = self._row_locked(lease.mission_id)
        if row is None:
            raise MissionLeaseLostError("MISSION_LEASE_NOT_FOUND")
        current = self._row_to_record(row)
        if (
            current.business_id != lease.business_id
            or current.project_id != lease.project_id
            or current.lease_owner != lease.lease_owner
            or current.lease_token != lease.lease_token
            or current.fencing_token != lease.fencing_token
            or current.lease_expires_at is None
            or current.lease_expires_at <= now
        ):
            raise MissionLeaseLostError("MISSION_LEASE_LOST_OR_EXPIRED")
        return current

    def validate(
        self,
        lease: MissionLeaseRecord,
        *,
        now: Optional[datetime] = None,
    ) -> MissionLeaseRecord:
        """Revalidate exact owner/token/fence before an authoritative operation."""

        reference = _aware_utc(
            now or datetime.now(timezone.utc),
            code="MISSION_LEASE_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        self._require_mission_authority(
            mission_id=lease.mission_id,
            business_id=lease.business_id,
            project_id=lease.project_id,
        )
        with self._lock:
            self._require_open()
            return self._require_exact_live_lease_locked(lease, now=reference)

    def renew(
        self,
        lease: MissionLeaseRecord,
        *,
        lease_seconds: float = 60.0,
        now: Optional[datetime] = None,
    ) -> MissionLeaseRecord:
        """Extend a live lease without changing its fencing epoch."""

        seconds = self._validate_lease_seconds(lease_seconds)
        reference = _aware_utc(
            now or datetime.now(timezone.utc),
            code="MISSION_LEASE_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        encoded_now = _encode_time(reference)
        with self._lock:
            self._require_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                current = self._require_exact_live_lease_locked(lease, now=reference)
                assert current.lease_expires_at is not None
                base = max(current.lease_expires_at, reference)
                new_expiry = _encode_time(base + timedelta(seconds=seconds))
                updated = self._connection.execute(
                    """
                    UPDATE mission_leases
                    SET lease_expires_at = ?, updated_at = ?
                    WHERE mission_id = ? AND lease_owner = ? AND lease_token = ?
                      AND fencing_token = ?
                    """,
                    (
                        new_expiry,
                        encoded_now,
                        lease.mission_id,
                        lease.lease_owner,
                        lease.lease_token,
                        lease.fencing_token,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionLeaseLostError("MISSION_LEASE_CHANGED_DURING_RENEWAL")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            row = self._row_locked(lease.mission_id)
        assert row is not None
        return self._row_to_record(row)

    def release(
        self,
        lease: MissionLeaseRecord,
        *,
        now: Optional[datetime] = None,
    ) -> MissionLeaseRecord:
        """Release only the exact current live fenced lease."""

        reference = _aware_utc(
            now or datetime.now(timezone.utc),
            code="MISSION_LEASE_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        encoded_now = _encode_time(reference)
        with self._lock:
            self._require_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._require_exact_live_lease_locked(lease, now=reference)
                updated = self._connection.execute(
                    """
                    UPDATE mission_leases
                    SET lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, updated_at = ?
                    WHERE mission_id = ? AND lease_owner = ? AND lease_token = ?
                      AND fencing_token = ?
                    """,
                    (
                        encoded_now,
                        lease.mission_id,
                        lease.lease_owner,
                        lease.lease_token,
                        lease.fencing_token,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionLeaseLostError("MISSION_LEASE_CHANGED_DURING_RELEASE")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            row = self._row_locked(lease.mission_id)
        assert row is not None
        return self._row_to_record(row)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._connection.commit()
            finally:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "DurableMissionLeaseStore":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()