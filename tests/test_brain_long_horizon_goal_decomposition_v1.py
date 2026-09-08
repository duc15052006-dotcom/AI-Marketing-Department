from __future__ import annotations

import inspect
import unittest

import brain
from brain.contracts import BrainAgentId, GoalSpec, GoalStatus
from schemas.base import ValidationError

try:
    import brain.goal_decomposition as goal_decomposition_module
    from brain.goal_decomposition import (
        GoalDecomposition,
        GoalDecompositionRequest,
        GoalDependency,
        SuccessCriterionTrace,
        build_goal_decomposition,
    )

    GOAL_DECOMPOSITION_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability does not exist yet.
    GOAL_DECOMPOSITION_IMPORT_ERROR = exc


class BrainLongHorizonGoalDecompositionV1Tests(unittest.TestCase):
    def _require_capability(self) -> None:
        if GOAL_DECOMPOSITION_IMPORT_ERROR is not None:
            self.fail(
                "LONG_HORIZON_GOAL_DECOMPOSITION_CAPABILITY_MISSING: "
                f"{GOAL_DECOMPOSITION_IMPORT_ERROR}"
            )

    def _goal(
        self,
        goal_id: str,
        *,
        parent_goal_id: str | None = None,
        owner_agent: BrainAgentId = BrainAgentId.STRATEGIST,
        objective: str | None = None,
        success_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        status: GoalStatus = GoalStatus.OPEN,
    ) -> GoalSpec:
        return GoalSpec(
            goal_id=goal_id,
            objective=objective or f"Objective for {goal_id}",
            owner_agent=owner_agent,
            success_criteria=success_criteria or [],
            constraints=constraints or [],
            parent_goal_id=parent_goal_id,
            status=status,
        )

    def _dependency(self, prerequisite: str, dependent: str):
        self._require_capability()
        return GoalDependency(
            prerequisite_goal_id=prerequisite,
            dependent_goal_id=dependent,
            rationale=f"{prerequisite} enables {dependent}",
        )

    def _trace(
        self,
        criterion_goal_id: str,
        criterion: str,
        responsible_goal_ids: list[str],
    ):
        self._require_capability()
        return SuccessCriterionTrace(
            criterion_goal_id=criterion_goal_id,
            criterion=criterion,
            responsible_goal_ids=responsible_goal_ids,
        )

    def _request(
        self,
        *,
        root_goal: GoalSpec | None = None,
        subgoals: list[GoalSpec] | None = None,
        dependencies=None,
        criterion_traces=None,
    ):
        self._require_capability()
        root = root_goal or self._goal(
            "goal-root",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Grow qualified revenue", "Protect brand safety"],
            constraints=["Do not exceed approved budget"],
        )
        children = subgoals or [
            self._goal(
                "goal-research",
                parent_goal_id="goal-root",
                owner_agent=BrainAgentId.INTELLIGENCE,
                success_criteria=["Validate demand"],
            ),
            self._goal(
                "goal-strategy",
                parent_goal_id="goal-root",
                owner_agent=BrainAgentId.STRATEGIST,
                success_criteria=["Choose growth strategy"],
            ),
            self._goal(
                "goal-creative",
                parent_goal_id="goal-strategy",
                owner_agent=BrainAgentId.CREATIVE,
                success_criteria=["Produce compliant creative"],
            ),
        ]
        deps = dependencies
        if deps is None:
            deps = [self._dependency("goal-research", "goal-strategy")]
        traces = criterion_traces
        if traces is None:
            traces = [
                self._trace(
                    "goal-root",
                    "Grow qualified revenue",
                    ["goal-strategy", "goal-creative"],
                ),
                self._trace(
                    "goal-root",
                    "Protect brand safety",
                    ["goal-creative"],
                ),
            ]
        return GoalDecompositionRequest(
            decomposition_id="decomposition-growth",
            root_goal=root,
            subgoals=children,
            dependencies=deps,
            criterion_traces=traces,
        )

    def test_valid_nested_cross_agent_decomposition_is_canonical(self) -> None:
        self._require_capability()
        decomposition = build_goal_decomposition(self._request())
        self.assertIsInstance(decomposition, GoalDecomposition)
        self.assertEqual(decomposition.root_goal.goal_id, "goal-root")
        self.assertEqual(
            [goal.goal_id for goal in decomposition.subgoals],
            ["goal-research", "goal-strategy", "goal-creative"],
        )
        self.assertEqual(
            [goal.owner_agent for goal in decomposition.subgoals],
            [
                BrainAgentId.INTELLIGENCE,
                BrainAgentId.STRATEGIST,
                BrainAgentId.CREATIVE,
            ],
        )

    def test_public_brain_api_exports_goal_decomposition_capability(self) -> None:
        self._require_capability()
        for name in (
            "GoalDecomposition",
            "GoalDecompositionRequest",
            "GoalDependency",
            "SuccessCriterionTrace",
            "build_goal_decomposition",
        ):
            self.assertTrue(hasattr(brain, name), name)

    def test_root_cannot_claim_an_external_parent(self) -> None:
        self._require_capability()
        request = self._request(
            root_goal=self._goal("goal-root", parent_goal_id="goal-external")
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_decomposition_requires_at_least_one_subgoal(self) -> None:
        self._require_capability()
        request = GoalDecompositionRequest(
            decomposition_id="decomposition-empty",
            root_goal=self._goal("goal-root"),
            subgoals=[],
            dependencies=[],
            criterion_traces=[],
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_duplicate_goal_ids_fail_closed(self) -> None:
        self._require_capability()
        request = self._request(
            root_goal=self._goal("goal-root"),
            subgoals=[
                self._goal("goal-child", parent_goal_id="goal-root"),
                self._goal("goal-child", parent_goal_id="goal-root"),
            ],
            dependencies=[],
            criterion_traces=[],
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_subgoal_parent_must_exist_inside_same_decomposition(self) -> None:
        self._require_capability()
        request = self._request(
            root_goal=self._goal("goal-root"),
            subgoals=[self._goal("goal-child", parent_goal_id="goal-missing")],
            dependencies=[],
            criterion_traces=[],
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_parent_hierarchy_cycle_fails_closed(self) -> None:
        self._require_capability()
        request = self._request(
            root_goal=self._goal("goal-root"),
            subgoals=[
                self._goal("goal-a", parent_goal_id="goal-b"),
                self._goal("goal-b", parent_goal_id="goal-a"),
            ],
            dependencies=[],
            criterion_traces=[],
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_dependency_endpoints_must_be_known_goals(self) -> None:
        self._require_capability()
        request = self._request(
            dependencies=[self._dependency("goal-research", "goal-unknown")]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_dependency_self_edge_fails_closed(self) -> None:
        self._require_capability()
        request = self._request(
            dependencies=[self._dependency("goal-research", "goal-research")]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_dependency_cycle_fails_closed(self) -> None:
        self._require_capability()
        request = self._request(
            dependencies=[
                self._dependency("goal-research", "goal-strategy"),
                self._dependency("goal-strategy", "goal-research"),
            ]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_duplicate_dependency_edge_fails_closed(self) -> None:
        self._require_capability()
        request = self._request(
            dependencies=[
                self._dependency("goal-research", "goal-strategy"),
                self._dependency("goal-research", "goal-strategy"),
            ]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_sibling_dependency_is_valid_long_horizon_structure(self) -> None:
        self._require_capability()
        decomposition = build_goal_decomposition(self._request())
        edge = decomposition.dependencies[0]
        self.assertEqual(edge.prerequisite_goal_id, "goal-research")
        self.assertEqual(edge.dependent_goal_id, "goal-strategy")

    def test_trace_criterion_must_exist_on_declared_goal(self) -> None:
        self._require_capability()
        request = self._request(
            criterion_traces=[
                self._trace("goal-root", "Fabricated success criterion", ["goal-creative"]),
                self._trace("goal-root", "Protect brand safety", ["goal-creative"]),
            ]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_trace_responsibility_must_bind_true_descendants(self) -> None:
        self._require_capability()
        request = self._request(
            criterion_traces=[
                self._trace(
                    "goal-strategy",
                    "Choose growth strategy",
                    ["goal-research"],
                ),
                self._trace("goal-root", "Grow qualified revenue", ["goal-strategy"]),
                self._trace("goal-root", "Protect brand safety", ["goal-creative"]),
            ]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_trace_owner_cannot_be_its_own_responsible_descendant(self) -> None:
        self._require_capability()
        request = self._request(
            criterion_traces=[
                self._trace("goal-root", "Grow qualified revenue", ["goal-root"]),
                self._trace("goal-root", "Protect brand safety", ["goal-creative"]),
            ]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_every_root_success_criterion_requires_descendant_trace(self) -> None:
        self._require_capability()
        request = self._request(
            criterion_traces=[
                self._trace("goal-root", "Grow qualified revenue", ["goal-strategy"])
            ]
        )
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_intermediate_goal_criterion_can_trace_to_its_descendant(self) -> None:
        self._require_capability()
        request = self._request()
        request.criterion_traces.append(
            self._trace(
                "goal-strategy",
                "Choose growth strategy",
                ["goal-creative"],
            )
        )
        decomposition = build_goal_decomposition(request)
        self.assertEqual(
            decomposition.criterion_traces[-1].criterion_goal_id,
            "goal-strategy",
        )

    def test_goal_semantics_are_preserved_without_silent_dropping(self) -> None:
        self._require_capability()
        child = self._goal(
            "goal-research",
            parent_goal_id="goal-root",
            owner_agent=BrainAgentId.INTELLIGENCE,
            success_criteria=["Evidence threshold met", "Contradictions recorded"],
            constraints=["Observed sources only"],
            status=GoalStatus.BLOCKED,
        )
        request = self._request(
            root_goal=self._goal("goal-root"),
            subgoals=[child],
            dependencies=[],
            criterion_traces=[],
        )
        decomposition = build_goal_decomposition(request)
        canonical = decomposition.subgoals[0]
        self.assertEqual(canonical.success_criteria, child.success_criteria)
        self.assertEqual(canonical.constraints, child.constraints)
        self.assertEqual(canonical.status, GoalStatus.BLOCKED)
        self.assertEqual(canonical.parent_goal_id, "goal-root")

    def test_nested_post_construction_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.subgoals[0].parent_goal_id = "goal-external-after-construction"
        with self.assertRaises(ValidationError):
            build_goal_decomposition(request)

    def test_serialized_request_reconstructs_canonical_runtime_models(self) -> None:
        self._require_capability()
        payload = self._request().model_dump()
        decomposition = build_goal_decomposition(payload)
        self.assertIsInstance(decomposition, GoalDecomposition)
        self.assertIsInstance(decomposition.root_goal, GoalSpec)
        self.assertTrue(all(isinstance(goal, GoalSpec) for goal in decomposition.subgoals))
        self.assertTrue(
            all(isinstance(edge, GoalDependency) for edge in decomposition.dependencies)
        )
        self.assertTrue(
            all(
                isinstance(trace, SuccessCriterionTrace)
                for trace in decomposition.criterion_traces
            )
        )

    def test_output_does_not_alias_caller_owned_nested_inputs(self) -> None:
        self._require_capability()
        request = self._request()
        original_objective = request.subgoals[0].objective
        decomposition = build_goal_decomposition(request)
        decomposition.subgoals[0].objective = "mutated output only"
        self.assertEqual(request.subgoals[0].objective, original_objective)
        self.assertNotEqual(
            request.subgoals[0].objective,
            decomposition.subgoals[0].objective,
        )

    def test_semantic_contract_has_no_probability_confidence_or_runtime_authority(self) -> None:
        self._require_capability()
        model_fields = set(GoalDecompositionRequest.__dataclass_fields__) | set(
            GoalDecomposition.__dataclass_fields__
        )
        self.assertFalse({"confidence", "probability"} & model_fields)
        source = inspect.getsource(goal_decomposition_module)
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
