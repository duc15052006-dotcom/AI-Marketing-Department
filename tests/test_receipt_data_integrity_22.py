from datetime import datetime, timezone
import unittest

from runtime.artifacts import DepartmentRunArtifact
from runtime.context import RuntimeStatus
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class ReceiptDataIntegrity22Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 31, 0, 0, 0, tzinfo=timezone.utc)

    def _receipt(self, data):
        return ExecutionReceipt(
            execution_id="EXEC-DATA-INTEGRITY-22",
            run_id="RUN-DATA-INTEGRITY-22",
            agent_id="intelligence",
            capability_id="web_search",
            provider="search_adapter",
            request_hash="request-hash-22",
            started_at=self.now,
            completed_at=self.now,
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            result_hash="stored-result-hash-left-unchanged",
            data=data,
        )

    def _artifact(self, receipt):
        return DepartmentRunArtifact(
            run_id="RUN-DATA-INTEGRITY-22",
            objective="Seal current receipt payload",
            started_at=self.now,
            completed_at=self.now,
            status=RuntimeStatus.COMPLETED,
            execution_receipts=[receipt],
        )

    def test_data_mutation_with_same_stored_result_hash_changes_artifact_hash(self):
        original = self._artifact(self._receipt({"price": 100, "currency": "USD"}))
        tampered = self._artifact(self._receipt({"price": 999, "currency": "USD"}))

        self.assertEqual(
            original.execution_receipts[0].result_hash,
            tampered.execution_receipts[0].result_hash,
            "Precondition: stored result_hash must remain unchanged for the tamper audit.",
        )
        self.assertNotEqual(
            original.compute_artifact_hash(),
            tampered.compute_artifact_hash(),
            "Current receipt.data must be inside the artifact integrity boundary even if result_hash is stale or forged.",
        )

    def test_semantically_identical_dict_key_order_has_same_artifact_hash(self):
        first = self._artifact(self._receipt({"a": 1, "b": {"x": 2, "y": 3}}))
        second = self._artifact(self._receipt({"b": {"y": 3, "x": 2}, "a": 1}))

        self.assertEqual(first.compute_artifact_hash(), second.compute_artifact_hash())

    def test_none_data_hash_is_deterministic(self):
        first = self._artifact(self._receipt(None))
        second = self._artifact(self._receipt(None))
        self.assertEqual(first.compute_artifact_hash(), second.compute_artifact_hash())


if __name__ == "__main__":
    unittest.main()
