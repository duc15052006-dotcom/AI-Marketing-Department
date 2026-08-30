"""Runtime system-prompt composition for the permanent Five-Agent Department.

This module keeps agent-role semantics in the runtime/prompt layer. The
UniversalModelGateway remains provider-neutral and never needs to know which
logical marketing role is being executed.
"""

from __future__ import annotations

from typing import Optional

from integrations.models.agent_loader import AgentLoader


class AgentDnaLoadError(RuntimeError):
    """Raised when authoritative operating DNA cannot be loaded safely."""


def compose_runtime_agent_system_prompt(
    agent_id: str,
    stage_directive: str,
    *,
    loader: Optional[AgentLoader] = None,
) -> str:
    """Compose full operating DNA plus the current stage-specific directive.

    The permanent ``agent.md`` file is authoritative for role identity,
    boundaries, epistemic discipline, and professional operating rules. The
    stage directive only specifies the current task; it must never replace the
    DNA. Missing/empty DNA fails closed rather than silently falling back to a
    miniature role prompt.
    """
    active_loader = loader or AgentLoader()
    try:
        definition = active_loader.load_agent(agent_id)
    except Exception as exc:
        raise AgentDnaLoadError(f"AGENT_DNA_LOAD_FAILED[{agent_id}]: {exc}") from exc

    dna = (definition.system_dna or "").strip()
    if not dna:
        raise AgentDnaLoadError(f"AGENT_DNA_EMPTY[{agent_id}]")

    directive = (stage_directive or "").strip()
    if not directive:
        raise AgentDnaLoadError(f"STAGE_DIRECTIVE_EMPTY[{agent_id}]")

    return (
        f"=== AUTHORITATIVE OPERATING DNA: {definition.agent_id.upper()} ===\n"
        f"{dna}\n\n"
        "=== CURRENT RUNTIME STAGE DIRECTIVE ===\n"
        f"{directive}"
    )
