import unittest

from brain.action_policy import (
    CapabilityBindingDisposition,
    TrustedCapabilityBinding,
    evaluate_action_intent_capability_binding,
)
from brain.contracts import ActionIntent, BrainAgentId
from tools.capabilities import CapabilityRegistry


class BrainFileDataSemanticCapabilityBindingV1Tests(unittest.TestCase):
    EXPECTED = {
        "file_read": "WORKSPACE_READ",
        "file_write": "WORKSPACE_WRITE",
        "structured_storage_query": "STRUCTURED_DATA_QUERY",
        "data_export": "ARTIFACT_EXPORT",
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
        owner: BrainAgentId = BrainAgentId.CMO,
    ) -> ActionIntent:
        return ActionIntent(
            intent_id=f"INTENT-{capability_need}-{owner.value}",
            goal_id="GOAL-FILE-DATA-001",
            owner_agent=owner,
            purpose="Perform only the requested local file/data operation.",
            capability_need=capability_need,
            expected_observation="Auditable local file/data result for the exact semantic need.",
            evidence_required=False,
        )

    def test_each_file_data_capability_declares_and_binds_exact_semantic_need(self):
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

    def test_workspace_read_cannot_bind_workspace_write(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("WORKSPACE_READ"),
            self._binding("file_write"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_structured_query_cannot_bind_plain_file_read(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("STRUCTURED_DATA_QUERY"),
            self._binding("file_read"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_artifact_export_cannot_bind_workspace_write(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("ARTIFACT_EXPORT"),
            self._binding("file_write"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)

    def test_file_write_semantics_preserve_supported_agent_authority(self):
        assessment = evaluate_action_intent_capability_binding(
            self._intent("WORKSPACE_WRITE", owner=BrainAgentId.STRATEGIST),
            self._binding("file_write"),
        )
        self.assertEqual(CapabilityBindingDisposition.REJECTED, assessment.disposition)
        self.assertIn("AGENT_MISMATCH", assessment.reason)


if __name__ == "__main__":
    unittest.main()
