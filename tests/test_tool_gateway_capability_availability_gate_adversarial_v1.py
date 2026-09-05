"""Adversarial regression for ToolGateway capability availability gating.

Provider/media control-plane state must be authoritative. A capability marked
UNAVAILABLE must fail closed before provider dispatch, while DEGRADED remains
routable so a configured degraded provider can still serve requests.
"""

import unittest

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class _RecordingVideoAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.calls = []

    @property
    def adapter_name(self) -> str:
        return "video_gen_adapter"

    def execute(
        self,
        capability_id,
        parameters,
        timeout_seconds=30.0,
        *,
        run_id="",
        business_id="",
        project_id="",
    ):
        self.calls.append(
            {
                "capability_id": capability_id,
                "run_id": run_id,
                "parameters": dict(parameters),
            }
        )
        return AdapterResult(
            success=True,
            data={"provider_job_id": "job-should-not-run-when-unavailable"},
            execution_mode=ExecutionMode.MOCK,
        )


class TestToolGatewayCapabilityAvailabilityGateAdversarialV1(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.gateway = ToolGateway(capability_registry=self.registry)
        self.adapter = _RecordingVideoAdapter()
        self.gateway.register_adapter(self.adapter)
        self.capability = self.registry.get_capability("video_generation")
        self.assertIsNotNone(self.capability)

    def _execute(self):
        return self.gateway.execute(
            ToolRequest(
                run_id="RUN-VIDEO-AVAILABILITY-001",
                agent_id="creative",
                capability_id="video_generation",
                parameters={"prompt": "provider-neutral campaign video"},
            )
        )

    def test_unavailable_video_capability_fails_closed_before_provider_dispatch(self):
        self.capability.availability = "UNAVAILABLE"

        receipt = self._execute()

        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "CAPABILITY_UNAVAILABLE")
        self.assertEqual(self.adapter.calls, [])

    def test_degraded_video_capability_remains_dispatchable(self):
        self.capability.availability = "DEGRADED"

        receipt = self._execute()

        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(len(self.adapter.calls), 1)


if __name__ == "__main__":
    unittest.main()
