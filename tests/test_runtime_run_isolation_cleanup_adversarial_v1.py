"""Adversarial regression for run-scoped lineage and transient tool-cache cleanup."""
from __future__ import annotations
import os, unittest
from unittest.mock import patch
from knowledge.models import KnowledgeCitation
from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus
from tools.tool_gateway import ToolGateway

class RuntimeRunIsolationCleanupAdversarialV1Tests(unittest.TestCase):
    @staticmethod
    def _receipt(run_id: str) -> ExecutionReceipt:
        return ExecutionReceipt(run_id=run_id, agent_id="intelligence", capability_id="web_search", provider="test", request_hash=f"hash-{run_id}", status=ExecutionStatus.BLOCKED, execution_mode=ExecutionMode.MOCK)
    def test_completed_artifact_uses_only_context_lineage_and_clears_its_transient_cache(self) -> None:
        env = {"AI_MARKETING_KNOWLEDGE_EPHEMERAL": "1", "AI_MARKETING_MEMORY_EPHEMERAL": "1", "AI_MARKETING_LEARNING_EPHEMERAL": "1"}
        with patch.dict(os.environ, env, clear=False):
            runtime = FiveAgentDepartmentRuntime(tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()))
            run_id = "RUN-ISOLATION-A"; context = RuntimeContext(run_id=run_id, objective="isolation probe", status=RuntimeStatus.FAILED)
            context.stage_outputs["final_cmo"] = {"status": "FAILED"}; context.knowledge_refs = ["CIT-CURRENT-RUN"]
            runtime.lineage_inspector.add_citation(KnowledgeCitation(citation_id="CIT-OTHER-RUN", knowledge_id="KNOW-OTHER")); runtime._active_contexts[run_id] = context
            own_key = f"{run_id}:intelligence:web_search:isolation probe"; other_key = "RUN-ISOLATION-B:intelligence:web_search:other"
            runtime._executed_tool_idempotency_keys[own_key] = self._receipt(run_id); runtime._executed_tool_idempotency_keys[other_key] = self._receipt("RUN-ISOLATION-B")
            artifact = runtime.complete_run(context)
            self.assertEqual(artifact.lineage_summary.get("citations"), ["CIT-CURRENT-RUN"]); self.assertNotIn(own_key, runtime._executed_tool_idempotency_keys); self.assertIn(other_key, runtime._executed_tool_idempotency_keys); self.assertEqual(runtime.lineage_inspector.get_all_citations(), [])

if __name__ == "__main__": unittest.main()
