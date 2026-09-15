import unittest

from brain.action_policy import (
    CapabilityBindingDisposition,
    TrustedCapabilityBinding,
    evaluate_action_intent_capability_binding,
)
from brain.contracts import ActionIntent, BrainAgentId
from tools.capabilities import CapabilityRegistry


class BrainPublishSemanticCapabilityBindingV1Tests(unittest.TestCase):
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
            goal_id="GOAL-PUBLISH-001",
            owner_agent=BrainAgentId.CMO,
            purpose="Execute the exact approved external marketing action.",
            capability_need=capability_need,
            expected_observation="An auditable execution receipt for the requested action.",
            evidence_required=False,
        )

    def test_social_publishing_binds_only_content_publishing_semantics(self):
        descriptor = self.registry.get_capability("social_publishing")
        self.assertIn("CONTENT_PUBLISHING", descriptor.semantic_needs)

        assessment = evaluate_action_intent_capability_binding(
            self._intent("CONTENT_PUBLISHING"),
            self._binding("social_publishing"),
        )
        self.assertEqual(CapabilityBindingDisposition.BOUND, assessment.disposition)

        wrong = evaluate_action_intent_capability_binding(
            self._intent("CAMPAIGN_OPERATIONS"),
            self._binding("social_publishing"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, wrong.disposition)

    def test_content_scheduling_binds_content_publishing_semantics(self):
        descriptor = self.registry.get_capability("content_scheduling")
        self.assertIn("CONTENT_PUBLISHING", descriptor.semantic_needs)

        assessment = evaluate_action_intent_capability_binding(
            self._intent("CONTENT_PUBLISHING"),
            self._binding("content_scheduling"),
        )
        self.assertEqual(CapabilityBindingDisposition.BOUND, assessment.disposition)

    def test_platform_operations_uses_distinct_campaign_operations_semantics(self):
        descriptor = self.registry.get_capability("platform_operations")
        self.assertIn("CAMPAIGN_OPERATIONS", descriptor.semantic_needs)
        self.assertNotIn("CONTENT_PUBLISHING", descriptor.semantic_needs)

        assessment = evaluate_action_intent_capability_binding(
            self._intent("CAMPAIGN_OPERATIONS"),
            self._binding("platform_operations"),
        )
        self.assertEqual(CapabilityBindingDisposition.BOUND, assessment.disposition)

        wrong = evaluate_action_intent_capability_binding(
            self._intent("CONTENT_PUBLISHING"),
            self._binding("platform_operations"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, wrong.disposition)


if __name__ == "__main__":
    unittest.main()
