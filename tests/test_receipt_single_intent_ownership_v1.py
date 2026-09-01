"""Adversarial regression for one-receipt/one-intent ownership.

A single immutable execution receipt must not be reusable as finalization evidence
for two distinct consequential execution intents, even when their other binding
fields are identical.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.receipts import (
    ExecutionIntentState,
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreConflictError,
    ReconciliationOutcome,
)


class ReceiptSingleIntentOwnershipV1Tests(unittest.TestCase):
    @staticmethod
    def _prepare(repo: ExecutionReceiptRepository, *, request_id: str):
        intent = repo.prepare_execution_intent(
            request_id=request_id,
            run_id="RUN-RECEIPT-OWNER-001",
            agent_id="cmo",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="HASH-RECEIPT-OWNER-001",
            approval_reference="approval_ref_OWNER_A",
            business_id="BIZ-A",
            project_id="PROJ-A",
            chat_id="CHAT-A",
        )
        repo.mark_execution_intent_dispatching(intent.intent_id)
        return intent

    @staticmethod
    def _receipt() -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id="EXEC-SINGLE-OWNER-001",
            run_id="RUN-RECEIPT-OWNER-001",
            agent_id="cmo",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="HASH-RECEIPT-OWNER-001",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            approval_reference="approval_ref_OWNER_A",
            business_id="BIZ-A",
            project_id="PROJ-A",
            chat_id="CHAT-A",
            data={"publish_id": "PUB-OWNER-001"},
        )

    def _assert_receipt_cannot_finalize_two_intents(
        self,
        repo: ExecutionReceiptRepository,
    ) -> None:
        first = self._prepare(repo, request_id="REQ-OWNER-001")
        second = self._prepare(repo, request_id="REQ-OWNER-002")
        receipt = self._receipt()

        stored = repo.finalize_execution_intent(first.intent_id, receipt)
        self.assertEqual(stored.execution_id, receipt.execution_id)
        self.assertEqual(
            repo.assess_execution_intent(first.intent_id).outcome,
            ReconciliationOutcome.CONFIRMED_FINALIZED,
        )

        with self.assertRaisesRegex(
            ReceiptStoreConflictError,
            "EXECUTION_RECEIPT_ALREADY_LINKED_TO_OTHER_INTENT",
        ):
            repo.finalize_execution_intent(second.intent_id, receipt)

        first_after = repo.get_execution_intent(first.intent_id)
        second_after = repo.get_execution_intent(second.intent_id)
        self.assertIsNotNone(first_after)
        self.assertIsNotNone(second_after)
        self.assertEqual(first_after.state, ExecutionIntentState.FINALIZED)
        self.assertEqual(first_after.receipt_execution_id, receipt.execution_id)
        self.assertEqual(second_after.state, ExecutionIntentState.DISPATCHING)
        self.assertIsNone(second_after.receipt_execution_id)

    def test_exact_receipt_cannot_finalize_two_intents_in_memory_and_sqlite(self) -> None:
        memory_repo = ExecutionReceiptRepository()
        try:
            self._assert_receipt_cannot_finalize_two_intents(memory_repo)
        finally:
            memory_repo.close()

        with tempfile.TemporaryDirectory() as tmp:
            sqlite_repo = ExecutionReceiptRepository(
                database_path=Path(tmp) / "receipt-owner.sqlite3"
            )
            try:
                self._assert_receipt_cannot_finalize_two_intents(sqlite_repo)
            finally:
                sqlite_repo.close()


if __name__ == "__main__":
    unittest.main()
