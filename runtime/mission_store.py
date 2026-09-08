"""Durable authority-preserving persistence for long-lived Missions.

This module is deterministic runtime infrastructure.  It intentionally owns only
Mission persistence and scope authority.  Scheduling, wake dispatch, retries,
reconciliation, external effects, and Brain reasoning remain outside this
boundary.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional

from runtime.mission import MissionRecord, MissionStatus


class MissionStoreAuthorityError(RuntimeError):
    """Raised when persistence would violate canonical Mission authority."""


class MissionStoreCorruptionError(RuntimeError):
    """Raised when persisted Mission state disagrees with its authority index."""


class MissionStore:
    """SQLite-backed durable store for canonical ``MissionRecord`` snapshots."""

    def __init__(self, *, database_path: str) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("MISSION_STORE_DATABASE_PATH_REQUIRED")
        if database_path == ":memory:":
            raise ValueError("MISSION_STORE_REQUIRES_DURABLE_DATABASE_PATH")

        self._database_path = str(Path(database_path).expanduser())
        Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
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
    def _encode_mission(mission: MissionRecord) -> str:
        snapshot = mission.model_dump()
        return json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

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

    def save_mission(self, mission: MissionRecord) -> None:
        """Durably insert/update one Mission without permitting identity rebinding."""

        if not isinstance(mission, MissionRecord):
            raise TypeError("MISSION_STORE_REQUIRES_MISSION_RECORD")

        # MissionRecord.model_dump() takes the Mission authority lock and returns
        # one atomic serialized snapshot.  The indexed authority columns are read
        # from that same snapshot so persistence cannot mix lifecycle snapshots.
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

        with self._lock:
            self._require_open()
            existing = self._connection.execute(
                "SELECT business_id, project_id, user_id FROM missions WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()

            if existing is not None:
                existing_business, existing_project, existing_user = existing
                if (
                    existing_business != business_id
                    or existing_project != project_id
                    or existing_user != user_id
                ):
                    raise MissionStoreAuthorityError(
                        "MISSION_STORE_IDENTITY_SCOPE_REBIND_FORBIDDEN"
                    )

            with self._connection:
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

        # Fail closed if payload state has been corrupted independently of the
        # authority index.  Knowing a mission_id must never bypass scope binding.
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
