"""Adversarial RED for cancelled-run publishing authority.

Once runtime cancellation is authoritative, a consequential social-publishing
request must fail closed before ToolGateway dispatch. A live run remains allowed
to dispatch so the regression cannot be satisfied by disabling publishing.
"""

from __future__ import annotations

import unittest

from runtime.context import RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class _RecordingPublishGateway:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return ExecutionReceipt(
            execution_id="EXEC-CANCEL-PUBLISH-V1",
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
            data={"ok": True},
        )


class RuntimeCancelledPublishZeroDispatchV1Tests(unittest.TestCase):
    @staticmethod
    def _runtime_and_context(run_id: str):
        runtime = FiveAgentDepartmentRuntime()
        context = runtime.start_run(
            objective="cancelled publishing authority regression",
            trusted_run_id=run_id,
            business_id="BIZ-CANCEL-PUBLISH-V1",
            project_id="PROJ-CANCEL-PUBLISH-V1",
            chat_id="CHAT-CANCEL-PUBLISH-V1",
        )
        gateway = _RecordingPublishGateway()
        runtime.tool_gateway = gateway
        return runtime, context, gateway

    def test_cancelled_run_fails_closed_before_publish_dispatch(self) -> None:
        runtime, context, gateway = self._runtime_and_context("RUN-CANCEL-PUBLISH-V1")
        self.assertTrue(runtime.cancel_run(context.run_id))
        self.assertEqual(context.status, RuntimeStatus.CANCELLED)
        refs_before = tuple(context.execution_receipt_refs)

        with self.assertRaisesRegex(RuntimeError, "RUN_CANCELLED_BY_OPERATOR"):
            runtime.request_publish_action(context, platform="linkedin")

        self.assertEqual(gateway.calls, [], "cancelled run must dispatch zero publishing requests")
        self.assertEqual(context.status, RuntimeStatus.CANCELLED)
        self.assertEqual(tuple(context.execution_receipt_refs), refs_before)

    def test_live_run_publish_control_still_dispatches(self) -> None:
        runtime, context, gateway = self._runtime_and_context("RUN-LIVE-PUBLISH-V1")

        receipt = runtime.request_publish_action(context, platform="linkedin")

        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(gateway.calls[0].capability_id, "social_publishing")
        self.assertEqual(context.status, RuntimeStatus.RUNNING)
        self.assertIn(receipt.execution_id, context.execution_receipt_refs)


if __name__ == "__main__":
    unittest.main()
