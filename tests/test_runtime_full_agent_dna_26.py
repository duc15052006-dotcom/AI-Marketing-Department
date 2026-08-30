"""Regression coverage for authoritative Agent DNA in production runtime prompts."""

import tempfile
import unittest
from pathlib import Path

from governance.access_matrix import PERMANENT_FIVE_AGENTS
from integrations.models.agent_loader import AgentLoader
from runtime.agent_prompt import AgentDnaLoadError, compose_runtime_agent_system_prompt


class RuntimeFullAgentDna26Tests(unittest.TestCase):
    def test_all_five_permanent_agents_receive_full_dna_plus_stage_directive(self):
        unique_markers = {
            "cmo": "Chief Marketing Officer",
            "intelligence": "Intelligence",
            "strategist": "Marketing Strategist",
            "creative": "Creative",
            "performance": "Performance Marketer, Marketing Analyst",
        }
        for agent_id in PERMANENT_FIVE_AGENTS:
            directive = f"CURRENT STAGE FOR {agent_id}"
            prompt = compose_runtime_agent_system_prompt(agent_id, directive)
            self.assertIn("AUTHORITATIVE OPERATING DNA", prompt)
            self.assertIn(unique_markers[agent_id], prompt)
            self.assertIn(directive, prompt)
            self.assertGreater(len(prompt), 1000, f"{agent_id} unexpectedly received a miniature prompt")

    def test_missing_agent_definition_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = AgentLoader(workspace_root=Path(tmp))
            with self.assertRaises(AgentDnaLoadError) as ctx:
                compose_runtime_agent_system_prompt("cmo", "Stage directive", loader=loader)
        self.assertIn("AGENT_DNA_LOAD_FAILED", str(ctx.exception))

    def test_invalid_sixth_agent_is_rejected(self):
        with self.assertRaises(AgentDnaLoadError):
            compose_runtime_agent_system_prompt("agent_6", "Do work")

    def test_empty_stage_directive_fails_closed(self):
        with self.assertRaises(AgentDnaLoadError) as ctx:
            compose_runtime_agent_system_prompt("performance", "   ")
        self.assertIn("STAGE_DIRECTIVE_EMPTY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
