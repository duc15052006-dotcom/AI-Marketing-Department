"""Adversarial tests for provider-neutral Brain planning/replanning v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.planning as planning
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


class BrainPlanningReplanningV1Tests(unittest.TestCase):
    @staticmethod
    def _step(
        step_id: str,
        *,
        depends_on=None,
        state=PlanStepState.PENDING,
        owner="INTELLIGENCE",
    ) -> PlanStep:
        return PlanStep(
            step_id=step_id,
            goal_id="G-1",
            owner_agent=owner,
            objective=f"Complete {step_id}",
            depends_on=list(depends_on or []),
            completion_criteria=[f"{step_id} has a defensible result"],
            state=state,
        )

    def test_valid_dag_exposes_only_dependency_ready_pending_steps(self) -> None:
        plan = PlanSnapshot(
            plan_id="P-1",
            goal_id="G-1",
            steps=[
                self._step("S-1", state=PlanStepState.COMPLETED),
                self._step("S-2", depends_on=["S-1"]),
                self._step("S-3", depends_on=["S-2"]),
                self._step("S-4", state=PlanStepState.BLOCKED),
            ],
        )
        self.assertEqual(ready_step_ids(plan), ["S-2"])

        paused_for_replan = PlanSnapshot(
            plan_id="P-REPLAN",
            goal_id="G-1",
            status=PlanStatus.NEEDS_REVISION,
            steps=[self._step("S-R")],
        )
        self.assertEqual(
            ready_step_ids(paused_for_replan),
            [],
            "A plan marked NEEDS_REVISION must not expose stale steps as actionable.",
        )

    def test_plan_rejects_self_unknown_and_cyclic_dependencies(self) -> None:
        with self.assertRaises(ValidationError):
            self._step("S-1", depends_on=["S-1"])

        with self.assertRaises(ValidationError):
            PlanSnapshot(
                plan_id="P-UNKNOWN",
                goal_id="G-1",
                steps=[self._step("S-1", depends_on=["S-MISSING"])],
            )

        with self.assertRaises(ValidationError):
            PlanSnapshot(
                plan_id="P-CYCLE",
                goal_id="G-1",
                steps=[
                    self._step("S-1", depends_on=["S-2"]),
                    self._step("S-2", depends_on=["S-1"]),
                ],
            )

    def test_completed_step_cannot_claim_completion_before_dependency(self) -> None:
        with self.assertRaises(ValidationError):
            PlanSnapshot(
                plan_id="P-ORDER",
                goal_id="G-1",
                steps=[
                    self._step("S-1"),
                    self._step(
                        "S-2",
                        depends_on=["S-1"],
                        state=PlanStepState.COMPLETED,
                    ),
                ],
            )

    def test_satisfied_plan_requires_all_steps_completed(self) -> None:
        with self.assertRaises(ValidationError):
            PlanSnapshot(
                plan_id="P-SAT",
                goal_id="G-1",
                status=PlanStatus.SATISFIED,
                steps=[self._step("S-1")],
            )

    def test_noninitial_snapshot_requires_linear_parent_and_reason(self) -> None:
        with self.assertRaises(ValidationError):
            PlanSnapshot(
                plan_id="P-BAD-REV",
                goal_id="G-1",
                revision=2,
                parent_revision=None,
                revision_reason="New evidence",
                steps=[self._step("S-1")],
            )
        with self.assertRaises(ValidationError):
            PlanSnapshot(
                plan_id="P-BAD-PARENT",
                goal_id="G-1",
                revision=3,
                parent_revision=1,
                revision_reason="Skipped lineage",
                steps=[self._step("S-1")],
            )

    def test_revision_requires_explicit_fate_for_every_prior_step(self) -> None:
        plan = PlanSnapshot(
            plan_id="P-1",
            goal_id="G-1",
            steps=[self._step("S-1"), self._step("S-2", depends_on=["S-1"])],
        )
        revision = PlanRevision(
            revision_id="R-1",
            plan_id="P-1",
            from_revision=1,
            trigger=RevisionTrigger.NEW_EVIDENCE,
            reason="New evidence invalidates the first path",
            invalidated_step_ids=["S-1"],
            replacement_steps=[self._step("S-3")],
        )
        with self.assertRaises(ValidationError):
            apply_plan_revision(plan, revision)

    def test_revision_cannot_preserve_and_invalidate_same_step(self) -> None:
        with self.assertRaises(ValidationError):
            PlanRevision(
                revision_id="R-OVERLAP",
                plan_id="P-1",
                from_revision=1,
                trigger="CONTRADICTION",
                reason="Contradictory classification",
                preserved_step_ids=["S-1"],
                invalidated_step_ids=["S-1"],
            )

    def test_noop_revision_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            PlanRevision(
                revision_id="R-NOOP",
                plan_id="P-1",
                from_revision=1,
                trigger=RevisionTrigger.BETTER_PATH,
                reason="No actual plan change",
                preserved_step_ids=["S-1"],
            )

    def test_revision_is_snapshot_based_and_does_not_mutate_prior_plan(self) -> None:
        plan = PlanSnapshot(
            plan_id="P-1",
            goal_id="G-1",
            steps=[
                self._step("S-1", state=PlanStepState.COMPLETED),
                self._step("S-2", depends_on=["S-1"]),
            ],
        )
        before = plan.model_dump()
        revision = PlanRevision(
            revision_id="R-1",
            plan_id="P-1",
            from_revision=1,
            trigger=RevisionTrigger.USER_STEERING,
            reason="User narrowed the target segment",
            preserved_step_ids=["S-1"],
            invalidated_step_ids=["S-2"],
            replacement_steps=[self._step("S-3", depends_on=["S-1"])],
        )

        revised = apply_plan_revision(plan, revision)

        self.assertEqual(plan.model_dump(), before)
        self.assertEqual(plan.revision, 1)
        self.assertEqual(revised.revision, 2)
        self.assertEqual(revised.parent_revision, 1)
        self.assertEqual([step.step_id for step in revised.steps], ["S-1", "S-3"])

    def test_invalidated_dependency_cannot_be_silently_referenced(self) -> None:
        plan = PlanSnapshot(
            plan_id="P-1",
            goal_id="G-1",
            steps=[self._step("S-1"), self._step("S-2", depends_on=["S-1"])],
        )
        revision = PlanRevision(
            revision_id="R-1",
            plan_id="P-1",
            from_revision=1,
            trigger=RevisionTrigger.FAILED_ASSUMPTION,
            reason="The premise behind S-1 is false",
            preserved_step_ids=["S-2"],
            invalidated_step_ids=["S-1"],
        )
        with self.assertRaises(ValidationError):
            apply_plan_revision(plan, revision)

    def test_replacement_step_identity_cannot_reuse_historical_step_id(self) -> None:
        plan = PlanSnapshot(
            plan_id="P-1",
            goal_id="G-1",
            steps=[self._step("S-1")],
        )
        revision = PlanRevision(
            revision_id="R-1",
            plan_id="P-1",
            from_revision=1,
            trigger=RevisionTrigger.BETTER_PATH,
            reason="A better path was found",
            invalidated_step_ids=["S-1"],
            replacement_steps=[self._step("S-1")],
        )
        with self.assertRaises(ValidationError):
            apply_plan_revision(plan, revision)

    def test_terminal_plan_cannot_be_replanned_in_place(self) -> None:
        completed = self._step("S-1", state=PlanStepState.COMPLETED)
        plan = PlanSnapshot(
            plan_id="P-1",
            goal_id="G-1",
            status=PlanStatus.SATISFIED,
            steps=[completed],
        )
        revision = PlanRevision(
            revision_id="R-1",
            plan_id="P-1",
            from_revision=1,
            trigger=RevisionTrigger.CHANGED_CONTEXT,
            reason="Context changed after completion",
            invalidated_step_ids=["S-1"],
            replacement_steps=[self._step("S-2")],
        )
        with self.assertRaises(ValidationError):
            apply_plan_revision(plan, revision)

    def test_planning_module_has_no_body_layer_imports(self) -> None:
        source = inspect.getsource(planning)
        tree = ast.parse(source)
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "knowledge",
            "memory",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

        public_dump = PlanSnapshot(
            plan_id="P-CLEAN",
            goal_id="G-1",
            steps=[self._step("S-1")],
        ).model_dump()
        self.assertNotIn("provider_id", str(public_dump))
        self.assertNotIn("tool_id", str(public_dump))
        self.assertNotIn("queue_id", str(public_dump))
        self.assertNotIn("RUNNING", str(public_dump))
        self.assertNotIn("RETRY", str(public_dump))


if __name__ == "__main__":
    unittest.main()
