from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from knowledge.models import AuthorityLevel, KnowledgeDocument, KnowledgeSource, SourceType
from knowledge.repository import LocalKnowledgeRepository


class ProductionKnowledgeRestartDurabilityAdversarialV3Tests(unittest.TestCase):
    def test_local_production_facade_survives_restart_with_provenance_and_history(self) -> None:
        """Production LocalKnowledgeRepository must be durable across process-style recreation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge.sqlite3"
            old_db_path = os.environ.get("AI_MARKETING_KNOWLEDGE_DB_PATH")
            old_ephemeral = os.environ.get("AI_MARKETING_KNOWLEDGE_EPHEMERAL")
            try:
                os.environ["AI_MARKETING_KNOWLEDGE_DB_PATH"] = str(db_path)
                os.environ.pop("AI_MARKETING_KNOWLEDGE_EPHEMERAL", None)

                first_repo = LocalKnowledgeRepository()
                source = first_repo.save_source(
                    KnowledgeSource(
                        source_name="Restart durability fixture",
                        source_url_or_path="manual://restart-durability-v3",
                        source_type=SourceType.MARKET_RESEARCH,
                        authority_score=0.97,
                    )
                )
                first = first_repo.save_document(
                    KnowledgeDocument(
                        source_id=source.source_id,
                        title="Vietnam ecommerce durable intelligence",
                        source_type=SourceType.MARKET_RESEARCH,
                        content="Initial verified market evidence before restart.",
                        authority_level=AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                        scope="PROJECT:KNOWLEDGE-DURABILITY-V3",
                        tags=["restart", "durability", "intelligence"],
                        metadata={"marker": "v1", "provenance": "verified-source"},
                    ),
                    changed_by="intelligence",
                    summary="initial verified evidence",
                )
                self.assertTrue(first.chunks, "The persisted document must carry provenance-traceable chunks.")

                update = first_repo.get_document(first.knowledge_id)
                self.assertIsNotNone(update)
                assert update is not None
                update.content = "Updated verified market evidence before restart."
                update.metadata["marker"] = "v2"
                second = first_repo.save_document(
                    update,
                    changed_by="intelligence",
                    summary="verified evidence refresh",
                )
                self.assertEqual(2, second.version)
                expected_chunks = [chunk.model_dump() for chunk in second.chunks]

                close = getattr(first_repo, "close", None)
                if callable(close):
                    close()
                del first_repo

                reopened = LocalKnowledgeRepository()
                restored = reopened.get_document(first.knowledge_id)
                self.assertIsNotNone(
                    restored,
                    "Production knowledge disappeared after repository/process recreation.",
                )
                assert restored is not None
                self.assertEqual("Updated verified market evidence before restart.", restored.content)
                self.assertEqual("v2", restored.metadata.get("marker"))
                self.assertEqual("PROJECT:KNOWLEDGE-DURABILITY-V3", restored.scope)
                self.assertEqual(expected_chunks, [chunk.model_dump() for chunk in restored.chunks])

                restored_source = reopened.get_source(source.source_id)
                self.assertIsNotNone(restored_source)
                assert restored_source is not None
                self.assertEqual("manual://restart-durability-v3", restored_source.source_url_or_path)
                self.assertEqual(0.97, restored_source.authority_score)

                history = reopened.get_version_history(first.knowledge_id)
                self.assertEqual([1, 2], [item.version_number for item in history])
                self.assertEqual(
                    ["initial verified evidence", "verified evidence refresh"],
                    [item.change_summary for item in history],
                )

                reopened_close = getattr(reopened, "close", None)
                if callable(reopened_close):
                    reopened_close()

                self.assertTrue(
                    db_path.exists(),
                    "Production durability must use the explicitly isolated database path in this regression.",
                )
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
    unittest.main()
