"""Adversarial regression for receipt-to-intent authority correlation.

A consequential execution intent must not be finalized by a receipt that merely
copies the run/capability/request hash while contradicting another immutable
correlation dimension.
"""

from __future__ import annotations

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


class ReceiptIntentAuthorityCorrelationV1Tests(unittest.TestCase):
    def _prepared_repository(self):
        repo = ExecutionReceiptRepository()
        intent = repo.prepare_execution_intent(
            request_id="REQ-AUTH-001",
            run_id="RUN-AUTH-001",
            agent_id="performance",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="HASH-AUTH-001",
            business_id="BIZ-A",
            project_id="PROJ-A",
            chat_id="CHAT-A",
        )
        repo.mark_execution_intent_dispatching(intent.intent_id)
        return repo, intent

    @staticmethod
    def _receipt(**overrides):
        values = {
            "execution_id": "EXEC-AUTH-001",
            "run_id": "RUN-AUTH-001",
            "agent_id": "performance",
            "capability_id": "social_publishing",
            "provider": "social_publish_adapter",
            "request_hash": "HASH-AUTH-001",
            "status": ExecutionStatus.SUCCESS,
            "execution_mode": ExecutionMode.REAL,
            "business_id": "BIZ-A",
            "project_id": "PROJ-A",
            "chat_id": "CHAT-A",
            "data": {"publish_id": "PUB-001"},
        }
        values.update(overrides)
        return ExecutionReceipt(**values)

    def test_finalize_rejects_receipt_with_foreign_authority_dimension(self) -> None:
        variants = {
            "agent_id": {"agent_id": "creative"},
            "provider": {"provider": "foreign_publish_adapter"},
            "business_id": {"business_id": "BIZ-B"},
            "project_id": {"project_id": "PROJ-B"},
            "chat_id": {"chat_id": "CHAT-B"},
        }

        for dimension, overrides in variants.items():
            with self.subTest(dimension=dimension):
                repo, intent = self._prepared_repository()
                foreign_receipt = self._receipt(**overrides)

                with self.assertRaisesRegex(
                    ReceiptStoreIntegrityError,
                    "EXECUTION_INTENT_RECEIPT_BINDING_MISMATCH",
                ):
                    repo.finalize_execution_intent(intent.intent_id, foreign_receipt)

                current = repo.get_execution_intent(intent.intent_id)
                self.assertIsNotNone(current)
                self.assertEqual(current.state, ExecutionIntentState.DISPATCHING)
                self.assertIsNone(current.receipt_execution_id)
                self.assertIsNone(repo.get_receipt(foreign_receipt.execution_id))

    def test_exact_authority_receipt_still_finalizes_and_reconciles(self) -> None:
        repo, intent = self._prepared_repository()
        receipt = self._receipt()

        stored = repo.finalize_execution_intent(intent.intent_id, receipt)
        self.assertEqual(stored.execution_id, receipt.execution_id)

        current = repo.get_execution_intent(intent.intent_id)
        self.assertIsNotNone(current)
        self.assertEqual(current.state, ExecutionIntentState.FINALIZED)
        self.assertEqual(current.receipt_execution_id, receipt.execution_id)

        assessment = repo.assess_execution_intent(intent.intent_id)
        self.assertEqual(assessment.outcome, ReconciliationOutcome.CONFIRMED_FINALIZED)
        self.assertEqual(assessment.receipt_execution_id, receipt.execution_id)


if __name__ == "__main__":
    unittest.main()
