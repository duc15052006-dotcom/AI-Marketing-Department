"""Durable source-wake recovery records for Persistent Mission workers.

A bounded semantic callback may finish and durably record its result before the
source wake can schedule its continuation or acknowledge delivery.  This module
persists that callback result under the exact live Mission execution fence so a
reclaimed source wake can finish control-plane delivery without invoking the
semantic callback again.

The records live in the existing checkpoint SQLite database, but in a separate
table.  This keeps checkpoint/recovery state in one durable authority domain
without changing the historical checkpoint schema.  Connections are opened per
operation so the helper owns no process-lifetime SQLite handle.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from runtime.mission_store import MissionStore


class MissionCycleRecoveryAuthorityError(RuntimeError):
    """Raised when a cycle result is not backed by exact live Mission authority."""


class MissionCycleRecoveryStateError(RuntimeError):
    """Raised when one source wake is rebound to a different semantic result."""


class MissionCycleRecoveryCorruptionError(RuntimeError):
    """Raised when persisted cycle-recovery state cannot be decoded safely."""


@dataclass(frozen=True)
class MissionCycleRecoveryRecord:
    source_wake_id: str
    mission_id: str
    business_id: str
    project_id: Optional[str]
    checkpoint_sequence: int
    resume_cursor: str
    state: Dict[str, Any]
    next_wake_id: Optional[str]
    next_wake_at: Optional[datetime]
    next_wake_reason: Optional[str]
    created_at: datetime


class DurableMissionCycleRecoveryStore:
    """Persist semantic wake results before non-atomic delivery finalization."""

    _LEASE_ALIAS = "mission_cycle_recovery_lease_authority"
    _COLUMNS = (
        "source_wake_id, mission_id, business_id, project_id, "
        "checkpoint_sequence, resume_cursor, state_json, "
        "next_wake_id, next_wake_at, next_wake_reason, created_at"
    )

    def __init__(
        self,
        *,
        database_path: str,
        mission_store: MissionStore,
        lease_database_path: str,
    ) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("MISSION_CYCLE_RECOVERY_DATABASE_PATH_REQUIRED")
        if database_path == ":memory:":
            raise ValueError("MISSION_CYCLE_RECOVERY_REQUIRES_DURABLE_DATABASE_PATH")
        if not isinstance(mission_store, MissionStore):
            raise TypeError("MISSION_CYCLE_RECOVERY_REQUIRES_MISSION_STORE")
        if not isinstance(lease_database_path, str) or not lease_database_path.strip():
            raise ValueError("MISSION_CYCLE_RECOVERY_LEASE_DATABASE_PATH_REQUIRED")
        if lease_database_path == ":memory:":
            raise ValueError("MISSION_CYCLE_RECOVERY_LEASE_DATABASE_MUST_BE_DURABLE")

        self._database_path = str(Path(database_path).expanduser())
        self._lease_database_path = str(Path(lease_database_path).expanduser())
        if self._database_path == self._lease_database_path:
            raise ValueError("MISSION_CYCLE_RECOVERY_DATABASE_MUST_BE_SEPARATE_FROM_LEASE_DB")
        Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
        self._mission_store = mission_store
        self._initialize_schema()

    @property
    def database_path(self) -> str:
        return self._database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=30.0,
            check_same_thread=False,
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mission_cycle_recovery (
                    source_wake_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    business_id TEXT NOT NULL,
                    project_id TEXT NULL,
                    checkpoint_sequence INTEGER NOT NULL,
                    resume_cursor TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    next_wake_id TEXT NULL,
                    next_wake_at TEXT NULL,
                    next_wake_reason TEXT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mission_cycle_recovery_scope "
                "ON mission_cycle_recovery(business_id, project_id, mission_id, source_wake_id)"
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _aware_utc(value: object, *, code: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(code)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(code)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _encode_state(state: object) -> str:
        if not isinstance(state, dict):
            raise TypeError("MISSION_CYCLE_RECOVERY_STATE_MUST_BE_DICT")
        try:
            return json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("MISSION_CYCLE_RECOVERY_STATE_NOT_JSON_SERIALIZABLE") from exc

    @classmethod
    def _row_to_record(cls, row: Sequence[object]) -> MissionCycleRecoveryRecord:
        if len(row) != 11:
            raise MissionCycleRecoveryCorruptionError(
                "MISSION_CYCLE_RECOVERY_ROW_SHAPE_INVALID"
            )
        try:
            checkpoint_sequence = int(row[4])
            state = json.loads(str(row[6]))
            next_wake_at = (
                None if row[8] is None else datetime.fromisoformat(str(row[8]))
            )
            created_at = datetime.fromisoformat(str(row[10]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MissionCycleRecoveryCorruptionError(
                "MISSION_CYCLE_RECOVERY_ROW_INVALID"
            ) from exc
        if checkpoint_sequence < 1 or not isinstance(state, dict):
            raise MissionCycleRecoveryCorruptionError(
                "MISSION_CYCLE_RECOVERY_PAYLOAD_INVALID"
            )
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise MissionCycleRecoveryCorruptionError(
                "MISSION_CYCLE_RECOVERY_CREATED_AT_NOT_AWARE"
            )
        if next_wake_at is not None:
            if next_wake_at.tzinfo is None or next_wake_at.utcoffset() is None:
                raise MissionCycleRecoveryCorruptionError(
                    "MISSION_CYCLE_RECOVERY_NEXT_WAKE_AT_NOT_AWARE"
                )
            next_wake_at = next_wake_at.astimezone(timezone.utc)

        record = MissionCycleRecoveryRecord(
            source_wake_id=str(row[0]),
            mission_id=str(row[1]),
            business_id=str(row[2]),
            project_id=None if row[3] is None else str(row[3]),
            checkpoint_sequence=checkpoint_sequence,
            resume_cursor=str(row[5]),
            state=state,
            next_wake_id=None if row[7] is None else str(row[7]),
            next_wake_at=next_wake_at,
            next_wake_reason=None if row[9] is None else str(row[9]),
            created_at=created_at.astimezone(timezone.utc),
        )
        if (
            not record.source_wake_id
            or not record.mission_id
            or not record.business_id
            or not record.resume_cursor
        ):
            raise MissionCycleRecoveryCorruptionError(
                "MISSION_CYCLE_RECOVERY_REQUIRED_FIELD_MISSING"
            )
        continuation_fields = (
            record.next_wake_id is not None,
            record.next_wake_at is not None,
            record.next_wake_reason is not None,
        )
        if any(continuation_fields) and not all(continuation_fields):
            raise MissionCycleRecoveryCorruptionError(
                "MISSION_CYCLE_RECOVERY_CONTINUATION_INCOMPLETE"
            )
        return record

    @staticmethod
    def _same_payload(
        left: MissionCycleRecoveryRecord,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
        checkpoint_sequence: int,
        resume_cursor: str,
        state: Dict[str, Any],
        next_wake_id: Optional[str],
        next_wake_at: Optional[datetime],
        next_wake_reason: Optional[str],
    ) -> bool:
        return (
            left.mission_id == mission_id
            and left.business_id == business_id
            and left.project_id == project_id
            and left.checkpoint_sequence == checkpoint_sequence
            and left.resume_cursor == resume_cursor
            and left.state == state
            and left.next_wake_id == next_wake_id
            and left.next_wake_at == next_wake_at
            and left.next_wake_reason == next_wake_reason
        )

    def save_result(
        self,
        *,
        source_wake_id: str,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
        worker_id: str,
        lease_token: str,
        fencing_token: int,
        checkpoint_sequence: int,
        resume_cursor: str,
        state: Dict[str, Any],
        next_wake_id: Optional[str],
        next_wake_at: Optional[datetime],
        next_wake_reason: Optional[str],
        now: Optional[datetime] = None,
    ) -> MissionCycleRecoveryRecord:
        if not isinstance(source_wake_id, str) or not source_wake_id.strip():
            raise ValueError("MISSION_CYCLE_RECOVERY_SOURCE_WAKE_ID_REQUIRED")
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("MISSION_CYCLE_RECOVERY_MISSION_ID_REQUIRED")
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("MISSION_CYCLE_RECOVERY_BUSINESS_ID_REQUIRED")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise MissionCycleRecoveryAuthorityError(
                "MISSION_CYCLE_RECOVERY_WORKER_ID_REQUIRED"
            )
        if not isinstance(lease_token, str) or not lease_token.strip():
            raise MissionCycleRecoveryAuthorityError(
                "MISSION_CYCLE_RECOVERY_LEASE_TOKEN_REQUIRED"
            )
        if not isinstance(fencing_token, int) or isinstance(fencing_token, bool) or fencing_token < 1:
            raise MissionCycleRecoveryAuthorityError(
                "MISSION_CYCLE_RECOVERY_FENCING_TOKEN_INVALID"
            )
        if (
            not isinstance(checkpoint_sequence, int)
            or isinstance(checkpoint_sequence, bool)
            or checkpoint_sequence < 1
        ):
            raise MissionCycleRecoveryStateError(
                "MISSION_CYCLE_RECOVERY_CHECKPOINT_SEQUENCE_INVALID"
            )
        if not isinstance(resume_cursor, str) or not resume_cursor.strip():
            raise MissionCycleRecoveryStateError(
                "MISSION_CYCLE_RECOVERY_RESUME_CURSOR_REQUIRED"
            )

        normalized_next_at: Optional[datetime] = None
        if next_wake_at is None:
            if next_wake_id is not None or next_wake_reason is not None:
                raise MissionCycleRecoveryStateError(
                    "MISSION_CYCLE_RECOVERY_CONTINUATION_FIELDS_MISMATCH"
                )
        else:
            if not isinstance(next_wake_id, str) or not next_wake_id.strip():
                raise MissionCycleRecoveryStateError(
                    "MISSION_CYCLE_RECOVERY_NEXT_WAKE_ID_REQUIRED"
                )
            if not isinstance(next_wake_reason, str) or not next_wake_reason.strip():
                raise MissionCycleRecoveryStateError(
                    "MISSION_CYCLE_RECOVERY_NEXT_WAKE_REASON_REQUIRED"
                )
            normalized_next_at = self._aware_utc(
                next_wake_at,
                code="MISSION_CYCLE_RECOVERY_NEXT_WAKE_AT_MUST_BE_TIMEZONE_AWARE",
            )

        explicit_now = (
            None
            if now is None
            else self._aware_utc(
                now,
                code="MISSION_CYCLE_RECOVERY_NOW_MUST_BE_TIMEZONE_AWARE",
            )
        )
        normalized_source = source_wake_id.strip()
        normalized_mission = mission_id.strip()
        normalized_business = business_id.strip()
        normalized_worker = worker_id.strip()
        normalized_token = lease_token.strip()
        normalized_cursor = resume_cursor.strip()
        normalized_next_id = None if next_wake_id is None else next_wake_id.strip()
        normalized_next_reason = (
            None if next_wake_reason is None else next_wake_reason.strip()
        )
        encoded_state = self._encode_state(state)

        mission = self._mission_store.get_mission(
            normalized_mission,
            business_id=normalized_business,
            project_id=project_id,
        )
        if mission is None:
            raise MissionCycleRecoveryAuthorityError(
                "MISSION_CYCLE_RECOVERY_SCOPE_NOT_AUTHORIZED"
            )

        connection = self._connect()
        try:
            connection.execute(f"ATTACH DATABASE ? AS {self._LEASE_ALIAS}", (self._lease_database_path,))
            connection.execute("BEGIN IMMEDIATE")
            lease_row = connection.execute(
                f"""
                SELECT business_id, project_id, lease_owner, lease_token,
                       lease_expires_at, fencing_token
                FROM {self._LEASE_ALIAS}.mission_leases
                WHERE mission_id = ?
                """,
                (normalized_mission,),
            ).fetchone()
            if lease_row is None:
                raise MissionCycleRecoveryAuthorityError(
                    "MISSION_CYCLE_RECOVERY_EXECUTION_FENCE_NOT_FOUND"
                )
            lease_business, lease_project, owner, token, expires_at, current_fence = lease_row
            if lease_business != normalized_business or lease_project != project_id:
                raise MissionCycleRecoveryAuthorityError(
                    "MISSION_CYCLE_RECOVERY_EXECUTION_FENCE_SCOPE_MISMATCH"
                )
            if (
                owner != normalized_worker
                or token != normalized_token
                or int(current_fence) != fencing_token
            ):
                raise MissionCycleRecoveryAuthorityError(
                    "MISSION_CYCLE_RECOVERY_EXECUTION_FENCE_LOST"
                )
            if expires_at is None:
                raise MissionCycleRecoveryAuthorityError(
                    "MISSION_CYCLE_RECOVERY_EXECUTION_LEASE_NOT_LIVE"
                )
            try:
                expiry = datetime.fromisoformat(str(expires_at))
            except (TypeError, ValueError) as exc:
                raise MissionCycleRecoveryCorruptionError(
                    "MISSION_CYCLE_RECOVERY_LEASE_EXPIRY_INVALID"
                ) from exc
            if expiry.tzinfo is None or expiry.utcoffset() is None:
                raise MissionCycleRecoveryCorruptionError(
                    "MISSION_CYCLE_RECOVERY_LEASE_EXPIRY_NOT_AWARE"
                )
            reference = explicit_now or datetime.now(timezone.utc)
            reference = reference.astimezone(timezone.utc)
            if expiry.astimezone(timezone.utc) <= reference:
                raise MissionCycleRecoveryAuthorityError(
                    "MISSION_CYCLE_RECOVERY_EXECUTION_LEASE_EXPIRED"
                )

            existing_row = connection.execute(
                f"SELECT {self._COLUMNS} FROM mission_cycle_recovery WHERE source_wake_id = ?",
                (normalized_source,),
            ).fetchone()
            if existing_row is not None:
                existing = self._row_to_record(existing_row)
                if not self._same_payload(
                    existing,
                    mission_id=normalized_mission,
                    business_id=normalized_business,
                    project_id=project_id,
                    checkpoint_sequence=checkpoint_sequence,
                    resume_cursor=normalized_cursor,
                    state=state,
                    next_wake_id=normalized_next_id,
                    next_wake_at=normalized_next_at,
                    next_wake_reason=normalized_next_reason,
                ):
                    raise MissionCycleRecoveryStateError(
                        "MISSION_CYCLE_RECOVERY_SOURCE_WAKE_RESULT_CONFLICT"
                    )
                connection.commit()
                return existing

            created_at = reference
            connection.execute(
                """
                INSERT INTO mission_cycle_recovery(
                    source_wake_id, mission_id, business_id, project_id,
                    checkpoint_sequence, resume_cursor, state_json,
                    next_wake_id, next_wake_at, next_wake_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_source,
                    normalized_mission,
                    normalized_business,
                    project_id,
                    checkpoint_sequence,
                    normalized_cursor,
                    encoded_state,
                    normalized_next_id,
                    None if normalized_next_at is None else normalized_next_at.isoformat(),
                    normalized_next_reason,
                    created_at.isoformat(),
                ),
            )
            connection.commit()
            row = connection.execute(
                f"SELECT {self._COLUMNS} FROM mission_cycle_recovery WHERE source_wake_id = ?",
                (normalized_source,),
            ).fetchone()
            assert row is not None
            return self._row_to_record(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_result(
        self,
        *,
        source_wake_id: str,
        business_id: str,
        project_id: Optional[str],
    ) -> Optional[MissionCycleRecoveryRecord]:
        if not source_wake_id or not business_id:
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                f"""
                SELECT {self._COLUMNS}
                FROM mission_cycle_recovery
                WHERE source_wake_id = ? AND business_id = ?
                  AND ((project_id IS NULL AND ? IS NULL) OR project_id = ?)
                """,
                (source_wake_id, business_id, project_id, project_id),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else self._row_to_record(row)
