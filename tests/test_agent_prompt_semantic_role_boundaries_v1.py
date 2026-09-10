from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


def _agent(name: str) -> str:
    return (ROOT / ".agents" / "agents" / name / "agent.md").read_text(encoding="utf-8")


class AgentPromptSemanticRoleBoundariesV1Tests(unittest.TestCase):
    def test_cmo_keeps_strategy_positioning_and_commercial_authority(self):
        text = _agent("cmo")
        self.assertIn("Strategy & Positioning", text)
        self.assertIn("from the CMO executive strategy", text)
        self.assertIn("Content & Messaging", text)
        self.assertNotIn("Strategy & Positioning**: Beachheads, ICP prioritization, value proposition, and channel allocations from Content", text)
        self.assertNotIn("Hand off to **Content** to challenge commercial viability and market sizing", text)

    def test_creative_does_not_claim_primary_copy_or_script_ownership(self):
        text = _agent("creative")
        lowered = text.lower()
        for forbidden in (
            "creative director, copywriter, scriptwriter",
            "master copywriter, scriptwriter",
            "before writing individual scripts or drafting copy",
            "## 10. copywriting & anti-generic-ai writing standard",
            "content's positioning",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertIn("Content owns substantive copy, hooks, scripts, storytelling, CTA wording", text)
        self.assertIn("CMO-approved strategy/positioning", text)
        self.assertIn("visual concepts, storyboards, production specifications, and multimedia assets", text)

    def test_performance_handoffs_text_to_content_and_media_to_creative(self):
        text = _agent("performance")
        self.assertIn("script writing, hook drafting, CTA wording, and editorial content to **Content**", text)
        self.assertIn("image/video generation, storyboards, and editing to **Creative**", text)
        self.assertIn("receive positioning, target beachheads, offer boundaries, and trade-off decisions from **CMO**", text)
        self.assertNotIn("receive positioning architectures, target beachheads, and trade-off boundaries from **Content**", text)
        self.assertNotIn("script writing, hook drafting, and video editing to **Creative**", text)

    def test_body_execution_boundary_remains_explicit(self):
        creative = _agent("creative")
        performance = _agent("performance")
        self.assertIn("live publisher or deployment authority", creative)
        self.assertIn("governed runtime/Body", creative)
        self.assertIn("live scheduling/publishing remains a governed runtime/Body action", performance)


    def test_intelligence_handoffs_strategy_content_media_and_execution_correctly(self):
        text = _agent("intelligence")
        self.assertIn("strategy formulation, positioning, offer boundaries, and budget allocation to **CMO**", text)
        self.assertIn("messaging architecture, concepts, hooks, ad copy, scripts, and CTA wording to **Content**", text)
        self.assertIn("visual concepts, storyboards, multimedia asset rendering, and production timelines to **Creative**", text)
        self.assertIn("governed runtime/Body policy", text)
        self.assertNotIn("strategy formulation, positioning, and budget allocation to **CMO** and **Content**", text)
        self.assertNotIn("concept development, ad copy, and scripts to **Creative**", text)
        self.assertNotIn("ad setup and deployment to **Performance**", text)

    def test_cmo_delegates_text_media_and_live_execution_without_role_overlap(self):
        text = _agent("cmo")
        self.assertIn("messaging architecture, verbal concepts, hooks, copy, scripts, CTA wording, and editorial adaptation to **Content**", text)
        self.assertIn("visual concepts, storyboards, video timeline assembly, and image/video/audio asset synthesis to **Creative**", text)
        self.assertIn("external platform actions must pass governed runtime/Body policy", text)
        self.assertNotIn("delegate concept, hook, and copy generation to **Creative**", text)
        self.assertNotIn("delegate platform payload preparation to **Performance**", text)


if __name__ == "__main__":
    unittest.main()
