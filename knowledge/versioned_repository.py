"""Immutable-snapshot knowledge repository for managed platform knowledge.

The legacy LocalKnowledgeRepository keeps object references and hash-only version
records. This repository stores defensive copies of complete documents for every
version, enforces authority filters, and excludes inactive lifecycle states from
normal retrieval.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from knowledge.lifecycle_models import KnowledgeLifecycleState
from knowledge.models import (
    AuthorityLevel,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeVersion,
    SourceType,
)
from knowledge.repository import KnowledgeRepository


_AUTHORITY_RANK = {
    AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH: 4,
    AuthorityLevel.TIER_2_VERIFIED_RESEARCH: 3,
    AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA: 2,
    AuthorityLevel.TIER_4_UNVERIFIED_OBSERVATION: 1,
}

_INACTIVE_STATES = {
    KnowledgeLifecycleState.RETIRED.value,
    KnowledgeLifecycleState.SUPERSEDED.value,
    KnowledgeLifecycleState.DELETED.value,
}


class VersionedKnowledgeRepository(KnowledgeRepository):
    """In-memory v1 repository with immutable full-document version snapshots."""

    def __init__(self) -> None:
        self._documents: Dict[str, KnowledgeDocument] = {}
        self._sources: Dict[str, KnowledgeSource] = {}
        self._versions: Dict[str, List[KnowledgeVersion]] = {}
        self._snapshots: Dict[str, List[KnowledgeDocument]] = {}

    @staticmethod
    def _clone(value):
        return copy.deepcopy(value)

    def save_source(self, source: KnowledgeSource) -> KnowledgeSource:
        stored = self._clone(source)
        self._sources[stored.source_id] = stored
        return self._clone(stored)

    def get_source(self, source_id: str) -> Optional[KnowledgeSource]:
        source = self._sources.get(source_id)
        return self._clone(source) if source is not None else None

    def save_document(
        self,
        document: KnowledgeDocument,
        changed_by: str = "system",
        summary: str = "Saved",
    ) -> KnowledgeDocument:
        incoming = self._clone(document)
        existing = self._documents.get(incoming.knowledge_id)

        if existing is not None:
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
        self._versions.setdefault(incoming.knowledge_id, []).append(self._clone(version))
        self._snapshots.setdefault(incoming.knowledge_id, []).append(self._clone(incoming))
        self._documents[incoming.knowledge_id] = self._clone(incoming)
        return self._clone(incoming)

    def get_document(self, knowledge_id: str) -> Optional[KnowledgeDocument]:
        document = self._documents.get(knowledge_id)
        return self._clone(document) if document is not None else None

    def get_document_version(self, knowledge_id: str, version_number: int) -> Optional[KnowledgeDocument]:
        for snapshot in self._snapshots.get(knowledge_id, []):
            if snapshot.version == version_number:
                return self._clone(snapshot)
        return None

    def get_version_history(self, knowledge_id: str) -> List[KnowledgeVersion]:
        return self._clone(self._versions.get(knowledge_id, []))

    def list_documents(
        self,
        scope: Optional[str] = None,
        tags: Optional[List[str]] = None,
        authority_level: Optional[AuthorityLevel] = None,
        source_type: Optional[SourceType] = None,
        *,
        include_inactive: bool = False,
    ) -> List[KnowledgeDocument]:
        results = [self._clone(doc) for doc in self._documents.values()]
        if not include_inactive:
            results = [doc for doc in results if str(doc.freshness).upper() not in _INACTIVE_STATES]
        if scope is not None:
            results = [doc for doc in results if doc.scope == scope]
        if authority_level is not None:
            results = [doc for doc in results if doc.authority_level == authority_level]
        if source_type is not None:
            results = [doc for doc in results if doc.source_type == source_type]
        if tags:
            wanted = {tag.lower() for tag in tags}
            results = [doc for doc in results if wanted.intersection({tag.lower() for tag in doc.tags})]
        return results

    def query_knowledge(
        self,
        query: str,
        scope: Optional[str] = None,
        min_authority: Optional[AuthorityLevel] = None,
        *,
        include_inactive: bool = False,
    ) -> List[KnowledgeDocument]:
        needle = (query or "").strip().lower()
        documents = self.list_documents(scope=scope, include_inactive=include_inactive)
        if min_authority is not None:
            minimum = _AUTHORITY_RANK[min_authority]
            documents = [doc for doc in documents if _AUTHORITY_RANK.get(doc.authority_level, 0) >= minimum]
        if not needle:
            return documents
        return [
            doc
            for doc in documents
            if needle in doc.title.lower()
            or needle in doc.content.lower()
            or any(needle in tag.lower() for tag in doc.tags)
        ]

    def set_lifecycle_state(
        self,
        knowledge_id: str,
        state: KnowledgeLifecycleState,
        *,
        changed_by: str = "system",
        reason: str = "",
        metadata_updates: Optional[Dict[str, str]] = None,
    ) -> Optional[KnowledgeDocument]:
        document = self.get_document(knowledge_id)
        if document is None:
            return None
        document.freshness = state.value
        document.metadata["lifecycle_state"] = state.value
        document.metadata["lifecycle_changed_at"] = datetime.now(timezone.utc).isoformat()
        if reason:
            document.metadata["lifecycle_reason"] = reason
        if metadata_updates:
            document.metadata.update(metadata_updates)
        return self.save_document(
            document,
            changed_by=changed_by,
            summary=f"Lifecycle -> {state.value}: {reason}".rstrip(": "),
        )

    def supersede(
        self,
        old_knowledge_id: str,
        new_knowledge_id: str,
        *,
        changed_by: str = "system",
        reason: str = "Replaced by newer knowledge",
    ) -> bool:
        old = self.get_document(old_knowledge_id)
        new = self.get_document(new_knowledge_id)
        if old is None or new is None or old_knowledge_id == new_knowledge_id:
            return False
        updated = self.set_lifecycle_state(
            old_knowledge_id,
            KnowledgeLifecycleState.SUPERSEDED,
            changed_by=changed_by,
            reason=reason,
            metadata_updates={"superseded_by_id": new_knowledge_id},
        )
        if updated is None:
            return False
        new.metadata["supersedes_id"] = old_knowledge_id
        self.save_document(new, changed_by=changed_by, summary=f"Supersedes {old_knowledge_id}")
        return True

    def soft_delete(self, knowledge_id: str, *, changed_by: str = "system", reason: str = "Deleted") -> bool:
        return self.set_lifecycle_state(
            knowledge_id,
            KnowledgeLifecycleState.DELETED,
            changed_by=changed_by,
            reason=reason,
        ) is not None

    def restore_version(
        self,
        knowledge_id: str,
        version_number: int,
        *,
        changed_by: str = "system",
    ) -> Optional[KnowledgeDocument]:
        snapshot = self.get_document_version(knowledge_id, version_number)
        if snapshot is None:
            return None
        snapshot.metadata["restored_from_version"] = str(version_number)
        snapshot.freshness = KnowledgeLifecycleState.ACTIVE.value
        return self.save_document(
            snapshot,
            changed_by=changed_by,
            summary=f"Restored content from version {version_number}",
        )

    def verify_provenance(self, citation: KnowledgeCitation) -> bool:
        document = self.get_document(citation.knowledge_id)
        if document is None:
            return False
        if citation.source_id and citation.source_id != document.source_id:
            return False
        if self.get_source(document.source_id) is None:
            return False
        if citation.chunk_id and not any(chunk.chunk_id == citation.chunk_id for chunk in document.chunks):
            return False
        return document.content_hash == document.calculate_content_hash()
