"""Durable SQLite implementation of the LearningRepository contract."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from memory.learning import LearningEvent, LearningRepository
from memory.models import PromotionState


PathLike = Union[str, Path]


def _parse_datetime(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _learning_from_json(payload: str) -> LearningEvent:
    data: Dict[str, Any] = json.loads(payload)
    return LearningEvent(
        learning_event_id=str(data["learning_event_id"]),
        campaign_id=str(data["campaign_id"]),
        hypothesis=str(data["hypothesis"]),
        experiment_id=str(data["experiment_id"]),
        baseline=dict(data.get("baseline") or {}),
        treatment=dict(data.get("treatment") or {}),
        primary_metric=str(data["primary_metric"]),
        secondary_metrics=dict(data.get("secondary_metrics") or {}),
        observed_result=dict(data.get("observed_result") or {}),
        sample_or_evidence=dict(data.get("sample_or_evidence") or {}),
        confidence=float(data.get("confidence", 0.5)),
        decision=str(data["decision"]),
        lesson=str(data["lesson"]),
        applicability_scope=str(data.get("applicability_scope") or "GLOBAL"),
        promotion_status=PromotionState(
            data.get("promotion_status") or PromotionState.CANDIDATE_MEMORY.value
        ),
        retest_required=bool(data.get("retest_required", False)),
        created_at=_parse_datetime(data.get("created_at")),
        metadata=dict(data.get("metadata") or {}),
    )


class SQLiteLearningRepository(LearningRepository):
    """Crash-safe SQLite learning store with atomic upsert semantics."""

    def __init__(self, database_path: PathLike) -> None:
        self.database_path = str(database_path)
        self._lock = threading.RLock()
        self._connection: Optional[sqlite3.Connection] = None

        if self.database_path != ":memory:":
            path = Path(self.database_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.database_path = str(path)

        self._connection = sqlite3.connect(
            self.database_path,
            timeout=30.0,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA synchronous = FULL")
        if self.database_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize_schema()

    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("learning_repository_closed")
        return self._connection

    def _initialize_schema(self) -> None:
        with self._lock, self._conn():
            self._conn().executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_events (
                    learning_event_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    promotion_status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_learning_campaign
                    ON learning_events(campaign_id);
                CREATE INDEX IF NOT EXISTS idx_learning_scope
                    ON learning_events(scope_key);
                CREATE INDEX IF NOT EXISTS idx_learning_promotion
                    ON learning_events(promotion_status);
                """
            )

    def close(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                connection.close()

    def __enter__(self) -> "SQLiteLearningRepository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def record_learning(self, event: LearningEvent) -> LearningEvent:
        payload = _json_dumps(event.model_dump())
        with self._lock, self._conn():
            self._conn().execute(
                """
                INSERT INTO learning_events(
                    learning_event_id,
                    campaign_id,
                    scope_key,
                    promotion_status,
                    payload
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(learning_event_id) DO UPDATE SET
                    campaign_id = excluded.campaign_id,
                    scope_key = excluded.scope_key,
                    promotion_status = excluded.promotion_status,
                    payload = excluded.payload
                """,
                (
                    event.learning_event_id,
                    event.campaign_id,
                    event.applicability_scope,
                    event.promotion_status.value,
                    payload,
                ),
            )
        return _learning_from_json(payload)

    def get_learning(self, learning_event_id: str) -> Optional[LearningEvent]:
        with self._lock:
            row = self._conn().execute(
                "SELECT payload FROM learning_events WHERE learning_event_id = ?",
                (learning_event_id,),
            ).fetchone()
        return _learning_from_json(row["payload"]) if row is not None else None

    def list_learnings(
        self,
        campaign_id: Optional[str] = None,
        scope: Optional[str] = None,
        promotion_status: Optional[PromotionState] = None,
    ) -> List[LearningEvent]:
        clauses: List[str] = []
        params: List[Any] = []

        if campaign_id:
            clauses.append("campaign_id = ?")
            params.append(campaign_id)
        if scope:
            clauses.append("(scope_key = ? OR scope_key = 'GLOBAL')")
            params.append(scope)
        if promotion_status is not None:
            clauses.append("promotion_status = ?")
            params.append(promotion_status.value)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn().execute(
                f"SELECT payload FROM learning_events{where} ORDER BY rowid ASC",
                tuple(params),
            ).fetchall()
        return [_learning_from_json(row["payload"]) for row in rows]

    def query_learnings_for_context(self, context_tags: List[str]) -> List[LearningEvent]:
        tag_set = {str(tag).lower() for tag in context_tags}
        return [
            event
            for event in self.list_learnings()
            if any(
                tag in event.lesson.lower() or tag in event.hypothesis.lower()
                for tag in tag_set
            )
        ]
