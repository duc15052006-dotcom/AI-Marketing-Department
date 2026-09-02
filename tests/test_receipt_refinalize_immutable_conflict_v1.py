"""Adversarial regression for immutable receipt re-finalization.

Replaying finalization for an already-settled intent is idempotent only when the
submitted receipt is exactly the already-persisted immutable receipt. Reusing the
same execution_id and authority binding with a contradictory payload must fail
closed instead of silently returning the earlier receipt.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.receipts import (
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreConflictError,
)


class ReceiptRefinalizeImmutableConflictV1Tests(unittest.TestCase):
    @staticmethod
    def _receipt(*, publish_id: str = "PUB-001", status: ExecutionStatus = ExecutionStatus.SUCCESS):
        return ExecutionReceipt(
            execution_id="EXEC-REFINALIZE-001",
            run_id="RUN-REFINALIZE-001",
            agent_id="performance",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="HASH-REFINALIZE-001",
            status=status,
            execution_mode=ExecutionMode.REAL,
            business_id="BIZ-A",
            project_id="PROJ-A",
            chat_id="CHAT-A",
            data={"publish_id": publish_id},
        )

    @staticmethod
    def _prepare(repo: ExecutionReceiptRepository):
        intent = repo.prepare_execution_intent(
            request_id="REQ-REFINALIZE-001",
            run_id="RUN-REFINALIZE-001",
            agent_id="performance",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="HASH-REFINALIZE-001",
            execution_mode=ExecutionMode.REAL,
            business_id="BIZ-A",
            project_id="PROJ-A",
            chat_id="CHAT-A",
        )
        repo.mark_execution_intent_dispatching(intent.intent_id)
        return intent

    def _assert_conflicting_refinalization_rejected(
        self,
        repo: ExecutionReceiptRepository,
        *,
        ambiguous: bool,
    ) -> None:
        intent = self._prepare(repo)
        original = self._receipt()
        stored = repo.finalize_execution_intent(intent.intent_id, original, ambiguous=ambiguous)
        self.assertEqual(stored.data, {"publish_id": "PUB-001"})

        conflicting = self._receipt(publish_id="PUB-CONTRADICTS-PERSISTED")
        with self.assertRaisesRegex(
            ReceiptStoreConflictError,
            "EXECUTION_RECEIPT_IMMUTABLE_CONFLICT",
        ):
            repo.finalize_execution_intent(intent.intent_id, conflicting, ambiguous=ambiguous)

        persisted = repo.get_receipt(original.execution_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.data, {"publish_id": "PUB-001"})

    def test_refinalization_rejects_conflicting_payload_in_memory_and_sqlite(self) -> None:
        for storage in ("memory", "sqlite"):
            for ambiguous in (False, True):
                with self.subTest(storage=storage, ambiguous=ambiguous):
                    if storage == "memory":
                        repo = ExecutionReceiptRepository()
                        self._assert_conflicting_refinalization_rejected(repo, ambiguous=ambiguous)
                        repo.close()
                    else:
                        with tempfile.TemporaryDirectory() as tmp:
                            db_path = Path(tmp) / "receipt-refinalize.sqlite3"
                            repo = ExecutionReceiptRepository(database_path=db_path)
                            self._assert_conflicting_refinalization_rejected(repo, ambiguous=ambiguous)
                            repo.close()

    def test_exact_receipt_refinalization_remains_idempotent(self) -> None:
        repo = ExecutionReceiptRepository()
        intent = self._prepare(repo)
        receipt = self._receipt()

        first = repo.finalize_execution_intent(intent.intent_id, receipt)
        second = repo.finalize_execution_intent(intent.intent_id, receipt)

        self.assertEqual(second.model_dump(), first.model_dump())
        self.assertEqual(len(repo.list_receipts_for_run("RUN-REFINALIZE-001")), 1)
        repo.close()


if __name__ == "__main__":
    unittest.main()
