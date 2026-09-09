import unittest

from schemas.base import ValidationError
from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionRecord,
    GoalSpec,
)
from brain.cognitive_loop import (
    CognitiveCycleRequest,
    CognitivePhase,
    derive_cognitive_cycle,
)
from brain.planning import PlanSnapshot, PlanStep, PlanStepState


class BrainActionIntentSingleStepBindingV1Tests(unittest.TestCase):
    def goal(self):
        return GoalSpec(
            goal_id="goal-1",
            objective="Keep every semantic action owned by one exact plan step",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Action provenance remains unambiguous"],
            constraints=["No cross-step ActionIntent aliases"],
        )

    def decision(self):
        return DecisionRecord(
            decision_id="decision-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            statement="Proceed with the evidence-grounded semantic actions",
            rationale="Canonical evidence supports the plan",
            evidence_refs=["ev-1"],
        )

    def intent(self, intent_id):
        return ActionIntent(
            intent_id=intent_id,
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            purpose=f"Prepare {intent_id}",
            capability_need="MARKET_EXPERIMENT",
            expected_observation=f"Observed result for {intent_id}",
            decision_id="decision-1",
            evidence_required=True,
        )

    def step(
        self,
        step_id,
        intent_id,
        *,
        state=PlanStepState.PENDING,
        depends_on=None,
    ):
        return PlanStep(
            step_id=step_id,
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            objective=f"Execute semantic step {step_id}",
            completion_criteria=[f"{step_id} observed"],
            action_intent_ids=[intent_id],
            state=state,
            depends_on=list(depends_on or []),
        )

    def request(self, steps, intents):
        return CognitiveCycleRequest(
            cycle_id="cycle-1",
            goal=self.goal(),
            plan=PlanSnapshot(
                plan_id="plan-1",
                goal_id="goal-1",
                steps=steps,
            ),
            decisions=[self.decision()],
            action_intents=intents,
        )

    def test_one_intent_cannot_be_bound_to_two_ready_steps(self):
        request = self.request(
            [
                self.step("step-1", "intent-1"),
                self.step("step-2", "intent-1"),
            ],
            [self.intent("intent-1")],
        )

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_completed_step_intent_cannot_be_rebound_to_a_ready_step(self):
        request = self.request(
            [
                self.step(
                    "step-completed",
                    "intent-1",
                    state=PlanStepState.COMPLETED,
                ),
                self.step(
                    "step-ready",
                    "intent-1",
                    depends_on=["step-completed"],
                ),
            ],
            [self.intent("intent-1")],
        )

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_post_construction_cross_step_alias_is_revalidated(self):
        request = self.request(
            [
                self.step("step-1", "intent-1"),
                self.step("step-2", "intent-2"),
            ],
            [self.intent("intent-1"), self.intent("intent-2")],
        )
        request.plan.steps[1].action_intent_ids = ["intent-1"]

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_distinct_step_intents_remain_action_ready(self):
        cycle = derive_cognitive_cycle(
            self.request(
                [
                    self.step("step-1", "intent-1"),
                    self.step("step-2", "intent-2"),
                ],
                [self.intent("intent-1"), self.intent("intent-2")],
            )
        )

        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, ["intent-1", "intent-2"])


if __name__ == "__main__":
    unittest.main()
