"""Production wiring regressions for full Agent DNA system prompts."""

import unittest
from unittest.mock import patch

from integrations.models.base import ModelResponse, ModelResponseStatus
from runtime.agent_prompt import AgentDnaLoadError
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
            content, error = self.runtime._call_agent_llm(
                agent_id,
                sentinel,
                "test user prompt",
            )
            self.assertEqual(content, "OK")
            self.assertIsNone(error)
            req = self.gateway.requests[-1]
            system_text = req.messages[0].content
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
            content, error = self.runtime._call_agent_llm(
                "cmo",
                "CMO stage directive",
                "test user prompt",
            )
        self.assertIsNone(content)
        self.assertIn("AGENT_DNA_LOAD_FAILED", error)
        self.assertEqual(len(self.gateway.requests), before)


if __name__ == "__main__":
    unittest.main()
