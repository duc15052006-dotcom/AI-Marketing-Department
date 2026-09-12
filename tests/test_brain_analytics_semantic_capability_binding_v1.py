import unittest

from brain.action_policy import (
    CapabilityBindingDisposition,
    TrustedCapabilityBinding,
    evaluate_action_intent_capability_binding,
)
from brain.contracts import ActionIntent, BrainAgentId
from tools.capabilities import CapabilityRegistry


class BrainAnalyticsSemanticCapabilityBindingV1Tests(unittest.TestCase):
    EXPECTED = {
        "analytics_retrieval": "PERFORMANCE_TELEMETRY",
        "kpi_calculation": "KPI_COMPUTATION",
        "attribution_data_access": "ATTRIBUTION_EVIDENCE",
        "experiment_result_analysis": "EXPERIMENT_ANALYSIS",
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
    def _intent(
        capability_need: str,
        owner: BrainAgentId = BrainAgentId.PERFORMANCE,
    ) -> ActionIntent:
        return ActionIntent(
            intent_id=f"INTENT-{capability_need}-{owner.value}",
            goal_id="GOAL-ANALYTICS-001",
            owner_agent=owner,
            purpose="Use the exact analytical evidence or computation required by the goal.",
            capability_need=capability_need,
            expected_observation="Auditable analytical evidence or computation for the requested semantic need.",
            evidence_required=True,
        )

    def test_each_analytics_capability_declares_and_binds_its_exact_semantic_need(self):
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

    def test_performance_telemetry_cannot_bind_kpi_computation(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("PERFORMANCE_TELEMETRY"),
            self._binding("kpi_calculation"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_kpi_computation_cannot_bind_attribution_evidence(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("KPI_COMPUTATION"),
            self._binding("attribution_data_access"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_experiment_analysis_cannot_bind_telemetry_retrieval(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("EXPERIMENT_ANALYSIS"),
            self._binding("analytics_retrieval"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_attribution_semantics_preserve_supported_agent_authority(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("ATTRIBUTION_EVIDENCE", owner=BrainAgentId.CONTENT),
            self._binding("attribution_data_access"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)
        self.assertIn("AGENT_MISMATCH", assessment.reason)


if __name__ == "__main__":
    unittest.main()
