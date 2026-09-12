"""Workspace-contained Knowledge/File Manager v1.

Provides the governed entrypoint for local files, manual text, and already-
observed URL content. It intentionally does not fetch URLs itself and never
reads arbitrary absolute paths.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

from governance.redaction import sanitize_sensitive_text
from knowledge.lifecycle_models import (
    KnowledgeFileAsset,
    KnowledgeImportResult,
    KnowledgeLifecycleState,
    KnowledgeScope,
)
from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.versioned_repository import VersionedKnowledgeRepository
from tools.filesystem_guard import FilesystemSecurityError, resolve_safe_path


class KnowledgeFileManager:
    """High-level knowledge manager with strict workspace and lifecycle rules."""

    DEFAULT_ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".csv"}

    def __init__(
        self,
        workspace_root: Path,
        *,
        repository: Optional[VersionedKnowledgeRepository] = None,
        allowed_extensions: Optional[Iterable[str]] = None,
        max_file_bytes: int = 10 * 1024 * 1024,
        chunk_size: int = 1000,
    ) -> None:
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        if chunk_size < 100:
            raise ValueError("chunk_size must be >= 100")
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.repository = repository or VersionedKnowledgeRepository()
        self.allowed_extensions = {
            (ext if ext.startswith(".") else f".{ext}").lower()
            for ext in (allowed_extensions or self.DEFAULT_ALLOWED_EXTENSIONS)
        }
        self.max_file_bytes = max_file_bytes
        self.chunk_size = chunk_size
        self._assets: Dict[str, KnowledgeFileAsset] = {}

    @staticmethod
    def _normalize_text(raw_text: str, extension: str) -> str:
        if extension == ".json":
            parsed = json.loads(raw_text)
            return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)
        if extension == ".csv":
            reader = csv.DictReader(io.StringIO(raw_text))
            rows = list(reader)
            if reader.fieldnames is None:
                raise ValueError("CSV is missing a header row")
            lines = [", ".join(f"{key}: {row.get(key, '')}" for key in reader.fieldnames) for row in rows]
            return "\n".join(lines)
        return raw_text

    def _find_duplicate(self, content_hash: str, scope_key: str) -> Optional[KnowledgeDocument]:
        for document in self.repository.list_documents(scope=scope_key):
            if document.content_hash == content_hash:
                return document
        return None

    def _save_document(
        self,
        *,
        source_name: str,
        source_locator: str,
        source_type: SourceType,
        content: str,
        scope: KnowledgeScope,
        title: str,
        tags: Optional[List[str]],
        authority_level: AuthorityLevel,
        created_by: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> KnowledgeImportResult:
        normalized = content.strip()
        if len(normalized) < 5:
            return KnowledgeImportResult(success=False, error_code="EMPTY_CONTENT", error="Knowledge content is empty.")

        scope_key = scope.canonical_key()
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        duplicate = self._find_duplicate(content_hash, scope_key)
        if duplicate is not None:
            return KnowledgeImportResult(
                success=True,
                knowledge_id=duplicate.knowledge_id,
                source_id=duplicate.source_id,
                version=duplicate.version,
                duplicate_of=duplicate.knowledge_id,
            )

        source = self.repository.save_source(
            KnowledgeSource(
                source_name=source_name,
                source_url_or_path=source_locator,
                source_type=source_type,
                authority_score=1.0
                if authority_level == AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH
                else 0.85,
            )
        )
        document = KnowledgeDocument(
            source_id=source.source_id,
            title=title or source_name,
            source_type=source_type,
            content=normalized,
            authority_level=authority_level,
            freshness=KnowledgeLifecycleState.ACTIVE.value,
            tags=list(tags or []),
            scope=scope_key,
            metadata={
                "lifecycle_state": KnowledgeLifecycleState.ACTIVE.value,
                "scope_key": scope_key,
                **dict(metadata or {}),
            },
        )
        document.content_hash = content_hash
        document.generate_chunks(chunk_size=self.chunk_size)
        saved = self.repository.save_document(document, changed_by=created_by, summary="Managed knowledge ingestion")
        return KnowledgeImportResult(
            success=True,
            knowledge_id=saved.knowledge_id,
            source_id=saved.source_id,
            version=saved.version,
        )

    def ingest_file(
        self,
        relative_path: str,
        *,
        scope: Optional[KnowledgeScope] = None,
        source_type: SourceType = SourceType.MARKET_RESEARCH,
        authority_level: AuthorityLevel = AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
        title: str = "",
        tags: Optional[List[str]] = None,
        created_by: str = "operator",
    ) -> KnowledgeImportResult:
        scope = scope or KnowledgeScope()
        try:
            target = resolve_safe_path(self.workspace_root, relative_path, operation="read")
        except FilesystemSecurityError as exc:
            return KnowledgeImportResult(success=False, error_code=exc.error_code, error=exc.message)

        extension = target.suffix.lower()
        if extension not in self.allowed_extensions:
            return KnowledgeImportResult(
                success=False,
                error_code="UNSUPPORTED_FILE_TYPE",
                error=f"Unsupported knowledge file extension: {extension or '<none>'}",
            )

        size_bytes = target.stat().st_size
        if size_bytes > self.max_file_bytes:
            return KnowledgeImportResult(
                success=False,
                error_code="FILE_TOO_LARGE",
                error=f"Knowledge file exceeds the {self.max_file_bytes} byte limit.",
            )

        try:
            raw_text = target.read_text(encoding="utf-8")
            content = self._normalize_text(raw_text, extension)
        except UnicodeDecodeError:
            return KnowledgeImportResult(
                success=False,
                error_code="UNSUPPORTED_ENCODING",
                error="Knowledge files must be UTF-8 text in v1.",
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return KnowledgeImportResult(success=False, error_code="PARSE_ERROR", error=str(exc))

        result = self._save_document(
            source_name=target.name,
            source_locator=relative_path,
            source_type=source_type,
            content=content,
            scope=scope,
            title=title or target.stem,
            tags=tags,
            authority_level=authority_level,
            created_by=created_by,
            metadata={"ingestion_kind": "LOCAL_FILE", "relative_path": relative_path},
        )
        if not result.success or result.duplicate_of:
            return result

        asset = KnowledgeFileAsset(
            relative_path=relative_path,
            filename=target.name,
            extension=extension,
            size_bytes=size_bytes,
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            scope_key=scope.canonical_key(),
            knowledge_id=result.knowledge_id or "",
        )
        self._assets[asset.asset_id] = asset
        result.asset_id = asset.asset_id
        return result

    def ingest_text(
        self,
        content: str,
        *,
        source_name: str,
        scope: Optional[KnowledgeScope] = None,
        source_type: SourceType = SourceType.MARKET_RESEARCH,
        authority_level: AuthorityLevel = AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
        title: str = "",
        tags: Optional[List[str]] = None,
        created_by: str = "operator",
    ) -> KnowledgeImportResult:
        return self._save_document(
            source_name=source_name,
            source_locator=f"manual://{source_name}",
            source_type=source_type,
            content=content,
            scope=scope or KnowledgeScope(),
            title=title or source_name,
            tags=tags,
            authority_level=authority_level,
            created_by=created_by,
            metadata={"ingestion_kind": "MANUAL_TEXT"},
        )

    @staticmethod
    def _sanitize_observed_url(url: str) -> str:
        """Remove URL userinfo and redact credential-like values before persistence."""
        raw = (url or "").strip()
        if not raw:
            return ""
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return sanitize_sensitive_text(raw)
        safe_netloc = parsed.netloc.rsplit("@", 1)[-1]
        without_fragment = urlunsplit(
            (parsed.scheme, safe_netloc, parsed.path, parsed.query, "")
        )
        safe_base = sanitize_sensitive_text(without_fragment)
        if not parsed.fragment:
            return safe_base
        safe_fragment = sanitize_sensitive_text(parsed.fragment)
        return f"{safe_base}#{safe_fragment}"

    def ingest_observed_url(
        self,
        url: str,
        extracted_content: str,
        *,
        source_name: str,
        scope: Optional[KnowledgeScope] = None,
        source_type: SourceType = SourceType.MARKET_RESEARCH,
        authority_level: AuthorityLevel = AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA,
        tags: Optional[List[str]] = None,
        created_by: str = "intelligence",
    ) -> KnowledgeImportResult:
        """Store content already fetched by a governed observation capability.

        The manager never pretends a URL has been fetched. Empty extracted
        content fails closed instead of creating placeholder knowledge.
        """
        if not extracted_content or len(extracted_content.strip()) < 5:
            return KnowledgeImportResult(
                success=False,
                error_code="OBSERVATION_CONTENT_REQUIRED",
                error="Observed URL ingestion requires extracted source content.",
            )
        return self._save_document(
            source_name=source_name,
            source_locator=self._sanitize_observed_url(url),
            source_type=source_type,
            content=extracted_content,
            scope=scope or KnowledgeScope(),
            title=source_name,
            tags=tags,
            authority_level=authority_level,
            created_by=created_by,
            metadata={"ingestion_kind": "OBSERVED_URL"},
        )

    def retrieve(
        self,
        query: str,
        *,
        scope: Optional[KnowledgeScope] = None,
        include_global: bool = True,
        min_authority: Optional[AuthorityLevel] = None,
    ) -> List[KnowledgeDocument]:
        requested = scope or KnowledgeScope()
        scope_key = requested.canonical_key()
        results = self.repository.query_knowledge(query, scope=scope_key, min_authority=min_authority)
        if include_global and scope_key != "GLOBAL":
            global_results = self.repository.query_knowledge(query, scope="GLOBAL", min_authority=min_authority)
            known = {doc.knowledge_id for doc in results}
            results.extend(doc for doc in global_results if doc.knowledge_id not in known)
        return results

    def replace_document(
        self,
        old_knowledge_id: str,
        new_content: str,
        *,
        changed_by: str = "operator",
        source_name: Optional[str] = None,
    ) -> KnowledgeImportResult:
        old = self.repository.get_document(old_knowledge_id)
        if old is None:
            return KnowledgeImportResult(success=False, error_code="NOT_FOUND", error="Knowledge document not found.")
        source = self.repository.get_source(old.source_id)
        replacement = self._save_document(
            source_name=source_name or (source.source_name if source else old.title),
            source_locator=(source.source_url_or_path if source else f"replacement://{old_knowledge_id}"),
            source_type=old.source_type,
            content=new_content,
            scope=self._scope_from_key(old.scope),
            title=old.title,
            tags=list(old.tags),
            authority_level=old.authority_level,
            created_by=changed_by,
            metadata={"replacement_for": old_knowledge_id},
        )
        if not replacement.success or not replacement.knowledge_id:
            return replacement
        if replacement.knowledge_id == old_knowledge_id:
            return replacement
        if not self.repository.supersede(old_knowledge_id, replacement.knowledge_id, changed_by=changed_by):
            return KnowledgeImportResult(success=False, error_code="SUPERSEDE_FAILED", error="Replacement could not supersede old knowledge.")
        replacement_doc = self.repository.get_document(replacement.knowledge_id)
        if replacement_doc is not None:
            replacement.version = replacement_doc.version
        return replacement

    @staticmethod
    def _scope_from_key(scope_key: str) -> KnowledgeScope:
        if scope_key == "GLOBAL" or not scope_key:
            return KnowledgeScope()
        values: Dict[str, str] = {}
        mapping = {
            "BUSINESS": "business_id",
            "PROJECT": "project_id",
            "BRAND": "brand_id",
            "PRODUCT": "product_id",
            "CAMPAIGN": "campaign_id",
        }
        for part in scope_key.split("|"):
            name, sep, value = part.partition(":")
            if not sep or name not in mapping:
                raise ValueError(f"unsupported legacy knowledge scope: {scope_key}")
            values[mapping[name]] = value
        return KnowledgeScope(**values)

    def retire_document(self, knowledge_id: str, *, reason: str, changed_by: str = "operator") -> bool:
        return self.repository.set_lifecycle_state(
            knowledge_id,
            KnowledgeLifecycleState.RETIRED,
            changed_by=changed_by,
            reason=reason,
        ) is not None

    def delete_document(self, knowledge_id: str, *, reason: str, changed_by: str = "operator") -> bool:
        """Audit-safe soft delete. No hard deletion is exposed in v1."""
        return self.repository.soft_delete(knowledge_id, changed_by=changed_by, reason=reason)

    def restore_version(self, knowledge_id: str, version_number: int, *, changed_by: str = "operator") -> Optional[KnowledgeDocument]:
        return self.repository.restore_version(knowledge_id, version_number, changed_by=changed_by)

    def get_asset(self, asset_id: str) -> Optional[KnowledgeFileAsset]:
        asset = self._assets.get(asset_id)
        if asset is None:
            return None
        import copy
        return copy.deepcopy(asset)

    def list_assets(self, *, scope: Optional[KnowledgeScope] = None) -> List[KnowledgeFileAsset]:
        import copy
        assets = list(self._assets.values())
        if scope is not None:
            key = scope.canonical_key()
            assets = [asset for asset in assets if asset.scope_key == key]
        return copy.deepcopy(assets)
