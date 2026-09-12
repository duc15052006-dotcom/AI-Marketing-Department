"""Regression locks for run-scoped approval-reference canonicalization."""

import unittest

from runtime.context import RuntimeContext, RuntimeStatus
from runtime.deployment_binding import (
    DEPLOYMENT_ERROR_PREFIX,
    clear_deployment_binding_registry_for_tests,
)
from tools.receipts import ExecutionReceipt, ExecutionStatus


class TestApprovalReferenceScopeIsolation(unittest.TestCase):
    def setUp(self):
        clear_deployment_binding_registry_for_tests()

    @staticmethod
    def _receipt(run_id: str, approval_reference: str) -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id="EXEC-COLLISION-001",
            run_id=run_id,
            agent_id="cmo",
            capability_id="social_publishing",
            provider="publishing_sandbox",
            status=ExecutionStatus.APPROVAL_REQUIRED,
            request_hash="c" * 64,
            approval_reference=approval_reference,
        )

    @staticmethod
    def _context(run_id: str) -> RuntimeContext:
        return RuntimeContext(
            run_id=run_id,
            objective="Verify approval scope isolation",
            business_id="BIZ-APPROVAL-SCOPE",
            project_id="PROJ-APPROVAL-SCOPE",
            chat_id="CHAT-APPROVAL-SCOPE",
            campaign_id="CAMP-APPROVAL-SCOPE",
            status=RuntimeStatus.WAITING_FOR_APPROVAL,
        )

    def test_same_execution_id_in_different_runs_resolves_only_within_run_scope(self):
        run_a = "RUN-APPROVAL-SCOPE-A"
        run_b = "RUN-APPROVAL-SCOPE-B"
        self._receipt(run_a, "APPR-SERVER-A")
        self._receipt(run_b, "APPR-SERVER-B")

        checkpoint_a = self._context(run_a).create_checkpoint(
            pending_approval_id="EXEC-COLLISION-001"
        )
        checkpoint_b = self._context(run_b).create_checkpoint(
            pending_approval_id="EXEC-COLLISION-001"
        )

        self.assertEqual(checkpoint_a.pending_approval_id, "APPR-SERVER-A")
        self.assertEqual(checkpoint_b.pending_approval_id, "APPR-SERVER-B")

    def test_conflicting_reference_for_same_run_and_execution_id_fails_closed(self):
        run_id = "RUN-APPROVAL-SCOPE-CONFLICT"
        self._receipt(run_id, "APPR-SERVER-ORIGINAL")

        with self.assertRaisesRegex(RuntimeError, DEPLOYMENT_ERROR_PREFIX):
            self._receipt(run_id, "APPR-SERVER-CONFLICT")

        checkpoint = self._context(run_id).create_checkpoint(
            pending_approval_id="EXEC-COLLISION-001"
        )
        self.assertEqual(checkpoint.pending_approval_id, "APPR-SERVER-ORIGINAL")

    def test_direct_server_approval_reference_remains_unchanged(self):
        run_id = "RUN-APPROVAL-SCOPE-DIRECT"
        self._receipt(run_id, "APPR-SERVER-MAPPED")

        checkpoint = self._context(run_id).create_checkpoint(
            pending_approval_id="APPR-SERVER-DIRECT"
        )

        self.assertEqual(checkpoint.pending_approval_id, "APPR-SERVER-DIRECT")


if __name__ == "__main__":
    unittest.main()
