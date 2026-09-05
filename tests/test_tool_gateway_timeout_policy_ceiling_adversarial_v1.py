"""Adversarial regression for ToolGateway timeout policy ceiling.

A caller may request a *shorter* execution deadline, but must never be able to
extend a capability's declared timeout policy.  The capability policy is the
safety ceiling; ToolRequest.timeout_seconds is only a narrowing override.
"""

import unittest

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class _RecordingSearchAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.timeouts = []

    @property
    def adapter_name(self) -> str:
        return "search_adapter"

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
        self.timeouts.append(timeout_seconds)
        return AdapterResult(
            success=True,
            data={"ok": True},
            execution_mode=ExecutionMode.MOCK,
        )


class TestToolGatewayTimeoutPolicyCeilingAdversarialV1(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.gateway = ToolGateway(capability_registry=self.registry)
        self.adapter = _RecordingSearchAdapter()
        self.gateway.register_adapter(self.adapter)
        self.capability = self.registry.get_capability("web_search")
        self.assertIsNotNone(self.capability)
        self.assertEqual(self.capability.timeout_policy, 15.0)

    def _execute(self, requested_timeout):
        return self.gateway.execute(
            ToolRequest(
                run_id="RUN-TIMEOUT-CEILING-001",
                agent_id="intelligence",
                capability_id="web_search",
                parameters={"query": "timeout policy ceiling regression"},
                timeout_seconds=requested_timeout,
            )
        )

    def test_request_cannot_extend_capability_timeout_policy(self):
        receipt = self._execute(600.0)

        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(self.adapter.timeouts, [15.0])

    def test_request_can_narrow_capability_timeout_policy(self):
        receipt = self._execute(2.0)

        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(self.adapter.timeouts, [2.0])


if __name__ == "__main__":
    unittest.main()
