from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_api.server as server
from app_api.server import DepartmentAPIHandler, DepartmentAppBackend
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class RuntimeDurableActivityReceiptsListingV1Tests(unittest.TestCase):
    """Activity API must expose receipts from the authoritative durable store."""

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

    def test_list_all_activity_receipts_survives_durable_backend_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "backend_instance.json"

            with patch("app_api.server.get_backend_state_file_path", return_value=state_file):
                first = DepartmentAppBackend()
                receipt = ExecutionReceipt(
                    execution_id="EXEC-ACTIVITY-DURABLE-1",
                    run_id="RUN-ACTIVITY-DURABLE-1",
                    agent_id="cmo",
                    capability_id="analytics_read",
                    provider="analytics_adapter",
                    request_hash="activity-durable-hash-1",
                    status=ExecutionStatus.SUCCESS,
                    execution_mode=ExecutionMode.SANDBOX,
                    data={"ok": True},
                )
                try:
                    self.assertTrue(first.receipt_repo.durable)
                    first.receipt_repo.save_receipt(receipt)
                finally:
                    first.receipt_repo.close()

                restarted = DepartmentAppBackend()
                try:
                    self.assertIsNotNone(
                        restarted.receipt_repo.get_receipt(receipt.execution_id),
                        "CONTROL_FAILURE: receipt itself did not survive the durable restart",
                    )
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
                        receipt.execution_id,
                        execution_ids,
                        "DURABLE_ACTIVITY_RECEIPT_INVISIBLE: list-all activity API reads the legacy in-memory cache instead of the authoritative durable receipt store",
                    )
                finally:
                    restarted.receipt_repo.close()


if __name__ == "__main__":
    unittest.main()
