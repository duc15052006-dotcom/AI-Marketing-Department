"""Agent Definition Loader.

Loads, validates, and parses agent definitions from `.agents/agents/<agent>/agent.md`.
Enforces the invariant of exactly five permanent marketing agents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Set
from schemas.base import BaseModel, Field

PERMANENT_AGENT_IDS: Set[str] = {
    "cmo",
    "intelligence",
    "strategist",
    "creative",
    "performance",
}


class AgentDefinition(BaseModel):
    """Parsed in-memory agent definition."""
    agent_id: str
    name: str
    description: str
    system_dna: str
    file_path: str


class AgentLoader:
    """Loads and parses agent.md definitions for the model execution bridge."""

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        if workspace_root is None:
            # Default to repository root
            self.workspace_root = Path(__file__).resolve().parent.parent.parent
        else:
            self.workspace_root = workspace_root

    def is_valid_agent_id(self, agent_id: str) -> bool:
        """Verify if agent_id belongs to the exactly five permanent agents."""
        return agent_id.lower().strip() in PERMANENT_AGENT_IDS

    def load_agent(self, agent_id: str) -> AgentDefinition:
        """Load and parse an agent definition from disk."""
        norm_id = agent_id.lower().strip()

        if not self.is_valid_agent_id(norm_id):
            raise ValueError(
                f"INVALID_AGENT_ID: '{agent_id}' is not one of the five permanent agents "
                f"({sorted(list(PERMANENT_AGENT_IDS))}). Creating or invoking a sixth core agent is prohibited."
            )

        agent_file = (
            self.workspace_root
            / ".agents"
            / "agents"
            / norm_id
            / "agent.md"
        )

        if not agent_file.exists():
            raise FileNotFoundError(f"Agent definition file missing: {agent_file}")

        raw_text = agent_file.read_text(encoding="utf-8")
        frontmatter, dna_body = self._parse_markdown_frontmatter(raw_text)

        name = frontmatter.get("name", norm_id)
        description = frontmatter.get("description", "")

        return AgentDefinition(
            agent_id=norm_id,
            name=name,
            description=description,
            system_dna=dna_body,
            file_path=str(agent_file),
        )

    def load_all_agents(self) -> Dict[str, AgentDefinition]:
        """Load all five permanent agent definitions."""
        return {aid: self.load_agent(aid) for aid in PERMANENT_AGENT_IDS}

    @staticmethod
    def _parse_markdown_frontmatter(content: str) -> tuple[Dict[str, str], str]:
        """Extract YAML frontmatter and body from markdown."""
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, content

        frontmatter_lines = []
        body_lines = []
        in_frontmatter = True
        found_closing = False

        for line in lines[1:]:
            if in_frontmatter:
                if line.strip() == "---":
                    in_frontmatter = False
                    found_closing = True
                    continue
                frontmatter_lines.append(line)
            else:
                body_lines.append(line)

        if not found_closing:
            return {}, content

        # Simple YAML key-value parser to avoid heavy external dependencies
        frontmatter: Dict[str, str] = {}
        for fline in frontmatter_lines:
            fline = fline.strip()
            if not fline or fline.startswith("#"):
                continue
            if ":" in fline:
                key, val = fline.split(":", 1)
                frontmatter[key.strip()] = val.strip().strip("'\"")

        return frontmatter, "\n".join(body_lines).strip()
