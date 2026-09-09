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
    CognitiveDirectiveKind,
    CognitivePhase,
    derive_cognitive_cycle,
)
from brain.planning import PlanSnapshot, PlanStep
from brain.reflection import CognitiveReflectionReport, ReflectionDirective


class BrainReflectionDecisionBindingV1Tests(unittest.TestCase):
    def goal(self):
        return GoalSpec(
            goal_id="goal-1",
            objective="Keep reflection provenance bound to canonical decisions",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Every reflection resolves its exact decision"],
            constraints=["No dangling semantic revision targets"],
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
                    objective="Prepare the evidence-grounded action",
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
            statement="Proceed with the semantic experiment",
            rationale="Canonical evidence supports the next step",
            evidence_refs=["ev-1"],
        )

    def intent(self):
        return ActionIntent(
            intent_id="intent-1",
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            purpose="Prepare the selected semantic experiment",
            capability_need="MARKET_EXPERIMENT",
            expected_observation="Observed experiment outcome",
            decision_id="decision-1",
            evidence_required=True,
        )

    def reflection(self, **overrides):
        data = dict(
            reflection_id="reflection-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            decision_id="decision-1",
            source_snapshot_id="world-1",
            directives=[ReflectionDirective.REVISE_DECISION],
            reasons=["Canonical scrutiny requires decision revision"],
        )
        data.update(overrides)
        return CognitiveReflectionReport(**data)

    def request(self, reflection):
        return CognitiveCycleRequest(
            cycle_id="cycle-1",
            goal=self.goal(),
            plan=self.plan(),
            decisions=[self.decision()],
            action_intents=[self.intent()],
            reflection_reports=[reflection],
        )

    def test_unknown_reflection_decision_id_fails_closed(self):
        request = self.request(self.reflection(decision_id="decision-missing"))

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_reflection_agent_must_match_backing_decision_agent(self):
        request = self.request(self.reflection(agent_id=BrainAgentId.STRATEGIST))

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_post_construction_reflection_decision_mutation_is_revalidated(self):
        request = self.request(self.reflection())
        request.reflection_reports[0].decision_id = "decision-missing"

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_valid_bound_reflection_still_routes_to_exact_decision_revision(self):
        cycle = derive_cognitive_cycle(self.request(self.reflection()))

        self.assertEqual(cycle.phase, CognitivePhase.DECISION)
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.REVISE_DECISION],
        )
        self.assertEqual(cycle.directives[0].target_ids, ["decision-1"])
        self.assertEqual(cycle.action_intent_ids, [])


if __name__ == "__main__":
    unittest.main()
