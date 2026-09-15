import unittest

from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    GoalSpec,
)
from brain.cognitive_loop import (
    CognitiveCycleRequest,
    CognitiveDirectiveKind,
    CognitivePhase,
    derive_cognitive_cycle,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStep


class BrainAbandonedPlanRoutingV1Tests(unittest.TestCase):
    def goal(self):
        return GoalSpec(
            goal_id="goal-1",
            objective="Choose a valid next cognitive path",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["A canonical plan path exists"],
            constraints=["No impossible plan revision directives"],
        )

    def plan(self, status=PlanStatus.ACTIVE):
        return PlanSnapshot(
            plan_id="plan-1",
            goal_id="goal-1",
            status=status,
            steps=[
                PlanStep(
                    step_id="step-1",
                    goal_id="goal-1",
                    owner_agent=BrainAgentId.CMO,
                    objective="Prepare the next semantic action",
                    completion_criteria=["Decision recorded"],
                    action_intent_ids=["intent-1"],
                )
            ],
        )

    def decision(self):
        return DecisionRecord(
            decision_id="decision-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            statement="Proceed with the active plan",
            rationale="Canonical evidence supports the semantic action",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["ev-1"],
        )

    def intent(self):
        return ActionIntent(
            intent_id="intent-1",
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            purpose="Prepare the selected experiment",
            capability_need="MARKET_EXPERIMENT",
            expected_observation="Observed experiment outcome",
            decision_id="decision-1",
            evidence_required=True,
        )

    def request(self, plan):
        return CognitiveCycleRequest(
            cycle_id="cycle-1",
            goal=self.goal(),
            plan=plan,
            decisions=[self.decision()],
            action_intents=[self.intent()],
        )

    def test_abandoned_plan_requires_new_planning_not_impossible_revision(self):
        cycle = derive_cognitive_cycle(self.request(self.plan(PlanStatus.ABANDONED)))

        self.assertEqual(cycle.phase, CognitivePhase.PLANNING)
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.BUILD_PLAN],
        )
        self.assertEqual(cycle.directives[0].target_ids, ["goal-1"])
        self.assertEqual(cycle.action_intent_ids, [])

    def test_post_construction_abandoned_mutation_is_revalidated_and_requires_new_plan(self):
        request = self.request(self.plan(PlanStatus.ACTIVE))
        request.plan.status = PlanStatus.ABANDONED

        cycle = derive_cognitive_cycle(request)

        self.assertEqual(cycle.phase, CognitivePhase.PLANNING)
        self.assertEqual(cycle.directives[0].kind, CognitiveDirectiveKind.BUILD_PLAN)
        self.assertEqual(cycle.action_intent_ids, [])

    def test_needs_revision_plan_remains_replannable(self):
        cycle = derive_cognitive_cycle(self.request(self.plan(PlanStatus.NEEDS_REVISION)))

        self.assertEqual(cycle.phase, CognitivePhase.REPLANNING)
        self.assertEqual(cycle.directives[0].kind, CognitiveDirectiveKind.REPLAN)
        self.assertEqual(cycle.directives[0].target_ids, ["plan-1"])
        self.assertEqual(cycle.action_intent_ids, [])

    def test_active_plan_control_remains_action_ready(self):
        cycle = derive_cognitive_cycle(self.request(self.plan(PlanStatus.ACTIVE)))

        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, ["intent-1"])


if __name__ == "__main__":
    unittest.main()
