import unittest

from brain.action_policy import (
    ActionDisposition,
    TrustedCapabilityBinding,
    authorize_action_intent_capability,
)
from brain.contracts import ActionIntent, BrainAgentId


class TestBrainActionIntentCapabilityBindingV1(unittest.TestCase):
    def _intent(
        self,
        *,
        capability_need="MARKET_RESEARCH",
        owner=BrainAgentId.INTELLIGENCE,
    ):
        return ActionIntent(
            intent_id="INTENT-1",
            goal_id="GOAL-1",
            owner_agent=owner,
            purpose="Collect authoritative market evidence",
            capability_need=capability_need,
            expected_observation="Grounded market observations",
            decision_id="DECISION-1",
            evidence_required=True,
        )

    def _binding(
        self,
        *,
        semantic_needs=("MARKET_RESEARCH",),
        supported_agents=("INTELLIGENCE", "STRATEGIST", "CMO"),
    ):
        return TrustedCapabilityBinding(
            capability_id="web_search",
            semantic_needs=semantic_needs,
            supported_agents=supported_agents,
        )

    def test_matching_trusted_capability_binding_is_allowed(self):
        result = authorize_action_intent_capability(self._intent(), self._binding())
        self.assertEqual(result.disposition, ActionDisposition.ALLOW)
        self.assertEqual(result.intent_id, "INTENT-1")

    def test_wrong_semantic_capability_cannot_satisfy_action_intent(self):
        result = authorize_action_intent_capability(
            self._intent(capability_need="MARKET_RESEARCH"),
            self._binding(semantic_needs=("IMAGE_GENERATE",)),
        )
        self.assertEqual(result.disposition, ActionDisposition.BLOCK)
        self.assertIn("CAPABILITY_NEED_MISMATCH", result.reason)

    def test_cross_agent_capability_binding_is_rejected(self):
        result = authorize_action_intent_capability(
            self._intent(owner=BrainAgentId.INTELLIGENCE),
            self._binding(supported_agents=("CREATIVE", "CMO")),
        )
        self.assertEqual(result.disposition, ActionDisposition.BLOCK)
        self.assertIn("CAPABILITY_AGENT_MISMATCH", result.reason)

    def test_raw_caller_dictionary_cannot_substitute_for_trusted_binding(self):
        with self.assertRaisesRegex(ValueError, "TrustedCapabilityBinding"):
            authorize_action_intent_capability(
                self._intent(),
                {
                    "capability_id": "social_publishing",
                    "semantic_needs": ["MARKET_RESEARCH"],
                    "supported_agents": ["INTELLIGENCE"],
                },
            )


if __name__ == "__main__":
    unittest.main()
