"""Truthfulness contract for built-in Creative media simulation adapters."""

import unittest

from tools.adapters import MediaCreationAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode


MEDIA_CAPABILITIES = (
    "image_generation",
    "image_editing",
    "video_generation",
    "video_editing_rendering",
)


class CreativeMediaMockTruthfulnessV1Tests(unittest.TestCase):
    def test_builtin_media_capabilities_disclose_mock_only_availability(self) -> None:
        registry = CapabilityRegistry()

        for capability_id in MEDIA_CAPABILITIES:
            with self.subTest(capability_id=capability_id):
                descriptor = registry.get_capability(capability_id)
                self.assertIsNotNone(descriptor)
                self.assertEqual(descriptor.availability, "MOCK_ONLY")

    def test_mock_media_adapter_never_claims_a_real_render(self) -> None:
        for capability_id in MEDIA_CAPABILITIES:
            adapter_name = {
                "image_generation": "image_gen_adapter",
                "image_editing": "image_edit_adapter",
                "video_generation": "video_gen_adapter",
                "video_editing_rendering": "video_edit_adapter",
            }[capability_id]
            with self.subTest(capability_id=capability_id):
                result = MediaCreationAdapter(name=adapter_name).execute(
                    capability_id,
                    {"prompt": "provider-neutral campaign media"},
                    run_id="RUN-MEDIA-TRUTH-V1",
                    business_id="BIZ-MEDIA-TRUTH-V1",
                    project_id="PROJ-MEDIA-TRUTH-V1",
                )

                self.assertTrue(result.success)
                self.assertEqual(result.execution_mode, ExecutionMode.MOCK)
                self.assertEqual(result.data["status"], "SIMULATED")
                self.assertTrue(result.data["is_simulated"])
                self.assertNotIn("RENDERED", str(result.data).upper())
                self.assertTrue(result.artifact_refs)
                self.assertTrue(
                    all(ref.startswith("mock-art-") for ref in result.artifact_refs)
                )


if __name__ == "__main__":
    unittest.main()
