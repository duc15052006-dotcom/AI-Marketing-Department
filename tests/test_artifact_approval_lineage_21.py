from datetime import datetime, timezone
import hashlib
import unittest

from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RuntimeStatus
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class ArtifactApprovalLineage21Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 31, 0, 0, 0, tzinfo=timezone.utc)

    def _receipt(self, approval_reference: str) -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id="EXEC-APPROVAL-LINEAGE-21",
            run_id="RUN-APPROVAL-LINEAGE-21",
            agent_id="cmo",
            capability_id="social_publishing",
            provider="social_publish_adapter",
            request_hash="request-hash-21",
            started_at=self.now,
            completed_at=self.now,
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            approval_reference=approval_reference,
            business_id="BIZ-APPROVAL-LINEAGE-21",
        )

    def _artifact(self, receipt: ExecutionReceipt, approvals=None) -> DepartmentRunArtifact:
        return DepartmentRunArtifact(
            run_id="RUN-APPROVAL-LINEAGE-21",
            objective="Audit consequential approval lineage",
            business_id="BIZ-APPROVAL-LINEAGE-21",
            started_at=self.now,
            completed_at=self.now,
            status=RuntimeStatus.COMPLETED,
            execution_receipts=[receipt],
            approvals=[] if approvals is None else approvals,
        )

    def test_receipt_approval_reference_derives_non_secret_audit_lineage(self):
        token = "appr_super_secret_one_shot_token"
        artifact = self._artifact(self._receipt(token))

        self.assertEqual(len(artifact.approvals), 1)
        audit = artifact.approvals[0]
        self.assertEqual(
            audit["approval_reference_hash"],
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(audit["capability_id"], "social_publishing")
        self.assertEqual(audit["request_hash"], "request-hash-21")
        self.assertNotIn(token, repr(artifact.approvals))

    def test_approval_reference_mutation_changes_artifact_hash(self):
        first = self._artifact(self._receipt("appr_token_a"))
        tampered = self._artifact(self._receipt("appr_token_b"))

        self.assertNotEqual(
            first.compute_artifact_hash(),
            tampered.compute_artifact_hash(),
            "Changing the approval authority reference must invalidate artifact integrity.",
        )

    def test_explicit_approval_audit_is_not_overwritten(self):
        explicit = [{"approval_reference_hash": "presealed", "decision": "APPROVED"}]
        artifact = self._artifact(self._receipt("appr_token_a"), approvals=explicit)
        self.assertEqual(artifact.approvals, explicit)


if __name__ == "__main__":
    unittest.main()
