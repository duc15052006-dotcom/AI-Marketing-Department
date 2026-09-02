"""Adversarial regression for execution intent/receipt approval provenance binding.

The RED state intentionally leaves production unchanged and requires the durable
intent's approval audit reference to remain correlated with the finalized receipt.
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
    ReceiptStoreIntegrityError,
    ReconciliationOutcome,
)


class ReceiptApprovalProvenanceBindingV1Tests(unittest.TestCase):
    @staticmethod
    def _receipt(*, approval_reference: str) -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id="EXEC-APPROVAL-BIND-001",
            run_id="RUN-APPROVAL-BIND-001",
            agent_id="cmo",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="HASH-APPROVAL-BIND-001",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            approval_reference=approval_reference,
            business_id="BIZ-A",
            project_id="PROJ-A",
            chat_id="CHAT-A",
            data={"publish_id": "PUB-001"},
        )

    @staticmethod
    def _prepare(repo: ExecutionReceiptRepository):
        intent = repo.prepare_execution_intent(
            request_id="REQ-APPROVAL-BIND-001",
            run_id="RUN-APPROVAL-BIND-001",
            agent_id="cmo",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="HASH-APPROVAL-BIND-001",
            execution_mode=ExecutionMode.REAL,
            approval_reference="approval_ref_AUTH_A",
            business_id="BIZ-A",
            project_id="PROJ-A",
            chat_id="CHAT-A",
        )
        repo.mark_execution_intent_dispatching(intent.intent_id)
        return intent

    def _assert_foreign_approval_reference_rejected(
        self,
        repo: ExecutionReceiptRepository,
    ) -> None:
        intent = self._prepare(repo)
        foreign = self._receipt(approval_reference="approval_ref_AUTH_B")

        with self.assertRaisesRegex(
            ReceiptStoreIntegrityError,
            "EXECUTION_INTENT_RECEIPT_BINDING_MISMATCH",
        ):
            repo.finalize_execution_intent(intent.intent_id, foreign)

        current = repo.get_execution_intent(intent.intent_id)
        self.assertIsNotNone(current)
        self.assertEqual(current.state, ExecutionIntentState.DISPATCHING)
        self.assertIsNone(current.receipt_execution_id)
        self.assertIsNone(repo.get_receipt(foreign.execution_id))

    def test_finalize_rejects_foreign_approval_reference_in_memory_and_sqlite(self) -> None:
        memory_repo = ExecutionReceiptRepository()
        try:
            self._assert_foreign_approval_reference_rejected(memory_repo)
        finally:
            memory_repo.close()

        with tempfile.TemporaryDirectory() as tmp:
            sqlite_repo = ExecutionReceiptRepository(
                database_path=Path(tmp) / "approval-binding.sqlite3"
            )
            try:
                self._assert_foreign_approval_reference_rejected(sqlite_repo)
            finally:
                sqlite_repo.close()

    def test_exact_approval_reference_still_finalizes_and_reconciles(self) -> None:
        repo = ExecutionReceiptRepository()
        try:
            intent = self._prepare(repo)
            receipt = self._receipt(approval_reference="approval_ref_AUTH_A")
            stored = repo.finalize_execution_intent(intent.intent_id, receipt)
            self.assertEqual(stored.execution_id, receipt.execution_id)
            assessment = repo.assess_execution_intent(intent.intent_id)
            self.assertEqual(
                assessment.outcome,
                ReconciliationOutcome.CONFIRMED_FINALIZED,
            )
        finally:
            repo.close()


if __name__ == "__main__":
    unittest.main()
