"""Regression coverage for valid extension-only structured handoff payloads."""

import json
import unittest

from runtime.context import RuntimeContext
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.handoff import HANDOFF_SENTINEL
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class StructuredHandoffEmptyExtension29Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = FiveAgentDepartmentRuntime(
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )

    @staticmethod
    def _raw(payload):
        return f"visible prose\n{HANDOFF_SENTINEL}\n```json\n{json.dumps(payload)}\n```"

    def test_creative_spec_survives_empty_epistemic_buckets(self):
        context = RuntimeContext(run_id="RUN-EMPTY-CREATIVE", objective="test")
        payload = {
            "facts": [], "observations": [], "assumptions": [], "unknowns": [],
            "hypotheses": [], "recommendations": [], "claims": [],
            "creative_spec": {"concept_name": "SOURCE-PRODUCED-CONCEPT"},
        }
        output, parsed, status = self.runtime._finalize_stage_handoff(
            context,
            "creative",
            "creative",
            self._raw(payload),
            {"stage": "CREATIVE", "agent": "creative", "status": "COMPLETED"},
        )
        self.assertEqual(status, "EMPTY")
        self.assertIsInstance(parsed, dict)
        self.assertEqual(output["creative_spec"]["concept_name"], "SOURCE-PRODUCED-CONCEPT")

    def test_performance_evaluation_survives_empty_epistemic_buckets(self):
        context = RuntimeContext(run_id="RUN-EMPTY-PERF", objective="test")
        payload = {
            "facts": [], "observations": [], "assumptions": [], "unknowns": [],
            "hypotheses": [], "recommendations": [], "claims": [],
            "evaluation": {"evaluation_status": "INCONCLUSIVE"},
        }
        output, parsed, status = self.runtime._finalize_stage_handoff(
            context,
            "performance",
            "performance",
            self._raw(payload),
            {
                "stage": "PERFORMANCE",
                "agent": "performance",
                "status": "COMPLETED",
                "funnel_kpi": "insufficient evidence",
                "experiment_blueprint": {},
            },
        )
        self.assertEqual(status, "EMPTY")
        self.assertIsInstance(parsed, dict)
        self.assertEqual(output["evaluation"]["evaluation_status"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
