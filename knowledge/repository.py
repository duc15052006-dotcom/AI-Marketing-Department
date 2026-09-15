"""Knowledge Repository and Provenance Layer (Phase 5.1).

Provides provider-neutral storage, versioning, search, and provenance lookup
for all durable reference knowledge.
"""

from __future__ import annotations

import abc
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from knowledge.models import (
    AuthorityLevel,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeVersion,
    SourceType,
)


def get_default_knowledge_database_path() -> Path:
    """Return the durable per-user production knowledge database path.

    ``AI_MARKETING_KNOWLEDGE_DB_PATH`` is an explicit operations/test override.
    Otherwise Windows uses APPDATA/LOCALAPPDATA and non-Windows systems use the
    user's home directory. The parent directory is created by the SQLite backend.
    """

    override = os.environ.get("AI_MARKETING_KNOWLEDGE_DB_PATH")
    if override:
        return Path(override).expanduser()

    app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if app_data:
        return Path(app_data) / "AI-Marketing-Department" / "knowledge" / "knowledge.sqlite3"
    return Path.home() / ".ai-marketing-department" / "knowledge" / "knowledge.sqlite3"


class KnowledgeRepository(abc.ABC):
    """Abstract interface for knowledge storage and querying."""

    @abc.abstractmethod
    def save_document(self, document: KnowledgeDocument, changed_by: str = "system", summary: str = "Update") -> KnowledgeDocument:
        pass

    @abc.abstractmethod
    def get_document(self, knowledge_id: str) -> Optional[KnowledgeDocument]:
        pass

    @abc.abstractmethod
    def list_documents(
        self,
        scope: Optional[str] = None,
        tags: Optional[List[str]] = None,
        authority_level: Optional[AuthorityLevel] = None,
        source_type: Optional[SourceType] = None,
    ) -> List[KnowledgeDocument]:
        pass

    @abc.abstractmethod
    def save_source(self, source: KnowledgeSource) -> KnowledgeSource:
        pass

    @abc.abstractmethod
    def get_source(self, source_id: str) -> Optional[KnowledgeSource]:
        pass

    @abc.abstractmethod
    def get_version_history(self, knowledge_id: str) -> List[KnowledgeVersion]:
        pass

    @abc.abstractmethod
    def query_knowledge(self, query: str, scope: Optional[str] = None, min_authority: Optional[AuthorityLevel] = None) -> List[KnowledgeDocument]:
        pass


class LocalKnowledgeRepository(KnowledgeRepository):
    """Compatibility facade for the application's local knowledge repository.

    Normal runtime construction is durable and returns SQLiteKnowledgeRepository.
    ``AI_MARKETING_KNOWLEDGE_EPHEMERAL=1`` is reserved for hermetic legacy tests
    that intentionally exercise the historical in-memory behavior.
    """

    def __new__(cls):
        if cls is LocalKnowledgeRepository and os.environ.get("AI_MARKETING_KNOWLEDGE_EPHEMERAL") != "1":
            # Lazy import avoids a module cycle: sqlite_repository ->
            # versioned_repository -> KnowledgeRepository (this module).
            from knowledge.sqlite_repository import SQLiteKnowledgeRepository

            return SQLiteKnowledgeRepository(get_default_knowledge_database_path())
        return super().__new__(cls)

    def __init__(self) -> None:
        self._documents: Dict[str, KnowledgeDocument] = {}
        self._sources: Dict[str, KnowledgeSource] = {}
        self._versions: Dict[str, List[KnowledgeVersion]] = {}

    def save_source(self, source: KnowledgeSource) -> KnowledgeSource:
        self._sources[source.source_id] = source
        return source

    def get_source(self, source_id: str) -> Optional[KnowledgeSource]:
        return self._sources.get(source_id)

    def save_document(self, document: KnowledgeDocument, changed_by: str = "system", summary: str = "Saved") -> KnowledgeDocument:
        if not document.content_hash:
            document.content_hash = document.calculate_content_hash()
        if not document.chunks:
            document.generate_chunks()

        existing = self._documents.get(document.knowledge_id)
        if existing:
            document.version = existing.version + 1
            document.updated_at = datetime.now(timezone.utc)

        # Create version snapshot
        ver = KnowledgeVersion(
            document_id=document.knowledge_id,
            version_number=document.version,
            changed_by=changed_by,
            change_summary=summary,
            content_hash=document.content_hash,
        )
        if document.knowledge_id not in self._versions:
            self._versions[document.knowledge_id] = []
        self._versions[document.knowledge_id].append(ver)

        self._documents[document.knowledge_id] = document
        return document

    def get_document(self, knowledge_id: str) -> Optional[KnowledgeDocument]:
        return self._documents.get(knowledge_id)

    def get_version_history(self, knowledge_id: str) -> List[KnowledgeVersion]:
        return self._versions.get(knowledge_id, [])

    def list_documents(
        self,
        scope: Optional[str] = None,
        tags: Optional[List[str]] = None,
        authority_level: Optional[AuthorityLevel] = None,
        source_type: Optional[SourceType] = None,
    ) -> List[KnowledgeDocument]:
        results = list(self._documents.values())
        if scope:
            results = [d for d in results if d.scope == scope]
        if authority_level:
            results = [d for d in results if d.authority_level == authority_level]
        if source_type:
            results = [d for d in results if d.source_type == source_type]
        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [d for d in results if tag_set.intersection(set(t.lower() for t in d.tags))]
        return results

    def query_knowledge(self, query: str, scope: Optional[str] = None, min_authority: Optional[AuthorityLevel] = None) -> List[KnowledgeDocument]:
        q_lower = query.lower()
        docs = self.list_documents(scope=scope)
        matched = []
        for d in docs:
            if q_lower in d.title.lower() or q_lower in d.content.lower() or any(q_lower in t.lower() for t in d.tags):
                matched.append(d)
        return matched

    def verify_provenance(self, citation: KnowledgeCitation) -> bool:
        """Verify whether a knowledge citation resolves to an authentic document/chunk."""
        doc = self.get_document(citation.knowledge_id)
        if not doc:
            return False
        if citation.chunk_id:
            chunk_exists = any(c.chunk_id == citation.chunk_id for c in doc.chunks)
            if not chunk_exists:
                return False
        return True
