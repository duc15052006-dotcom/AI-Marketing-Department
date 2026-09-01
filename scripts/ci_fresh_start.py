"""Fresh-start acceptance guard for durable, scope-safe knowledge storage."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable

from knowledge.lifecycle_models import KnowledgeScope
from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.repository import LocalKnowledgeRepository
from knowledge.sqlite_repository import SQLiteKnowledgeRepository


def _expect_scope_violation(action: Callable[[], object]) -> None:
    try:
        action()
    except PermissionError as exc:
        if str(exc) != "scope_violation":
            raise AssertionError(f"unexpected_permission_error:{exc}") from exc
        return
    raise AssertionError("expected_scope_violation")


def main() -> int:
    scope_a = KnowledgeScope(project_id="fresh-start-a").canonical_key()
    scope_b = KnowledgeScope(project_id="fresh-start-b").canonical_key()

    old_db_path = os.environ.get("AI_MARKETING_KNOWLEDGE_DB_PATH")
    old_ephemeral = os.environ.get("AI_MARKETING_KNOWLEDGE_EPHEMERAL")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge.sqlite3"
            os.environ["AI_MARKETING_KNOWLEDGE_DB_PATH"] = str(db_path)
            os.environ.pop("AI_MARKETING_KNOWLEDGE_EPHEMERAL", None)

            # Verify the production compatibility facade resolves to durable storage.
            facade = LocalKnowledgeRepository()
            if not isinstance(facade, SQLiteKnowledgeRepository):
                raise AssertionError("local_repository_not_durable")
            facade.close()

            owner = SQLiteKnowledgeRepository(db_path, access_scope=scope_a)
            source = owner.save_source(
                KnowledgeSource(
                    source_name="Fresh-start source",
                    source_url_or_path="manual://fresh-start",
                    source_type=SourceType.MARKET_RESEARCH,
                    authority_score=0.99,
                )
            )
            first = owner.save_document(
                KnowledgeDocument(
                    source_id=source.source_id,
                    title="Fresh-start durability fixture",
                    source_type=SourceType.MARKET_RESEARCH,
                    content="Version one",
                    authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                    scope=scope_a,
                    tags=["fresh-start", "tenant-a"],
                    metadata={"owner": "fresh-start-a", "marker": "v1"},
                ),
                changed_by="fresh-start-a",
                summary="initial",
            )
            updated = owner.get_document(first.knowledge_id)
            if updated is None:
                raise AssertionError("missing_document_before_restart")
            updated.content = "Version two"
            updated.metadata["marker"] = "v2"
            second = owner.save_document(updated, changed_by="fresh-start-a", summary="second")
            if second.version != 2:
                raise AssertionError("version_increment_failed")
            owner.close()

            if not db_path.exists() or db_path.stat().st_size <= 0:
                raise AssertionError("durable_database_missing")

            # Destroy/recreate the repository and prove full state survives.
            reopened = SQLiteKnowledgeRepository(db_path, access_scope=scope_a)
            current = reopened.get_document(first.knowledge_id)
            if current is None:
                raise AssertionError("document_missing_after_restart")
            if current.content != "Version two" or current.metadata.get("marker") != "v2":
                raise AssertionError("current_snapshot_corrupted_after_restart")
            if current.scope != scope_a:
                raise AssertionError("scope_corrupted_after_restart")
            if reopened.get_source(source.source_id) is None:
                raise AssertionError("source_missing_after_restart")

            history = reopened.get_version_history(first.knowledge_id)
            if [item.version_number for item in history] != [1, 2]:
                raise AssertionError("version_history_corrupted_after_restart")
            if [item.change_summary for item in history] != ["initial", "second"]:
                raise AssertionError("version_metadata_corrupted_after_restart")

            prior = reopened.get_document_version(first.knowledge_id, 1)
            if prior is None or prior.content != "Version one" or prior.metadata.get("marker") != "v1":
                raise AssertionError("prior_snapshot_corrupted_after_restart")
            reopened.close()

            # A distinct private scope must fail closed after persistence/restart.
            other = SQLiteKnowledgeRepository(db_path, access_scope=scope_b)
            _expect_scope_violation(lambda: other.get_document(first.knowledge_id))
            _expect_scope_violation(lambda: other.get_document_version(first.knowledge_id, 1))
            _expect_scope_violation(lambda: other.get_version_history(first.knowledge_id))
            _expect_scope_violation(lambda: other.get_source(source.source_id))
            _expect_scope_violation(lambda: other.list_documents(scope=scope_a))
            _expect_scope_violation(lambda: other.query_knowledge("Version", scope=scope_a))
            _expect_scope_violation(
                lambda: other.save_document(
                    KnowledgeDocument(
                        source_id=source.source_id,
                        title="Forbidden write",
                        source_type=SourceType.MARKET_RESEARCH,
                        content="Must never cross the private boundary",
                        scope=scope_a,
                    ),
                    changed_by="fresh-start-b",
                    summary="forbidden",
                )
            )
            other.close()

            owner_final = SQLiteKnowledgeRepository(db_path, access_scope=scope_a)
            visible = owner_final.list_documents(scope=scope_a)
            if [item.knowledge_id for item in visible] != [first.knowledge_id]:
                raise AssertionError("cross_scope_write_modified_owner_state")
            owner_final.close()

        print("FRESH_START_DURABLE_KNOWLEDGE_OK")
        return 0
    finally:
        if old_db_path is None:
            os.environ.pop("AI_MARKETING_KNOWLEDGE_DB_PATH", None)
        else:
            os.environ["AI_MARKETING_KNOWLEDGE_DB_PATH"] = old_db_path
        if old_ephemeral is None:
            os.environ.pop("AI_MARKETING_KNOWLEDGE_EPHEMERAL", None)
        else:
            os.environ["AI_MARKETING_KNOWLEDGE_EPHEMERAL"] = old_ephemeral


if __name__ == "__main__":
    raise SystemExit(main())
