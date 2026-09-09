from __future__ import annotations

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


class RuntimeDefaultEffectJournalDurabilityV1Tests(unittest.TestCase):
    """Production backend must preserve consequential dispatch authority across restart."""

    def test_backend_restart_preserves_and_reconciles_dispatched_effect_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "backend_instance.json"
            db_path = state_file.with_name("execution_receipts.sqlite3")

            with patch("app_api.server.get_backend_state_file_path", return_value=state_file):
                first = DepartmentAppBackend()
                self.addCleanup(lambda: first.receipt_repo.close())

                self.assertTrue(
                    first.receipt_repo.durable,
                    "PRODUCTION_EFFECT_JOURNAL_NOT_DURABLE: DepartmentAppBackend uses an in-memory receipt repository",
                )
                self.assertEqual(db_path.resolve(), first.receipt_repo.database_path)

                intent = first.receipt_repo.prepare_execution_intent(
                    request_id="REQ-RUNTIME-CRASH-1",
                    run_id="RUN-RUNTIME-CRASH-1",
                    agent_id="cmo",
                    capability_id="social_publishing",
                    provider="sandbox_publisher",
                    request_hash="runtime-crash-hash-1",
                    execution_mode=ExecutionMode.SANDBOX,
                    business_id="BIZ-RUNTIME-1",
                    project_id="PROJ-RUNTIME-1",
                )
                first.receipt_repo.mark_execution_intent_dispatching(intent.intent_id)
                first.receipt_repo.close()

                restarted = DepartmentAppBackend()
                self.addCleanup(lambda: restarted.receipt_repo.close())
                restored = restarted.receipt_repo.get_execution_intent(intent.intent_id)

                self.assertIsNotNone(restored)
                assert restored is not None
                self.assertEqual(
                    ExecutionIntentState.AMBIGUOUS,
                    restored.state,
                    "RESTART_DISPATCH_AUTHORITY_NOT_RECONCILED: a crash after DISPATCHING must be sealed AMBIGUOUS before continuation",
                )
                assessment = restarted.receipt_repo.assess_execution_intent(intent.intent_id)
                self.assertEqual(
                    ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME,
                    assessment.outcome,
                )
                self.assertEqual(1, restored.dispatch_count)
                self.assertEqual(ExecutionMode.SANDBOX, restored.execution_mode)


if __name__ == "__main__":
    unittest.main()
