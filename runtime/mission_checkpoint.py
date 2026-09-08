"""Durable crash-recovery checkpoints for Continuity Runtime Missions.

This module is deterministic runtime infrastructure.  It persists detached
resume state and accepts a checkpoint write only while the caller owns the exact
live Mission execution owner/token/fencing epoch.  The execution-fence read and
checkpoint append occur inside one SQLite transaction so a stale worker cannot
validate, lose its lease to a takeover, and then persist progress.

It deliberately does not execute the five-agent runtime, schedule wakes, retry
external effects, reconcile unknown outcomes, or perform Brain reasoning.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional, Sequence

from runtime.mission_store import MissionStore


class MissionCheckpointAuthorityError(RuntimeError):
    """Raised when a checkpoint write/read violates Mission execution authority."""


class MissionCheckpointStateError(RuntimeError):
    """Raised when checkpoint progression is not monotonic or otherwise valid."""


class MissionCheckpointCorruptionError(RuntimeError):
    """Raised when durable checkpoint state cannot be decoded safely."""


@dataclass(frozen=True)
class MissionCheckpointRecord:
    """Detached durable resume snapshot for one Mission checkpoint sequence."""

    checkpoint_id: str
    mission_id: str
    business_id: str
    project_id: Optional[str]
    worker_id: str
    lease_token: str
    fencing_token: int
    checkpoint_sequence: int
    resume_cursor: str
    state: Dict[str, Any]
    created_at: datetime


class DurableMissionCheckpointStore:
    """SQLite-backed append-only Mission checkpoint authority."""

    _LEASE_ALIAS = "mission_checkpoint_lease_authority"
    _COLUMNS = (
        "checkpoint_id, mission_id, business_id, project_id, worker_id, "
        "lease_token, fencing_token, checkpoint_sequence, resume_cursor, "
        "state_json, created_at"
    )

    def __init__(
        self,
        *,
        database_path: str,
        mission_store: MissionStore,
        lease_database_path: str,
    ) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("MISSION_CHECKPOINT_DATABASE_PATH_REQUIRED")
        if database_path == ":memory:":
            raise ValueError("MISSION_CHECKPOINT_REQUIRES_DURABLE_DATABASE_PATH")
        if not isinstance(mission_store, MissionStore):
            raise TypeError("MISSION_CHECKPOINT_REQUIRES_MISSION_STORE")
        if not isinstance(lease_database_path, str) or not lease_database_path.strip():
            raise ValueError("MISSION_CHECKPOINT_LEASE_DATABASE_PATH_REQUIRED")
        if lease_database_path == ":memory:":
            raise ValueError("MISSION_CHECKPOINT_LEASE_DATABASE_MUST_BE_DURABLE")

        self._database_path = str(Path(database_path).expanduser())
        self._lease_database_path = str(Path(lease_database_path).expanduser())
        if self._database_path == self._lease_database_path:
            raise ValueError("MISSION_CHECKPOINT_DATABASE_MUST_BE_SEPARATE_FROM_LEASE_DB")

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
            CREATE TABLE IF NOT EXISTS mission_checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                business_id TEXT NOT NULL,
                project_id TEXT NULL,
                worker_id TEXT NOT NULL,
                lease_token TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                checkpoint_sequence INTEGER NOT NULL,
                resume_cursor TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(mission_id, checkpoint_sequence)
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mission_checkpoints_scope_latest "
            "ON mission_checkpoints(business_id, project_id, mission_id, checkpoint_sequence DESC)"
        )
        self._connection.commit()

        self._connection.execute(
            f"ATTACH DATABASE ? AS {self._LEASE_ALIAS}",
            (self._lease_database_path,),
        )
        lease_table = self._connection.execute(
            f"""
            SELECT name
            FROM {self._LEASE_ALIAS}.sqlite_master
            WHERE type = 'table' AND name = 'mission_leases'
            """
        ).fetchone()
        if lease_table is None:
            self._connection.execute(f"DETACH DATABASE {self._LEASE_ALIAS}")
            self._connection.close()
            self._closed = True
            raise MissionCheckpointAuthorityError(
                "MISSION_CHECKPOINT_LEASE_AUTHORITY_TABLE_MISSING"
            )

    @property
    def durable(self) -> bool:
        return True

    @property
    def database_path(self) -> str:
        return self._database_path

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("MISSION_CHECKPOINT_STORE_CLOSED")

    @staticmethod
    def _aware_utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _encode_state(state: object) -> str:
        if not isinstance(state, dict):
            raise TypeError("MISSION_CHECKPOINT_STATE_MUST_BE_DICT")
        try:
            return json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("MISSION_CHECKPOINT_STATE_NOT_JSON_SERIALIZABLE") from exc

    @classmethod
    def _row_to_record(cls, row: Sequence[object]) -> MissionCheckpointRecord:
        if len(row) != 11:
            raise MissionCheckpointCorruptionError("MISSION_CHECKPOINT_ROW_SHAPE_INVALID")
        try:
            fencing_token = int(row[6])
            checkpoint_sequence = int(row[7])
            created_at = datetime.fromisoformat(str(row[10]))
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("created_at")
            state = json.loads(str(row[9]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MissionCheckpointCorruptionError("MISSION_CHECKPOINT_ROW_INVALID") from exc

        if fencing_token < 1 or checkpoint_sequence < 1:
            raise MissionCheckpointCorruptionError("MISSION_CHECKPOINT_SEQUENCE_OR_FENCE_INVALID")
        if not isinstance(state, dict):
            raise MissionCheckpointCorruptionError("MISSION_CHECKPOINT_STATE_INVALID")

        record = MissionCheckpointRecord(
            checkpoint_id=str(row[0]),
            mission_id=str(row[1]),
            business_id=str(row[2]),
            project_id=None if row[3] is None else str(row[3]),
            worker_id=str(row[4]),
            lease_token=str(row[5]),
            fencing_token=fencing_token,
            checkpoint_sequence=checkpoint_sequence,
            resume_cursor=str(row[8]),
            state=state,
            created_at=created_at.astimezone(timezone.utc),
        )
        if (
            not record.checkpoint_id
            or not record.mission_id
            or not record.business_id
            or not record.worker_id
            or not record.lease_token
            or not record.resume_cursor
        ):
            raise MissionCheckpointCorruptionError("MISSION_CHECKPOINT_REQUIRED_FIELD_MISSING")
        return record

    def _lease_row_locked(self, mission_id: str) -> Optional[Sequence[object]]:
        return self._connection.execute(
            f"""
            SELECT business_id, project_id, lease_owner, lease_token,
                   lease_expires_at, fencing_token
            FROM {self._LEASE_ALIAS}.mission_leases
            WHERE mission_id = ?
            """,
            (mission_id,),
        ).fetchone()

    def _latest_sequence_locked(self, mission_id: str) -> Optional[int]:
        row = self._connection.execute(
            """
            SELECT checkpoint_sequence
            FROM mission_checkpoints
            WHERE mission_id = ?
            ORDER BY checkpoint_sequence DESC
            LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        return None if row is None else int(row[0])

    def save_checkpoint(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
        worker_id: str,
        lease_token: str,
        fencing_token: int,
        checkpoint_sequence: int,
        resume_cursor: str,
        state: Dict[str, Any],
    ) -> MissionCheckpointRecord:
        """Append one checkpoint under the exact current live Mission fence."""

        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("MISSION_CHECKPOINT_MISSION_ID_REQUIRED")
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("MISSION_CHECKPOINT_BUSINESS_ID_REQUIRED")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise MissionCheckpointAuthorityError("MISSION_CHECKPOINT_WORKER_ID_REQUIRED")
        if not isinstance(lease_token, str) or not lease_token.strip():
            raise MissionCheckpointAuthorityError("MISSION_CHECKPOINT_LEASE_TOKEN_REQUIRED")
        if (
            not isinstance(fencing_token, int)
            or isinstance(fencing_token, bool)
            or fencing_token < 1
        ):
            raise MissionCheckpointAuthorityError("MISSION_CHECKPOINT_FENCING_TOKEN_INVALID")
        if (
            not isinstance(checkpoint_sequence, int)
            or isinstance(checkpoint_sequence, bool)
            or checkpoint_sequence < 1
        ):
            raise MissionCheckpointStateError("MISSION_CHECKPOINT_SEQUENCE_INVALID")
        if not isinstance(resume_cursor, str) or not resume_cursor.strip():
            raise MissionCheckpointStateError("MISSION_CHECKPOINT_RESUME_CURSOR_REQUIRED")

        normalized_mission_id = mission_id.strip()
        normalized_business_id = business_id.strip()
        normalized_worker = worker_id.strip()
        normalized_lease_token = lease_token.strip()
        normalized_cursor = resume_cursor.strip()
        encoded_state = self._encode_state(state)

        mission = self._mission_store.get_mission(
            normalized_mission_id,
            business_id=normalized_business_id,
            project_id=project_id,
        )
        if mission is None:
            raise MissionCheckpointAuthorityError("MISSION_CHECKPOINT_SCOPE_NOT_AUTHORIZED")

        created_at = self._aware_utc_now()
        encoded_created_at = created_at.isoformat()
        checkpoint_id = uuid.uuid4().hex

        with self._lock:
            self._require_open()
            try:
                # A transaction spans the checkpoint DB and attached lease DB.
                # The live fence cannot be replaced between this authority read
                # and the durable checkpoint append.
                self._connection.execute("BEGIN IMMEDIATE")
                lease_row = self._lease_row_locked(normalized_mission_id)
                if lease_row is None:
                    raise MissionCheckpointAuthorityError(
                        "MISSION_CHECKPOINT_EXECUTION_FENCE_NOT_FOUND"
                    )
                (
                    lease_business,
                    lease_project,
                    lease_owner,
                    current_lease_token,
                    lease_expires_at,
                    current_fencing_token,
                ) = lease_row
                if lease_business != normalized_business_id or lease_project != project_id:
                    raise MissionCheckpointAuthorityError(
                        "MISSION_CHECKPOINT_EXECUTION_FENCE_SCOPE_MISMATCH"
                    )
                if (
                    lease_owner != normalized_worker
                    or current_lease_token != normalized_lease_token
                    or int(current_fencing_token) != fencing_token
                ):
                    raise MissionCheckpointAuthorityError(
                        "MISSION_CHECKPOINT_EXECUTION_FENCE_LOST"
                    )
                if lease_expires_at is None:
                    raise MissionCheckpointAuthorityError(
                        "MISSION_CHECKPOINT_EXECUTION_LEASE_NOT_LIVE"
                    )
                try:
                    expiry = datetime.fromisoformat(str(lease_expires_at))
                except (TypeError, ValueError) as exc:
                    raise MissionCheckpointCorruptionError(
                        "MISSION_CHECKPOINT_LEASE_EXPIRY_INVALID"
                    ) from exc
                if expiry.tzinfo is None or expiry.utcoffset() is None:
                    raise MissionCheckpointCorruptionError(
                        "MISSION_CHECKPOINT_LEASE_EXPIRY_NOT_TIMEZONE_AWARE"
                    )
                if expiry.astimezone(timezone.utc) <= created_at:
                    raise MissionCheckpointAuthorityError(
                        "MISSION_CHECKPOINT_EXECUTION_LEASE_EXPIRED"
                    )

                latest_sequence = self._latest_sequence_locked(normalized_mission_id)
                if latest_sequence is not None and checkpoint_sequence <= latest_sequence:
                    raise MissionCheckpointStateError(
                        "MISSION_CHECKPOINT_SEQUENCE_MUST_ADVANCE"
                    )

                self._connection.execute(
                    """
                    INSERT INTO mission_checkpoints(
                        checkpoint_id, mission_id, business_id, project_id,
                        worker_id, lease_token, fencing_token,
                        checkpoint_sequence, resume_cursor, state_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        checkpoint_id,
                        normalized_mission_id,
                        normalized_business_id,
                        project_id,
                        normalized_worker,
                        normalized_lease_token,
                        fencing_token,
                        checkpoint_sequence,
                        normalized_cursor,
                        encoded_state,
                        encoded_created_at,
                    ),
                )
                self._connection.commit()
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise MissionCheckpointStateError(
                    "MISSION_CHECKPOINT_SEQUENCE_CONFLICT"
                ) from exc
            except Exception:
                self._connection.rollback()
                raise

            row = self._connection.execute(
                f"SELECT {self._COLUMNS} FROM mission_checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()

        assert row is not None
        return self._row_to_record(row)

    def get_latest(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
    ) -> Optional[MissionCheckpointRecord]:
        """Return a detached latest checkpoint only for exact Mission scope."""

        if not mission_id or not business_id:
            return None
        with self._lock:
            self._require_open()
            row = self._connection.execute(
                f"""
                SELECT {self._COLUMNS}
                FROM mission_checkpoints
                WHERE mission_id = ? AND business_id = ?
                  AND ((project_id IS NULL AND ? IS NULL) OR project_id = ?)
                ORDER BY checkpoint_sequence DESC
                LIMIT 1
                """,
                (mission_id, business_id, project_id, project_id),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._connection.commit()
            finally:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "DurableMissionCheckpointStore":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
