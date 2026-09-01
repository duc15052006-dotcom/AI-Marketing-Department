"""Adversarial regression tests for durable, scope-safe knowledge storage.

RED-first contract: these tests intentionally target the durable repository
implementation before production code is added.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge.lifecycle_models import KnowledgeScope
from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.sqlite_repository import SQLiteKnowledgeRepository


class DurableKnowledgeRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "knowledge.sqlite3"
        self.scope_a = KnowledgeScope(project_id="tenant-a").canonical_key()
        self.scope_b = KnowledgeScope(project_id="tenant-b").canonical_key()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _repository(self, scope_key: str) -> SQLiteKnowledgeRepository:
        return SQLiteKnowledgeRepository(self.db_path, access_scope=scope_key)

    def _seed_source_and_document(self, repository: SQLiteKnowledgeRepository) -> KnowledgeDocument:
        source = repository.save_source(
            KnowledgeSource(
                source_name="Durability fixture",
                source_url_or_path="manual://durability-fixture",
                source_type=SourceType.MARKET_RESEARCH,
                authority_score=0.95,
            )
        )
        document = KnowledgeDocument(
            source_id=source.source_id,
            title="Tenant A research",
            source_type=SourceType.MARKET_RESEARCH,
            content="Initial durable content",
            authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
            scope=self.scope_a,
            tags=["durable", "tenant-a"],
            metadata={"owner": "tenant-a", "marker": "v1"},
        )
        return repository.save_document(document, changed_by="tenant-a", summary="initial")

    def test_restart_preserves_document_source_metadata_and_history(self) -> None:
        repository = self._repository(self.scope_a)
        first = self._seed_source_and_document(repository)
        source_id = first.source_id
        knowledge_id = first.knowledge_id

        updated = repository.get_document(knowledge_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        updated.content = "Updated durable content"
        updated.metadata["marker"] = "v2"
        second = repository.save_document(updated, changed_by="tenant-a", summary="second")
        self.assertEqual(second.version, 2)
        repository.close()

        reopened = self._repository(self.scope_a)
        current = reopened.get_document(knowledge_id)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current.content, "Updated durable content")
        self.assertEqual(current.metadata["marker"], "v2")
        self.assertEqual(current.scope, self.scope_a)
        self.assertIsNotNone(reopened.get_source(source_id))

        history = reopened.get_version_history(knowledge_id)
        self.assertEqual([item.version_number for item in history], [1, 2])
        self.assertEqual([item.change_summary for item in history], ["initial", "second"])

        prior = reopened.get_document_version(knowledge_id, 1)
        self.assertIsNotNone(prior)
        assert prior is not None
        self.assertEqual(prior.content, "Initial durable content")
        self.assertEqual(prior.metadata["marker"], "v1")
        reopened.close()

    def test_persisted_non_owner_read_is_denied_after_restart(self) -> None:
        owner = self._repository(self.scope_a)
        saved = self._seed_source_and_document(owner)
        owner.close()

        other_tenant = self._repository(self.scope_b)
        with self.assertRaisesRegex(PermissionError, r"^scope_violation$"):
            other_tenant.get_document(saved.knowledge_id)
        with self.assertRaisesRegex(PermissionError, r"^scope_violation$"):
            other_tenant.get_document_version(saved.knowledge_id, 1)
        with self.assertRaisesRegex(PermissionError, r"^scope_violation$"):
            other_tenant.get_version_history(saved.knowledge_id)
        other_tenant.close()

    def test_cross_tenant_query_and_write_fail_closed(self) -> None:
        owner = self._repository(self.scope_a)
        saved = self._seed_source_and_document(owner)
        owner.close()

        other_tenant = self._repository(self.scope_b)
        with self.assertRaisesRegex(PermissionError, r"^scope_violation$"):
            other_tenant.list_documents(scope=self.scope_a)
        with self.assertRaisesRegex(PermissionError, r"^scope_violation$"):
            other_tenant.query_knowledge("durable", scope=self.scope_a)

        foreign = KnowledgeDocument(
            source_id=saved.source_id,
            title="Forbidden overwrite",
            source_type=SourceType.MARKET_RESEARCH,
            content="Tenant B must not write into tenant A scope",
            scope=self.scope_a,
        )
        with self.assertRaisesRegex(PermissionError, r"^scope_violation$"):
            other_tenant.save_document(foreign, changed_by="tenant-b", summary="forbidden")
        other_tenant.close()

        owner_reopened = self._repository(self.scope_a)
        documents = owner_reopened.list_documents(scope=self.scope_a)
        self.assertEqual([doc.knowledge_id for doc in documents], [saved.knowledge_id])
        owner_reopened.close()


if __name__ == "__main__":
    unittest.main()
