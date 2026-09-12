"""Lineage claim identity must be deterministic and receipt tracing must respect run scope."""
from __future__ import annotations
import hashlib, unittest
from runtime.lineage import LineageInspector
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus

class RuntimeLineageScopeAdversarialV1Tests(unittest.TestCase):
    def test_claim_id_is_deterministic_and_cross_run_receipt_is_rejected(self) -> None:
        receipt = ExecutionReceipt(run_id="RUN-A", agent_id="cmo", capability_id="social_publishing", provider="sandbox", request_hash="lineage-hash", status=ExecutionStatus.SUCCESS, execution_mode=ExecutionMode.MOCK)
        inspector = LineageInspector(receipts=[receipt]); claim = "Published Campaign"
        trace = inspector.trace_claim_to_receipt(claim, receipt.execution_id, run_id="RUN-A")
        self.assertTrue(trace.valid); self.assertEqual(trace.chain[0].node_id, "CLAIM-" + hashlib.sha256(claim.encode("utf-8")).hexdigest())
        cross = inspector.trace_claim_to_receipt(claim, receipt.execution_id, run_id="RUN-B")
        self.assertFalse(cross.valid); self.assertTrue(any("RUN_SCOPE_MISMATCH" in item for item in cross.missing_links))
        inspector.remove_receipts_for_run("RUN-A"); self.assertEqual(inspector.get_all_receipts(), [])

if __name__ == "__main__": unittest.main()
