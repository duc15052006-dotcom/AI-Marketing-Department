from datetime import datetime, timezone
import unittest

from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RuntimeStatus


class ArtifactApprovalHash20Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 31, 0, 0, 0, tzinfo=timezone.utc)

    def _artifact(self, approvals):
        return DepartmentRunArtifact(
            run_id="RUN-APPROVAL-HASH-20",
            objective="Seal human approval provenance",
            business_id="BIZ-APPROVAL-HASH-20",
            started_at=self.now,
            completed_at=self.now,
            status=RuntimeStatus.COMPLETED,
            approvals=approvals,
        )

    def test_approval_mutation_changes_artifact_hash(self):
        approved = self._artifact([
            {
                "approval_id": "APR-001",
                "capability_id": "social_publish",
                "request_fingerprint": "req-hash-001",
                "approved_by": "operator-a",
                "decision": "APPROVED",
            }
        ])
        tampered = self._artifact([
            {
                "approval_id": "APR-001",
                "capability_id": "social_publish",
                "request_fingerprint": "req-hash-001",
                "approved_by": "operator-b",
                "decision": "APPROVED",
            }
        ])

        self.assertNotEqual(
            approved.compute_artifact_hash(),
            tampered.compute_artifact_hash(),
            "Approval history must be inside the authoritative artifact integrity boundary.",
        )

    def test_empty_approval_list_hash_is_deterministic(self):
        first = self._artifact([])
        second = self._artifact([])
        self.assertEqual(first.compute_artifact_hash(), second.compute_artifact_hash())


if __name__ == "__main__":
    unittest.main()
