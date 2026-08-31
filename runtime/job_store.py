"""Durable local job state for the AI Marketing Department platform.

This module intentionally owns persistence only. It does not execute jobs and it
never decides whether a recovered job is safe to retry. Recovery policy remains
in ``runtime.queue.RunManager`` so external side effects cannot be replayed by a
storage layer.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from runtime.context import ExecutionCheckpoint


class JobStoreError(RuntimeError):
    """Base error raised by durable job storage."""


class JobStoreIntegrityError(JobStoreError):
    """Raised when persisted job/checkpoint data fails integrity verification."""


class JobStoreConflictError(JobStoreError):
    """Raised when a persistence operation would overwrite incompatible state."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _sqlite_failure(operation: str, exc: sqlite3.Error) -> JobStoreError:
    """Translate raw SQLite failures into the platform durability error boundary."""
    safe = sanitize_sensitive_text(str(exc))
    return JobStoreError(f"JOB_STORE_{operation}_FAILED: {safe}")


@dataclass(frozen=True)
class DurableJobRecord:
    """Serializable durable projection of one queue job."""

    run_id: str
    objective: str
    status: str
    created_at: str
    business_id: Optional[str] = None
    project_id: Optional[str] = None
    chat_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    recovery_reason: Optional[str] = None
    artifact_hash: Optional[str] = None
    attempt_count: int = 0
    updated_at: str = ""
    schema_version: int = 1
    record_hash: str = ""

    def normalized(self) -> "DurableJobRecord":
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("RUN_ID_REQUIRED: durable job run_id is required")
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("OBJECTIVE_REQUIRED: durable job objective is required")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("STATUS_REQUIRED: durable job status is required")
        if not isinstance(self.attempt_count, int) or isinstance(self.attempt_count, bool) or self.attempt_count < 0:
            raise ValueError("INVALID_ATTEMPT_COUNT: attempt_count must be a non-negative integer")

        normalized = replace(
            self,
            run_id=self.run_id.strip(),
            objective=sanitize_sensitive_text(self.objective),
            status=self.status.strip().upper(),
            error=sanitize_sensitive_text(self.error) if self.error else None,
            recovery_reason=sanitize_sensitive_text(self.recovery_reason) if self.recovery_reason else None,
            updated_at=self.updated_at or _utc_now_iso(),
        )
        return replace(normalized, record_hash=normalized.calculate_hash())

    def hash_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "objective": self.objective,
            "business_id": self.business_id,
            "project_id": self.project_id,
            "chat_id": self.chat_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "recovery_reason": self.recovery_reason,
            "artifact_hash": self.artifact_hash,
            "attempt_count": self.attempt_count,
            "updated_at": self.updated_at,
        }

    def calculate_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.hash_payload()).encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        return bool(self.record_hash) and self.record_hash == self.calculate_hash()


class SQLiteJobRepository:
    """Thread-safe SQLite repository for durable job state and checkpoints.

    SQLite is part of the Python standard library, keeps the local application
    zero-service, and gives us transactional updates across worker threads. The
    repository uses WAL + FULL synchronous mode because losing the last job state
    during a crash defeats the purpose of recovery.
    """

    TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.database_path),
            timeout=5.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    run_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    business_id TEXT,
                    project_id TEXT,
                    chat_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    recovery_reason TEXT,
                    artifact_hash TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    record_hash TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    checkpoint_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES jobs(run_id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT,
                    message TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES jobs(run_id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_job_events_run ON job_events(run_id, event_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_job_checkpoints_run ON job_checkpoints(run_id, created_at)")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> DurableJobRecord:
        record = DurableJobRecord(
            run_id=row["run_id"],
            objective=row["objective"],
            business_id=row["business_id"],
            project_id=row["project_id"],
            chat_id=row["chat_id"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            recovery_reason=row["recovery_reason"],
            artifact_hash=row["artifact_hash"],
            attempt_count=int(row["attempt_count"]),
            updated_at=row["updated_at"],
            schema_version=int(row["schema_version"]),
            record_hash=row["record_hash"],
        )
        if not record.verify_integrity():
            raise JobStoreIntegrityError(
                f"JOB_RECORD_INTEGRITY_MISMATCH: run_id={record.run_id}"
            )
        return record

    def _append_event_locked(
        self,
        run_id: str,
        event_type: str,
        status: Optional[str],
        message: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO job_events(run_id, event_type, status, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                event_type,
                status,
                sanitize_sensitive_text(message) if message else None,
                _utc_now_iso(),
            ),
        )

    def create_job(self, record: DurableJobRecord) -> DurableJobRecord:
        normalized = record.normalized()
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO jobs(
                            run_id, objective, business_id, project_id, chat_id, status,
                            created_at, started_at, completed_at, error, recovery_reason,
                            artifact_hash, attempt_count, updated_at, schema_version, record_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            normalized.run_id,
                            normalized.objective,
                            normalized.business_id,
                            normalized.project_id,
                            normalized.chat_id,
                            normalized.status,
                            normalized.created_at,
                            normalized.started_at,
                            normalized.completed_at,
                            normalized.error,
                            normalized.recovery_reason,
                            normalized.artifact_hash,
                            normalized.attempt_count,
                            normalized.updated_at,
                            normalized.schema_version,
                            normalized.record_hash,
                        ),
                    )
                    self._append_event_locked(normalized.run_id, "CREATED", normalized.status)
            except sqlite3.IntegrityError as exc:
                raise JobStoreConflictError(
                    f"JOB_ALREADY_EXISTS: run_id={normalized.run_id}"
                ) from exc
            except sqlite3.Error as exc:
                raise _sqlite_failure("CREATE", exc) from exc
        return normalized

    def save_job(
        self,
        record: DurableJobRecord,
        *,
        event_type: str = "STATE_UPDATED",
        message: Optional[str] = None,
    ) -> DurableJobRecord:
        normalized = replace(record, updated_at=_utc_now_iso(), record_hash="").normalized()
        with self._lock:
            try:
                with self._conn:
                    cur = self._conn.execute(
                        """
                        UPDATE jobs SET
                            objective=?, business_id=?, project_id=?, chat_id=?, status=?,
                            created_at=?, started_at=?, completed_at=?, error=?, recovery_reason=?,
                            artifact_hash=?, attempt_count=?, updated_at=?, schema_version=?, record_hash=?
                        WHERE run_id=?
                        """,
                        (
                            normalized.objective,
                            normalized.business_id,
                            normalized.project_id,
                            normalized.chat_id,
                            normalized.status,
                            normalized.created_at,
                            normalized.started_at,
                            normalized.completed_at,
                            normalized.error,
                            normalized.recovery_reason,
                            normalized.artifact_hash,
                            normalized.attempt_count,
                            normalized.updated_at,
                            normalized.schema_version,
                            normalized.record_hash,
                            normalized.run_id,
                        ),
                    )
                    if cur.rowcount != 1:
                        raise JobStoreConflictError(
                            f"JOB_NOT_FOUND: run_id={normalized.run_id}"
                        )
                    self._append_event_locked(
                        normalized.run_id,
                        event_type,
                        normalized.status,
                        message,
                    )
            except JobStoreError:
                raise
            except sqlite3.Error as exc:
                raise _sqlite_failure("SAVE", exc) from exc
        return normalized

    def get_job(self, run_id: str) -> Optional[DurableJobRecord]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE run_id=?", (run_id,)).fetchone()
            return self._row_to_record(row) if row is not None else None

    def list_jobs(self, statuses: Optional[Iterable[str]] = None) -> List[DurableJobRecord]:
        with self._lock:
            if statuses is None:
                rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at, run_id").fetchall()
            else:
                normalized_statuses = [str(status).upper() for status in statuses]
                if not normalized_statuses:
                    return []
                placeholders = ",".join("?" for _ in normalized_statuses)
                rows = self._conn.execute(
                    f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at, run_id",
                    normalized_statuses,
                ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def list_nonterminal_jobs(self) -> List[DurableJobRecord]:
        with self._lock:
            placeholders = ",".join("?" for _ in self.TERMINAL_STATUSES)
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE status NOT IN ({placeholders}) ORDER BY created_at, run_id",
                sorted(self.TERMINAL_STATUSES),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def mark_recovery_required(
        self,
        run_id: str,
        reason: str = "PROCESS_RESTART_RECONCILIATION_REQUIRED",
    ) -> DurableJobRecord:
        current = self.get_job(run_id)
        if current is None:
            raise JobStoreConflictError(f"JOB_NOT_FOUND: run_id={run_id}")
        if current.status in self.TERMINAL_STATUSES:
            return current
        recovered = replace(
            current,
            status="RECOVERY_REQUIRED",
            completed_at=None,
            recovery_reason=sanitize_sensitive_text(reason),
            record_hash="",
        )
        return self.save_job(
            recovered,
            event_type="RECOVERY_REQUIRED",
            message=reason,
        )

    def delete_unstarted_job(self, run_id: str) -> bool:
        """Rollback an admission that never reached a worker.

        This is deliberately narrow; started or non-QUEUED jobs are retained for
        audit instead of being hard-deleted.
        """
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT status, started_at FROM jobs WHERE run_id=?", (run_id,)
                ).fetchone()
                if row is None:
                    return False
                if row["status"] != "QUEUED" or row["started_at"] is not None:
                    raise JobStoreConflictError(
                        f"JOB_DELETE_FORBIDDEN: run_id={run_id} has entered execution lifecycle"
                    )
                with self._conn:
                    self._conn.execute("DELETE FROM jobs WHERE run_id=?", (run_id,))
                return True
            except JobStoreError:
                raise
            except sqlite3.Error as exc:
                raise _sqlite_failure("DELETE", exc) from exc

    def append_checkpoint(self, checkpoint: ExecutionCheckpoint) -> bool:
        calculated = checkpoint.calculate_checkpoint_hash()
        if not checkpoint.checkpoint_hash or checkpoint.checkpoint_hash != calculated:
            raise JobStoreIntegrityError(
                f"CHECKPOINT_INTEGRITY_MISMATCH: checkpoint_id={checkpoint.checkpoint_id}"
            )

        payload = sanitize_sensitive_payload(checkpoint.model_dump())
        payload_json = _canonical_json(payload)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO job_checkpoints(
                            checkpoint_id, run_id, checkpoint_hash, payload_json, payload_hash, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            checkpoint.checkpoint_id,
                            checkpoint.run_id,
                            checkpoint.checkpoint_hash,
                            payload_json,
                            payload_hash,
                            checkpoint.timestamp.isoformat(),
                        ),
                    )
                    self._append_event_locked(
                        checkpoint.run_id,
                        "CHECKPOINT_SAVED",
                        checkpoint.status.value,
                        checkpoint.checkpoint_id,
                    )
            except sqlite3.IntegrityError as exc:
                try:
                    existing = self._conn.execute(
                        "SELECT payload_hash FROM job_checkpoints WHERE checkpoint_id=?",
                        (checkpoint.checkpoint_id,),
                    ).fetchone()
                except sqlite3.Error as lookup_exc:
                    raise _sqlite_failure("CHECKPOINT_LOOKUP", lookup_exc) from lookup_exc
                if existing is not None and existing["payload_hash"] == payload_hash:
                    return False
                raise JobStoreConflictError(
                    f"CHECKPOINT_ALREADY_EXISTS: checkpoint_id={checkpoint.checkpoint_id}"
                ) from exc
            except sqlite3.Error as exc:
                raise _sqlite_failure("CHECKPOINT_SAVE", exc) from exc
        return True

    def list_checkpoints(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_checkpoints WHERE run_id=? ORDER BY created_at, checkpoint_id",
                (run_id,),
            ).fetchall()
            checkpoints: List[Dict[str, Any]] = []
            for row in rows:
                payload_json = row["payload_json"]
                expected_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
                if expected_hash != row["payload_hash"]:
                    raise JobStoreIntegrityError(
                        f"CHECKPOINT_PAYLOAD_INTEGRITY_MISMATCH: checkpoint_id={row['checkpoint_id']}"
                    )
                payload = json.loads(payload_json)
                try:
                    payload_created_at = datetime.fromisoformat(str(payload.get("timestamp"))).isoformat()
                except (TypeError, ValueError) as exc:
                    raise JobStoreIntegrityError(
                        f"CHECKPOINT_INDEX_METADATA_MISMATCH: checkpoint_id={row['checkpoint_id']} field=created_at"
                    ) from exc
                indexed_metadata = {
                    "checkpoint_id": payload.get("checkpoint_id"),
                    "run_id": payload.get("run_id"),
                    "checkpoint_hash": payload.get("checkpoint_hash"),
                    "created_at": payload_created_at,
                }
                for field, payload_value in indexed_metadata.items():
                    if row[field] != payload_value:
                        raise JobStoreIntegrityError(
                            f"CHECKPOINT_INDEX_METADATA_MISMATCH: checkpoint_id={row['checkpoint_id']} field={field}"
                        )
                checkpoints.append(payload)
            return checkpoints

    def list_events(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id, run_id, event_type, status, message, created_at "
                "FROM job_events WHERE run_id=? ORDER BY event_id",
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SQLiteJobRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
