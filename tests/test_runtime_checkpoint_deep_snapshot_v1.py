"""Adversarial RED for RuntimeContext checkpoint snapshot isolation.

ExecutionCheckpoint advertises a snapshot of runtime working state. Nested
mutable state must therefore be detached from both the live RuntimeContext and
from later checkpoint consumers. A shallow dict copy is not a snapshot.
"""

from __future__ import annotations

import unittest

from runtime.context import RuntimeContext, RuntimeStage, RuntimeStatus


class RuntimeCheckpointDeepSnapshotV1Tests(unittest.TestCase):
    @staticmethod
    def _context() -> RuntimeContext:
        context = RuntimeContext(
            run_id="RUN-CHECKPOINT-DEEP-SNAPSHOT-V1",
            objective="Prove checkpoint history cannot drift after capture",
            business_id="BIZ-CHECKPOINT-DEEP-SNAPSHOT-V1",
            project_id="PROJ-CHECKPOINT-DEEP-SNAPSHOT-V1",
        )
        context.status = RuntimeStatus.RUNNING
        context.current_stage = RuntimeStage.INTELLIGENCE
        context.working_state["adaptive_plan"] = {
            "waves": [["intelligence-market", "intelligence-customers"]],
            "metadata": {
                "selected_kinds": ["intelligence.market", "intelligence.customers"],
                "rejected_kinds": [],
            },
        }
        context.working_state["audit"] = [
            {"event": "PLAN_COMPILED", "details": {"mode": "ADAPTIVE_DAG"}}
        ]
        return context

    def test_live_nested_mutation_cannot_rewrite_historical_checkpoint(self) -> None:
        context = self._context()
        checkpoint = context.create_checkpoint()

        expected_snapshot = {
            "adaptive_plan": {
                "waves": [["intelligence-market", "intelligence-customers"]],
                "metadata": {
                    "selected_kinds": ["intelligence.market", "intelligence.customers"],
                    "rejected_kinds": [],
                },
            },
            "audit": [
                {"event": "PLAN_COMPILED", "details": {"mode": "ADAPTIVE_DAG"}}
            ],
        }

        context.working_state["adaptive_plan"]["waves"][0].append("MUTATED-LATER")
        context.working_state["adaptive_plan"]["metadata"]["rejected_kinds"].append("late.kind")
        context.working_state["audit"][0]["details"]["mode"] = "REWRITTEN_AFTER_CHECKPOINT"
        context.working_state["audit"].append({"event": "LATE_EVENT"})

        self.assertEqual(
            checkpoint.working_state_snapshot,
            expected_snapshot,
            "a historical checkpoint must not drift when live nested working_state mutates later",
        )

    def test_checkpoint_nested_mutation_cannot_modify_live_working_state(self) -> None:
        context = self._context()
        checkpoint = context.create_checkpoint()

        checkpoint.working_state_snapshot["adaptive_plan"]["waves"][0].append("SNAPSHOT-ONLY")
        checkpoint.working_state_snapshot["adaptive_plan"]["metadata"]["selected_kinds"].clear()
        checkpoint.working_state_snapshot["audit"][0]["details"]["mode"] = "SNAPSHOT-TAMPER"

        self.assertEqual(
            context.working_state["adaptive_plan"]["waves"],
            [["intelligence-market", "intelligence-customers"]],
            "checkpoint consumers must not be able to mutate live nested runtime state through aliases",
        )
        self.assertEqual(
            context.working_state["adaptive_plan"]["metadata"]["selected_kinds"],
            ["intelligence.market", "intelligence.customers"],
        )
        self.assertEqual(
            context.working_state["audit"][0]["details"]["mode"],
            "ADAPTIVE_DAG",
        )

    def test_top_level_snapshot_mapping_is_already_detached_control(self) -> None:
        context = self._context()
        checkpoint = context.create_checkpoint()
        context.working_state["new_top_level_key"] = {"value": 1}

        self.assertNotIn("new_top_level_key", checkpoint.working_state_snapshot)


if __name__ == "__main__":
    unittest.main()
