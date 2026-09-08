"""Durable authority-preserving persistence for long-lived Missions.

This module is deterministic runtime infrastructure. It owns Mission persistence,
scope authority, and the atomic write-side fencing boundary used by long-lived
Mission workers. Scheduling, retries, reconciliation, external effects, and Brain
reasoning remain outside this boundary.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional, Sequence

from runtime.mission import MissionRecord, MissionStatus


class MissionStoreAuthorityError(RuntimeError):
    """Raised when persistence would violate canonical Mission authority."""


class MissionStoreCorruptionError(RuntimeError):
    """Raised when persisted Mission state disagrees with its authority index."""


class MissionStore:
    """SQLite-backed durable store for canonical ``MissionRecord`` snapshots."""

    _LEASE_DATABASE_ALIAS = "mission_lease_authority"

    def __init__(self, *, database_path: str) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("MISSION_STORE_DATABASE_PATH_REQUIRED")
        if database_path == ":memory:":
            raise ValueError("MISSION_STORE_REQUIRES_DURABLE_DATABASE_PATH")

        self._database_path = str(Path(database_path).expanduser())
        Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._closed = False
        self._lease_database_path: Optional[str] = None
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
            CREATE TABLE IF NOT EXISTS missions (
                mission_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                project_id TEXT NULL,
                user_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    @property
    def durable(self) -> bool:
        """This store always uses an on-disk SQLite database."""

        return True

    @property
    def database_path(self) -> str:
        return self._database_path

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("MISSION_STORE_CLOSED")

    @staticmethod
    def _decode_mission(payload_json: str) -> MissionRecord:
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MissionStoreCorruptionError("MISSION_STORE_PAYLOAD_INVALID_JSON") from exc

        if not isinstance(payload, dict):
            raise MissionStoreCorruptionError("MISSION_STORE_PAYLOAD_INVALID_TYPE")

        try:
            status = payload.get("status", MissionStatus.CREATED.value)
            payload["status"] = MissionStatus(status)

            created_at = payload.get("created_at")
            if isinstance(created_at, str):
                payload["created_at"] = datetime.fromisoformat(created_at)

            mission = MissionRecord(**payload)
        except (TypeError, ValueError) as exc:
            raise MissionStoreCorruptionError("MISSION_STORE_PAYLOAD_INVALID_MISSION") from exc

        return mission

    @staticmethod
    def _snapshot_fields(mission: MissionRecord) -> tuple[str, str, Optional[str], str, str, str]:
        if not isinstance(mission, MissionRecord):
            raise TypeError("MISSION_STORE_REQUIRES_MISSION_RECORD")

        # MissionRecord.model_dump() holds the Mission authority lock and returns
        # one atomic lifecycle snapshot. Indexed authority columns and payload are
        # derived from that exact same snapshot.
        snapshot = mission.model_dump()
        mission_id = snapshot["mission_id"]
        business_id = snapshot["business_id"]
        project_id = snapshot.get("project_id")
        user_id = snapshot["user_id"]
        payload_json = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        updated_at = datetime.now(timezone.utc).isoformat()
        return mission_id, business_id, project_id, user_id, payload_json, updated_at

    def bind_execution_lease_database(self, database_path: str) -> None:
        """Bind the one durable Mission-lease authority used for fenced writes.

        The lease database is attached to the MissionStore connection so an
        authoritative lease check and the Mission snapshot update execute inside
        one SQLite transaction. Binding is idempotent for the exact same path and
        fails closed if a second lease authority is presented.
        """

        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("MISSION_STORE_LEASE_DATABASE_PATH_REQUIRED")
        if database_path == ":memory:":
            raise ValueError("MISSION_STORE_LEASE_DATABASE_MUST_BE_DURABLE")

        normalized = str(Path(database_path).expanduser())
        if normalized == self._database_path:
            raise ValueError("MISSION_STORE_LEASE_DATABASE_MUST_BE_SEPARATE")

        with self._lock:
            self._require_open()
            if self._lease_database_path is not None:
                if self._lease_database_path != normalized:
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_MULTIPLE_LEASE_AUTHORITIES_FORBIDDEN"
                    )
                return

            self._connection.execute(
                f"ATTACH DATABASE ? AS {self._LEASE_DATABASE_ALIAS}",
                (normalized,),
            )
            table = self._connection.execute(
                f"""
                SELECT name
                FROM {self._LEASE_DATABASE_ALIAS}.sqlite_master
                WHERE type = 'table' AND name = 'mission_leases'
                """
            ).fetchone()
            if table is None:
                self._connection.execute(
                    f"DETACH DATABASE {self._LEASE_DATABASE_ALIAS}"
                )
                raise MissionStoreAuthorityError(
                    "MISSION_STORE_LEASE_AUTHORITY_TABLE_MISSING"
                )
            self._lease_database_path = normalized

    def _existing_identity_locked(self, mission_id: str) -> Optional[Sequence[object]]:
        return self._connection.execute(
            "SELECT business_id, project_id, user_id FROM missions WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()

    @staticmethod
    def _require_identity_match(
        existing: Optional[Sequence[object]],
        *,
        business_id: str,
        project_id: Optional[str],
        user_id: str,
    ) -> None:
        if existing is None:
            return
        existing_business, existing_project, existing_user = existing
        if (
            existing_business != business_id
            or existing_project != project_id
            or existing_user != user_id
        ):
            raise MissionStoreAuthorityError(
                "MISSION_STORE_IDENTITY_SCOPE_REBIND_FORBIDDEN"
            )

    def _lease_row_locked(self, mission_id: str) -> Optional[Sequence[object]]:
        if self._lease_database_path is None:
            return None
        return self._connection.execute(
            f"""
            SELECT business_id, project_id, lease_owner, lease_token,
                   lease_expires_at, fencing_token
            FROM {self._LEASE_DATABASE_ALIAS}.mission_leases
            WHERE mission_id = ?
            """,
            (mission_id,),
        ).fetchone()

    def _write_snapshot_locked(
        self,
        *,
        mission_id: str,
        business_id: str,
        project_id: Optional[str],
        user_id: str,
        payload_json: str,
        updated_at: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO missions (
                mission_id,
                business_id,
                project_id,
                user_id,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(mission_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                mission_id,
                business_id,
                project_id,
                user_id,
                payload_json,
                updated_at,
            ),
        )

    def save_mission(self, mission: MissionRecord) -> None:
        """Persist only Missions that have never entered fenced execution.

        Once durable execution fencing exists for a Mission, all later writes must
        carry the exact current worker/token/fencing epoch through
        :meth:`save_mission_fenced`.
        """

        fields = self._snapshot_fields(mission)
        mission_id, business_id, project_id, user_id, payload_json, updated_at = fields

        with self._lock:
            self._require_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._require_identity_match(
                    self._existing_identity_locked(mission_id),
                    business_id=business_id,
                    project_id=project_id,
                    user_id=user_id,
                )
                if self._lease_row_locked(mission_id) is not None:
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_FENCED_WRITE_REQUIRED"
                    )
                self._write_snapshot_locked(
                    mission_id=mission_id,
                    business_id=business_id,
                    project_id=project_id,
                    user_id=user_id,
                    payload_json=payload_json,
                    updated_at=updated_at,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def save_mission_fenced(
        self,
        mission: MissionRecord,
        *,
        worker_id: str,
        lease_token: str,
        fencing_token: int,
    ) -> None:
        """Atomically validate the current execution fence and persist Mission.

        Validation and payload update share one SQLite transaction spanning the
        Mission database and its attached durable lease database. A stale worker
        therefore cannot pass validation and then race a takeover before writing.
        """

        if not isinstance(worker_id, str) or not worker_id.strip():
            raise MissionStoreAuthorityError("MISSION_STORE_WORKER_ID_REQUIRED")
        if not isinstance(lease_token, str) or not lease_token.strip():
            raise MissionStoreAuthorityError("MISSION_STORE_LEASE_TOKEN_REQUIRED")
        if not isinstance(fencing_token, int) or isinstance(fencing_token, bool) or fencing_token < 1:
            raise MissionStoreAuthorityError("MISSION_STORE_FENCING_TOKEN_INVALID")

        fields = self._snapshot_fields(mission)
        mission_id, business_id, project_id, user_id, payload_json, updated_at = fields

        with self._lock:
            self._require_open()
            if self._lease_database_path is None:
                raise MissionStoreAuthorityError(
                    "MISSION_STORE_LEASE_AUTHORITY_NOT_BOUND"
                )
            try:
                # BEGIN IMMEDIATE makes the lease authority read and Mission write
                # part of the same attached-database transaction boundary.
                self._connection.execute("BEGIN IMMEDIATE")
                self._require_identity_match(
                    self._existing_identity_locked(mission_id),
                    business_id=business_id,
                    project_id=project_id,
                    user_id=user_id,
                )
                row = self._lease_row_locked(mission_id)
                if row is None:
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_EXECUTION_FENCE_NOT_FOUND"
                    )

                (
                    lease_business,
                    lease_project,
                    lease_owner,
                    current_lease_token,
                    lease_expires_at,
                    current_fencing_token,
                ) = row
                if lease_business != business_id or lease_project != project_id:
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_EXECUTION_FENCE_SCOPE_MISMATCH"
                    )
                if (
                    lease_owner != worker_id.strip()
                    or current_lease_token != lease_token.strip()
                    or int(current_fencing_token) != fencing_token
                ):
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_EXECUTION_FENCE_LOST"
                    )
                if lease_expires_at is None:
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_EXECUTION_LEASE_NOT_LIVE"
                    )
                try:
                    expires_at = datetime.fromisoformat(str(lease_expires_at))
                except (TypeError, ValueError) as exc:
                    raise MissionStoreCorruptionError(
                        "MISSION_STORE_EXECUTION_LEASE_EXPIRY_INVALID"
                    ) from exc
                if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                    raise MissionStoreCorruptionError(
                        "MISSION_STORE_EXECUTION_LEASE_EXPIRY_NOT_TIMEZONE_AWARE"
                    )

                # Evaluate lease expiry only after the durable transaction and
                # authoritative lease read. Contention cannot reuse a stale
                # pre-transaction clock to authorize a Mission snapshot write.
                reference = datetime.now(timezone.utc)
                if expires_at.astimezone(timezone.utc) <= reference:
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_EXECUTION_LEASE_EXPIRED"
                    )

                self._write_snapshot_locked(
                    mission_id=mission_id,
                    business_id=business_id,
                    project_id=project_id,
                    user_id=user_id,
                    payload_json=payload_json,
                    updated_at=updated_at,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def get_mission(
        self,
        mission_id: str,
        *,
        business_id: str,
        project_id: Optional[str],
    ) -> Optional[MissionRecord]:
        """Return a detached Mission only when exact authority scope matches."""

        if not mission_id or not business_id:
            return None

        with self._lock:
            self._require_open()
            row = self._connection.execute(
                """
                SELECT business_id, project_id, user_id, payload_json
                FROM missions
                WHERE mission_id = ?
                """,
                (mission_id,),
            ).fetchone()

        if row is None:
            return None

        stored_business, stored_project, stored_user, payload_json = row
        if stored_business != business_id or stored_project != project_id:
            return None

        mission = self._decode_mission(payload_json)
        if (
            mission.mission_id != mission_id
            or mission.business_id != stored_business
            or mission.project_id != stored_project
            or mission.user_id != stored_user
        ):
            raise MissionStoreCorruptionError("MISSION_STORE_AUTHORITY_INDEX_MISMATCH")

        return mission

    def close(self) -> None:
        """Flush and close the durable connection; safe to call repeatedly."""

        with self._lock:
            if self._closed:
                return
            try:
                self._connection.commit()
            finally:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "MissionStore":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
