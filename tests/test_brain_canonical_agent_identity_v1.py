"""Regression coverage for the five permanent Brain identities.

The product contract is exactly CMO, Intelligence, Content, Creative, and
Performance. ``STRATEGIST`` may only be accepted as a legacy serialized input;
it must never remain a canonical Brain identity or permanent agent package.
"""

from pathlib import Path
import unittest

from brain.contracts import BrainAgentId, GoalSpec
from integrations.models.registry import AgentId, ModelPolicy, ModelTarget, normalize_agent_id
from runtime.context import RuntimeStage
from runtime.progress import ProgressAgent, ProgressStage, runtime_stage_to_progress_stage


EXPECTED_CANONICAL_ROLES = {
    "CMO",
    "INTELLIGENCE",
    "CONTENT",
    "CREATIVE",
    "PERFORMANCE",
}


class TestCanonicalBrainAgentIdentityV1(unittest.TestCase):
    def test_brain_contract_exposes_exactly_the_five_product_roles(self):
        self.assertEqual(
            {role.value for role in BrainAgentId},
            EXPECTED_CANONICAL_ROLES,
        )
        self.assertFalse(
            hasattr(BrainAgentId, "STRATEGIST"),
            "STRATEGIST must not remain a canonical Brain enum member",
        )

    def test_permanent_agent_packages_match_canonical_roles(self):
        agents_dir = Path(__file__).resolve().parent.parent / ".agents" / "agents"
        discovered = {entry.name for entry in agents_dir.iterdir() if entry.is_dir()}
        self.assertEqual(
            discovered,
            {"cmo", "intelligence", "content", "creative", "performance"},
        )

    def test_legacy_strategist_input_is_normalized_to_content(self):
        goal = GoalSpec(
            goal_id="legacy-role-migration",
            objective="Preserve old serialized Brain state without preserving old identity",
            owner_agent="STRATEGIST",
        )
        self.assertIs(goal.owner_agent, BrainAgentId.CONTENT)
        self.assertEqual(goal.owner_agent.value, "CONTENT")

    def test_runtime_and_progress_legacy_stage_normalize_to_content(self):
        self.assertIs(RuntimeStage("STRATEGIST"), RuntimeStage.CONTENT)
        self.assertIs(ProgressStage("STRATEGIST"), ProgressStage.CONTENT)
        self.assertIs(ProgressAgent("STRATEGIST"), ProgressAgent.CONTENT)
        self.assertIs(runtime_stage_to_progress_stage("STRATEGIST"), ProgressStage.CONTENT)
        self.assertFalse(hasattr(RuntimeStage, "STRATEGIST"))
        self.assertFalse(hasattr(ProgressStage, "STRATEGIST"))
        self.assertFalse(hasattr(ProgressAgent, "STRATEGIST"))

    def test_model_policy_legacy_strategist_override_routes_to_content(self):
        target = ModelTarget(provider_id="xkiro", model_id="legacy-content-model")
        policy = ModelPolicy(agent_overrides={"STRATEGIST": target})
        self.assertEqual(normalize_agent_id("STRATEGIST"), AgentId.CONTENT.value)
        self.assertFalse(hasattr(AgentId, "STRATEGIST"))
        self.assertIn(AgentId.CONTENT.value, policy.agent_overrides)
        self.assertNotIn("STRATEGIST", policy.agent_overrides)
        self.assertEqual(
            policy.resolve_target_for_agent("content").model_id,
            "legacy-content-model",
        )

    def test_no_python_code_references_removed_strategist_enum_member(self):
        repo_root = Path(__file__).resolve().parent.parent
        forbidden = "BrainAgentId." + "STRATEGIST"
        offenders = []
        for path in repo_root.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            parts = set(path.parts)
            if {".venv", "venv", "site-packages"} & parts:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if forbidden in source:
                offenders.append(str(path.relative_to(repo_root)))
        self.assertEqual(
            offenders,
            [],
            "Removed canonical STRATEGIST enum is still referenced in: " + ", ".join(offenders),
        )

    def test_agent_manifests_do_not_depend_on_removed_strategist_package(self):
        repo_root = Path(__file__).resolve().parent.parent
        manifests = repo_root / ".agents" / "agents"
        forbidden = '"' + "strategist" + '"'
        offenders = []
        for path in manifests.glob("*/manifest.json"):
            if forbidden in path.read_text(encoding="utf-8").lower():
                offenders.append(str(path.relative_to(repo_root)))
        self.assertEqual(
            offenders,
            [],
            "Permanent agent manifests still reference removed strategist package: "
            + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
