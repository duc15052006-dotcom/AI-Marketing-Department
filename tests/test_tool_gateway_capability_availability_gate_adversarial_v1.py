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

    def _set_availability(self, availability):
        descriptor = self.registry.get_capability("video_generation")
        self.assertIsNotNone(descriptor)
        descriptor.availability = availability
        self.registry.register_capability(descriptor)

    def test_unavailable_video_capability_fails_closed_before_provider_dispatch(self):
        self._set_availability("UNAVAILABLE")

        receipt = self._execute()

        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "CAPABILITY_UNAVAILABLE")
        self.assertEqual(self.adapter.calls, [])

    def test_degraded_video_capability_remains_dispatchable(self):
        self._set_availability("DEGRADED")

        receipt = self._execute()

        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(len(self.adapter.calls), 1)

    def test_unrecognized_agent_precedes_unavailable_control_plane_state(self):
        self._set_availability("UNAVAILABLE")

        receipt = self.gateway.execute(
            ToolRequest(
                run_id="RUN-VIDEO-AVAILABILITY-002",
                agent_id="agent_6",
                capability_id="video_generation",
                parameters={"prompt": "must never dispatch"},
            )
        )

        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "UNRECOGNIZED_AGENT")
        self.assertEqual(self.adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
