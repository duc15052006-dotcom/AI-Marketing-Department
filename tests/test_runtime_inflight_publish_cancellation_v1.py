"""Adversarial regression for cancellation racing an in-flight publish.

A consequential publishing dispatch may already be in flight when the operator
cancels the run. The external result must still be retained for audit, but a
late SUCCESS receipt must never revive the cancelled RuntimeContext to RUNNING.
"""

from __future__ import annotations

import threading
import unittest

from runtime.context import RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class _BlockingPublishGateway:
    def __init__(self) -> None:
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def execute(self, request, **_kwargs):
        self.calls.append(request)
        self.entered.set()
        if not self.release.wait(timeout=5.0):
            raise RuntimeError("TEST_GATEWAY_RELEASE_TIMEOUT")
        return ExecutionReceipt(
            execution_id="EXEC-INFLIGHT-CANCEL-PUBLISH-V1",
            run_id=request.run_id,
            agent_id=request.agent_id,
            capability_id=request.capability_id,
            provider="TEST",
            request_hash="0" * 64,
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.MOCK,
            business_id=request.business_id,
            project_id=request.project_id,
            chat_id=request.chat_id,
            data={"accepted": True},
        )


class RuntimeInflightPublishCancellationV1Tests(unittest.TestCase):
    @staticmethod
    def _runtime_and_context():
        runtime = FiveAgentDepartmentRuntime()
        context = runtime.start_run(
            objective="in-flight publish cancellation authority regression",
            trusted_run_id="RUN-INFLIGHT-CANCEL-PUBLISH-V1",
            business_id="BIZ-INFLIGHT-CANCEL-PUBLISH-V1",
            project_id="PROJ-INFLIGHT-CANCEL-PUBLISH-V1",
            chat_id="CHAT-INFLIGHT-CANCEL-PUBLISH-V1",
        )
        gateway = _BlockingPublishGateway()
        runtime.tool_gateway = gateway
        return runtime, context, gateway

    def test_late_publish_success_cannot_revive_operator_cancelled_run(self) -> None:
        runtime, context, gateway = self._runtime_and_context()
        result = {}

        def publish() -> None:
            try:
                result["receipt"] = runtime.request_publish_action(
                    context,
                    platform="linkedin",
                )
            except BaseException as exc:  # captured so the test cannot hide worker failure
                result["error"] = exc

        worker = threading.Thread(target=publish, name="publish-worker", daemon=True)
        worker.start()
        self.assertTrue(
            gateway.entered.wait(timeout=5.0),
            "publish dispatch did not become in-flight",
        )

        self.assertTrue(runtime.cancel_run(context.run_id))
        self.assertEqual(context.status, RuntimeStatus.CANCELLED)
        self.assertTrue(runtime.is_cancelled(context.run_id))

        gateway.release.set()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive(), "publish worker did not terminate")
        self.assertNotIn("error", result, result.get("error"))

        receipt = result.get("receipt")
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(len(gateway.calls), 1, "in-flight publish must never be retried")

        # The provider may already have accepted the action, so its receipt is
        # audit evidence and must not be discarded merely because cancellation won.
        self.assertIn(receipt.execution_id, context.execution_receipt_refs)
        lineage_ids = {item.execution_id for item in runtime.lineage_inspector.get_all_receipts()}
        self.assertIn(receipt.execution_id, lineage_ids)

        # Cancellation is the authoritative terminal lifecycle decision.
        self.assertEqual(
            context.status,
            RuntimeStatus.CANCELLED,
            "late publish SUCCESS must not revive CANCELLED -> RUNNING",
        )
        self.assertTrue(runtime.is_cancelled(context.run_id))

    def test_non_cancelled_publish_control_still_returns_to_running(self) -> None:
        runtime, context, gateway = self._runtime_and_context()
        gateway.release.set()

        receipt = runtime.request_publish_action(context, platform="linkedin")

        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(context.status, RuntimeStatus.RUNNING)
        self.assertFalse(runtime.is_cancelled(context.run_id))
        self.assertEqual(len(gateway.calls), 1)


if __name__ == "__main__":
    unittest.main()
