from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_api.server as server
import tools.receipts as receipts_module
from app_api.server import DepartmentAPIHandler, DepartmentAppBackend
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus


class RuntimeEffectAuthorityStackV2Tests(unittest.TestCase):
    """Production effect authority must compose durability, reconciliation, and activity reads."""

    @staticmethod
    def _invoke_activity_receipts_get() -> tuple[object, int]:
        handler = DepartmentAPIHandler.__new__(DepartmentAPIHandler)
        handler.headers = {
            "Host": "127.0.0.1",
            "Authorization": f"Bearer {server.GLOBAL_API_SESSION_TOKEN}",
        }
        handler.path = "/api/activity/receipts"
        captured: dict[str, object] = {}

        def _capture(data: object, status_code: int = 200) -> None:
            captured["data"] = data
            captured["status_code"] = status_code

        handler._send_json = _capture  # type: ignore[method-assign]
        handler.do_GET()
        return captured.get("data"), int(captured.get("status_code", 0))

    @staticmethod
    def _require_composed_boundary() -> None:
        missing: list[str] = []
        if not hasattr(ExecutionReceiptRepository, "list_receipts"):
            missing.append("ExecutionReceiptRepository.list_receipts")
        if not hasattr(ExecutionReceiptRepository, "record_execution_reconciliation"):
            missing.append("ExecutionReceiptRepository.record_execution_reconciliation")
        if not hasattr(ExecutionReceiptRepository, "get_execution_reconciliation"):
            missing.append("ExecutionReceiptRepository.get_execution_reconciliation")
        if not hasattr(receipts_module, "ExecutionReconciliationRecord"):
            missing.append("ExecutionReconciliationRecord")
        outcome = getattr(receipts_module, "ReconciliationOutcome", None)
        for name in (
            "CONFIRMED_EXTERNAL_ACTION_APPLIED",
            "CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED",
        ):
            if outcome is None or not hasattr(outcome, name):
                missing.append(f"ReconciliationOutcome.{name}")
        if missing:
            raise AssertionError(
                "RUNTIME_EFFECT_AUTHORITY_STACK_FRAGMENTED: " + ", ".join(sorted(missing))
            )

    def test_production_effect_authority_stack_is_composed_on_one_restart_safe_backend(self) -> None:
        self._require_composed_boundary()

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "backend_instance.json"
            with patch("app_api.server.get_backend_state_file_path", return_value=state_file):
                first = DepartmentAppBackend()
                try:
                    self.assertTrue(first.receipt_repo.durable)
                    self.assertIs(
                        first.tool_gateway.receipt_repository,
                        first.receipt_repo,
                        "TOOL_GATEWAY_EFFECT_JOURNAL_SPLIT: production gateway must use the backend authority journal",
                    )
                    receipt = ExecutionReceipt(
                        execution_id="EXEC-EFFECT-STACK-V2",
                        run_id="RUN-EFFECT-STACK-V2",
                        agent_id="performance",
                        capability_id="analytics_read",
                        provider="analytics_adapter",
                        request_hash="effect-stack-v2-read",
                        status=ExecutionStatus.SUCCESS,
                        execution_mode=ExecutionMode.SANDBOX,
                        data={"ok": True},
                    )
                    first.receipt_repo.save_receipt(receipt)
                    intent = first.receipt_repo.prepare_execution_intent(
                        request_id="REQ-EFFECT-STACK-V2",
                        run_id="RUN-EFFECT-STACK-V2",
                        agent_id="performance",
                        capability_id="publish_content",
                        provider="provider-x",
                        request_hash="effect-stack-v2-write",
                        execution_mode=ExecutionMode.REAL,
                        business_id="BIZ-EFFECT-V2",
                        project_id="PROJ-EFFECT-V2",
                        mission_id="MISSION-EFFECT-V2",
                        commitment_id="COMMIT-EFFECT-V2",
                    )
                    first.receipt_repo.mark_execution_intent_dispatching(intent.intent_id)
                    intent_id = intent.intent_id
                finally:
                    first.receipt_repo.close()

                restarted = DepartmentAppBackend()
                try:
                    restored = restarted.receipt_repo.get_execution_intent(intent_id)
                    self.assertIsNotNone(restored)
                    assert restored is not None
                    self.assertEqual(
                        receipts_module.ExecutionIntentState.AMBIGUOUS,
                        restored.state,
                        "RESTART_DID_NOT_SEAL_AMBIGUOUS: unfinished external effect must reconcile before continuation",
                    )

                    evidence_hash = hashlib.sha256(
                        b"provider confirms external object exists"
                    ).hexdigest()
                    reconciliation = restarted.receipt_repo.record_execution_reconciliation(
                        intent_id,
                        outcome=receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_APPLIED,
                        evidence_hash=evidence_hash,
                        evidence_source="provider-observation",
                        business_id="BIZ-EFFECT-V2",
                        project_id="PROJ-EFFECT-V2",
                        mission_id="MISSION-EFFECT-V2",
                        commitment_id="COMMIT-EFFECT-V2",
                    )
                    self.assertEqual(intent_id, reconciliation.intent_id)

                    with patch("app_api.server.APP_BACKEND", restarted):
                        payload, status_code = self._invoke_activity_receipts_get()
                    self.assertEqual(200, status_code)
                    self.assertIsInstance(payload, list)
                    execution_ids = {
                        item.get("execution_id")
                        for item in payload
                        if isinstance(item, dict)
                    }
                    self.assertIn(
                        "EXEC-EFFECT-STACK-V2",
                        execution_ids,
                        "DURABLE_ACTIVITY_RECEIPT_INVISIBLE: production activity surface must read the same durable authority journal",
                    )
                finally:
                    restarted.receipt_repo.close()

                reopened = DepartmentAppBackend()
                try:
                    durable = reopened.receipt_repo.get_execution_reconciliation(intent_id)
                    self.assertIsNotNone(durable)
                    assert durable is not None
                    self.assertEqual(evidence_hash, durable.evidence_hash)
                    self.assertEqual(
                        receipts_module.ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_APPLIED,
                        reopened.receipt_repo.assess_execution_intent(intent_id).outcome,
                    )
                    with self.assertRaises(receipts_module.ReceiptStoreConflictError):
                        reopened.receipt_repo.mark_execution_intent_dispatching(intent_id)
                finally:
                    reopened.receipt_repo.close()


if __name__ == "__main__":
    unittest.main()
