"""Adversarial regression for blocked-goal fail-closed semantics."""

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
    CognitiveDirectiveKind,
    CognitivePhase,
    CognitiveCycleRequest,
    derive_cognitive_cycle,
)
from brain.planning import PlanSnapshot, PlanStep


class BrainBlockedGoalFailClosedV1Tests(unittest.TestCase):
    def goal(self, **overrides):
        data = dict(
            goal_id="goal-blocked-1",
            objective="Proceed only while the canonical goal is actionable",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Validated next step"],
            constraints=["No action while blocked"],
        )
        data.update(overrides)
        return GoalSpec(**data)

    def plan(self):
        return PlanSnapshot(
            plan_id="plan-blocked-1",
            goal_id="goal-blocked-1",
            steps=[
                PlanStep(
                    step_id="step-blocked-1",
                    goal_id="goal-blocked-1",
                    owner_agent=BrainAgentId.CMO,
                    objective="Prepare the validated next action",
                    completion_criteria=["Decision recorded"],
                    action_intent_ids=["intent-blocked-1"],
                )
            ],
        )

    def decision(self):
        return DecisionRecord(
            decision_id="decision-blocked-1",
            goal_id="goal-blocked-1",
            agent_id=BrainAgentId.CMO,
            statement="Proceed when the goal is actionable",
            rationale="Canonical evidence supports the semantic path",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["ev-blocked-1"],
        )

    def intent(self):
        return ActionIntent(
            intent_id="intent-blocked-1",
            goal_id="goal-blocked-1",
            owner_agent=BrainAgentId.CMO,
            purpose="Run the selected semantic action",
            capability_need="MARKET_EXPERIMENT",
            expected_observation="Observed experiment outcome",
            decision_id="decision-blocked-1",
            evidence_required=True,
        )

    def request(self, goal):
        return CognitiveCycleRequest(
            cycle_id="cycle-blocked-1",
            goal=goal,
            evidence_needs=[],
            unknowns=[],
            plan=self.plan(),
            decisions=[self.decision()],
            action_intents=[self.intent()],
            reflection_reports=[],
        )

    def assert_blocked_fail_closed(self, cycle):
        self.assertEqual(cycle.phase.value, "BLOCKED")
        self.assertNotEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, [])
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.STOP],
        )
        self.assertNotEqual(cycle.phase, CognitivePhase.COMPLETE)

    def test_canonical_blocked_goal_cannot_reach_action_ready(self):
        cycle = derive_cognitive_cycle(
            self.request(self.goal(status=GoalStatus.BLOCKED))
        )
        self.assert_blocked_fail_closed(cycle)

    def test_post_construction_blocked_mutation_is_revalidated_and_fails_closed(self):
        goal = self.goal()
        request = self.request(goal)
        request.goal.status = GoalStatus.BLOCKED
        cycle = derive_cognitive_cycle(request)
        self.assert_blocked_fail_closed(cycle)

    def test_open_goal_baseline_remains_action_ready(self):
        cycle = derive_cognitive_cycle(self.request(self.goal(status=GoalStatus.OPEN)))
        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, ["intent-blocked-1"])
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.PREPARE_ACTION],
        )


if __name__ == "__main__":
    unittest.main()
