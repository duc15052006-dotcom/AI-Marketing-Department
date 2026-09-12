import unittest

from brain.action_policy import (
    CapabilityBindingDisposition,
    TrustedCapabilityBinding,
    evaluate_action_intent_capability_binding,
)
from brain.contracts import ActionIntent, BrainAgentId
from tools.capabilities import CapabilityRegistry


class BrainCreativeSemanticCapabilityBindingV1Tests(unittest.TestCase):
    EXPECTED = {
        "text_generation_support": "TEXT_CREATION",
        "image_generation": "IMAGE_GENERATION",
        "image_editing": "IMAGE_EDITING",
        "video_generation": "VIDEO_GENERATION",
        "video_editing_rendering": "VIDEO_EDITING",
    }

    def setUp(self):
        self.registry = CapabilityRegistry()

    def _binding(self, capability_id: str) -> TrustedCapabilityBinding:
        descriptor = self.registry.get_capability(capability_id)
        self.assertIsNotNone(descriptor)
        return TrustedCapabilityBinding(
            capability_id=descriptor.capability_id,
            semantic_needs=tuple(descriptor.semantic_needs),
            supported_agents=tuple(descriptor.supported_agents),
        )

    @staticmethod
    def _intent(capability_need: str) -> ActionIntent:
        return ActionIntent(
            intent_id=f"INTENT-{capability_need}",
            goal_id="GOAL-CREATIVE-001",
            owner_agent=BrainAgentId.CREATIVE,
            purpose="Produce the exact requested creative modality.",
            capability_need=capability_need,
            expected_observation="An auditable creative artifact in the requested modality.",
            evidence_required=False,
        )

    def test_each_creative_capability_declares_and_binds_its_exact_semantic_need(self):
        for capability_id, semantic_need in self.EXPECTED.items():
            with self.subTest(capability_id=capability_id):
                descriptor = self.registry.get_capability(capability_id)
                self.assertEqual([semantic_need], descriptor.semantic_needs)
                assessment = evaluate_action_intent_capability_binding(
                    self._intent(semantic_need),
                    self._binding(capability_id),
                )
                self.assertEqual(
                    CapabilityBindingDisposition.BOUND,
                    assessment.disposition,
                )

    def test_text_creation_cannot_bind_image_generation(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("TEXT_CREATION"),
            self._binding("image_generation"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_image_generation_cannot_bind_image_editing(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("IMAGE_GENERATION"),
            self._binding("image_editing"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_video_generation_cannot_bind_video_editing(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("VIDEO_GENERATION"),
            self._binding("video_editing_rendering"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_cross_modality_intent_cannot_bind_wrong_creative_capability(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("VIDEO_GENERATION"),
            self._binding("image_generation"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)


if __name__ == "__main__":
    unittest.main()
