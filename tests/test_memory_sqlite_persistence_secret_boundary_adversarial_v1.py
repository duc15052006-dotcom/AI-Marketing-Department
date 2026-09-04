"""Adversarial durable-Memory secret persistence boundary regression.

A direct repository caller must not be able to persist raw credential material by
bypassing ``MemoryManager``.  The durable repository itself is the final storage
trust boundary and must reuse the shared governance redaction policy.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository


CONTENT_SECRET = "sk-persistboundary1234567890"
CONTEXT_SECRET = "sk-contextboundary1234567890"
METADATA_SECRET = "client-secret-boundary-1234567890"
EVIDENCE_SECRET = "evidence-token-boundary-1234567890"


class MemorySQLitePersistenceSecretBoundaryAdversarialV1(unittest.TestCase):
    def test_direct_repository_write_cannot_persist_raw_credentials(self) -> None:
        old_db_path = os.environ.get("AI_MARKETING_MEMORY_DB_PATH")
        old_ephemeral = os.environ.get("AI_MARKETING_MEMORY_EPHEMERAL")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                db_path = Path(temp_dir) / "memory.sqlite3"
                os.environ["AI_MARKETING_MEMORY_DB_PATH"] = str(db_path)
                os.environ.pop("AI_MARKETING_MEMORY_EPHEMERAL", None)

                original = MemoryItem(
                    memory_type=MemoryType.DECISION_MEMORY,
                    agent_source="Strategist",
                    run_id="RUN-SECRET-BOUNDARY-V1",
                    context={
                        "campaign": "AUTUMN-SALE",
                        "api_key": CONTEXT_SECRET,
                        "nested": {"authorization": f"Bearer {CONTEXT_SECRET}"},
                    },
                    content=f"Keep marker SAFE-MARKER; leaked credential {CONTENT_SECRET}",
                    evidence_refs=[
                        f"https://evidence.invalid/item?access_token={EVIDENCE_SECRET}&page=1"
                    ],
                    confidence=0.93,
                    promotion_level=PromotionState.VERIFIED_MEMORY,
                    scope="BUSINESS:BIZ-SECRET|PROJECT:PROJ-SECRET",
                    metadata={
                        "test_marker": "SAFE-MARKER",
                        "client_secret": METADATA_SECRET,
                    },
                )

                repo = LocalMemoryRepository()
                try:
                    saved = repo.save_memory(original)
                    # Persistence redaction must not mutate the caller-owned object.
                    self.assertIn(CONTENT_SECRET, original.content)
                    self.assertEqual(original.context["api_key"], CONTEXT_SECRET)
                    self.assertEqual(original.metadata["client_secret"], METADATA_SECRET)
                    self.assertNotIn(CONTENT_SECRET, saved.content)
                finally:
                    close_repo = getattr(repo, "close", None)
                    if callable(close_repo):
                        close_repo()

                with sqlite3.connect(str(db_path)) as connection:
                    row = connection.execute(
                        "SELECT payload FROM memories WHERE memory_id = ?",
                        (original.memory_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                raw_payload = str(row[0])

                for raw_secret in (
                    CONTENT_SECRET,
                    CONTEXT_SECRET,
                    METADATA_SECRET,
                    EVIDENCE_SECRET,
                ):
                    self.assertNotIn(
                        raw_secret,
                        raw_payload,
                        "Raw credential material reached durable Memory storage.",
                    )

                self.assertIn("SAFE-MARKER", raw_payload)
                self.assertIn(original.memory_id, raw_payload)
                self.assertIn(original.scope, raw_payload)

                reopened = LocalMemoryRepository()
                try:
                    restored = reopened.get_memory(original.memory_id)
                    self.assertIsNotNone(restored)
                    self.assertIn("SAFE-MARKER", restored.content)
                    self.assertEqual(restored.metadata["test_marker"], "SAFE-MARKER")
                    self.assertEqual(restored.memory_id, original.memory_id)
                    self.assertEqual(restored.scope, original.scope)
                    for raw_secret in (
                        CONTENT_SECRET,
                        CONTEXT_SECRET,
                        METADATA_SECRET,
                        EVIDENCE_SECRET,
                    ):
                        self.assertNotIn(raw_secret, str(restored.model_dump()))
                finally:
                    close_reopened = getattr(reopened, "close", None)
                    if callable(close_reopened):
                        close_reopened()
        finally:
            if old_db_path is None:
                os.environ.pop("AI_MARKETING_MEMORY_DB_PATH", None)
            else:
                os.environ["AI_MARKETING_MEMORY_DB_PATH"] = old_db_path

            if old_ephemeral is None:
                os.environ.pop("AI_MARKETING_MEMORY_EPHEMERAL", None)
            else:
                os.environ["AI_MARKETING_MEMORY_EPHEMERAL"] = old_ephemeral


if __name__ == "__main__":
    unittest.main()
