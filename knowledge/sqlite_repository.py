"""Durable, scope-safe SQLite knowledge repository.

This implementation preserves the VersionedKnowledgeRepository public contract
while moving sources, current documents, immutable version records, and full
version snapshots onto durable storage. A repository may optionally be bound to
one canonical knowledge scope; cross-scope private access then fails closed with
PermissionError("scope_violation").
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from knowledge.lifecycle_models import KnowledgeLifecycleState
from knowledge.models import (
    AuthorityLevel,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeVersion,
    SourceType,
)
from knowledge.versioned_repository import VersionedKnowledgeRepository


_INACTIVE_STATES = {
    KnowledgeLifecycleState.RETIRED.value,
    KnowledgeLifecycleState.SUPERSEDED.value,
    KnowledgeLifecycleState.DELETED.value,
}


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


def _source_from_json(payload: str) -> KnowledgeSource:
    data = json.loads(payload)
    return KnowledgeSource(
        source_id=data["source_id"],
        source_name=data["source_name"],
        source_url_or_path=data["source_url_or_path"],
        source_type=SourceType(data["source_type"]),
        verified_at=_parse_datetime(data.get("verified_at")),
        authority_score=float(data.get("authority_score", 1.0)),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
    )


def _chunk_from_dict(data: Dict[str, Any]) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=data["chunk_id"],
        document_id=data["document_id"],
        text=data["text"],
        chunk_index=int(data.get("chunk_index", 0)),
        tags=list(data.get("tags") or []),
        metadata=dict(data.get("metadata") or {}),
        provenance_ref=str(data.get("provenance_ref") or ""),
    )


def _document_from_json(payload: str) -> KnowledgeDocument:
    data = json.loads(payload)
    return KnowledgeDocument(
        knowledge_id=data["knowledge_id"],
        source_id=data["source_id"],
        title=data["title"],
        source_type=SourceType(data["source_type"]),
        content=data["content"],
        version=int(data.get("version", 1)),
        authority_level=AuthorityLevel(data["authority_level"]),
        freshness=str(data.get("freshness") or "FRESH"),
        tags=list(data.get("tags") or []),
        scope=str(data.get("scope") or "GLOBAL"),
        content_hash=str(data.get("content_hash") or ""),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_parse_datetime(data.get("updated_at")) or datetime.now(timezone.utc),
        metadata=dict(data.get("metadata") or {}),
        chunks=[_chunk_from_dict(item) for item in (data.get("chunks") or [])],
    )


def _version_from_json(payload: str) -> KnowledgeVersion:
    data = json.loads(payload)
    return KnowledgeVersion(
        version_id=data["version_id"],
        document_id=data["document_id"],
        version_number=int(data.get("version_number", 1)),
        changed_by=str(data.get("changed_by") or "system"),
        change_summary=str(data.get("change_summary") or "Saved"),
        created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        content_hash=str(data.get("content_hash") or ""),
    )


class SQLiteKnowledgeRepository(VersionedKnowledgeRepository):
    """SQLite-backed implementation of the versioned knowledge contract.

    ``access_scope=None`` represents the privileged internal repository used by
    the application composition root. Supplying a canonical scope key creates a
    fail-closed scope-bound view suitable for tenant/project isolation checks.
    GLOBAL documents remain readable from a scope-bound view, but writes are
    limited to that view's exact scope.
    """

    def __init__(self, database_path: PathLike, *, access_scope: Optional[str] = None) -> None:
        # Do not call VersionedKnowledgeRepository.__init__: its dictionaries are
        # intentionally bypassed so durable state has one source of truth.
        self.database_path = str(database_path)
        self.access_scope = self._normalize_scope(access_scope) if access_scope is not None else None
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
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA synchronous = FULL")
        if self.database_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize_schema()

    @staticmethod
    def _normalize_scope(scope: Optional[str]) -> str:
        normalized = str(scope or "GLOBAL").strip()
        return "GLOBAL" if normalized.upper() == "GLOBAL" else normalized

    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("knowledge_repository_closed")
        return self._connection

    def _initialize_schema(self) -> None:
        with self._lock, self._conn():
            self._conn().executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    source_id TEXT PRIMARY KEY,
                    scope_key TEXT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    knowledge_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_versions (
                    knowledge_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    version_payload TEXT NOT NULL,
                    snapshot_payload TEXT NOT NULL,
                    PRIMARY KEY (knowledge_id, version_number),
                    FOREIGN KEY (knowledge_id)
                        REFERENCES knowledge_documents(knowledge_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_scope
                    ON knowledge_documents(scope_key);
                CREATE INDEX IF NOT EXISTS idx_knowledge_versions_document
                    ON knowledge_versions(knowledge_id, version_number);
                CREATE INDEX IF NOT EXISTS idx_knowledge_sources_scope
                    ON knowledge_sources(scope_key);
                """
            )

    def close(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                connection.close()

    def __enter__(self) -> "SQLiteKnowledgeRepository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _assert_read_scope(self, scope: Optional[str]) -> None:
        if self.access_scope is None:
            return
        normalized = self._normalize_scope(scope)
        if normalized in {self.access_scope, "GLOBAL"}:
            return
        raise PermissionError("scope_violation")

    def _assert_write_scope(self, scope: Optional[str]) -> None:
        if self.access_scope is None:
            return
        if self._normalize_scope(scope) == self.access_scope:
            return
        raise PermissionError("scope_violation")

    def _assert_source_read_scope(self, scope: Optional[str]) -> None:
        if self.access_scope is None:
            return
        if scope is not None and self._normalize_scope(scope) in {self.access_scope, "GLOBAL"}:
            return
        # A NULL source scope is legacy/privileged data with unknown ownership;
        # a scope-bound reader must not infer ownership from it.
        raise PermissionError("scope_violation")

    def save_source(self, source: KnowledgeSource) -> KnowledgeSource:
        stored = self._clone(source)
        with self._lock, self._conn():
            existing = self._conn().execute(
                "SELECT scope_key FROM knowledge_sources WHERE source_id = ?",
                (stored.source_id,),
            ).fetchone()

            if self.access_scope is not None:
                if existing is not None:
                    existing_scope = existing["scope_key"]
                    if existing_scope is None or self._normalize_scope(existing_scope) != self.access_scope:
                        raise PermissionError("scope_violation")
                stored_scope: Optional[str] = self.access_scope
            else:
                stored_scope = existing["scope_key"] if existing is not None else None

            self._conn().execute(
                """
                INSERT INTO knowledge_sources(source_id, scope_key, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    scope_key = excluded.scope_key,
                    payload = excluded.payload
                """,
                (stored.source_id, stored_scope, _json_dumps(stored.model_dump())),
            )
        return self._clone(stored)

    def get_source(self, source_id: str) -> Optional[KnowledgeSource]:
        with self._lock:
            row = self._conn().execute(
                "SELECT scope_key, payload FROM knowledge_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        self._assert_source_read_scope(row["scope_key"])
        return _source_from_json(row["payload"])

    def save_document(
        self,
        document: KnowledgeDocument,
        changed_by: str = "system",
        summary: str = "Saved",
    ) -> KnowledgeDocument:
        incoming = self._clone(document)
        incoming.scope = self._normalize_scope(incoming.scope)
        self._assert_write_scope(incoming.scope)

        with self._lock, self._conn():
            row = self._conn().execute(
                "SELECT scope_key, payload FROM knowledge_documents WHERE knowledge_id = ?",
                (incoming.knowledge_id,),
            ).fetchone()

            if row is not None:
                existing_scope = self._normalize_scope(row["scope_key"])
                self._assert_write_scope(existing_scope)
                existing = _document_from_json(row["payload"])
                if self.access_scope is not None and existing_scope != incoming.scope:
                    raise PermissionError("scope_violation")
                incoming.version = existing.version + 1
                incoming.created_at = existing.created_at
                incoming.updated_at = datetime.now(timezone.utc)
            else:
                incoming.version = max(1, int(incoming.version or 1))

            incoming.content_hash = incoming.calculate_content_hash()
            incoming.generate_chunks()

            version = KnowledgeVersion(
                document_id=incoming.knowledge_id,
                version_number=incoming.version,
                changed_by=changed_by,
                change_summary=summary,
                content_hash=incoming.content_hash,
            )
            document_payload = _json_dumps(incoming.model_dump())

            self._conn().execute(
                """
                INSERT INTO knowledge_documents(knowledge_id, scope_key, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(knowledge_id) DO UPDATE SET
                    scope_key = excluded.scope_key,
                    payload = excluded.payload
                """,
                (incoming.knowledge_id, incoming.scope, document_payload),
            )
            self._conn().execute(
                """
                INSERT INTO knowledge_versions(
                    knowledge_id,
                    version_number,
                    version_payload,
                    snapshot_payload
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    incoming.knowledge_id,
                    incoming.version,
                    _json_dumps(version.model_dump()),
                    document_payload,
                ),
            )

        return self._clone(incoming)

    def get_document(self, knowledge_id: str) -> Optional[KnowledgeDocument]:
        with self._lock:
            row = self._conn().execute(
                "SELECT scope_key, payload FROM knowledge_documents WHERE knowledge_id = ?",
                (knowledge_id,),
            ).fetchone()
        if row is None:
            return None
        self._assert_read_scope(row["scope_key"])
        return _document_from_json(row["payload"])

    def get_document_version(self, knowledge_id: str, version_number: int) -> Optional[KnowledgeDocument]:
        with self._lock:
            owner = self._conn().execute(
                "SELECT scope_key FROM knowledge_documents WHERE knowledge_id = ?",
                (knowledge_id,),
            ).fetchone()
            if owner is None:
                return None
            self._assert_read_scope(owner["scope_key"])
            row = self._conn().execute(
                """
                SELECT snapshot_payload
                FROM knowledge_versions
                WHERE knowledge_id = ? AND version_number = ?
                """,
                (knowledge_id, int(version_number)),
            ).fetchone()
        if row is None:
            return None
        return _document_from_json(row["snapshot_payload"])

    def get_version_history(self, knowledge_id: str) -> List[KnowledgeVersion]:
        with self._lock:
            owner = self._conn().execute(
                "SELECT scope_key FROM knowledge_documents WHERE knowledge_id = ?",
                (knowledge_id,),
            ).fetchone()
            if owner is None:
                return []
            self._assert_read_scope(owner["scope_key"])
            rows = self._conn().execute(
                """
                SELECT version_payload
                FROM knowledge_versions
                WHERE knowledge_id = ?
                ORDER BY version_number ASC
                """,
                (knowledge_id,),
            ).fetchall()
        return [_version_from_json(row["version_payload"]) for row in rows]

    def list_documents(
        self,
        scope: Optional[str] = None,
        tags: Optional[List[str]] = None,
        authority_level: Optional[AuthorityLevel] = None,
        source_type: Optional[SourceType] = None,
        *,
        include_inactive: bool = False,
    ) -> List[KnowledgeDocument]:
        normalized_scope: Optional[str] = None
        if scope is not None:
            normalized_scope = self._normalize_scope(scope)
            self._assert_read_scope(normalized_scope)

        with self._lock:
            if normalized_scope is not None:
                rows = self._conn().execute(
                    "SELECT payload FROM knowledge_documents WHERE scope_key = ? ORDER BY rowid ASC",
                    (normalized_scope,),
                ).fetchall()
            elif self.access_scope is not None:
                rows = self._conn().execute(
                    """
                    SELECT payload
                    FROM knowledge_documents
                    WHERE scope_key IN (?, 'GLOBAL')
                    ORDER BY rowid ASC
                    """,
                    (self.access_scope,),
                ).fetchall()
            else:
                rows = self._conn().execute(
                    "SELECT payload FROM knowledge_documents ORDER BY rowid ASC"
                ).fetchall()

        results = [_document_from_json(row["payload"]) for row in rows]
        if not include_inactive:
            results = [doc for doc in results if str(doc.freshness).upper() not in _INACTIVE_STATES]
        if authority_level is not None:
            results = [doc for doc in results if doc.authority_level == authority_level]
        if source_type is not None:
            results = [doc for doc in results if doc.source_type == source_type]
        if tags:
            wanted = {tag.lower() for tag in tags}
            results = [doc for doc in results if wanted.intersection({tag.lower() for tag in doc.tags})]
        return results
