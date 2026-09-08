from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId
from brain.planning import (
    PlanRevision,
    PlanSnapshot,
    PlanStatus,
    PlanStep,
    PlanStepState,
    RevisionTrigger,
    apply_plan_revision,
    ready_step_ids,
)
from schemas.base import ValidationError


class BrainPlanSnapshotIntegrityV1Tests(unittest.TestCase):
    @staticmethod
    def _blocked_plan() -> PlanSnapshot:
        return PlanSnapshot(
            plan_id="P-INTEGRITY",
            goal_id="G-INTEGRITY",
            status=PlanStatus.ACTIVE,
            steps=[
                PlanStep(
                    step_id="S-ROOT",
                    goal_id="G-INTEGRITY",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    objective="Establish prerequisite evidence.",
                    state=PlanStepState.PENDING,
                ),
                PlanStep(
                    step_id="S-CHILD",
                    goal_id="G-INTEGRITY",
                    owner_agent=BrainAgentId.STRATEGIST,
                    objective="Act only after the prerequisite.",
                    depends_on=["S-ROOT"],
                    state=PlanStepState.PENDING,
                ),
            ],
        )

    def test_dependency_removal_after_validation_fails_closed(self) -> None:
        plan = self._blocked_plan()
        self.assertNotIn("S-CHILD", ready_step_ids(plan))
        plan.steps[1].depends_on = []
        with self.assertRaises(ValidationError):
            ready_step_ids(plan)

    def test_schema_valid_state_mutation_after_validation_fails_closed(self) -> None:
        plan = self._blocked_plan()
        plan.steps[0].state = PlanStepState.COMPLETED
        with self.assertRaises(ValidationError):
            ready_step_ids(plan)

    def test_plan_status_mutation_after_validation_fails_closed(self) -> None:
        plan = self._blocked_plan()
        plan.status = PlanStatus.ABANDONED
        with self.assertRaises(ValidationError):
            ready_step_ids(plan)

    def test_new_snapshot_can_legitimately_advance_dependency_state(self) -> None:
        advanced = PlanSnapshot(
            plan_id="P-INTEGRITY-ADVANCED",
            goal_id="G-INTEGRITY",
            status=PlanStatus.ACTIVE,
            steps=[
                PlanStep(
                    step_id="S-ROOT",
                    goal_id="G-INTEGRITY",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    objective="Establish prerequisite evidence.",
                    state=PlanStepState.COMPLETED,
                ),
                PlanStep(
                    step_id="S-CHILD",
                    goal_id="G-INTEGRITY",
                    owner_agent=BrainAgentId.STRATEGIST,
                    objective="Act only after the prerequisite.",
                    depends_on=["S-ROOT"],
                    state=PlanStepState.PENDING,
                ),
            ],
        )
        self.assertIn("S-CHILD", ready_step_ids(advanced))

    def test_mutated_snapshot_cannot_be_smuggled_through_revision(self) -> None:
        plan = self._blocked_plan()
        plan.steps[1].depends_on = []
        revision = PlanRevision(
            revision_id="PR-INTEGRITY",
            plan_id="P-INTEGRITY",
            from_revision=1,
            trigger=RevisionTrigger.BETTER_PATH,
            reason="Create an explicit new cognitive path.",
            preserved_step_ids=["S-ROOT"],
            invalidated_step_ids=["S-CHILD"],
            replacement_steps=[
                PlanStep(
                    step_id="S-REPLACEMENT",
                    goal_id="G-INTEGRITY",
                    owner_agent=BrainAgentId.STRATEGIST,
                    objective="Use the revised explicit path.",
                    depends_on=["S-ROOT"],
                    state=PlanStepState.PENDING,
                )
            ],
        )
        with self.assertRaises(ValidationError):
            apply_plan_revision(plan, revision)


if __name__ == "__main__":
    unittest.main()
