"""Adversarial regression for runtime decision-memory write scope authority."""

from __future__ import annotations

import unittest

from memory.repository import LocalMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.context import RuntimeStatus


class RuntimeMemoryWriteScopeAuthorityV1Tests(unittest.TestCase):
    def test_complete_run_ignores_mutable_memory_scope_spoof_and_writes_project_scope(self) -> None:
        memory_repo = LocalMemoryRepository()
        runtime = FiveAgentDepartmentRuntime(memory_repo=memory_repo)
        context = runtime.start_run(
            objective="authoritative memory write scope",
            business_id="BIZ_A",
            project_id="PROJ_A",
        )

        # Mutable shared state is intentionally attacker-controlled/non-authoritative.
        context.working_state["memory_scope"] = "SCOPE_ATTACKER"
        context.stage_outputs["final_cmo"] = {
            "status": "READY_FOR_DEPLOYMENT",
            "approval_status": "APPROVED",
        }
        context.status = RuntimeStatus.RUNNING

        artifact = runtime.complete_run(context)

        saved = memory_repo.list_memories(run_id=context.run_id)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].scope, "PROJECT:PROJ_A")
        self.assertNotEqual(saved[0].scope, "SCOPE_ATTACKER")

        self.assertEqual(len(artifact.learning_candidates), 1)
        self.assertEqual(artifact.learning_candidates[0].scope, "PROJECT:PROJ_A")

    def test_complete_run_business_only_scope_is_not_global(self) -> None:
        memory_repo = LocalMemoryRepository()
        runtime = FiveAgentDepartmentRuntime(memory_repo=memory_repo)
        context = runtime.start_run(
            objective="business memory write scope",
            business_id="BIZ_A",
        )
        context.stage_outputs["final_cmo"] = {
            "status": "READY_FOR_DEPLOYMENT",
            "approval_status": "APPROVED",
        }
        context.status = RuntimeStatus.RUNNING

        runtime.complete_run(context)

        saved = memory_repo.list_memories(run_id=context.run_id)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].scope, "BUSINESS:BIZ_A")


if __name__ == "__main__":
    unittest.main()
