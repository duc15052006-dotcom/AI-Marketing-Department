from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_api.server import DepartmentAppBackend
from tools.receipts import (
    ExecutionIntentState,
    ExecutionMode,
    ReconciliationOutcome,
)


class ProductionDurableReceiptWiringV1Tests(unittest.TestCase):
    @staticmethod
    def _close_backend(backend: DepartmentAppBackend) -> None:
        backend.run_manager.shutdown(wait=True, cancel_pending=True, timeout_seconds=2.0)
        backend.receipt_repo.close()

    def test_production_backend_preserves_dispatching_intent_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            with patch.dict(
                os.environ,
                {
                    "APPDATA": str(runtime_root),
                    "LOCALAPPDATA": str(runtime_root),
                },
                clear=False,
            ):
                first = DepartmentAppBackend()
                try:
                    self.assertTrue(
                        first.receipt_repo.durable,
                        "Production DepartmentAppBackend must use the crash-safe SQLite receipt journal.",
                    )
                    self.assertIsNotNone(first.receipt_repo.database_path)
                    database_path = first.receipt_repo.database_path

                    intent = first.receipt_repo.prepare_execution_intent(
                        request_id="REQ-PROD-DURABLE-WIRING-001",
                        run_id="RUN-PROD-DURABLE-WIRING-001",
                        agent_id="cmo",
                        capability_id="production_durable_wiring_publish",
                        provider="production_durable_wiring_adapter",
                        request_hash="prod-durable-wiring-request-hash",
                        execution_mode=ExecutionMode.REAL,
                    )
                    first.receipt_repo.mark_execution_intent_dispatching(intent.intent_id)
                finally:
                    self._close_backend(first)

                second = DepartmentAppBackend()
                try:
                    self.assertTrue(second.receipt_repo.durable)
                    self.assertEqual(database_path, second.receipt_repo.database_path)

                    recovered = second.receipt_repo.get_execution_intent(intent.intent_id)
                    self.assertIsNotNone(
                        recovered,
                        "A production restart must not lose a consequential DISPATCHING intent.",
                    )
                    self.assertEqual(ExecutionIntentState.DISPATCHING, recovered.state)
                    self.assertEqual(1, recovered.dispatch_count)

                    assessments = second.receipt_repo.reconcile_unfinished_intents()
                    assessment = next(
                        item for item in assessments if item.intent_id == intent.intent_id
                    )
                    self.assertEqual(
                        ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME,
                        assessment.outcome,
                    )

                    sealed = second.receipt_repo.get_execution_intent(intent.intent_id)
                    self.assertIsNotNone(sealed)
                    self.assertEqual(ExecutionIntentState.AMBIGUOUS, sealed.state)
                finally:
                    self._close_backend(second)


if __name__ == "__main__":
    unittest.main()
