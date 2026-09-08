from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import tools.receipts as receipts_module
from tools.receipts import (
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
)


class RuntimeMissionEffectJournalV1Tests(unittest.TestCase):
    """Mission external-effect evidence must be durable and authority-bound."""

    def _require_mission_effect_boundary(self) -> None:
        constructor = inspect.signature(ExecutionReceiptRepository.__init__)
        required_module_symbols = (
            "ExecutionIntentState",
            "ReconciliationOutcome",
            "ReceiptStoreIntegrityError",
        )
        missing = [name for name in required_module_symbols if not hasattr(receipts_module, name)]
        required_repo_methods = (
            "prepare_execution_intent",
            "get_execution_intent",
            "mark_execution_intent_dispatching",
            "finalize_execution_intent",
            "assess_execution_intent",
            "reconcile_unfinished_intents",
            "close",
        )
        missing.extend(name for name in required_repo_methods if not hasattr(ExecutionReceiptRepository, name))
        if "database_path" not in constructor.parameters:
            missing.append("database_path")
        receipt_fields = getattr(ExecutionReceipt, "__dataclass_fields__", {})
        if not receipt_fields:
            receipt_fields = getattr(ExecutionReceipt, "model_fields", {})
        for name in ("mission_id", "commitment_id"):
            if name not in receipt_fields:
                missing.append(f"ExecutionReceipt.{name}")
        if missing:
            self.fail("MISSION_EFFECT_JOURNAL_BOUNDARY_MISSING: " + ", ".join(sorted(set(missing))))

    @staticmethod
    def _receipt(*, mission_id: str, commitment_id: str) -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id="EXEC-MISSION-EFFECT-1",
            run_id="RUN-EFFECT-1",
            agent_id="performance",
            capability_id="publish_content",
            provider="provider-x",
            request_hash="hash-effect-1",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            business_id="BIZ-1",
            project_id="PROJ-1",
            mission_id=mission_id,
            commitment_id=commitment_id,
            data={"provider_object_id": "opaque-object-1"},
        )

    def test_legacy_in_memory_receipt_repository_remains_available(self) -> None:
        repo = ExecutionReceiptRepository()
        receipt = ExecutionReceipt(
            execution_id="EXEC-LEGACY-CONTROL",
            run_id="RUN-LEGACY-CONTROL",
            agent_id="performance",
            capability_id="analytics_read",
            provider="mock",
            request_hash="legacy-hash",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.MOCK,
        )
        stored = repo.save_receipt(receipt)
        self.assertEqual(receipt.execution_id, stored.execution_id)
        self.assertIsNotNone(repo.get_receipt(receipt.execution_id))

    def test_durable_intent_survives_restart_with_exact_mission_commitment_authority(self) -> None:
        self._require_mission_effect_boundary()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "effects.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db)
            intent = repo.prepare_execution_intent(
                request_id="REQ-EFFECT-1",
                run_id="RUN-EFFECT-1",
                agent_id="performance",
                capability_id="publish_content",
                provider="provider-x",
                request_hash="hash-effect-1",
                execution_mode=ExecutionMode.REAL,
                business_id="BIZ-1",
                project_id="PROJ-1",
                mission_id="MISSION-1",
                commitment_id="COMMIT-1",
            )
            repo.mark_execution_intent_dispatching(intent.intent_id)
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db)
            restored = reopened.get_execution_intent(intent.intent_id)
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual("MISSION-1", restored.mission_id)
            self.assertEqual("COMMIT-1", restored.commitment_id)
            self.assertEqual("BIZ-1", restored.business_id)
            self.assertEqual("PROJ-1", restored.project_id)
            self.assertEqual(receipts_module.ExecutionIntentState.DISPATCHING, restored.state)
            reopened.close()

    def test_receipt_cannot_finalize_foreign_mission_or_commitment(self) -> None:
        self._require_mission_effect_boundary()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "effects.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db)
            intent = repo.prepare_execution_intent(
                request_id="REQ-EFFECT-1",
                run_id="RUN-EFFECT-1",
                agent_id="performance",
                capability_id="publish_content",
                provider="provider-x",
                request_hash="hash-effect-1",
                execution_mode=ExecutionMode.REAL,
                business_id="BIZ-1",
                project_id="PROJ-1",
                mission_id="MISSION-1",
                commitment_id="COMMIT-1",
            )
            repo.mark_execution_intent_dispatching(intent.intent_id)
            with self.assertRaises(receipts_module.ReceiptStoreIntegrityError):
                repo.finalize_execution_intent(intent.intent_id, self._receipt(mission_id="MISSION-FOREIGN", commitment_id="COMMIT-1"))
            with self.assertRaises(receipts_module.ReceiptStoreIntegrityError):
                repo.finalize_execution_intent(intent.intent_id, self._receipt(mission_id="MISSION-1", commitment_id="COMMIT-FOREIGN"))
            accepted = repo.finalize_execution_intent(intent.intent_id, self._receipt(mission_id="MISSION-1", commitment_id="COMMIT-1"))
            self.assertEqual("MISSION-1", accepted.mission_id)
            self.assertEqual("COMMIT-1", accepted.commitment_id)
            repo.close()

    def test_restart_reconciliation_preserves_mission_lineage_and_never_claims_failure(self) -> None:
        self._require_mission_effect_boundary()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "effects.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db)
            intent = repo.prepare_execution_intent(
                request_id="REQ-EFFECT-AMBIG",
                run_id="RUN-EFFECT-AMBIG",
                agent_id="performance",
                capability_id="publish_content",
                provider="provider-x",
                request_hash="hash-effect-ambig",
                execution_mode=ExecutionMode.REAL,
                business_id="BIZ-1",
                project_id="PROJ-1",
                mission_id="MISSION-1",
                commitment_id="COMMIT-1",
            )
            repo.mark_execution_intent_dispatching(intent.intent_id)
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db)
            assessments = reopened.reconcile_unfinished_intents()
            assessment = next(item for item in assessments if item.intent_id == intent.intent_id)
            self.assertEqual(receipts_module.ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME, assessment.outcome)
            restored = reopened.get_execution_intent(intent.intent_id)
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual("MISSION-1", restored.mission_id)
            self.assertEqual("COMMIT-1", restored.commitment_id)
            self.assertEqual(receipts_module.ExecutionIntentState.AMBIGUOUS, restored.state)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
