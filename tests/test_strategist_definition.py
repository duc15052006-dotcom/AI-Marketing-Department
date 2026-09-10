"""Regression tests for the canonical Content migration.

The former Strategist ASI was removed from the permanent five-agent architecture.
These tests intentionally verify that no strategist DNA file is resurrected and that
Content owns the semantic/content responsibilities that replaced it.
"""

import unittest
from pathlib import Path

from tests.test_agent_manifests import parse_yaml_frontmatter


class TestContentMigrationDefinition(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent / ".agents" / "agents"
        self.strategist_path = root / "strategist" / "agent.md"
        self.content_path = root / "content" / "agent.md"
        self.assertFalse(
            self.strategist_path.exists(),
            "strategist/agent.md must not exist after canonical Content migration",
        )
        self.assertTrue(self.content_path.exists(), "content/agent.md does not exist")
        self.content = self.content_path.read_text(encoding="utf-8")
        self.frontmatter = parse_yaml_frontmatter(self.content)

    def test_content_frontmatter_is_canonical(self):
        self.assertEqual(self.frontmatter.get("name"), "content")
        self.assertIn("Content Strategy", self.frontmatter.get("description", ""))

    def test_content_identity_and_role_boundaries(self):
        self.assertIn("Content ASI", self.content)
        self.assertIn("five-agent AI Marketing Department", self.content)
        self.assertIn("convert verified market evidence and CMO-approved strategy", self.content)
        self.assertIn("You are **not** the CMO", self.content)
        self.assertIn("You are **not** Intelligence", self.content)
        self.assertIn("You are **not** Creative", self.content)
        self.assertIn("You are **not** Performance", self.content)

    def test_content_owns_semantic_layer(self):
        for capability in (
            "CONTENT_STRATEGY",
            "MESSAGE_ARCHITECTURE",
            "COPY_AND_SCRIPT",
            "EDITORIAL_PLANNING",
            "SEO_CONTENT_BRIEFING",
            "CHANNEL_CONTENT_ADAPTATION",
            "CONTENT_EXPERIMENT_HYPOTHESES",
        ):
            self.assertIn(capability, self.content)

    def test_content_preserves_epistemic_discipline(self):
        for state in ("OBSERVED / VERIFIED", "INFERRED", "HYPOTHESIS", "UNKNOWN"):
            self.assertIn(state, self.content)
        self.assertIn("Never turn an inference into a fact", self.content)
        self.assertIn("do not fill the gap with plausible prose", self.content)

    def test_content_message_copy_and_hook_system(self):
        self.assertIn("Message Architecture", self.content)
        self.assertIn("Copywriting System", self.content)
        self.assertIn("Hook rules", self.content)
        self.assertIn("AIDA", self.content)
        self.assertIn("PAS", self.content)
        self.assertIn("Hook–Value–Proof–CTA", self.content)

    def test_content_handoffs_preserve_five_agent_boundaries(self):
        self.assertIn("Market/customer/competitor research gaps -> **Intelligence**", self.content)
        self.assertIn("Positioning, GTM choices, major offer strategy, budget trade-offs -> **CMO**", self.content)
        self.assertIn("Visual concepts, storyboards, image/video production specs, multimedia generation -> **Creative**", self.content)
        self.assertIn("Paid campaign execution, analytics, attribution, KPI verification -> **Performance**", self.content)
        self.assertNotIn("Strategist ASI", self.content)


if __name__ == "__main__":
    unittest.main()
