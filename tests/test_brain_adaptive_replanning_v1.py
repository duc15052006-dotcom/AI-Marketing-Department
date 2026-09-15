from __future__ import annotations

import inspect
import unittest

import brain
from brain.contracts import BrainAgentId
from brain.planning import (
    PlanSnapshot,
    PlanStatus,
    PlanStep,
    PlanStepState,
    RevisionTrigger,
)
from schemas.base import ValidationError

try:
    import brain.adaptive_replanning as adaptive_replanning_module
    from brain.adaptive_replanning import (
        AdaptiveReplanRequest,
        AdaptiveReplanResult,
        ReplanSignal,
        apply_adaptive_replan,
    )

    ADAPTIVE_REPLANNING_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability does not exist yet.
    ADAPTIVE_REPLANNING_IMPORT_ERROR = exc


class BrainAdaptiveReplanningV1Tests(unittest.TestCase):
    def _require_capability(self) -> None:
        if ADAPTIVE_REPLANNING_IMPORT_ERROR is not None:
            self.fail(
                "ADAPTIVE_REPLANNING_CAPABILITY_MISSING: "
                f"{ADAPTIVE_REPLANNING_IMPORT_ERROR}"
            )

    def _step(
        self,
        step_id: str,
        *,
        owner_agent: BrainAgentId = BrainAgentId.CONTENT,
        depends_on: list[str] | None = None,
        state: PlanStepState = PlanStepState.PENDING,
        objective: str | None = None,
    ) -> PlanStep:
        return PlanStep(
            step_id=step_id,
            goal_id="goal-launch",
            owner_agent=owner_agent,
            objective=objective or f"Objective for {step_id}",
            depends_on=depends_on or [],
            completion_criteria=[f"Complete {step_id}"],
            state=state,
        )

    def _plan(self, *, status: PlanStatus = PlanStatus.ACTIVE) -> PlanSnapshot:
        return PlanSnapshot(
            plan_id="plan-launch",
            goal_id="goal-launch",
            revision=3,
            parent_revision=2,
            revision_reason="Previous evidence update",
            status=status,
            steps=[
                self._step(
                    "step-research",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    state=PlanStepState.COMPLETED,
                ),
                self._step(
                    "step-strategy",
                    owner_agent=BrainAgentId.CONTENT,
                    depends_on=["step-research"],
                ),
                self._step(
                    "step-creative",
                    owner_agent=BrainAgentId.CREATIVE,
                    depends_on=["step-strategy"],
                ),
            ],
        )

    def _signal(
        self,
        *,
        affected_step_ids: list[str] | None = None,
        trigger: RevisionTrigger = RevisionTrigger.CONTRADICTION,
        reason: str = "New contradictory evidence invalidates the strategy path",
    ):
        self._require_capability()
        return ReplanSignal(
            signal_id="signal-contradiction-1",
            plan_id="plan-launch",
            goal_id="goal-launch",
            trigger=trigger,
            reason=reason,
            affected_step_ids=(
                ["step-strategy", "step-creative"]
                if affected_step_ids is None
                else affected_step_ids
            ),
        )

    def _replacement_steps(self) -> list[PlanStep]:
        return [
            self._step(
                "step-strategy-v2",
                owner_agent=BrainAgentId.CONTENT,
                depends_on=["step-research"],
            ),
            self._step(
                "step-creative-v2",
                owner_agent=BrainAgentId.CREATIVE,
                depends_on=["step-strategy-v2"],
            ),
        ]

    def _request(
        self,
        *,
        current_plan: PlanSnapshot | None = None,
        signal=None,
        replacement_steps: list[PlanStep] | None = None,
    ):
        self._require_capability()
        return AdaptiveReplanRequest(
            current_plan=current_plan or self._plan(),
            signal=signal or self._signal(),
            replacement_steps=(
                self._replacement_steps()
                if replacement_steps is None
                else replacement_steps
            ),
        )

    def test_valid_replan_delegates_to_canonical_revision_semantics(self) -> None:
        self._require_capability()
        result = apply_adaptive_replan(self._request())
        self.assertIsInstance(result, AdaptiveReplanResult)
        self.assertEqual(result.revision.plan_id, "plan-launch")
        self.assertEqual(result.revision.from_revision, 3)
        self.assertEqual(result.revision.preserved_step_ids, ["step-research"])
        self.assertEqual(
            result.revision.invalidated_step_ids,
            ["step-strategy", "step-creative"],
        )
        self.assertEqual(result.revised_plan.revision, 4)
        self.assertEqual(result.revised_plan.parent_revision, 3)
        self.assertEqual(
            [step.step_id for step in result.revised_plan.steps],
            ["step-research", "step-strategy-v2", "step-creative-v2"],
        )

    def test_public_brain_api_exports_adaptive_replanning_capability(self) -> None:
        self._require_capability()
        for name in (
            "AdaptiveReplanRequest",
            "AdaptiveReplanResult",
            "ReplanSignal",
            "apply_adaptive_replan",
        ):
            self.assertTrue(hasattr(brain, name), name)

    def test_signal_plan_id_must_match_current_plan(self) -> None:
        self._require_capability()
        signal = self._signal()
        signal.plan_id = "plan-other"
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(self._request(signal=signal))

    def test_signal_goal_id_must_match_current_plan(self) -> None:
        self._require_capability()
        signal = self._signal()
        signal.goal_id = "goal-other"
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(self._request(signal=signal))

    def test_affected_step_ids_must_exist_on_current_plan(self) -> None:
        self._require_capability()
        request = self._request(
            signal=self._signal(affected_step_ids=["step-unknown"]),
            replacement_steps=[],
        )
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_duplicate_affected_step_ids_fail_closed(self) -> None:
        self._require_capability()
        with self.assertRaises(ValidationError):
            self._signal(
                affected_step_ids=["step-strategy", "step-strategy"]
            )

    def test_noop_replan_is_rejected(self) -> None:
        self._require_capability()
        request = self._request(
            signal=self._signal(affected_step_ids=[]),
            replacement_steps=[],
        )
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_signal_affected_steps_are_exactly_the_invalidated_prior_steps(self) -> None:
        self._require_capability()
        request = self._request(
            signal=self._signal(affected_step_ids=["step-creative"]),
            replacement_steps=[
                self._step(
                    "step-creative-v2",
                    owner_agent=BrainAgentId.CREATIVE,
                    depends_on=["step-strategy"],
                )
            ],
        )
        result = apply_adaptive_replan(request)
        self.assertEqual(result.revision.invalidated_step_ids, ["step-creative"])
        self.assertEqual(
            result.revision.preserved_step_ids,
            ["step-research", "step-strategy"],
        )

    def test_completed_step_can_be_explicitly_invalidated_when_signal_requires_it(self) -> None:
        self._require_capability()
        request = self._request(
            signal=self._signal(affected_step_ids=["step-research"]),
            replacement_steps=[
                self._step(
                    "step-research-v2",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                ),
                self._step(
                    "step-strategy-v2",
                    owner_agent=BrainAgentId.CONTENT,
                    depends_on=["step-research-v2"],
                ),
                self._step(
                    "step-creative-v2",
                    owner_agent=BrainAgentId.CREATIVE,
                    depends_on=["step-strategy-v2"],
                ),
            ],
        )
        # Explicitly invalidate all downstream steps too so the revised DAG remains valid.
        request.signal.affected_step_ids = [
            "step-research",
            "step-strategy",
            "step-creative",
        ]
        result = apply_adaptive_replan(request)
        self.assertIn("step-research", result.revision.invalidated_step_ids)
        self.assertEqual(result.revised_plan.steps[0].step_id, "step-research-v2")

    def test_terminal_plan_cannot_be_replanned(self) -> None:
        self._require_capability()
        satisfied = PlanSnapshot(
            plan_id="plan-launch",
            goal_id="goal-launch",
            revision=3,
            parent_revision=2,
            revision_reason="Goal completed",
            status=PlanStatus.SATISFIED,
            steps=[
                self._step(
                    "step-done",
                    owner_agent=BrainAgentId.CMO,
                    state=PlanStepState.COMPLETED,
                )
            ],
        )
        request = self._request(
            current_plan=satisfied,
            signal=self._signal(affected_step_ids=["step-done"]),
            replacement_steps=[self._step("step-new")],
        )
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_replacement_step_ids_must_be_fresh(self) -> None:
        self._require_capability()
        request = self._request(
            signal=self._signal(affected_step_ids=["step-strategy"]),
            replacement_steps=[self._step("step-strategy")],
        )
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_replacement_steps_must_remain_bound_to_plan_goal(self) -> None:
        self._require_capability()
        replacement = self._step("step-strategy-v2")
        replacement.goal_id = "goal-other"
        request = self._request(
            signal=self._signal(affected_step_ids=["step-strategy", "step-creative"]),
            replacement_steps=[replacement],
        )
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_dangling_dependency_after_invalidation_fails_closed(self) -> None:
        self._require_capability()
        request = self._request(
            signal=self._signal(affected_step_ids=["step-strategy"]),
            replacement_steps=[],
        )
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_replacement_dependency_cycle_fails_closed(self) -> None:
        self._require_capability()
        request = self._request(
            replacement_steps=[
                self._step("step-strategy-v2", depends_on=["step-creative-v2"]),
                self._step("step-creative-v2", depends_on=["step-strategy-v2"]),
            ]
        )
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_cross_agent_step_ownership_is_preserved(self) -> None:
        self._require_capability()
        result = apply_adaptive_replan(self._request())
        owners = {
            step.step_id: step.owner_agent for step in result.revised_plan.steps
        }
        self.assertEqual(owners["step-research"], BrainAgentId.INTELLIGENCE)
        self.assertEqual(owners["step-strategy-v2"], BrainAgentId.CONTENT)
        self.assertEqual(owners["step-creative-v2"], BrainAgentId.CREATIVE)

    def test_signal_provenance_is_preserved_in_revision(self) -> None:
        self._require_capability()
        signal = self._signal(
            trigger=RevisionTrigger.CHANGED_CONTEXT,
            reason="Campaign constraints changed after user steering",
        )
        result = apply_adaptive_replan(self._request(signal=signal))
        self.assertEqual(result.signal.signal_id, signal.signal_id)
        self.assertEqual(result.revision.trigger, RevisionTrigger.CHANGED_CONTEXT)
        self.assertEqual(result.revision.reason, signal.reason)
        self.assertEqual(result.revised_plan.revision_reason, signal.reason)
        self.assertEqual(
            result.revision.revision_id,
            f"adaptive-replan:{signal.signal_id}",
        )

    def test_nested_plan_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.current_plan.steps[0].goal_id = "goal-mutated-after-construction"
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_nested_signal_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.signal.affected_step_ids.append("step-unknown-after-construction")
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_nested_replacement_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.replacement_steps[0].depends_on.append("step-missing-after-construction")
        with self.assertRaises(ValidationError):
            apply_adaptive_replan(request)

    def test_serialized_request_reconstructs_canonical_runtime_models(self) -> None:
        self._require_capability()
        payload = self._request().model_dump()
        result = apply_adaptive_replan(payload)
        self.assertIsInstance(result, AdaptiveReplanResult)
        self.assertIsInstance(result.current_plan, PlanSnapshot)
        self.assertIsInstance(result.signal, ReplanSignal)
        self.assertTrue(
            all(isinstance(step, PlanStep) for step in result.revision.replacement_steps)
        )
        self.assertIsInstance(result.revised_plan, PlanSnapshot)

    def test_output_does_not_alias_caller_owned_nested_inputs(self) -> None:
        self._require_capability()
        request = self._request()
        original_objective = request.current_plan.steps[0].objective
        result = apply_adaptive_replan(request)
        result.current_plan.steps[0].objective = "mutated result only"
        result.revised_plan.steps[0].objective = "mutated revised plan only"
        self.assertEqual(request.current_plan.steps[0].objective, original_objective)
        self.assertNotEqual(
            request.current_plan.steps[0].objective,
            result.current_plan.steps[0].objective,
        )

    def test_semantic_contract_has_no_probability_confidence_or_runtime_authority(self) -> None:
        self._require_capability()
        model_fields = (
            set(ReplanSignal.__dataclass_fields__)
            | set(AdaptiveReplanRequest.__dataclass_fields__)
            | set(AdaptiveReplanResult.__dataclass_fields__)
        )
        self.assertFalse({"confidence", "probability"} & model_fields)
        source = inspect.getsource(adaptive_replanning_module)
        forbidden_import_fragments = (
            "import runtime",
            "from runtime",
            "import providers",
            "from providers",
            "import tools",
            "from tools",
            "import connectors",
            "from connectors",
            "import persistence",
            "from persistence",
        )
        for fragment in forbidden_import_fragments:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
