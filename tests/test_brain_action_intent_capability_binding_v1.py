import unittest

import brain.action_policy as action_policy
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

    def _evaluate(self, intent, binding):
        evaluator = getattr(
            action_policy,
            "evaluate_action_intent_capability_binding",
            None,
        )
        self.assertIsNotNone(
            evaluator,
            "STILL_PRESENT: Brain has no semantic ActionIntent-to-capability binding evaluator.",
        )
        return evaluator(intent, binding)

    def _disposition(self, name):
        enum_type = getattr(action_policy, "CapabilityBindingDisposition", None)
        self.assertIsNotNone(
            enum_type,
            "STILL_PRESENT: Brain has no non-execution capability binding disposition.",
        )
        return getattr(enum_type, name)

    def test_matching_trusted_capability_binding_is_bound_not_execution_authorized(self):
        result = self._evaluate(self._intent(), self._binding())
        self.assertEqual(result.disposition, self._disposition("BOUND"))
        self.assertEqual(result.intent_id, "INTENT-1")
        self.assertEqual(result.capability_id, "web_search")
        self.assertEqual(result.semantic_need, "MARKET_RESEARCH")
        self.assertFalse(hasattr(result, "authorization"))

    def test_wrong_semantic_capability_cannot_satisfy_action_intent(self):
        result = self._evaluate(
            self._intent(capability_need="MARKET_RESEARCH"),
            self._binding(semantic_needs=("IMAGE_GENERATE",)),
        )
        self.assertEqual(result.disposition, self._disposition("REJECTED"))
        self.assertIn("CAPABILITY_NEED_MISMATCH", result.reason)

    def test_cross_agent_capability_binding_is_rejected(self):
        result = self._evaluate(
            self._intent(owner=BrainAgentId.INTELLIGENCE),
            self._binding(supported_agents=("CREATIVE", "CMO")),
        )
        self.assertEqual(result.disposition, self._disposition("REJECTED"))
        self.assertIn("CAPABILITY_AGENT_MISMATCH", result.reason)

    def test_all_agent_marker_can_bind_any_permanent_agent(self):
        result = self._evaluate(
            self._intent(owner=BrainAgentId.PERFORMANCE),
            self._binding(supported_agents=("ALL",)),
        )
        self.assertEqual(result.disposition, self._disposition("BOUND"))

    def test_raw_caller_dictionary_cannot_substitute_for_trusted_binding(self):
        evaluator = getattr(
            action_policy,
            "evaluate_action_intent_capability_binding",
            None,
        )
        self.assertIsNotNone(
            evaluator,
            "STILL_PRESENT: Brain has no semantic ActionIntent-to-capability binding evaluator.",
        )
        with self.assertRaisesRegex(ValueError, "TrustedCapabilityBinding"):
            evaluator(
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

    def test_supported_agent_mapping_is_bound_into_capability_fingerprint(self):
        capability = CapabilityRegistry().get_capability("web_search")
        self.assertIsNotNone(capability)
        original = capability.fingerprint()
        capability.supported_agents = ["creative"]
        self.assertNotEqual(original, capability.fingerprint())


if __name__ == "__main__":
    unittest.main()
