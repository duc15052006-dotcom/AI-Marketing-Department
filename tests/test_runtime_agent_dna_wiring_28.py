"""Production regressions for authoritative full Agent DNA system prompts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integrations.models.agent_loader import AgentLoader
from integrations.models.base import ModelResponse, ModelResponseStatus
from runtime.agent_prompt import AgentDnaLoadError, compose_runtime_agent_system_prompt
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class CapturingGateway:
    def __init__(self) -> None:
        self.requests = []
        self.provider_registry = None
        self.model_policy = None

    def generate(self, request, **kwargs):
        self.requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            provider="capturing_test",
            model_name="capturing_test",
            status=ModelResponseStatus.SUCCESS,
            content="OK",
        )


class RuntimeAgentDnaWiring28Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = CapturingGateway()
        self.runtime = FiveAgentDepartmentRuntime(
            model_gateway=self.gateway,
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )

    def test_call_agent_llm_uses_full_dna_for_all_five_agents(self):
        markers = {
            "cmo": "Chief Marketing Officer",
            "intelligence": "Intelligence",
            "strategist": "Marketing Strategist",
            "creative": "Creative",
            "performance": "Performance Marketer, Marketing Analyst",
        }
        for agent_id, marker in markers.items():
            sentinel = f"STAGE-DIRECTIVE-{agent_id.upper()}"
            content, error = self.runtime._call_agent_llm(agent_id, sentinel, "test user prompt")
            self.assertEqual(content, "OK")
            self.assertIsNone(error)
            system_text = self.gateway.requests[-1].messages[0].content
            self.assertIn("AUTHORITATIVE OPERATING DNA", system_text)
            self.assertIn(marker, system_text)
            self.assertIn(sentinel, system_text)
            self.assertGreater(len(system_text), 1000)

    def test_dna_load_failure_blocks_gateway_dispatch(self):
        before = len(self.gateway.requests)
        with patch(
            "runtime.engine.compose_runtime_agent_system_prompt",
            side_effect=AgentDnaLoadError("AGENT_DNA_LOAD_FAILED[cmo]"),
        ):
            content, error = self.runtime._call_agent_llm("cmo", "CMO stage directive", "test user prompt")
        self.assertIsNone(content)
        self.assertIn("AGENT_DNA_LOAD_FAILED", error)
        self.assertEqual(len(self.gateway.requests), before)

    def test_missing_definition_and_sixth_agent_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = AgentLoader(workspace_root=Path(tmp))
            with self.assertRaises(AgentDnaLoadError):
                compose_runtime_agent_system_prompt("cmo", "Stage directive", loader=loader)
        with self.assertRaises(AgentDnaLoadError):
            compose_runtime_agent_system_prompt("agent_6", "Do work")

    def test_empty_stage_directive_fails_closed(self):
        with self.assertRaises(AgentDnaLoadError) as ctx:
            compose_runtime_agent_system_prompt("performance", "   ")
        self.assertIn("STAGE_DIRECTIVE_EMPTY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
