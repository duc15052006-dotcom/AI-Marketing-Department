from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import tools.receipts as receipts_module
from tools.receipts import ExecutionMode, ExecutionReceiptRepository


class RuntimeMissionReconciliationEngineV1Tests(unittest.TestCase):
    """Ambiguous Mission effects require durable evidence before resolution."""

    @staticmethod
    def _evidence_hash(label: str) -> str:
        return hashlib.sha256(label.encode("utf-8")).hexdigest()

    def _require_resolution_boundary(self) -> None:
        missing: list[str] = []
        if not hasattr(receipts_module, "ExecutionReconciliationRecord"):
            missing.append("ExecutionReconciliationRecord")
        outcome = getattr(receipts_module, "ReconciliationOutcome", None)
        for name in (
            "CONFIRMED_EXTERNAL_ACTION_APPLIED",
            "CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED",
        ):
            if outcome is None or not hasattr(outcome, name):
                missing.append(f"ReconciliationOutcome.{name}")
        for name in (
            "record_execution_reconciliation",
            "get_execution_reconciliation",
        ):
            if not hasattr(ExecutionReceiptRepository, name):
                missing.append(f"ExecutionReceiptRepository.{name}")
        if missing:
            self.fail(
                "MISSION_RECONCILIATION_RESOLUTION_BOUNDARY_MISSING: "
                + ", ".join(sorted(missing))
            )

    @staticmethod
    def _prepare_ambiguous(repo: ExecutionReceiptRepository, *, suffix: str):
        intent = repo.prepare_execution_intent(
            request_id=f"REQ-RECON-{suffix}",
            run_id=f"RUN-RECON-{suffix}",
            agent_id="performance",
            capability_id="publish_content",
            provider="provider-x",
            request_hash=f"hash-recon-{suffix}",
            execution_mode=ExecutionMode.REAL,
            business_id="BIZ-1",
            project_id="PROJ-1",
            mission_id="MISSION-1",
            commitment_id="COMMIT-1",
        )
        repo.mark_execution_intent_dispatching(intent.intent_id)
        repo.reconcile_unfinished_intents()
        restored = repo.get_execution_intent(intent.intent_id)
        assert restored is not None
        return restored

    def test_control_restart_seals_dispatching_as_ambiguous_without_redispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "reconciliation.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db)
            intent = repo.prepare_execution_intent(
                request_id="REQ-RECON-CONTROL",
                run_id="RUN-RECON-CONTROL",
                agent_id="performance",
                capability_id="publish_content",
                provider="provider-x",
                request_hash="hash-recon-control",
                execution_mode=ExecutionMode.REAL,
                business_id="BIZ-1",
                project_id="PROJ-1",
                mission_id="MISSION-1",
                commitment_id="COMMIT-1",
            )
            repo.mark_execution_intent_dispatching(intent.intent_id)
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db)
            assessment = next(
                item
                for item in reopened.reconcile_unfinished_intents()
                if item.intent_id == intent.intent_id
            )
            self.assertEqual(
                receipts_module.ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME,
                assessment.outcome,
            )
            restored = reopened.get_execution_intent(intent.intent_id)
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(receipts_module.ExecutionIntentState.AMBIGUOUS, restored.state)
            self.assertEqual(1, restored.dispatch_count)
            with self.assertRaises(receipts_module.ReceiptStoreConflictError):
                reopened.mark_execution_intent_dispatching(intent.intent_id)
            reopened.close()

    def test_confirmed_applied_resolution_is_durable_and_never_redispatches_original_intent(self) -> None:
        self._require_resolution_boundary()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "reconciliation.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db)
            intent = self._prepare_ambiguous(repo, suffix="APPLIED")
            recorded = repo.record_execution_reconciliation(
                intent.intent_id,
                outcome=receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_APPLIED,
                evidence_hash=self._evidence_hash("provider says object exists"),
                evidence_source="provider-observation",
                business_id="BIZ-1",
                project_id="PROJ-1",
                mission_id="MISSION-1",
                commitment_id="COMMIT-1",
            )
            self.assertEqual(intent.intent_id, recorded.intent_id)
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db)
            durable = reopened.get_execution_reconciliation(intent.intent_id)
            self.assertIsNotNone(durable)
            assert durable is not None
            self.assertEqual(recorded.reconciliation_id, durable.reconciliation_id)
            self.assertEqual("MISSION-1", durable.mission_id)
            self.assertEqual("COMMIT-1", durable.commitment_id)
            self.assertEqual(
                receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_APPLIED,
                reopened.assess_execution_intent(intent.intent_id).outcome,
            )
            with self.assertRaises(receipts_module.ReceiptStoreConflictError):
                reopened.mark_execution_intent_dispatching(intent.intent_id)
            reopened.close()

    def test_reconciliation_rejects_foreign_mission_or_commitment_evidence(self) -> None:
        self._require_resolution_boundary()
        with tempfile.TemporaryDirectory() as tmp:
            repo = ExecutionReceiptRepository(database_path=Path(tmp) / "reconciliation.sqlite3")
            intent = self._prepare_ambiguous(repo, suffix="FOREIGN")
            kwargs = dict(
                outcome=receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_APPLIED,
                evidence_hash=self._evidence_hash("provider evidence"),
                evidence_source="provider-observation",
                business_id="BIZ-1",
                project_id="PROJ-1",
            )
            with self.assertRaises(receipts_module.ReceiptStoreIntegrityError):
                repo.record_execution_reconciliation(
                    intent.intent_id,
                    mission_id="MISSION-FOREIGN",
                    commitment_id="COMMIT-1",
                    **kwargs,
                )
            with self.assertRaises(receipts_module.ReceiptStoreIntegrityError):
                repo.record_execution_reconciliation(
                    intent.intent_id,
                    mission_id="MISSION-1",
                    commitment_id="COMMIT-FOREIGN",
                    **kwargs,
                )
            self.assertIsNone(repo.get_execution_reconciliation(intent.intent_id))
            repo.close()

    def test_same_resolution_is_idempotent_but_contradictory_resolution_conflicts(self) -> None:
        self._require_resolution_boundary()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "reconciliation.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db)
            intent = self._prepare_ambiguous(repo, suffix="IDEMPOTENT")
            evidence_hash = self._evidence_hash("provider says object absent")
            kwargs = dict(
                evidence_hash=evidence_hash,
                evidence_source="provider-observation",
                business_id="BIZ-1",
                project_id="PROJ-1",
                mission_id="MISSION-1",
                commitment_id="COMMIT-1",
            )
            first = repo.record_execution_reconciliation(
                intent.intent_id,
                outcome=receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED,
                **kwargs,
            )
            same = repo.record_execution_reconciliation(
                intent.intent_id,
                outcome=receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED,
                **kwargs,
            )
            self.assertEqual(first.reconciliation_id, same.reconciliation_id)
            with self.assertRaises(receipts_module.ReceiptStoreConflictError):
                repo.record_execution_reconciliation(
                    intent.intent_id,
                    outcome=receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_APPLIED,
                    **kwargs,
                )
            self.assertEqual(
                receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED,
                repo.assess_execution_intent(intent.intent_id).outcome,
            )
            with self.assertRaises(receipts_module.ReceiptStoreConflictError):
                repo.mark_execution_intent_dispatching(intent.intent_id)
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db)
            durable = reopened.get_execution_reconciliation(intent.intent_id)
            self.assertIsNotNone(durable)
            assert durable is not None
            self.assertEqual(first.reconciliation_id, durable.reconciliation_id)
            self.assertEqual(evidence_hash, durable.evidence_hash)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
