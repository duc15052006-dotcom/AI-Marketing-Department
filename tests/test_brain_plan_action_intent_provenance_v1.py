import unittest

from brain.contracts import ActionIntent, BrainAgentId
from brain.planning import (
    PlanSnapshot,
    PlanStep,
    validate_plan_action_intent_bindings,
)
from schemas.base import ValidationError


class TestBrainPlanActionIntentProvenanceV1(unittest.TestCase):
    def _plan(self, *, intent_id="INTENT-1", owner=BrainAgentId.INTELLIGENCE):
        return PlanSnapshot(
            plan_id="PLAN-1",
            goal_id="GOAL-1",
            steps=[
                PlanStep(
                    step_id="STEP-1",
                    goal_id="GOAL-1",
                    owner_agent=owner,
                    objective="Collect authoritative market evidence",
                    action_intent_ids=[intent_id],
                )
            ],
        )

    def _intent(
        self,
        *,
        intent_id="INTENT-1",
        goal_id="GOAL-1",
        owner=BrainAgentId.INTELLIGENCE,
    ):
        return ActionIntent(
            intent_id=intent_id,
            goal_id=goal_id,
            owner_agent=owner,
            purpose="Collect market evidence",
            capability_need="MARKET_RESEARCH",
            expected_observation="Authoritative market observations",
            evidence_required=True,
        )

    def test_valid_binding_is_accepted(self):
        validate_plan_action_intent_bindings(self._plan(), [self._intent()])

    def test_dangling_action_intent_id_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "unknown action intent"):
            validate_plan_action_intent_bindings(
                self._plan(intent_id="INTENT-MISSING"),
                [self._intent()],
            )

    def test_cross_goal_action_intent_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "goal_id"):
            validate_plan_action_intent_bindings(
                self._plan(),
                [self._intent(goal_id="GOAL-OTHER")],
            )

    def test_cross_agent_action_intent_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "owner_agent"):
            validate_plan_action_intent_bindings(
                self._plan(),
                [self._intent(owner=BrainAgentId.CONTENT)],
            )


if __name__ == "__main__":
    unittest.main()
