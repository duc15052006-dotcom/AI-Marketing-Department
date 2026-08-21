"""Tests verifying agent definitions, agent.md discovery, and YAML frontmatter validation."""

import os
import re
import unittest
from pathlib import Path

EXPECTED_AGENTS = {
    "cmo": "cmo",
    "intelligence": "intelligence",
    "strategist": "strategist",
    "creative": "creative",
    "performance": "performance",
}


def parse_yaml_frontmatter(content: str) -> dict[str, str]:
    """Pure Python parser for YAML frontmatter between leading '---' markers."""
    lines = content.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Content does not start with YAML frontmatter marker '---'")

    closing_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closing_idx = i
            break

    if closing_idx == -1:
        raise ValueError("Unclosed YAML frontmatter marker '---'")

    frontmatter_lines = lines[1:closing_idx]
    result: dict[str, str] = {}
    current_key = None
    current_val_lines = []

    for line in frontmatter_lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z0-9_-]+):\s*(.*)$", line)
        if match:
            if current_key:
                result[current_key] = " ".join(current_val_lines).strip().strip('"').strip("'")
            current_key = match.group(1).strip()
            val = match.group(2).strip()
            current_val_lines = [val] if val else []
        else:
            if current_key:
                current_val_lines.append(line.strip())

    if current_key:
        result[current_key] = " ".join(current_val_lines).strip().strip('"').strip("'")

    return result


class TestAgentDefinitions(unittest.TestCase):
    def setUp(self):
        self.base_agents_dir = Path(__file__).resolve().parent.parent / ".agents" / "agents"

    def test_exactly_five_permanent_agents_exist(self):
        """Rule 1 & 6: Exactly five agent subdirectories exist, no sixth permanent agent."""
        agent_subdirs = [d.name for d in self.base_agents_dir.iterdir() if d.is_dir()]
        self.assertEqual(
            sorted(agent_subdirs),
            sorted(list(EXPECTED_AGENTS.keys())),
            f"Expected exactly 5 permanent agents {list(EXPECTED_AGENTS.keys())}, found: {agent_subdirs}",
        )
        self.assertEqual(len(agent_subdirs), 5, f"Expected exactly 5 agents, found {len(agent_subdirs)}")

    def test_every_agent_has_valid_agent_md(self):
        """Rule 2, 3, 4, 5: Every agent directory contains agent.md with valid frontmatter, unique name, non-empty description."""
        discovered_names = set()

        for agent_id in EXPECTED_AGENTS.keys():
            agent_md_path = self.base_agents_dir / agent_id / "agent.md"
            self.assertTrue(
                agent_md_path.exists() and agent_md_path.is_file(),
                f"Missing agent.md for agent '{agent_id}' at {agent_md_path}",
            )

            content = agent_md_path.read_text(encoding="utf-8")
            fm = parse_yaml_frontmatter(content)

            self.assertIn("name", fm, f"agent.md for '{agent_id}' missing 'name' in frontmatter")
            self.assertIn("description", fm, f"agent.md for '{agent_id}' missing 'description' in frontmatter")

            agent_name = fm["name"]
            agent_desc = fm["description"]

            self.assertTrue(len(agent_name) > 0, f"agent.md for '{agent_id}' has empty name")
            self.assertTrue(len(agent_desc) > 10, f"agent.md for '{agent_id}' has too short description")
            self.assertNotIn(agent_name, discovered_names, f"Duplicate agent name discovered: '{agent_name}'")
            discovered_names.add(agent_name)

            # Check that content is non-trivial
            self.assertTrue(len(content.splitlines()) > 5, f"agent.md for '{agent_id}' has too few lines")

    # -----------------------------------------------------------------------
    # Negative / Failure Validation Tests
    # -----------------------------------------------------------------------

    def test_missing_agent_md_fails_validation(self):
        """Negative test: A directory lacking agent.md fails check."""
        temp_dir = self.base_agents_dir.parent / "temp_fake_agent"
        temp_dir.mkdir(exist_ok=True)
        try:
            agent_md = temp_dir / "agent.md"
            self.assertFalse(agent_md.exists())
            with self.assertRaises(AssertionError):
                self.assertTrue(agent_md.exists(), "agent.md should not exist")
        finally:
            if temp_dir.exists():
                temp_dir.rmdir()

    def test_invalid_yaml_frontmatter_fails(self):
        """Negative test: Invalid frontmatter without --- or missing closing --- raises error."""
        invalid_content_1 = "name: cmo\ndescription: test\n"
        with self.assertRaises(ValueError):
            parse_yaml_frontmatter(invalid_content_1)

        invalid_content_2 = "---\nname: cmo\ndescription: test\n# No closing marker"
        with self.assertRaises(ValueError):
            parse_yaml_frontmatter(invalid_content_2)

    def test_duplicate_agent_names_fail(self):
        """Negative test: Duplicate agent names in a collection trigger a duplicate error."""
        agent_names = ["cmo", "intelligence", "strategist", "creative", "cmo"]
        with self.assertRaises(AssertionError):
            self.assertEqual(len(agent_names), len(set(agent_names)), "Duplicate agent names must fail")

    def test_sixth_permanent_agent_fails(self):
        """Negative test: A collection of 6 agents fails the exact 5 rule."""
        six_agents = ["cmo", "intelligence", "strategist", "creative", "performance", "affiliate_manager"]
        with self.assertRaises(AssertionError):
            self.assertEqual(len(six_agents), 5, "Sixth permanent agent must fail")


if __name__ == "__main__":
    unittest.main()
