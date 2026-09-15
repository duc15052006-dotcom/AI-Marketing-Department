from __future__ import annotations

import unittest

from memory.models import MemoryType, PromotionState
from memory.repository import LocalMemoryRepository
from runtime.artifacts import MemoryWriteCandidate
from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime


class MemoryWriteScopeIsolationV1Tests(unittest.TestCase):
    def test_complete_run_persists_candidate_under_exact_trusted_memory_scope(self) -> None:
        repository = LocalMemoryRepository()
        runtime = FiveAgentDepartmentRuntime(
            model_gateway=object(),
            memory_repo=repository,
        )
        trusted_scope = "SCOPE_TENANT_ALPHA_PRIVATE"
        context = RuntimeContext(
            run_id="RUN-MEMORY-SCOPE-ALPHA",
            objective="Scoped memory persistence regression",
            business_id="BIZ_ALPHA",
            campaign_id="CAMP_ALPHA",
            user_id="USER_ALPHA",
            trusted_memory_scope=trusted_scope,
            status=RuntimeStatus.RUNNING,
        )
        # Mutable shared state is attacker-controlled and must never become
        # persistence authority over the immutable trusted scope.
        context.working_state["memory_scope"] = "SCOPE_ATTACKER"
        context.stage_outputs["final_cmo"] = {
            "status": "READY_FOR_DEPLOYMENT",
            "approval_status": "APPROVED_WITH_CONDITIONS",
        }

        artifact = runtime.complete_run(context)
        memories = repository.list_memories(run_id=context.run_id)

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].scope, trusted_scope)
        self.assertNotEqual(memories[0].scope, "SCOPE_ATTACKER")
        self.assertNotEqual(memories[0].scope, "GLOBAL")
        self.assertEqual(len(artifact.learning_candidates), 1)
        self.assertEqual(artifact.learning_candidates[0].scope, trusted_scope)
        self.assertNotEqual(artifact.learning_candidates[0].scope, "SCOPE_ATTACKER")

    def test_legacy_direct_candidate_without_scope_remains_global(self) -> None:
        candidate = MemoryWriteCandidate(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="cmo",
            content="Legacy direct candidate",
            confidence=0.5,
            target_initial_state=PromotionState.CANDIDATE_MEMORY,
        )

        item = candidate.to_memory_item("RUN-LEGACY-GLOBAL")

        self.assertEqual(candidate.scope, "GLOBAL")
        self.assertEqual(item.scope, "GLOBAL")


if __name__ == "__main__":
    unittest.main()
