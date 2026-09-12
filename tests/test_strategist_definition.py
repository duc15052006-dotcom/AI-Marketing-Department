"""Regression tests for the canonical Content migration.

The former Strategist ASI was removed from the permanent five-agent architecture.
These tests intentionally verify that no strategist DNA file is resurrected, that
Content owns the semantic/content responsibilities that replaced it, that CMO owns
executive strategy, and that historical Strategist surfaces cannot be mistaken for
current authority.
"""

import unittest
from pathlib import Path

from tests.test_agent_manifests import parse_yaml_frontmatter


class TestContentMigrationDefinition(unittest.TestCase):
    def setUp(self):
        repo_root = Path(__file__).resolve().parent.parent
        root = repo_root / ".agents" / "agents"
        self.strategist_path = root / "strategist" / "agent.md"
        self.content_path = root / "content" / "agent.md"
        self.legacy_strategist_evaluation_path = repo_root / "STRATEGIST_EVALUATION.md"
        self.cmo_evaluation_path = repo_root / "CMO_EVALUATION.md"
        self.content_evaluation_path = repo_root / "CONTENT_EVALUATION.md"
        self.source_of_truth_path = repo_root / "SOURCE_OF_TRUTH.md"
        self.architecture_path = repo_root / "ARCHITECTURE.md"
        self.agent_protocol_path = repo_root / "AGENT_PROTOCOL.md"
        self.security_model_path = repo_root / "SECURITY_MODEL.md"
        self.ui_permission_model_path = repo_root / "UI_PERMISSION_MODEL.md"
        self.roadmap_path = repo_root / "ROADMAP.md"
        self.creative_engine_path = repo_root / "CREATIVE_ENGINE.md"
        self.assertFalse(
            self.strategist_path.exists(),
            "strategist/agent.md must not exist after canonical Content migration",
        )
        self.assertTrue(self.content_path.exists(), "content/agent.md does not exist")
        for required_path in (
            self.legacy_strategist_evaluation_path,
            self.cmo_evaluation_path,
            self.content_evaluation_path,
            self.source_of_truth_path,
            self.architecture_path,
            self.agent_protocol_path,
            self.security_model_path,
            self.ui_permission_model_path,
            self.roadmap_path,
            self.creative_engine_path,
        ):
            self.assertTrue(required_path.exists(), f"required canonical/migration document missing: {required_path.name}")
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
        self.assertIn("Do not fill the gap with plausible prose", self.content)

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

    def test_legacy_strategist_evaluation_is_non_authoritative(self):
        legacy = self.legacy_strategist_evaluation_path.read_text(encoding="utf-8")
        self.assertIn("LEGACY / NON-AUTHORITATIVE", legacy)
        self.assertIn("exactly five permanent ASIs", legacy)
        self.assertIn("CONTENT_EVALUATION.md", legacy)
        self.assertIn("e932320f28badb52bbb2dd968036debcb6ad87e5", legacy)
        self.assertIn("must never recreate a sixth agent", legacy)
        self.assertNotIn("The Strategist acts as the strategic engine", legacy)

    def test_legacy_benchmark_ownership_is_split_across_cmo_and_content(self):
        cmo_eval = self.cmo_evaluation_path.read_text(encoding="utf-8")
        content_eval = self.content_evaluation_path.read_text(encoding="utf-8")

        self.assertIn("There is no permanent Strategist identity and no sixth agent", cmo_eval)
        self.assertIn("e932320f28badb52bbb2dd968036debcb6ad87e5", cmo_eval)
        self.assertNotIn("The Strategist acts as the strategic engine", cmo_eval)
        self.assertNotIn("Strategist:", cmo_eval)

        cmo_owned_legacy_ids = tuple(i for i in range(1, 26) if i not in (8, 18))
        for legacy_id in cmo_owned_legacy_ids:
            self.assertIn(
                f"### Legacy S{legacy_id} ",
                cmo_eval,
                f"CMO evaluation lost migrated executive-strategy coverage for legacy S{legacy_id}",
            )

        self.assertNotIn("### Legacy S8 ", cmo_eval)
        self.assertNotIn("### Legacy S18 ", cmo_eval)
        self.assertIn("### Legacy S8 ", content_eval)
        self.assertIn("### Legacy S18 ", content_eval)
        self.assertIn("exactly five permanent ASIs", content_eval)
        self.assertIn("e932320f28badb52bbb2dd968036debcb6ad87e5", content_eval)
        self.assertIn("Creative then owns visual concepts", content_eval)

    def test_authoritative_docs_define_only_canonical_five_agents(self):
        source = self.source_of_truth_path.read_text(encoding="utf-8")
        architecture = self.architecture_path.read_text(encoding="utf-8")
        protocol = self.agent_protocol_path.read_text(encoding="utf-8")

        self.assertIn(
            "`CMO`, `Intelligence`, `Content`, `Creative`, and `Performance`",
            source,
        )
        self.assertIn("no permanent Strategist agent and no Agent 6", source)
        self.assertIn("Final CMO reuses CMO", source)
        self.assertIn("An empty fallback chain means no fallback", source)
        self.assertIn("chronological implementation/evaluation history", source)
        self.assertNotIn(
            "`CMO`, `Intelligence`, `Strategist`, `Creative`, and `Performance`",
            source,
        )

        self.assertIn("## 2. Exactly five permanent agents", architecture)
        self.assertIn("Historical `STRATEGIST` / `STRATEGY` names are not permanent identities", architecture)
        self.assertIn("3. CONTENT", architecture)
        self.assertIn("6. CMO (final; same CMO identity)", architecture)
        self.assertIn("An empty fallback chain grants no fallback authority", architecture)
        self.assertNotIn("### 2.3 Strategist", architecture)
        self.assertNotIn("3. STRATEGIST:", architecture)

        self.assertIn("All permanent inter-agent communication is bounded to exactly five logical identities", protocol)
        self.assertIn("CMO | INTELLIGENCE | CONTENT | CREATIVE | PERFORMANCE", protocol)
        self.assertIn("INTELLIGENCE\n   ↓\nCONTENT", protocol)
        self.assertIn("Final CMO is not Agent 6", protocol)
        self.assertIn("An empty fallback chain means no fallback", protocol)
        self.assertNotIn('"supporting_agents": ["STRATEGIST"]', protocol)
        self.assertNotIn("Pass validated ResearchReport to STRATEGIST", protocol)

    def test_governance_docs_cannot_regrant_legacy_or_mode_based_authority(self):
        security = self.security_model_path.read_text(encoding="utf-8")
        ui_permissions = self.ui_permission_model_path.read_text(encoding="utf-8")
        roadmap = self.roadmap_path.read_text(encoding="utf-8")

        self.assertIn("Exactly five permanent logical agents", security)
        self.assertIn("Agent identity is not execution authority", security)
        self.assertIn("## 5. Autonomy modes do not create authority", security)
        self.assertIn("an empty chain means no fallback", security)
        self.assertNotIn("| **STRATEGIST** |", security)
        self.assertNotIn("Agents execute", security)

        self.assertIn("There is no permanent Strategist or Agent 6", ui_permissions)
        self.assertIn("does **not** create new permission", ui_permissions)
        self.assertIn("an empty fallback chain means no fallback", ui_permissions)
        self.assertNotIn("Pre-approved budgets & variants execute", ui_permissions)

        self.assertIn("LEGACY / NON-AUTHORITATIVE ROADMAP", roadmap)
        self.assertIn("4f51ac5c0d7bba98751246afc54ceee1475e03de", roadmap)
        self.assertIn("exactly five permanent logical agents", roadmap)
        self.assertIn("an empty fallback chain means no fallback", roadmap)
        self.assertNotIn("### PHASE 1 — Agent Core & Foundational Architecture (CURRENT)", roadmap)

    def test_creative_engine_preserves_content_semantics_and_media_boundary(self):
        creative_engine = self.creative_engine_path.read_text(encoding="utf-8")

        self.assertIn("The Creative Engine does **not** replace the Content ASI", creative_engine)
        self.assertIn("**Content** — message architecture, hooks, copy, scripts, CTA wording", creative_engine)
        self.assertIn("**Creative** — visual/multimedia concept, art direction, storyboard", creative_engine)
        self.assertIn("The hook/script/CTA identifiers point back to Content-owned semantic artifacts", creative_engine)
        self.assertIn("Producing a media file does not mean it was published", creative_engine)
        self.assertIn("examples only", creative_engine)
        self.assertNotIn("│ Hook Generation │", creative_engine)
        self.assertNotIn("│ Scriptwriting   │", creative_engine)
        self.assertNotIn("cryptographic metadata manifest", creative_engine)


if __name__ == "__main__":
    unittest.main()
