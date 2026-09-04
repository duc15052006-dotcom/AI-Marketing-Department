"""Adversarial production-memory durability regression.

Production composition currently constructs ``LocalMemoryRepository``.  This
regression requires that facade to preserve a complete MemoryItem across a
fresh repository/process-style recreation when production durability is
selected.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository


class ProductionMemoryRestartDurabilityAdversarialV1(unittest.TestCase):
    def test_production_memory_survives_repository_recreation(self) -> None:
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
                    run_id="RUN-DURABILITY-V1",
                    context={"channel": "paid-social", "objective": "conversion"},
                    content="Keep the winning offer framing after restart.",
                    evidence_refs=["RECEIPT-DURABILITY-V1"],
                    confidence=0.91,
                    promotion_level=PromotionState.VERIFIED_MEMORY,
                    scope="BUSINESS:BIZ-1|PROJECT:PROJ-1",
                    metadata={"test_marker": "durable-memory-v1"},
                )

                first_repo = LocalMemoryRepository()
                first_repo.save_memory(original)
                close_first = getattr(first_repo, "close", None)
                if callable(close_first):
                    close_first()

                second_repo = LocalMemoryRepository()
                try:
                    restored = second_repo.get_memory(original.memory_id)
                    self.assertIsNotNone(
                        restored,
                        "Production memory disappeared after repository/process recreation.",
                    )
                    self.assertEqual(restored.memory_id, original.memory_id)
                    self.assertEqual(restored.memory_type, original.memory_type)
                    self.assertEqual(restored.agent_source, original.agent_source)
                    self.assertEqual(restored.run_id, original.run_id)
                    self.assertEqual(restored.context, original.context)
                    self.assertEqual(restored.content, original.content)
                    self.assertEqual(restored.evidence_refs, original.evidence_refs)
                    self.assertEqual(restored.confidence, original.confidence)
                    self.assertEqual(restored.promotion_level, original.promotion_level)
                    self.assertEqual(restored.scope, original.scope)
                    self.assertEqual(restored.metadata, original.metadata)
                finally:
                    close_second = getattr(second_repo, "close", None)
                    if callable(close_second):
                        close_second()
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
