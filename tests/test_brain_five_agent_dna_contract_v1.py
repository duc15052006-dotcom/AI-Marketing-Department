"""Adversarial tests for the provider-neutral five-agent Brain DNA contract."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.agent_dna as agent_dna
from brain.agent_dna import (
    AgentDNAProfile,
    AgentFunction,
    EpistemicPosture,
    canonical_agent_profiles,
    get_agent_profile,
    resolve_permanent_agent,
)
from brain.contracts import BrainAgentId
from schemas.base import ValidationError


class FiveAgentDNAContractV1Tests(unittest.TestCase):
    def test_registry_contains_exactly_the_five_brain_agents(self) -> None:
        profiles = canonical_agent_profiles()
        self.assertEqual(len(profiles), 5)
        self.assertEqual(
            {profile.agent_id for profile in profiles},
            set(BrainAgentId),
        )

    def test_each_agent_has_one_distinct_canonical_marketing_function(self) -> None:
        expected = {
            BrainAgentId.CMO: AgentFunction.EXECUTIVE_ORCHESTRATION,
            BrainAgentId.INTELLIGENCE: AgentFunction.MARKET_INTELLIGENCE,
            BrainAgentId.STRATEGIST: AgentFunction.STRATEGY_AND_GROWTH,
            BrainAgentId.CREATIVE: AgentFunction.CREATIVE_COMMUNICATION,
            BrainAgentId.PERFORMANCE: AgentFunction.PERFORMANCE_AND_MEASUREMENT,
        }
        actual = {profile.agent_id: profile.function for profile in canonical_agent_profiles()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(set(actual.values())), 5)

    def test_only_cmo_has_commercial_signoff_but_no_agent_has_live_execution_authority(self) -> None:
        profiles = canonical_agent_profiles()
        signoff_agents = {
            profile.agent_id for profile in profiles if profile.commercial_signoff_authority
        }
        self.assertEqual(signoff_agents, {BrainAgentId.CMO})
        self.assertTrue(all(not profile.live_execution_authority for profile in profiles))

    def test_non_cmo_cannot_self_escalate_to_commercial_signoff(self) -> None:
        base = get_agent_profile(BrainAgentId.INTELLIGENCE).model_dump()
        base["commercial_signoff_authority"] = True
        with self.assertRaises(ValidationError):
            AgentDNAProfile(**base)

    def test_no_profile_can_self_grant_live_execution_authority(self) -> None:
        base = get_agent_profile(BrainAgentId.CMO).model_dump()
        base["live_execution_authority"] = True
        with self.assertRaises(ValidationError):
            AgentDNAProfile(**base)

    def test_agent_function_identity_cannot_be_swapped(self) -> None:
        base = get_agent_profile(BrainAgentId.CREATIVE).model_dump()
        base["function"] = AgentFunction.MARKET_INTELLIGENCE
        with self.assertRaises(ValidationError):
            AgentDNAProfile(**base)

    def test_cmo_boundary_is_orchestration_not_specialist_execution(self) -> None:
        profile = get_agent_profile(BrainAgentId.CMO)
        self.assertTrue(
            {
                "TASK_DECOMPOSITION",
                "COMMERCIAL_GOVERNANCE",
                "SPECIALIST_QUALITY_REVIEW",
            }.issubset(set(profile.owned_responsibilities))
        )
        self.assertTrue(
            {
                "PRIMARY_MARKET_RESEARCH",
                "PRIMARY_CREATIVE_PRODUCTION",
                "PRIMARY_PERFORMANCE_ANALYSIS",
                "LIVE_EXECUTION",
            }.issubset(set(profile.forbidden_authorities))
        )

    def test_intelligence_owns_evidence_not_strategy_or_signoff(self) -> None:
        profile = get_agent_profile(BrainAgentId.INTELLIGENCE)
        self.assertTrue(
            {"EVIDENCE_DISCOVERY", "SOURCE_VERIFICATION", "UNCERTAINTY_REDUCTION"}.issubset(
                set(profile.owned_responsibilities)
            )
        )
        self.assertTrue(
            {
                "FINAL_COMMERCIAL_SIGNOFF",
                "PRIMARY_STRATEGY_FORMULATION",
                "PRIMARY_CREATIVE_PRODUCTION",
                "LIVE_EXECUTION",
            }.issubset(set(profile.forbidden_authorities))
        )

    def test_strategist_owns_choices_tradeoffs_and_hypotheses_not_primary_research(self) -> None:
        profile = get_agent_profile(BrainAgentId.STRATEGIST)
        self.assertTrue(
            {
                "SEGMENTATION_TARGETING_POSITIONING",
                "STRATEGIC_TRADEOFFS",
                "HYPOTHESIS_DESIGN",
            }.issubset(set(profile.owned_responsibilities))
        )
        self.assertIn("PRIMARY_MARKET_RESEARCH", profile.forbidden_authorities)
        self.assertIn("PRIMARY_CREATIVE_PRODUCTION", profile.forbidden_authorities)
        self.assertIn("PRIMARY_PERFORMANCE_ANALYSIS", profile.forbidden_authorities)

    def test_creative_owns_message_and_asset_specification_without_fact_invention_authority(self) -> None:
        profile = get_agent_profile(BrainAgentId.CREATIVE)
        self.assertTrue(
            {
                "CONCEPT_DEVELOPMENT",
                "COPY_AND_SCRIPT",
                "CREATIVE_PRODUCTION_SPECIFICATION",
            }.issubset(set(profile.owned_responsibilities))
        )
        self.assertIn("INVENT_PRODUCT_OR_EVIDENCE_FACTS", profile.forbidden_authorities)
        self.assertIn("FINAL_COMMERCIAL_SIGNOFF", profile.forbidden_authorities)
        self.assertIn("PRIMARY_PERFORMANCE_ANALYSIS", profile.forbidden_authorities)

    def test_performance_owns_measurement_and_learning_without_spend_authority(self) -> None:
        profile = get_agent_profile(BrainAgentId.PERFORMANCE)
        self.assertTrue(
            {
                "MEASUREMENT_VALIDATION",
                "FUNNEL_DIAGNOSIS",
                "EXPERIMENT_ANALYSIS",
                "LEARNING_EXTRACTION",
            }.issubset(set(profile.owned_responsibilities))
        )
        self.assertIn("FINAL_COMMERCIAL_SIGNOFF", profile.forbidden_authorities)
        self.assertIn("LIVE_EXECUTION", profile.forbidden_authorities)

    def test_epistemic_postures_are_role_specific(self) -> None:
        expected = {
            BrainAgentId.CMO: EpistemicPosture.EVIDENCE_GOVERNANCE,
            BrainAgentId.INTELLIGENCE: EpistemicPosture.EVIDENCE_DISCOVERY,
            BrainAgentId.STRATEGIST: EpistemicPosture.EVIDENCE_DEPENDENT_STRATEGY,
            BrainAgentId.CREATIVE: EpistemicPosture.EVIDENCE_DEPENDENT_CREATION,
            BrainAgentId.PERFORMANCE: EpistemicPosture.EMPIRICAL_MEASUREMENT,
        }
        self.assertEqual(
            {profile.agent_id: profile.epistemic_posture for profile in canonical_agent_profiles()},
            expected,
        )

    def test_primary_handoffs_reference_only_existing_peers_and_never_self(self) -> None:
        valid = set(BrainAgentId)
        for profile in canonical_agent_profiles():
            self.assertTrue(set(profile.primary_handoff_targets).issubset(valid))
            self.assertNotIn(profile.agent_id, profile.primary_handoff_targets)

    def test_core_marketing_feedback_loop_is_explicit_without_creating_agent_six(self) -> None:
        cmo = get_agent_profile(BrainAgentId.CMO)
        intelligence = get_agent_profile(BrainAgentId.INTELLIGENCE)
        strategist = get_agent_profile(BrainAgentId.STRATEGIST)
        creative = get_agent_profile(BrainAgentId.CREATIVE)
        performance = get_agent_profile(BrainAgentId.PERFORMANCE)

        self.assertTrue(
            {
                BrainAgentId.INTELLIGENCE,
                BrainAgentId.STRATEGIST,
                BrainAgentId.CREATIVE,
                BrainAgentId.PERFORMANCE,
            }.issubset(set(cmo.primary_handoff_targets))
        )
        self.assertIn(BrainAgentId.STRATEGIST, intelligence.primary_handoff_targets)
        self.assertIn(BrainAgentId.CREATIVE, strategist.primary_handoff_targets)
        self.assertIn(BrainAgentId.PERFORMANCE, creative.primary_handoff_targets)
        self.assertIn(BrainAgentId.CMO, performance.primary_handoff_targets)

    def test_registry_access_returns_copies_not_mutable_policy_authority(self) -> None:
        first = get_agent_profile(BrainAgentId.CMO)
        first.owned_responsibilities.append("INJECTED_AUTHORITY")
        second = get_agent_profile(BrainAgentId.CMO)
        self.assertNotIn("INJECTED_AUTHORITY", second.owned_responsibilities)

        collection = canonical_agent_profiles()
        collection.pop()
        self.assertEqual(len(canonical_agent_profiles()), 5)

    def test_unknown_permanent_agent_is_rejected_instead_of_promoted(self) -> None:
        self.assertEqual(resolve_permanent_agent("cmo"), BrainAgentId.CMO)
        self.assertEqual(resolve_permanent_agent(" Intelligence "), BrainAgentId.INTELLIGENCE)
        for invalid in ("affiliate_manager", "research_specialist", "agent_6", ""):
            with self.assertRaises(ValidationError):
                resolve_permanent_agent(invalid)

    def test_profile_semantic_tags_are_unique_upper_snake_and_non_overlapping(self) -> None:
        for profile in canonical_agent_profiles():
            self.assertEqual(len(profile.owned_responsibilities), len(set(profile.owned_responsibilities)))
            self.assertEqual(len(profile.forbidden_authorities), len(set(profile.forbidden_authorities)))
            self.assertFalse(set(profile.owned_responsibilities) & set(profile.forbidden_authorities))
            for tag in [*profile.owned_responsibilities, *profile.forbidden_authorities]:
                self.assertEqual(tag, tag.upper())
                self.assertNotIn(" ", tag)

    def test_agent_dna_contract_has_no_body_or_provider_dependency(self) -> None:
        source = inspect.getsource(agent_dna)
        tree = ast.parse(source)
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "knowledge",
            "memory",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

        serialized = str([p.model_dump() for p in canonical_agent_profiles()]).lower()
        for forbidden in (
            "provider_id",
            "model_id",
            "openai",
            "astra",
            "gemini",
            "claude",
            "tool_id",
            "connector_id",
            "queue_status",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
