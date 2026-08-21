"""Structural validation test for AI Marketing Department."""

import unittest
from pathlib import Path

REQUIRED_DIRECTORIES = [
    ".agents/agents/cmo",
    ".agents/agents/intelligence",
    ".agents/agents/strategist",
    ".agents/agents/creative",
    ".agents/agents/performance",
    ".agents/skills",
    ".agents/rules",
    ".agents/workflows",
    "config",
    "knowledge/marketing",
    "knowledge/consumer_psychology",
    "knowledge/strategy",
    "knowledge/copywriting",
    "knowledge/storytelling",
    "knowledge/platforms",
    "knowledge/analytics",
    "knowledge/creative",
    "memory/business",
    "memory/experiments",
    "memory/learnings",
    "memory/failures",
    "company",
    "brands",
    "products",
    "campaigns",
    "research",
    "creatives",
    "analytics",
    "experiments",
    "reports",
    "creative_engine/concepts",
    "creative_engine/scripts",
    "creative_engine/storyboards",
    "creative_engine/assets",
    "creative_engine/image_generation",
    "creative_engine/video_generation",
    "creative_engine/voice",
    "creative_engine/audio",
    "creative_engine/subtitles",
    "creative_engine/editing",
    "creative_engine/rendering",
    "creative_engine/thumbnails",
    "creative_engine/quality_control",
    "integrations/observation",
    "integrations/platforms",
    "integrations/models",
    "integrations/mentor",
    "tools",
    "schemas",
    "logs",
    "tests",
]

REQUIRED_DOCUMENTS = [
    "ARCHITECTURE.md",
    "AGENT_PROTOCOL.md",
    "DATA_MODEL.md",
    "SECURITY_MODEL.md",
    "CREATIVE_ENGINE.md",
    "LEARNING_SYSTEM.md",
    "ROADMAP.md",
    "STATUS_MATRIX.md",
    "ANTIGRAVITY_RUNTIME_CHECK.md",
    "UI_ARCHITECTURE.md",
    "UI_SCREENS.md",
    "UI_COMPONENTS.md",
    "UI_STATE_MODEL.md",
    "UI_PERMISSION_MODEL.md",
    "CHAT_WORKSPACE_SPEC.md",
    "CMO_EVALUATION.md",
    "INTELLIGENCE_EVALUATION.md",
    "STRATEGIST_EVALUATION.md",
    "CREATIVE_EVALUATION.md",
    "PERFORMANCE_EVALUATION.md",
    "COLLABORATION_EVALUATION.md",
    "COLLABORATION_RUNTIME_GAP.md",
    "OPEN_SOURCE_TOOL_AUDIT.md",
    "TOOL_DECISION_MATRIX.md",
    "OBSERVATION_V0_ARCHITECTURE.md",
    "CAPABILITY_REGISTRY_SPEC.md",
    "TOOL_GATEWAY_SPEC.md",
    "TOOL_DEPENDENCY_MATRIX.md",
    "TOOL_SECURITY_POLICY.md",
]


class TestStructure(unittest.TestCase):
    def test_required_directories_exist(self):
        base = Path(__file__).resolve().parent.parent
        for rel_path in REQUIRED_DIRECTORIES:
            d = base / rel_path
            self.assertTrue(d.exists() and d.is_dir(), f"Missing required directory: {rel_path}")

    def test_required_documents_exist(self):
        base = Path(__file__).resolve().parent.parent
        for doc in REQUIRED_DOCUMENTS:
            f = base / doc
            self.assertTrue(f.exists() and f.is_file(), f"Missing required architecture document: {doc}")
            self.assertGreater(f.stat().st_size, 200, f"Architecture document {doc} appears truncated or empty")


if __name__ == "__main__":
    unittest.main()
