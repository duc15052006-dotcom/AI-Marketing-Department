import unittest

from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    GoalSpec,
)
from brain.cognitive_loop import CognitiveCycleRequest, CognitivePhase, derive_cognitive_cycle
from brain.planning import PlanSnapshot, PlanStep
from schemas.base import ValidationError


class BrainActionIntentEvidenceRequiredV1Tests(unittest.TestCase):
    def goal(self):
        return GoalSpec(
            goal_id="goal-1",
            objective="Choose an evidence-grounded next action",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["A defensible next action is selected"],
            constraints=["Do not manufacture evidence authority"],
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
                    objective="Prepare the selected semantic action",
                    action_intent_ids=["intent-1"],
                )
            ],
        )

    def decision(self, *, evidence_refs):
        return DecisionRecord(
            decision_id="decision-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            statement="Proceed with the selected action",
            rationale="The semantic decision controls whether action may be prepared",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=evidence_refs,
        )

    def intent(self, *, evidence_required):
        return ActionIntent(
            intent_id="intent-1",
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            purpose="Prepare the selected semantic action",
            capability_need="MARKET_EXPERIMENT",
            expected_observation="Observed experiment outcome",
            decision_id="decision-1",
            evidence_required=evidence_required,
        )

    def request(self, *, evidence_required, evidence_refs):
        return CognitiveCycleRequest(
            cycle_id="cycle-1",
            goal=self.goal(),
            plan=self.plan(),
            decisions=[self.decision(evidence_refs=evidence_refs)],
            action_intents=[self.intent(evidence_required=evidence_required)],
        )

    def test_required_evidence_cannot_reach_action_ready_without_decision_lineage(self):
        request = self.request(evidence_required=True, evidence_refs=[])

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_post_construction_evidence_requirement_mutation_fails_closed(self):
        request = self.request(evidence_required=False, evidence_refs=[])
        request.action_intents[0].evidence_required = True

        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_non_evidence_required_intent_can_remain_action_ready_without_decision_evidence(self):
        request = self.request(evidence_required=False, evidence_refs=[])

        cycle = derive_cognitive_cycle(request)

        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, ["intent-1"])

    def test_required_evidence_with_decision_lineage_remains_action_ready(self):
        request = self.request(evidence_required=True, evidence_refs=["evidence-1"])

        cycle = derive_cognitive_cycle(request)

        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, ["intent-1"])


if __name__ == "__main__":
    unittest.main()
