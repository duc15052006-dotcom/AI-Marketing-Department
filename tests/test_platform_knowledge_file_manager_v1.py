"""Regression tests for governed Knowledge/File Manager v1."""

import tempfile
import unittest
from pathlib import Path

from knowledge.file_manager import KnowledgeFileManager
from knowledge.lifecycle_models import KnowledgeScope
from knowledge.models import AuthorityLevel, KnowledgeCitation, SourceType
from knowledge.versioned_repository import VersionedKnowledgeRepository


class KnowledgeFileManagerV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.manager = KnowledgeFileManager(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_file_ingestion_is_contained_and_records_relative_provenance(self) -> None:
        (self.root / "research").mkdir()
        (self.root / "research" / "decor.md").write_text("Decor customers value compact storage.", encoding="utf-8")
        scope = KnowledgeScope(project_id="PROJ-1", product_id="PROD-1")

        result = self.manager.ingest_file(
            "research/decor.md",
            scope=scope,
            source_type=SourceType.CUSTOMER_RESEARCH,
        )
        self.assertTrue(result.success)
        self.assertIsNotNone(result.asset_id)

        asset = self.manager.get_asset(result.asset_id or "")
        self.assertIsNotNone(asset)
        self.assertEqual(asset.relative_path, "research/decor.md")
        self.assertNotIn(str(self.root), asset.relative_path)

        document = self.manager.repository.get_document(result.knowledge_id or "")
        self.assertEqual(document.scope, "PROJECT:PROJ-1|PRODUCT:PROD-1")
        source = self.manager.repository.get_source(document.source_id)
        self.assertEqual(source.source_url_or_path, "research/decor.md")

    def test_parent_traversal_and_absolute_path_are_blocked(self) -> None:
        outside = self.root.parent / "knowledge-secret.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            traversal = self.manager.ingest_file("../knowledge-secret.txt")
            self.assertFalse(traversal.success)
            self.assertEqual(traversal.error_code, "PATH_OUTSIDE_ALLOWED_ROOT")

            absolute = self.manager.ingest_file(str(outside.resolve()))
            self.assertFalse(absolute.success)
            self.assertEqual(absolute.error_code, "ABSOLUTE_PATH_FORBIDDEN")
        finally:
            outside.unlink(missing_ok=True)

    def test_scope_isolation_allows_exact_scope_plus_global_only(self) -> None:
        global_result = self.manager.ingest_text(
            "Global marketing principle about customer proof.",
            source_name="global",
        )
        a = self.manager.ingest_text(
            "Project alpha private customer proof.",
            source_name="alpha",
            scope=KnowledgeScope(project_id="A"),
        )
        b = self.manager.ingest_text(
            "Project beta private customer proof.",
            source_name="beta",
            scope=KnowledgeScope(project_id="B"),
        )
        self.assertTrue(global_result.success and a.success and b.success)

        alpha_docs = self.manager.retrieve("proof", scope=KnowledgeScope(project_id="A"), include_global=True)
        alpha_ids = {doc.knowledge_id for doc in alpha_docs}
        self.assertIn(global_result.knowledge_id, alpha_ids)
        self.assertIn(a.knowledge_id, alpha_ids)
        self.assertNotIn(b.knowledge_id, alpha_ids)

    def test_retired_and_deleted_documents_are_excluded_from_normal_retrieval(self) -> None:
        retired = self.manager.ingest_text("Retired campaign insight.", source_name="retired")
        deleted = self.manager.ingest_text("Deleted campaign insight.", source_name="deleted")
        self.assertTrue(self.manager.retire_document(retired.knowledge_id or "", reason="obsolete"))
        self.assertTrue(self.manager.delete_document(deleted.knowledge_id or "", reason="operator request"))

        self.assertEqual(self.manager.retrieve("Retired"), [])
        self.assertEqual(self.manager.retrieve("Deleted"), [])
        self.assertIsNotNone(self.manager.repository.get_document(retired.knowledge_id or ""))
        self.assertIsNotNone(self.manager.repository.get_document(deleted.knowledge_id or ""))

    def test_authority_floor_is_enforced(self) -> None:
        high = self.manager.ingest_text(
            "Verified conversion baseline.",
            source_name="high",
            authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
        )
        low = self.manager.ingest_text(
            "Unverified conversion baseline.",
            source_name="low",
            authority_level=AuthorityLevel.TIER_4_UNVERIFIED_OBSERVATION,
        )
        docs = self.manager.retrieve(
            "conversion baseline",
            min_authority=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
        )
        ids = {doc.knowledge_id for doc in docs}
        self.assertIn(high.knowledge_id, ids)
        self.assertNotIn(low.knowledge_id, ids)

    def test_version_snapshots_are_immutable_and_restorable(self) -> None:
        result = self.manager.ingest_text("Version one content.", source_name="versions")
        knowledge_id = result.knowledge_id or ""
        doc = self.manager.repository.get_document(knowledge_id)
        doc.content = "Version two content."
        saved_v2 = self.manager.repository.save_document(doc, changed_by="test", summary="v2")
        self.assertEqual(saved_v2.version, 2)

        v1 = self.manager.repository.get_document_version(knowledge_id, 1)
        self.assertEqual(v1.content, "Version one content.")
        current = self.manager.repository.get_document(knowledge_id)
        current.content = "Mutated caller copy only."
        self.assertEqual(self.manager.repository.get_document(knowledge_id).content, "Version two content.")

        restored = self.manager.restore_version(knowledge_id, 1, changed_by="test")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.version, 3)
        self.assertEqual(restored.content, "Version one content.")

    def test_replace_creates_new_document_and_supersedes_old(self) -> None:
        old = self.manager.ingest_text("Old product specification.", source_name="spec")
        replacement = self.manager.replace_document(old.knowledge_id or "", "New product specification.")
        self.assertTrue(replacement.success)
        self.assertNotEqual(old.knowledge_id, replacement.knowledge_id)

        old_doc = self.manager.repository.get_document(old.knowledge_id or "")
        new_doc = self.manager.repository.get_document(replacement.knowledge_id or "")
        self.assertEqual(old_doc.freshness, "SUPERSEDED")
        self.assertEqual(old_doc.metadata["superseded_by_id"], new_doc.knowledge_id)
        self.assertEqual(new_doc.metadata["supersedes_id"], old_doc.knowledge_id)
        self.assertNotIn(old_doc.knowledge_id, {doc.knowledge_id for doc in self.manager.retrieve("product specification")})

    def test_observed_url_requires_real_extracted_content(self) -> None:
        failed = self.manager.ingest_observed_url(
            "https://example.com/research",
            "",
            source_name="example",
        )
        self.assertFalse(failed.success)
        self.assertEqual(failed.error_code, "OBSERVATION_CONTENT_REQUIRED")

        stored = self.manager.ingest_observed_url(
            "https://example.com/research",
            "Observed customer discussion content.",
            source_name="example",
        )
        self.assertTrue(stored.success)
        document = self.manager.repository.get_document(stored.knowledge_id or "")
        source = self.manager.repository.get_source(document.source_id)
        self.assertEqual(source.source_url_or_path, "https://example.com/research")

    def test_provenance_checks_source_and_document_hash(self) -> None:
        result = self.manager.ingest_text("Grounded product fact.", source_name="product")
        document = self.manager.repository.get_document(result.knowledge_id or "")
        citation = KnowledgeCitation(
            knowledge_id=document.knowledge_id,
            chunk_id=document.chunks[0].chunk_id,
            source_id=document.source_id,
        )
        self.assertTrue(self.manager.repository.verify_provenance(citation))
        bad = KnowledgeCitation(
            knowledge_id=document.knowledge_id,
            chunk_id=document.chunks[0].chunk_id,
            source_id="SRC-WRONG",
        )
        self.assertFalse(self.manager.repository.verify_provenance(bad))


class VersionedRepositoryV1Tests(unittest.TestCase):
    def test_repository_defensive_copy_prevents_external_mutation(self) -> None:
        repository = VersionedKnowledgeRepository()
        manager = KnowledgeFileManager(Path(tempfile.mkdtemp()), repository=repository)
        result = manager.ingest_text("Stable knowledge content.", source_name="stable")
        first = repository.get_document(result.knowledge_id or "")
        first.tags.append("caller-only")
        second = repository.get_document(result.knowledge_id or "")
        self.assertNotIn("caller-only", second.tags)


if __name__ == "__main__":
    unittest.main()
