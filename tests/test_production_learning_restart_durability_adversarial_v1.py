"""Adversarial restart-durability contract for production learning storage."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memory.learning import LearningEvent, LocalLearningRepository
from memory.models import PromotionState


class ProductionLearningRestartDurabilityAdversarialV1Tests(unittest.TestCase):
    def test_learning_and_operator_updates_survive_repository_recreation(self) -> None:
        old_ephemeral = os.environ.get("AI_MARKETING_LEARNING_EPHEMERAL")
        old_path = os.environ.get("AI_MARKETING_LEARNING_DB_PATH")

        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "learning" / "learning.sqlite3"
            os.environ.pop("AI_MARKETING_LEARNING_EPHEMERAL", None)
            os.environ["AI_MARKETING_LEARNING_DB_PATH"] = str(database_path)

            first = None
            second = None
            try:
                event = LearningEvent(
                    learning_event_id="LRN-PROD-RESTART-V1",
                    campaign_id="CAMP-DURABLE-1",
                    hypothesis="A durable learning must survive a process restart.",
                    experiment_id="EXP-DURABLE-1",
                    baseline={"conversion_rate": 0.10},
                    treatment={"conversion_rate": 0.14},
                    primary_metric="conversion_rate",
                    secondary_metrics={"refund_rate": 0.01},
                    observed_result={"relative_lift": 0.40, "p_value": 0.01},
                    sample_or_evidence={"receipt_ids": ["EXEC-DURABLE-1"], "n": 5000},
                    confidence=0.99,
                    decision="SCALE",
                    lesson="Durable campaign evidence remains available after restart.",
                    applicability_scope="BRAND_SPECIFIC",
                    metadata={"brand_id": "BRAND-1"},
                )

                first = LocalLearningRepository()
                first.record_learning(event)
                event.promotion_status = PromotionState.PROMOTED_LEARNING
                event.retest_required = True
                first.record_learning(event)
                if hasattr(first, "close"):
                    first.close()
                    first = None

                second = LocalLearningRepository()
                restored = second.get_learning(event.learning_event_id)

                self.assertIsNotNone(
                    restored,
                    "Production learning events must not disappear after repository recreation.",
                )
                assert restored is not None
                self.assertEqual(restored.campaign_id, "CAMP-DURABLE-1")
                self.assertEqual(restored.promotion_status, PromotionState.PROMOTED_LEARNING)
                self.assertTrue(restored.retest_required)
                self.assertEqual(restored.observed_result["relative_lift"], 0.40)
                self.assertEqual(restored.sample_or_evidence["receipt_ids"], ["EXEC-DURABLE-1"])
                self.assertEqual(
                    [item.learning_event_id for item in second.list_learnings(campaign_id="CAMP-DURABLE-1")],
                    ["LRN-PROD-RESTART-V1"],
                )
                self.assertEqual(
                    [item.learning_event_id for item in second.query_learnings_for_context(["durable"])],
                    ["LRN-PROD-RESTART-V1"],
                )
                self.assertTrue(database_path.is_file())
            finally:
                for repository in (first, second):
                    if repository is not None and hasattr(repository, "close"):
                        repository.close()

                if old_ephemeral is None:
                    os.environ.pop("AI_MARKETING_LEARNING_EPHEMERAL", None)
                else:
                    os.environ["AI_MARKETING_LEARNING_EPHEMERAL"] = old_ephemeral
                if old_path is None:
                    os.environ.pop("AI_MARKETING_LEARNING_DB_PATH", None)
                else:
                    os.environ["AI_MARKETING_LEARNING_DB_PATH"] = old_path


if __name__ == "__main__":
    unittest.main()
