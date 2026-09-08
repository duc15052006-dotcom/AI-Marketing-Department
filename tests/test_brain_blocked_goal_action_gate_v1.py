import copy
import unittest

from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    GoalSpec,
    GoalStatus,
)
from brain.cognitive_loop import (
    CognitiveCycleRequest,
    CognitiveDirectiveKind,
    CognitivePhase,
    derive_cognitive_cycle,
)
from brain.planning import PlanSnapshot, PlanStep


class BlockedGoalActionGateV1Tests(unittest.TestCase):
    def goal(self, status=GoalStatus.OPEN):
        return GoalSpec(
            goal_id="goal-1",
            objective="Run only while the semantic goal is actionable",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Validated outcome"],
            constraints=["Fail closed while blocked"],
            status=status,
        )

    def plan(self):
        return PlanSnapshot(
            plan_id="plan-1",
            goal_id="goal-1",
            steps=[
                PlanStep(
                    step_id="step-1",
                    goal_id="goal-1",
                    owner_agent=BrainAgentId.CMO,
                    objective="Prepare the validated semantic action",
                    action_intent_ids=["intent-1"],
                )
            ],
        )

    def decision(self):
        return DecisionRecord(
            decision_id="decision-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            statement="Proceed when the goal is actionable",
            rationale="All ordinary semantic bindings are valid",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["ev-1"],
        )

    def intent(self):
        return ActionIntent(
            intent_id="intent-1",
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            purpose="Run the selected experiment",
            capability_need="MARKET_EXPERIMENT",
            expected_observation="Observed experiment outcome",
            decision_id="decision-1",
            evidence_required=False,
        )

    def request(self, status=GoalStatus.OPEN, **overrides):
        data = dict(
            cycle_id="cycle-1",
            goal=self.goal(status=status),
            evidence_needs=[],
            unknowns=[],
            plan=self.plan(),
            decisions=[self.decision()],
            action_intents=[self.intent()],
            reflection_reports=[],
        )
        data.update(overrides)
        return CognitiveCycleRequest(**data)

    def assert_blocked_stop(self, cycle):
        self.assertEqual(cycle.goal.status, GoalStatus.BLOCKED)
        self.assertEqual(cycle.phase, CognitivePhase.COMPLETE)
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.STOP],
        )
        self.assertEqual(cycle.action_intent_ids, [])
        self.assertNotIn(
            CognitiveDirectiveKind.PREPARE_ACTION,
            [directive.kind for directive in cycle.directives],
        )

    def test_blocked_goal_cannot_reach_action_ready_with_clean_artifacts(self):
        cycle = derive_cognitive_cycle(self.request(status=GoalStatus.BLOCKED))
        self.assert_blocked_stop(cycle)

    def test_blocked_goal_stops_before_missing_plan_can_route_to_planning(self):
        cycle = derive_cognitive_cycle(
            self.request(
                status=GoalStatus.BLOCKED,
                plan=None,
                decisions=[],
                action_intents=[],
            )
        )
        self.assert_blocked_stop(cycle)

    def test_serialized_blocked_goal_preserves_fail_closed_gate(self):
        raw = self.request(status=GoalStatus.BLOCKED).model_dump()
        cycle = derive_cognitive_cycle(copy.deepcopy(raw))
        self.assert_blocked_stop(cycle)

    def test_post_construction_status_mutation_is_revalidated_at_use_boundary(self):
        request = self.request()
        request.goal.status = GoalStatus.BLOCKED
        cycle = derive_cognitive_cycle(request)
        self.assert_blocked_stop(cycle)

    def test_open_goal_control_remains_action_ready(self):
        cycle = derive_cognitive_cycle(self.request(status=GoalStatus.OPEN))
        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, ["intent-1"])
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.PREPARE_ACTION],
        )


if __name__ == "__main__":
    unittest.main()
