"""Durable SQLite implementation of the legacy MemoryRepository contract.

The five-agent runtime still consumes ``MemoryRepository`` through the historical
``LocalMemoryRepository`` facade.  This module gives that facade a durable
production backend without changing agent behavior, MemoryManager governance,
or ContextCompiler semantics.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import MemoryRepository


PathLike = Union[str, Path]


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None or value == "":
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _memory_from_json(payload: str) -> MemoryItem:
    data: Dict[str, Any] = json.loads(payload)
    return MemoryItem(
        memory_id=data["memory_id"],
        memory_type=MemoryType(data["memory_type"]),
        agent_source=str(data["agent_source"]),
        run_id=str(data.get("run_id") or "RUN-UNKNOWN"),
        timestamp=_parse_datetime(data.get("timestamp")) or datetime.now(timezone.utc),
        context=dict(data.get("context") or {}),
        content=str(data.get("content") or ""),
        evidence_refs=list(data.get("evidence_refs") or []),
        confidence=float(data.get("confidence", 0.5)),
        status=str(data.get("status") or "ACTIVE"),
        promotion_level=PromotionState(data.get("promotion_level") or PromotionState.RAW_OBSERVATION.value),
        scope=str(data.get("scope") or "GLOBAL"),
        expiry_or_review_date=_parse_datetime(data.get("expiry_or_review_date")),
        metadata=dict(data.get("metadata") or {}),
    )


def _sanitized_memory_payload(memory: MemoryItem) -> Dict[str, Any]:
    """Return a persistence-safe copy without mutating caller-owned Memory state.

    Structural authority fields stay byte-for-byte equivalent to the validated
    ``MemoryItem``. Only payload-bearing fields that may contain external/user
    credential material are passed through the shared governance sanitizer.
    """

    data: Dict[str, Any] = dict(memory.model_dump())
    data["content"] = sanitize_sensitive_text(data.get("content"))
    data["context"] = sanitize_sensitive_payload(dict(data.get("context") or {}))
    data["metadata"] = sanitize_sensitive_payload(dict(data.get("metadata") or {}))
    data["evidence_refs"] = sanitize_sensitive_payload(list(data.get("evidence_refs") or []))
    return data


class SQLiteMemoryRepository(MemoryRepository):
    """SQLite-backed MemoryRepository with one durable source of truth."""

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
            raise RuntimeError("memory_repository_closed")
        return self._connection

    def _initialize_schema(self) -> None:
        with self._lock, self._conn():
            self._conn().executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    agent_source TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    promotion_level TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_type
                    ON memories(memory_type);
                CREATE INDEX IF NOT EXISTS idx_memories_agent
                    ON memories(agent_source);
                CREATE INDEX IF NOT EXISTS idx_memories_run
                    ON memories(run_id);
                CREATE INDEX IF NOT EXISTS idx_memories_promotion
                    ON memories(promotion_level);
                CREATE INDEX IF NOT EXISTS idx_memories_scope
                    ON memories(scope_key);
                """
            )

    def close(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                connection.close()

    def __enter__(self) -> "SQLiteMemoryRepository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def save_memory(self, memory: MemoryItem) -> MemoryItem:
        payload = _json_dumps(_sanitized_memory_payload(memory))
        with self._lock, self._conn():
            self._conn().execute(
                """
                INSERT INTO memories(
                    memory_id,
                    memory_type,
                    agent_source,
                    run_id,
                    promotion_level,
                    scope_key,
                    payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    memory_type = excluded.memory_type,
                    agent_source = excluded.agent_source,
                    run_id = excluded.run_id,
                    promotion_level = excluded.promotion_level,
                    scope_key = excluded.scope_key,
                    payload = excluded.payload
                """,
                (
                    memory.memory_id,
                    memory.memory_type.value,
                    memory.agent_source,
                    memory.run_id,
                    memory.promotion_level.value,
                    str(memory.scope or "GLOBAL"),
                    payload,
                ),
            )
        return _memory_from_json(payload)

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        with self._lock:
            row = self._conn().execute(
                "SELECT payload FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return _memory_from_json(row["payload"]) if row is not None else None

    def list_memories(
        self,
        memory_type: Optional[MemoryType] = None,
        agent_source: Optional[str] = None,
        run_id: Optional[str] = None,
        promotion_level: Optional[PromotionState] = None,
    ) -> List[MemoryItem]:
        clauses: List[str] = []
        params: List[Any] = []

        if memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(memory_type.value)
        if agent_source:
            clauses.append("LOWER(agent_source) = LOWER(?)")
            params.append(agent_source)
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if promotion_level is not None:
            clauses.append("promotion_level = ?")
            params.append(promotion_level.value)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT payload FROM memories{where} ORDER BY rowid ASC"
        with self._lock:
            rows = self._conn().execute(sql, tuple(params)).fetchall()
        return [_memory_from_json(row["payload"]) for row in rows]

    def query_memories(
        self,
        query: str,
        memory_types: Optional[List[MemoryType]] = None,
    ) -> List[MemoryItem]:
        needle = str(query or "").lower()
        results = self.list_memories()
        if memory_types:
            results = [memory for memory in results if memory.memory_type in memory_types]
        if not needle:
            return results
        return [
            memory
            for memory in results
            if needle in memory.content.lower()
            or any(needle in str(value).lower() for value in memory.context.values())
        ]

    def purge_expired_working_memories(self) -> int:
        """Preserve the historical facade contract by deleting expired working memory."""
        now = datetime.now(timezone.utc)
        expired_ids = [
            memory.memory_id
            for memory in self.list_memories(memory_type=MemoryType.WORKING_MEMORY)
            if memory.expiry_or_review_date is not None and now > memory.expiry_or_review_date
        ]
        if not expired_ids:
            return 0

        with self._lock, self._conn():
            self._conn().executemany(
                "DELETE FROM memories WHERE memory_id = ?",
                [(memory_id,) for memory_id in expired_ids],
            )
        return len(expired_ids)
