"""Adversarial regression for canonical project provenance on tool evidence.

Two project-scoped runs under the same business must not collapse their
ToolGateway observation evidence onto the same legacy business-only scope.
"""

from __future__ import annotations

import unittest

from runtime.context import RuntimeContext
from runtime.context_compiler import ContextCompiler
from runtime.scope_bridge import build_runtime_canonical_scope_plan
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class ToolObservationCanonicalProjectProvenanceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = ContextCompiler(capability_registry=CapabilityRegistry())

    def _compile_project_observation(self, project_id: str):
        ctx = RuntimeContext(
            run_id=f"RUN-{project_id}",
            objective="Audit campaign performance",
            business_id="BIZ_SHARED",
            project_id=project_id,
            chat_id=f"CHAT-{project_id}",
        )
        receipt = ExecutionReceipt(
            execution_id=f"EXEC-{project_id}",
            run_id=ctx.run_id,
            agent_id="performance",
            capability_id="analytics_retrieval",
            provider="analytics_adapter",
            request_hash=f"HASH-{project_id}",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            business_id=ctx.business_id,
            project_id=ctx.project_id,
            chat_id=ctx.chat_id,
            data={"project_marker": project_id},
        )
        package = self.compiler.compile_grounded_package(
            "performance",
            ctx,
            tool_receipts=[receipt],
        )
        tool_items = [
            item for item in package.evidence_items if item.source_type == "TOOL_RECEIPT"
        ]
        self.assertEqual(len(tool_items), 1)
        expected_scope = build_runtime_canonical_scope_plan(ctx).knowledge_scope_keys[0]
        return tool_items[0], expected_scope

    def test_same_business_distinct_projects_keep_distinct_canonical_scope(self) -> None:
        project_a, expected_a = self._compile_project_observation("PROJ_A")
        project_b, expected_b = self._compile_project_observation("PROJ_B")

        self.assertEqual(expected_a, "PROJECT:PROJ_A")
        self.assertEqual(expected_b, "PROJECT:PROJ_B")
        self.assertEqual(project_a.scope, expected_a)
        self.assertEqual(project_b.scope, expected_b)
        self.assertNotEqual(project_a.scope, project_b.scope)


if __name__ == "__main__":
    unittest.main()
