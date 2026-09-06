import unittest

import brain.action_policy as action_policy
from brain.action_policy import ActionDisposition
from brain.contracts import ActionIntent, BrainAgentId
from tools.capabilities import CapabilityRegistry


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
        binding_type = getattr(action_policy, "TrustedCapabilityBinding", None)
        self.assertIsNotNone(
            binding_type,
            "STILL_PRESENT: Brain has no TrustedCapabilityBinding authority contract.",
        )
        return binding_type(
            capability_id="web_search",
            semantic_needs=semantic_needs,
            supported_agents=supported_agents,
        )

    def _authorize(self, intent, binding):
        authorizer = getattr(action_policy, "authorize_action_intent_capability", None)
        self.assertIsNotNone(
            authorizer,
            "STILL_PRESENT: Brain has no semantic ActionIntent-to-capability authorizer.",
        )
        return authorizer(intent, binding)

    def test_matching_trusted_capability_binding_is_allowed(self):
        result = self._authorize(self._intent(), self._binding())
        self.assertEqual(result.disposition, ActionDisposition.ALLOW)
        self.assertEqual(result.intent_id, "INTENT-1")

    def test_wrong_semantic_capability_cannot_satisfy_action_intent(self):
        result = self._authorize(
            self._intent(capability_need="MARKET_RESEARCH"),
            self._binding(semantic_needs=("IMAGE_GENERATE",)),
        )
        self.assertEqual(result.disposition, ActionDisposition.BLOCK)
        self.assertIn("CAPABILITY_NEED_MISMATCH", result.reason)

    def test_cross_agent_capability_binding_is_rejected(self):
        result = self._authorize(
            self._intent(owner=BrainAgentId.INTELLIGENCE),
            self._binding(supported_agents=("CREATIVE", "CMO")),
        )
        self.assertEqual(result.disposition, ActionDisposition.BLOCK)
        self.assertIn("CAPABILITY_AGENT_MISMATCH", result.reason)

    def test_raw_caller_dictionary_cannot_substitute_for_trusted_binding(self):
        authorizer = getattr(action_policy, "authorize_action_intent_capability", None)
        self.assertIsNotNone(
            authorizer,
            "STILL_PRESENT: Brain has no semantic ActionIntent-to-capability authorizer.",
        )
        with self.assertRaisesRegex(ValueError, "TrustedCapabilityBinding"):
            authorizer(
                self._intent(),
                {
                    "capability_id": "social_publishing",
                    "semantic_needs": ["MARKET_RESEARCH"],
                    "supported_agents": ["INTELLIGENCE"],
                },
            )

    def test_registry_declares_market_research_semantics_for_web_search(self):
        capability = CapabilityRegistry().get_capability("web_search")
        self.assertIsNotNone(capability)
        self.assertTrue(
            hasattr(capability, "semantic_needs"),
            "STILL_PRESENT: trusted CapabilityDescriptor has no semantic_needs declaration.",
        )
        self.assertIn("MARKET_RESEARCH", capability.semantic_needs)

    def test_semantic_mapping_is_bound_into_capability_fingerprint(self):
        capability = CapabilityRegistry().get_capability("web_search")
        self.assertIsNotNone(capability)
        self.assertTrue(
            hasattr(capability, "semantic_needs"),
            "STILL_PRESENT: capability fingerprint cannot bind semantic mapping because semantic_needs is absent.",
        )
        original = capability.fingerprint()
        capability.semantic_needs = ["IMAGE_GENERATE"]
        self.assertNotEqual(original, capability.fingerprint())


if __name__ == "__main__":
    unittest.main()
