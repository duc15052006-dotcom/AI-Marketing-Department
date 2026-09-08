"""Durable time-based wake scheduling for long-lived Missions.

This module is Continuity Runtime infrastructure, not Brain logic.  It owns a
small authority boundary between durable Mission state and future wake work:

* wake records survive process restart;
* wake identity is bound to canonical Mission business/project scope;
* due work is claimed through bounded leases rather than destructive dequeue;
* expired leases can be reclaimed after worker/process loss;
* stale lease owners cannot acknowledge work after authority has moved.

The scheduler deliberately does not dispatch a Mission, retry external effects,
or reconcile unknown provider outcomes.  Those are later Continuity Runtime
boundaries that consume the durable wake lease produced here.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import List, Optional, Sequence

from runtime.mission import TERMINAL_MISSION_STATUSES, MissionRecord
from runtime.mission_store import MissionStore


class MissionSchedulerAuthorityError(RuntimeError):
    """Raised when a wake operation violates canonical Mission scope."""


class MissionSchedulerStateError(RuntimeError):
    """Raised when scheduler state cannot accept the requested transition."""


class MissionSchedulerLeaseError(RuntimeError):
    """Raised when a worker no longer owns the exact live wake lease."""


class MissionSchedulerCorruptionError(RuntimeError):
    """Raised when a persisted scheduler row cannot be decoded safely."""


class WakeState(str, Enum):
    SCHEDULED = "SCHEDULED"
    LEASED = "LEASED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class WakeRecord:
    """Detached immutable view of one durable wake row."""

    wake_id: str
    mission_id: str
    business_id: str
    project_id: Optional[str]
    due_at: datetime
    reason: str
    state: WakeState
    lease_owner: Optional[str]
    lease_token: Optional[str]
    lease_expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    version: int


def _require_aware_datetime(value: object, *, code: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(code)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(code)
    return value.astimezone(timezone.utc)


def _encode_time(value: datetime) -> str:
    return _require_aware_datetime(
        value,
        code="MISSION_SCHEDULER_TIME_MUST_BE_TIMEZONE_AWARE",
    ).isoformat()


def _decode_time(value: Optional[str], *, nullable: bool = False) -> Optional[datetime]:
    if value is None:
        if nullable:
            return None
        raise MissionSchedulerCorruptionError("MISSION_SCHEDULER_TIMESTAMP_MISSING")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise MissionSchedulerCorruptionError(
            "MISSION_SCHEDULER_TIMESTAMP_INVALID"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MissionSchedulerCorruptionError(
            "MISSION_SCHEDULER_TIMESTAMP_NOT_TIMEZONE_AWARE"
        )
    return parsed.astimezone(timezone.utc)


class DurableMissionScheduler:
    """SQLite-backed durable wake queue with crash-recoverable worker leases."""

    _ROW_COLUMNS = (
        "wake_id, mission_id, business_id, project_id, due_at, reason, state, "
        "lease_owner, lease_token, lease_expires_at, created_at, updated_at, version"
    )

    def __init__(self, *, database_path: str, mission_store: MissionStore) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("MISSION_SCHEDULER_DATABASE_PATH_REQUIRED")
        if database_path == ":memory:":
            raise ValueError("MISSION_SCHEDULER_REQUIRES_DURABLE_DATABASE_PATH")
        if not isinstance(mission_store, MissionStore):
            raise TypeError("MISSION_SCHEDULER_REQUIRES_MISSION_STORE")

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
            CREATE TABLE IF NOT EXISTS mission_wakes (
                wake_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                business_id TEXT NOT NULL,
                project_id TEXT NULL,
                due_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                state TEXT NOT NULL,
                lease_owner TEXT NULL,
                lease_token TEXT NULL,
                lease_expires_at TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mission_wakes_due
            ON mission_wakes(state, due_at, lease_expires_at)
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mission_wakes_mission
            ON mission_wakes(mission_id, business_id, project_id)
            """
        )
        self._connection.commit()

    @property
    def durable(self) -> bool:
        return True

    @property
    def database_path(self) -> str:
        return self._database_path

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("MISSION_SCHEDULER_CLOSED")

    @staticmethod
    def _row_to_record(row: Sequence[object]) -> WakeRecord:
        if len(row) != 13:
            raise MissionSchedulerCorruptionError("MISSION_SCHEDULER_ROW_SHAPE_INVALID")
        try:
            state = WakeState(str(row[6]))
            version = int(row[12])
            if version < 1:
                raise ValueError("version")
            due_at = _decode_time(str(row[4]))
            created_at = _decode_time(str(row[10]))
            updated_at = _decode_time(str(row[11]))
            lease_expires = _decode_time(
                None if row[9] is None else str(row[9]),
                nullable=True,
            )
        except (TypeError, ValueError) as exc:
            raise MissionSchedulerCorruptionError(
                "MISSION_SCHEDULER_ROW_INVALID"
            ) from exc

        assert due_at is not None
        assert created_at is not None
        assert updated_at is not None
        record = WakeRecord(
            wake_id=str(row[0]),
            mission_id=str(row[1]),
            business_id=str(row[2]),
            project_id=None if row[3] is None else str(row[3]),
            due_at=due_at,
            reason=str(row[5]),
            state=state,
            lease_owner=None if row[7] is None else str(row[7]),
            lease_token=None if row[8] is None else str(row[8]),
            lease_expires_at=lease_expires,
            created_at=created_at,
            updated_at=updated_at,
            version=version,
        )

        if not record.wake_id or not record.mission_id or not record.business_id:
            raise MissionSchedulerCorruptionError(
                "MISSION_SCHEDULER_AUTHORITY_IDENTITY_MISSING"
            )
        if not record.reason:
            raise MissionSchedulerCorruptionError("MISSION_SCHEDULER_REASON_MISSING")
        if record.state == WakeState.LEASED:
            if not record.lease_owner or not record.lease_token or record.lease_expires_at is None:
                raise MissionSchedulerCorruptionError(
                    "MISSION_SCHEDULER_LEASE_FIELDS_INCOMPLETE"
                )
        elif (
            record.lease_owner is not None
            or record.lease_token is not None
            or record.lease_expires_at is not None
        ):
            raise MissionSchedulerCorruptionError(
                "MISSION_SCHEDULER_NONLEASED_ROW_HAS_LEASE_AUTHORITY"
            )
        return record

    def _get_row_locked(self, wake_id: str) -> Optional[Sequence[object]]:
        return self._connection.execute(
            f"SELECT {self._ROW_COLUMNS} FROM mission_wakes WHERE wake_id = ?",
            (wake_id,),
        ).fetchone()

    def _require_schedulable_mission(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
    ) -> MissionRecord:
        mission = self._mission_store.get_mission(
            mission_id,
            business_id=business_id,
            project_id=project_id,
        )
        if mission is None:
            raise MissionSchedulerAuthorityError(
                "MISSION_SCHEDULER_MISSION_SCOPE_NOT_AUTHORIZED"
            )
        if mission.status in TERMINAL_MISSION_STATUSES:
            raise MissionSchedulerStateError(
                f"MISSION_SCHEDULER_TERMINAL_MISSION: {mission.status.value}"
            )
        return mission

    def schedule_wake(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
        due_at: datetime,
        reason: str,
        wake_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> WakeRecord:
        """Persist one future/immediate wake bound to exact Mission authority."""

        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("MISSION_SCHEDULER_MISSION_ID_REQUIRED")
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("MISSION_SCHEDULER_BUSINESS_ID_REQUIRED")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("MISSION_SCHEDULER_REASON_REQUIRED")
        normalized_due = _require_aware_datetime(
            due_at,
            code="MISSION_SCHEDULER_DUE_AT_MUST_BE_TIMEZONE_AWARE",
        )
        reference = _require_aware_datetime(
            now or datetime.now(timezone.utc),
            code="MISSION_SCHEDULER_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        normalized_wake_id = wake_id or f"WAKE-{uuid.uuid4().hex.upper()}"
        if not isinstance(normalized_wake_id, str) or not normalized_wake_id.strip():
            raise ValueError("MISSION_SCHEDULER_WAKE_ID_REQUIRED")

        self._require_schedulable_mission(
            mission_id=mission_id,
            business_id=business_id,
            project_id=project_id,
        )

        encoded_now = _encode_time(reference)
        with self._lock:
            self._require_open()
            if self._get_row_locked(normalized_wake_id) is not None:
                raise MissionSchedulerStateError("MISSION_SCHEDULER_WAKE_ID_ALREADY_EXISTS")
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO mission_wakes (
                        wake_id, mission_id, business_id, project_id,
                        due_at, reason, state,
                        lease_owner, lease_token, lease_expires_at,
                        created_at, updated_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, 1)
                    """,
                    (
                        normalized_wake_id,
                        mission_id,
                        business_id,
                        project_id,
                        _encode_time(normalized_due),
                        reason.strip(),
                        WakeState.SCHEDULED.value,
                        encoded_now,
                        encoded_now,
                    ),
                )
            row = self._get_row_locked(normalized_wake_id)
        assert row is not None
        return self._row_to_record(row)

    def get_wake(
        self,
        wake_id: str,
        *,
        business_id: str,
        project_id: Optional[str],
    ) -> Optional[WakeRecord]:
        """Read a wake only through exact business/project authority."""

        if not wake_id or not business_id:
            return None
        with self._lock:
            self._require_open()
            row = self._connection.execute(
                f"""
                SELECT {self._ROW_COLUMNS}
                FROM mission_wakes
                WHERE wake_id = ? AND business_id = ?
                  AND ((project_id IS NULL AND ? IS NULL) OR project_id = ?)
                """,
                (wake_id, business_id, project_id, project_id),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def claim_due(
        self,
        *,
        worker_id: str,
        now: Optional[datetime] = None,
        lease_seconds: float = 60.0,
        limit: int = 1,
    ) -> List[WakeRecord]:
        """Atomically lease due wakes; expired leases are eligible for recovery."""

        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("MISSION_SCHEDULER_WORKER_ID_REQUIRED")
        if not isinstance(lease_seconds, (int, float)) or isinstance(lease_seconds, bool):
            raise ValueError("MISSION_SCHEDULER_LEASE_SECONDS_INVALID")
        if lease_seconds <= 0:
            raise ValueError("MISSION_SCHEDULER_LEASE_SECONDS_INVALID")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("MISSION_SCHEDULER_LIMIT_INVALID")

        reference = _require_aware_datetime(
            now or datetime.now(timezone.utc),
            code="MISSION_SCHEDULER_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        encoded_now = _encode_time(reference)
        lease_expiry = _encode_time(reference + timedelta(seconds=float(lease_seconds)))
        claimed: List[WakeRecord] = []

        with self._lock:
            self._require_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                candidates = self._connection.execute(
                    f"""
                    SELECT {self._ROW_COLUMNS}
                    FROM mission_wakes
                    WHERE due_at <= ?
                      AND (
                        state = ?
                        OR (
                          state = ?
                          AND lease_expires_at IS NOT NULL
                          AND lease_expires_at <= ?
                        )
                      )
                    ORDER BY due_at ASC, created_at ASC, wake_id ASC
                    LIMIT ?
                    """,
                    (
                        encoded_now,
                        WakeState.SCHEDULED.value,
                        WakeState.LEASED.value,
                        encoded_now,
                        limit,
                    ),
                ).fetchall()

                for candidate in candidates:
                    current = self._row_to_record(candidate)
                    token = uuid.uuid4().hex
                    updated = self._connection.execute(
                        """
                        UPDATE mission_wakes
                        SET state = ?, lease_owner = ?, lease_token = ?,
                            lease_expires_at = ?, updated_at = ?, version = version + 1
                        WHERE wake_id = ? AND version = ?
                          AND (
                            state = ?
                            OR (
                              state = ?
                              AND lease_expires_at IS NOT NULL
                              AND lease_expires_at <= ?
                            )
                          )
                        """,
                        (
                            WakeState.LEASED.value,
                            worker_id.strip(),
                            token,
                            lease_expiry,
                            encoded_now,
                            current.wake_id,
                            current.version,
                            WakeState.SCHEDULED.value,
                            WakeState.LEASED.value,
                            encoded_now,
                        ),
                    )
                    if updated.rowcount != 1:
                        continue
                    row = self._get_row_locked(current.wake_id)
                    assert row is not None
                    claimed.append(self._row_to_record(row))
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

        # The lease is queue ownership, not Mission execution authority. Before a
        # wake is handed to a dispatcher, re-check durable Mission authority. A
        # Mission that became terminal while sleeping is cancelled instead of
        # being revived by stale scheduled work.
        dispatchable: List[WakeRecord] = []
        for record in claimed:
            mission = self._mission_store.get_mission(
                record.mission_id,
                business_id=record.business_id,
                project_id=record.project_id,
            )
            if mission is None or mission.status in TERMINAL_MISSION_STATUSES:
                self._cancel_claimed_wake(record, now=reference)
                continue
            dispatchable.append(record)
        return dispatchable

    def _cancel_claimed_wake(self, record: WakeRecord, *, now: datetime) -> None:
        encoded_now = _encode_time(now)
        with self._lock:
            self._require_open()
            with self._connection:
                self._connection.execute(
                    """
                    UPDATE mission_wakes
                    SET state = ?, lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, updated_at = ?, version = version + 1
                    WHERE wake_id = ? AND state = ?
                      AND lease_owner = ? AND lease_token = ? AND version = ?
                    """,
                    (
                        WakeState.CANCELLED.value,
                        encoded_now,
                        record.wake_id,
                        WakeState.LEASED.value,
                        record.lease_owner,
                        record.lease_token,
                        record.version,
                    ),
                )

    def acknowledge_wake(
        self,
        *,
        wake_id: str,
        worker_id: str,
        lease_token: str,
        now: Optional[datetime] = None,
    ) -> WakeRecord:
        """Durably acknowledge one wake only while the exact lease is still live."""

        if not wake_id or not worker_id or not lease_token:
            raise MissionSchedulerLeaseError("MISSION_SCHEDULER_LEASE_AUTHORITY_REQUIRED")
        reference = _require_aware_datetime(
            now or datetime.now(timezone.utc),
            code="MISSION_SCHEDULER_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        encoded_now = _encode_time(reference)

        with self._lock:
            self._require_open()
            with self._connection:
                updated = self._connection.execute(
                    """
                    UPDATE mission_wakes
                    SET state = ?, lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, updated_at = ?, version = version + 1
                    WHERE wake_id = ? AND state = ?
                      AND lease_owner = ? AND lease_token = ?
                      AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
                    """,
                    (
                        WakeState.ACKNOWLEDGED.value,
                        encoded_now,
                        wake_id,
                        WakeState.LEASED.value,
                        worker_id,
                        lease_token,
                        encoded_now,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionSchedulerLeaseError(
                        "MISSION_SCHEDULER_LEASE_NOT_OWNED_OR_EXPIRED"
                    )
            row = self._get_row_locked(wake_id)
        assert row is not None
        return self._row_to_record(row)

    def renew_lease(
        self,
        *,
        wake_id: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: float = 60.0,
        now: Optional[datetime] = None,
    ) -> WakeRecord:
        """Extend a currently live lease without allowing a stale owner to revive it."""

        if not wake_id or not worker_id or not lease_token:
            raise MissionSchedulerLeaseError("MISSION_SCHEDULER_LEASE_AUTHORITY_REQUIRED")
        if not isinstance(lease_seconds, (int, float)) or isinstance(lease_seconds, bool):
            raise ValueError("MISSION_SCHEDULER_LEASE_SECONDS_INVALID")
        if lease_seconds <= 0:
            raise ValueError("MISSION_SCHEDULER_LEASE_SECONDS_INVALID")
        reference = _require_aware_datetime(
            now or datetime.now(timezone.utc),
            code="MISSION_SCHEDULER_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        encoded_now = _encode_time(reference)

        with self._lock:
            self._require_open()
            row = self._get_row_locked(wake_id)
            if row is None:
                raise MissionSchedulerLeaseError("MISSION_SCHEDULER_WAKE_NOT_FOUND")
            current = self._row_to_record(row)
            if (
                current.state != WakeState.LEASED
                or current.lease_owner != worker_id
                or current.lease_token != lease_token
                or current.lease_expires_at is None
                or current.lease_expires_at <= reference
            ):
                raise MissionSchedulerLeaseError(
                    "MISSION_SCHEDULER_LEASE_NOT_OWNED_OR_EXPIRED"
                )
            base = max(current.lease_expires_at, reference)
            new_expiry = _encode_time(base + timedelta(seconds=float(lease_seconds)))
            with self._connection:
                updated = self._connection.execute(
                    """
                    UPDATE mission_wakes
                    SET lease_expires_at = ?, updated_at = ?, version = version + 1
                    WHERE wake_id = ? AND state = ?
                      AND lease_owner = ? AND lease_token = ? AND version = ?
                    """,
                    (
                        new_expiry,
                        encoded_now,
                        wake_id,
                        WakeState.LEASED.value,
                        worker_id,
                        lease_token,
                        current.version,
                    ),
                )
                if updated.rowcount != 1:
                    raise MissionSchedulerLeaseError(
                        "MISSION_SCHEDULER_LEASE_CHANGED_DURING_RENEWAL"
                    )
            renewed = self._get_row_locked(wake_id)
        assert renewed is not None
        return self._row_to_record(renewed)

    def cancel_wake(
        self,
        wake_id: str,
        *,
        business_id: str,
        project_id: Optional[str],
        now: Optional[datetime] = None,
    ) -> WakeRecord:
        """Cancel unacknowledged wake work through exact Mission scope authority."""

        if not wake_id or not business_id:
            raise MissionSchedulerAuthorityError(
                "MISSION_SCHEDULER_WAKE_SCOPE_AUTHORITY_REQUIRED"
            )
        reference = _require_aware_datetime(
            now or datetime.now(timezone.utc),
            code="MISSION_SCHEDULER_NOW_MUST_BE_TIMEZONE_AWARE",
        )
        encoded_now = _encode_time(reference)

        with self._lock:
            self._require_open()
            row = self._connection.execute(
                f"""
                SELECT {self._ROW_COLUMNS}
                FROM mission_wakes
                WHERE wake_id = ? AND business_id = ?
                  AND ((project_id IS NULL AND ? IS NULL) OR project_id = ?)
                """,
                (wake_id, business_id, project_id, project_id),
            ).fetchone()
            if row is None:
                raise MissionSchedulerAuthorityError(
                    "MISSION_SCHEDULER_WAKE_SCOPE_NOT_AUTHORIZED"
                )
            current = self._row_to_record(row)
            if current.state == WakeState.CANCELLED:
                return current
            if current.state == WakeState.ACKNOWLEDGED:
                raise MissionSchedulerStateError(
                    "MISSION_SCHEDULER_ACKNOWLEDGED_WAKE_IMMUTABLE"
                )

            with self._connection:
                self._connection.execute(
                    """
                    UPDATE mission_wakes
                    SET state = ?, lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, updated_at = ?, version = version + 1
                    WHERE wake_id = ? AND version = ?
                    """,
                    (
                        WakeState.CANCELLED.value,
                        encoded_now,
                        wake_id,
                        current.version,
                    ),
                )
            cancelled = self._get_row_locked(wake_id)
        assert cancelled is not None
        return self._row_to_record(cancelled)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._connection.commit()
            finally:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "DurableMissionScheduler":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
