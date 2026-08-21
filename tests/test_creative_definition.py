"""Tests verifying the Creative Agent Definition, Hardening Patch 2B.4.1, and Professional DNA integrity."""

import unittest
from pathlib import Path
from tests.test_agent_manifests import parse_yaml_frontmatter


class TestCreativeDefinition(unittest.TestCase):
    def setUp(self):
        self.creative_md_path = (
            Path(__file__).resolve().parent.parent
            / ".agents"
            / "agents"
            / "creative"
            / "agent.md"
        )
        self.assertTrue(self.creative_md_path.exists(), "creative/agent.md does not exist")
        self.content = self.creative_md_path.read_text(encoding="utf-8")
        self.frontmatter = parse_yaml_frontmatter(self.content)

    def test_creative_frontmatter_valid(self):
        """Verify Creative frontmatter has name 'creative' and non-empty description."""
        self.assertEqual(self.frontmatter.get("name"), "creative")
        self.assertIn("Creative Director", self.frontmatter.get("description", ""))

    def test_creative_identity_and_role_boundaries(self):
        """Verify Creative is defined as creative production engine and NOT primary researcher, strategist, or publisher."""
        self.assertIn("Creative Director, Copywriter, Scriptwriter, Visual Director & Creative Production Orchestrator", self.content)
        self.assertIn("transform validated market intelligence and strategic positioning into original", self.content)
        self.assertIn("primary market researcher", self.content)
        self.assertIn("final business strategist", self.content)
        self.assertIn("performance measurement authority", self.content)
        self.assertIn("ad network publisher", self.content)
        self.assertIn("final commercial and budgetary authority", self.content)

    def test_creative_input_contract_and_reference_coverage(self):
        """Patch 2B.4.1: Verify inspection of Creative Strategy Brief, product reference coverage, and prohibition of silent fabrication."""
        self.assertIn("Creative Input Contract", self.content)
        self.assertIn("CREATIVE INPUT AUDIT", self.content)
        self.assertIn("BUSINESS_OBJECTIVE", self.content)
        self.assertIn("TARGET_SEGMENT", self.content)
        self.assertIn("PRODUCT_REFERENCE_COVERAGE", self.content)
        self.assertIn("COMPLETE | PARTIAL | INSUFFICIENT", self.content)
        self.assertIn("WHAT_NOT_TO_DO", self.content)
        self.assertIn("Never silently invent product features", self.content)

    def test_strategy_to_creative_translation(self):
        """Verify translation of strategic brief into customer communication problems."""
        self.assertIn("Creative Brief Translation: Solving the Communication Problem", self.content)
        self.assertIn("Strategic Creative Framing", self.content)

    def test_human_understanding_and_ethical_psychology(self):
        """Verify consumer psychology mechanisms and strict prohibition of deceptive manipulation."""
        self.assertIn("Human Understanding & Ethical Consumer Psychology", self.content)
        self.assertIn("Persuasion Mechanisms", self.content)
        self.assertIn("Ethical Persuasion Guardrails", self.content)
        self.assertIn("Zero Tolerance for Deception", self.content)
        self.assertIn("Fabricated customer testimonials", self.content)
        self.assertIn("Deceptive artificial scarcity", self.content)

    def test_message_architecture_hierarchy(self):
        """Verify single primary message hierarchy and prohibition of communicating 10 messages in one asset."""
        self.assertIn("Message Architecture: The Singular Hierarchy", self.content)
        self.assertIn("THE ONE PRIMARY MESSAGE", self.content)
        self.assertIn("SUPPORTING MECHANISM", self.content)
        self.assertIn("CONCRETE PROOF / RTB", self.content)
        self.assertIn("OBJECTION NEUTRALIZED", self.content)

    def test_creative_territories_and_angle_generation(self):
        """Verify creative territories and diverse angle generation without cosmetic variations."""
        self.assertIn("Creative Territories & Angle Generation", self.content)
        self.assertIn("Transformation", self.content)
        self.assertIn("Live Demonstration", self.content)
        self.assertIn("Angle Generation Discipline (No Cosmetic Variations)", self.content)

    def test_concept_development_and_quality_separation(self):
        """Patch 2B.4.1: Verify structured concept schema and separate evaluation of concept quality vs media execution quality."""
        self.assertIn("Concept Development Framework & Quality Separation", self.content)
        self.assertIn("CONCEPT SPECIFICATION", self.content)
        self.assertIn("CONCEPT_NAME", self.content)
        self.assertIn("Concept Quality vs. Execution Quality Separation", self.content)
        self.assertIn("CONCEPT LAYER", self.content)
        self.assertIn("EXECUTION LAYER", self.content)

    def test_hook_engineering_and_promise_consistency(self):
        """Verify hook archetypes and strict hook-promise consistency to eliminate deceptive clickbait."""
        self.assertIn("Hook Engineering & Hook-Promise Consistency", self.content)
        self.assertIn("Hook Archetypes", self.content)
        self.assertIn("The Hook-Promise Consistency Mandate", self.content)
        self.assertIn("Clickbait that fails to deliver damages brand trust", self.content)

    def test_copywriting_and_anti_generic_ai_rules(self):
        """Verify copywriting standards and active elimination of generic synthetic AI writing tropes."""
        self.assertIn("Copywriting & Anti-Generic-AI Writing Standard", self.content)
        self.assertIn("Clarity over Cleverness", self.content)
        self.assertIn("Anti-Generic-AI Writing Protocol", self.content)
        self.assertIn("Formulaic Openings", self.content)
        self.assertIn("Generic Superlatives", self.content)

    def test_storytelling_and_content_relative_retention(self):
        """Patch 2B.4.1: Verify non-dogmatic storytelling and content-relative retention analysis across varying durations."""
        self.assertIn("Storytelling (Non-Dogmatic & Context-Appropriate)", self.content)
        self.assertIn("Video Retention Diagnosis (Content-Relative Analysis)", self.content)
        self.assertIn("Contextual Timeline Diagnosis", self.content)
        self.assertIn("ACTUAL_DURATION", self.content)
        self.assertIn("SCENE_BOUNDARIES", self.content)
        self.assertIn("CONTENT-RELATIVE RETENTION MAPPING", self.content)

    def test_visual_direction_and_anti_camera_fetishism(self):
        """Patch 2B.4.1: Verify visual intent takes precedence over camera brand equipment jargon."""
        self.assertIn("Visual Direction & Intent (Anti-Camera Fetishism)", self.content)
        self.assertIn("Visual Intent > Camera Brand Language", self.content)
        self.assertIn("Lighting Character", self.content)
        self.assertIn("Contrast & Depth", self.content)
        self.assertIn("Composition & Framing", self.content)

    def test_evidence_based_product_fidelity_and_unknowns(self):
        """Patch 2B.4.1: Verify product fidelity distinguishes verified facts from unknown details without fabrication."""
        self.assertIn("Evidence-Based Product Fidelity & Coverage", self.content)
        self.assertIn("VERIFIED_PRODUCT_FACT", self.content)
        self.assertIn("REFERENCE_VISIBLE_DETAIL", self.content)
        self.assertIn("UNKNOWN_DETAIL", self.content)
        self.assertIn("CREATIVE_INTERPRETATION", self.content)
        self.assertIn("Product Reference Coverage Governance", self.content)

    def test_generative_ai_media_direction_and_anti_prompt_bloat(self):
        """Patch 2B.4.1: Verify structured generative direction and rejection of prompt complexity/bloat."""
        self.assertIn("AI Generative Media Direction", self.content)
        self.assertIn("Functional Precision > Prompt Bloat", self.content)
        self.assertIn("AI IMAGE SPECIFICATION", self.content)
        self.assertIn("AI VIDEO GENERATION SPECIFICATION", self.content)

    def test_storyboard_and_shot_list_schemas(self):
        """Verify storyboard and shot list specification schemas."""
        self.assertIn("Storyboard & Shot List Schemas", self.content)
        self.assertIn("Storyboard Specification Schema", self.content)
        self.assertIn("SCENE_ID", self.content)
        self.assertIn("Shot List Specification Schema", self.content)
        self.assertIn("SHOT_ID", self.content)

    def test_video_editing_audio_subtitles_and_thumbnails(self):
        """Verify editing engine abstraction, purposeful transitions, audio balance, subtitles, and thumbnails."""
        self.assertIn("Video Editing, Audio, Subtitle & Thumbnail Direction", self.content)
        self.assertIn("Editing Engine Abstraction", self.content)
        self.assertIn("Purposeful Transitions", self.content)
        self.assertIn("Subtitle Typography", self.content)
        self.assertIn("Thumbnail / Cover Art Design", self.content)

    def test_divergence_heuristics_and_meaningful_variants(self):
        """Patch 2B.4.1: Verify divergence counts are explicitly heuristics that scale to task complexity."""
        self.assertIn("Creative Divergence Heuristics & Meaningful Variants", self.content)
        self.assertIn("Diverge Meaningfully, Converge with Evidence", self.content)
        self.assertIn("TASK_COMPLEXITY", self.content)
        self.assertIn("example heuristics, not rigid rules", self.content)

    def test_creative_critique_without_pseudo_precision(self):
        """Verify calibrated qualitative scoring (STRONG, ACCEPTABLE, WEAK) and anti-pseudo-precision."""
        self.assertIn("Creative Critique & Qualitative Evaluation", self.content)
        self.assertIn("STRONG", self.content)
        self.assertIn("ACCEPTABLE", self.content)
        self.assertIn("WEAK", self.content)
        self.assertIn("Avoid fabricated pseudo-precise decimal scoring", self.content)

    def test_cross_agent_review_and_qa_gates(self):
        """Verify cross-agent review matrix and pre-delivery creative QA gates."""
        self.assertIn("Cross-Agent Review & Creative QA Gates", self.content)
        self.assertIn("Cross-Agent Collaboration Matrix", self.content)
        self.assertIn("Mandatory Pre-Delivery Creative QA Gate", self.content)
        self.assertIn("PRODUCT FIDELITY", self.content)
        self.assertIn("AI MEDIA INTEGRITY", self.content)

    def test_originality_and_creative_memory(self):
        """Verify pattern abstraction without plagiarism and structured creative memory logging."""
        self.assertIn("Originality, Reference Use & Creative Memory", self.content)
        self.assertIn("Pattern Learning vs. Plagiarism", self.content)
        self.assertIn("Creative Memory Logging", self.content)

    def test_failure_protocol_and_communication_style(self):
        """Verify structured Creative Blocker Report and concept presentation format."""
        self.assertIn("Failure Protocol", self.content)
        self.assertIn("Creative Blocker Report", self.content)
        self.assertIn("MISSING_INPUT", self.content)
        self.assertIn("UNKNOWN_PRODUCT_DETAILS", self.content)
        self.assertIn("Creative Communication Style", self.content)
        self.assertIn("CONCEPT PRESENTATION", self.content)

    def test_creative_self_check_questions(self):
        """Verify the 18 diagnostic self-check audit questions for Creative."""
        self.assertIn("Creative Self-Check (18 Diagnostic Questions)", self.content)
        for i in range(1, 19):
            self.assertIn(f"{i}.", self.content)


if __name__ == "__main__":
    unittest.main()
