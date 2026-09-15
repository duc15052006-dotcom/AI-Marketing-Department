"""Production composition must persist and conservatively recover execution authority."""
from __future__ import annotations
import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from app_api.server import DepartmentAppBackend
from tools.receipts import ExecutionIntentState, ExecutionMode, ExecutionReceipt, ExecutionStatus

class ProductionReceiptRestartDurabilityAdversarialV1Tests(unittest.TestCase):
    @staticmethod
    def _env(tmpdir: str) -> dict[str, str]:
        return {"APPDATA": tmpdir, "LOCALAPPDATA": tmpdir, "AI_MARKETING_KNOWLEDGE_EPHEMERAL": "0", "AI_MARKETING_MEMORY_EPHEMERAL": "0", "AI_MARKETING_LEARNING_EPHEMERAL": "0"}

    def test_receipt_repository_is_durable_closed_and_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, self._env(tmpdir), clear=False):
            first = DepartmentAppBackend(); first_repo = first.receipt_repo
            self.assertTrue(first_repo.durable); self.assertIsNotNone(first_repo.database_path); assert first_repo.database_path is not None
            self.assertTrue(first_repo.database_path.is_relative_to(Path(tmpdir).resolve()))
            saved = first_repo.save_receipt(ExecutionReceipt(run_id="RUN-RECEIPT-RESTART-1", agent_id="intelligence", capability_id="web_search", provider="test-provider", request_hash="receipt-restart-hash", status=ExecutionStatus.BLOCKED, execution_mode=ExecutionMode.MOCK, error_class="TEST_BLOCK", error_message="durability probe"))
            first_path = first_repo.database_path; first.close(); self.assertTrue(first_repo._closed)
            second = DepartmentAppBackend()
            try:
                self.assertTrue(second.receipt_repo.durable); self.assertEqual(second.receipt_repo.database_path, first_path)
                restored = second.receipt_repo.get_receipt(saved.execution_id); self.assertIsNotNone(restored); assert restored is not None
                self.assertEqual(restored.run_id, "RUN-RECEIPT-RESTART-1"); self.assertEqual(restored.error_class, "TEST_BLOCK")
            finally: second.close()

    def test_dispatching_intent_becomes_ambiguous_on_backend_restart_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, self._env(tmpdir), clear=False):
            first = DepartmentAppBackend()
            intent = first.receipt_repo.prepare_execution_intent(request_id="REQ-CRASH-1", run_id="RUN-CRASH-1", agent_id="cmo", capability_id="social_publishing", provider="sandbox", request_hash="crash-hash")
            first.receipt_repo.mark_execution_intent_dispatching(intent.intent_id)
            first.close()
            second = DepartmentAppBackend()
            try:
                recovered = second.receipt_repo.get_execution_intent(intent.intent_id); self.assertIsNotNone(recovered); assert recovered is not None
                self.assertEqual(recovered.state, ExecutionIntentState.AMBIGUOUS)
                self.assertEqual(recovered.dispatch_count, 1)
                self.assertTrue(any(a.intent_id == intent.intent_id and a.outcome.value == "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME" for a in second.execution_recovery_assessments))
                self.assertIsNone(recovered.receipt_execution_id)
            finally: second.close()

if __name__ == "__main__": unittest.main()
