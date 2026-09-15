"""Regression coverage for canonical Content model-policy migration.

Historical STRATEGIST/STRATEGY inputs are accepted only as compatibility aliases.
Canonical model-policy state and outputs must use CONTENT and must not reintroduce
a sixth permanent ASI identity.
"""

from __future__ import annotations

import unittest

from integrations.models.registry import AgentId, ModelPolicy, ModelTarget, normalize_agent_id


class TestModelPolicyContentMigration(unittest.TestCase):
    def test_canonical_agent_id_set_contains_content_and_no_strategist(self) -> None:
        self.assertEqual(
            {agent.value for agent in AgentId},
            {"CMO", "INTELLIGENCE", "CONTENT", "CREATIVE", "PERFORMANCE"},
        )
        self.assertNotIn("STRATEGIST", AgentId.__members__)

    def test_legacy_strategist_identifiers_normalize_to_content(self) -> None:
        self.assertEqual(normalize_agent_id("STRATEGIST"), AgentId.CONTENT.value)
        self.assertEqual(normalize_agent_id("strategist"), AgentId.CONTENT.value)
        self.assertEqual(normalize_agent_id("STRATEGY"), AgentId.CONTENT.value)
        self.assertEqual(normalize_agent_id("CONTENT"), AgentId.CONTENT.value)

    def test_model_policy_migrates_legacy_strategist_override_to_content(self) -> None:
        legacy_target = ModelTarget(provider_id="legacy_provider", model_id="legacy-model")
        policy = ModelPolicy(agent_overrides={"STRATEGIST": legacy_target})

        self.assertEqual(set(policy.agent_overrides), {AgentId.CONTENT.value})
        self.assertNotIn("STRATEGIST", policy.agent_overrides)
        self.assertIs(policy.agent_overrides[AgentId.CONTENT.value], legacy_target)
        self.assertEqual(policy.resolve_target_for_agent("CONTENT"), legacy_target)
        self.assertEqual(policy.resolve_target_for_agent("STRATEGIST"), legacy_target)

    def test_content_override_stays_canonical_in_serialized_policy_state(self) -> None:
        content_target = ModelTarget(provider_id="content_provider", model_id="content-model")
        policy = ModelPolicy(agent_overrides={"CONTENT": content_target})

        dumped = policy.model_dump()
        self.assertEqual(set(dumped["agent_overrides"]), {AgentId.CONTENT.value})
        self.assertNotIn("STRATEGIST", dumped["agent_overrides"])
        self.assertEqual(policy.get_target_for_agent("CONTENT"), content_target)


if __name__ == "__main__":
    unittest.main()
