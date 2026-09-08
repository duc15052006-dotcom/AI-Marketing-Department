"""Adversarial RED contract for run-local sealed execution receipt authority.

Invariant under test:
A DepartmentRunArtifact may seal only execution receipts that belong to the
current immutable RuntimeContext authority. Mutable execution_receipt_refs must
not be able to inject receipts from another run, business, project, or chat into
the sealed artifact or into candidate-memory evidence refs. Legacy receipts
with missing optional scope fields remain compatible when their authoritative
run_id matches.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


RUN_ID = "RUN-RECEIPT-SCOPE-001"
BUSINESS_ID = "BIZ-RECEIPT-SCOPE-001"
PROJECT_ID = "PROJ-RECEIPT-SCOPE-001"
CHAT_ID = "CHAT-RECEIPT-SCOPE-001"


def _receipt(
    execution_id: str,
    *,
    run_id: str = RUN_ID,
    business_id: str | None = BUSINESS_ID,
    project_id: str | None = PROJECT_ID,
    chat_id: str | None = CHAT_ID,
) -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=execution_id,
        run_id=run_id,
        agent_id="intelligence",
        capability_id="web_search",
        provider="test_provider",
        request_hash=f"request-{execution_id}",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        status=ExecutionStatus.SUCCESS,
        execution_mode=ExecutionMode.REAL,
        business_id=business_id,
        project_id=project_id,
        chat_id=chat_id,
        result_hash=f"result-{execution_id}",
        data={"execution_id": execution_id},
    )


def _context(*receipt_ids: str) -> RuntimeContext:
    context = RuntimeContext(
        run_id=RUN_ID,
        objective="Seal only receipts owned by this runtime scope",
        business_id=BUSINESS_ID,
        project_id=PROJECT_ID,
        chat_id=CHAT_ID,
        status=RuntimeStatus.RUNNING,
    )
    context.execution_receipt_refs.extend(receipt_ids)
    return context


class TestRuntimeSealedReceiptScopeIsolationV1(unittest.TestCase):
    @staticmethod
    def _complete_with_receipts(
        context: RuntimeContext,
        *receipts: ExecutionReceipt,
    ):
        runtime = FiveAgentDepartmentRuntime()
        by_id = {receipt.execution_id: receipt for receipt in receipts}
        with (
            patch.object(
                runtime.tool_gateway.receipt_repository,
                "get_receipt",
                side_effect=lambda execution_id: by_id.get(execution_id),
            ),
            patch.object(runtime.memory_repo, "save_memory", return_value=None),
        ):
            return runtime.complete_run(context)

    def test_foreign_run_receipt_ref_cannot_enter_sealed_artifact(self) -> None:
        current = _receipt("EXEC-CURRENT-RUN")
        foreign = _receipt("EXEC-FOREIGN-RUN", run_id="RUN-FOREIGN")
        artifact = self._complete_with_receipts(
            _context(current.execution_id, foreign.execution_id),
            current,
            foreign,
        )

        self.assertEqual(
            [receipt.execution_id for receipt in artifact.execution_receipts],
            [current.execution_id],
            "STILL PRESENT: mutable receipt refs can inject another run's receipt into the sealed artifact.",
        )
        self.assertEqual(artifact.capabilities_used, [current.capability_id])

    def test_same_run_foreign_business_receipt_cannot_enter_sealed_artifact(self) -> None:
        current = _receipt("EXEC-CURRENT-BUSINESS")
        foreign = _receipt("EXEC-FOREIGN-BUSINESS", business_id="BIZ-FOREIGN")
        artifact = self._complete_with_receipts(
            _context(current.execution_id, foreign.execution_id),
            current,
            foreign,
        )

        self.assertEqual(
            [receipt.execution_id for receipt in artifact.execution_receipts],
            [current.execution_id],
            "STILL PRESENT: a same-run receipt with conflicting business authority is sealed.",
        )

    def test_same_run_foreign_project_receipt_cannot_enter_sealed_artifact(self) -> None:
        current = _receipt("EXEC-CURRENT-PROJECT")
        foreign = _receipt("EXEC-FOREIGN-PROJECT", project_id="PROJ-FOREIGN")
        artifact = self._complete_with_receipts(
            _context(current.execution_id, foreign.execution_id),
            current,
            foreign,
        )

        self.assertEqual(
            [receipt.execution_id for receipt in artifact.execution_receipts],
            [current.execution_id],
            "STILL PRESENT: a same-run receipt with conflicting project authority is sealed.",
        )

    def test_same_run_foreign_chat_receipt_cannot_enter_sealed_artifact(self) -> None:
        current = _receipt("EXEC-CURRENT-CHAT")
        foreign = _receipt("EXEC-FOREIGN-CHAT", chat_id="CHAT-FOREIGN")
        artifact = self._complete_with_receipts(
            _context(current.execution_id, foreign.execution_id),
            current,
            foreign,
        )

        self.assertEqual(
            [receipt.execution_id for receipt in artifact.execution_receipts],
            [current.execution_id],
            "STILL PRESENT: a same-run receipt with conflicting chat authority is sealed.",
        )

    def test_foreign_receipt_ref_cannot_enter_candidate_memory_evidence(self) -> None:
        current = _receipt("EXEC-CURRENT-MEMORY")
        foreign = _receipt("EXEC-FOREIGN-MEMORY", run_id="RUN-FOREIGN")
        context = _context(current.execution_id, foreign.execution_id)
        context.stage_outputs["final_cmo"] = {
            "status": "READY_FOR_DEPLOYMENT",
            "approval_status": "APPROVED",
        }

        artifact = self._complete_with_receipts(context, current, foreign)

        self.assertEqual(len(artifact.learning_candidates), 1)
        self.assertEqual(
            artifact.learning_candidates[0].evidence_refs,
            [current.execution_id],
            "STILL PRESENT: foreign receipt refs can be sealed into candidate-memory evidence.",
        )

    def test_legacy_unscoped_receipt_with_matching_run_remains_compatible(self) -> None:
        legacy = _receipt(
            "EXEC-LEGACY-UNSCOPED",
            business_id=None,
            project_id=None,
            chat_id=None,
        )
        artifact = self._complete_with_receipts(
            _context(legacy.execution_id),
            legacy,
        )

        self.assertEqual(
            [receipt.execution_id for receipt in artifact.execution_receipts],
            [legacy.execution_id],
        )


if __name__ == "__main__":
    unittest.main()
