"""Adversarial truthfulness contract for built-in creative media capabilities."""

from __future__ import annotations

import unittest

from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class MediaMockTruthfulnessAdversarialV1Tests(unittest.TestCase):
    CAPABILITY_IDS = (
        "image_generation",
        "image_editing",
        "video_generation",
        "video_editing_rendering",
    )

    def test_mock_media_never_advertises_production_availability(self) -> None:
        registry = CapabilityRegistry()
        for capability_id in self.CAPABILITY_IDS:
            with self.subTest(capability_id=capability_id):
                descriptor = registry.get_capability(capability_id)
                self.assertIsNotNone(descriptor)
                assert descriptor is not None
                self.assertEqual(
                    descriptor.availability,
                    "MOCK_ONLY",
                    "A synthetic local adapter must not advertise production availability.",
                )

    def test_mock_media_never_reports_real_rendering(self) -> None:
        gateway = ToolGateway(
            capability_registry=CapabilityRegistry(),
            policy_engine=PolicyEngine(),
            receipt_repository=ExecutionReceiptRepository(),
        )
        for capability_id in self.CAPABILITY_IDS:
            with self.subTest(capability_id=capability_id):
                receipt = gateway.execute(
                    ToolRequest(
                        run_id=f"RUN-MEDIA-MOCK-{capability_id.upper()}",
                        agent_id="creative",
                        capability_id=capability_id,
                        parameters={"prompt": "truthful media probe"},
                    )
                )

                self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
                self.assertEqual(receipt.execution_mode, ExecutionMode.MOCK)
                self.assertEqual(receipt.data["status"], "MOCK_RENDERED")
                self.assertTrue(receipt.data["simulated"])
                self.assertFalse(receipt.data["provider_network_called"])
                self.assertFalse(receipt.data["external_side_effect"])
                self.assertTrue(receipt.data["asset_id"].startswith("mock-art-"))


if __name__ == "__main__":
    unittest.main()
