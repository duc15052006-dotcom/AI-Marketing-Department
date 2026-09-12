import copy
import unittest

from schemas.base import ValidationError
from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    EvidenceNeed,
    GoalSpec,
)
from brain.cognitive_loop import CognitivePhase, CognitiveCycleRequest, derive_cognitive_cycle
from brain.planning import PlanSnapshot, PlanStep


class PlanEvidenceNeedBindingV1Tests(unittest.TestCase):
    def goal(self):
        return GoalSpec(
            goal_id="goal-1",
            objective="Choose an evidence-grounded experiment",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Validated next action"],
            constraints=["No unsupported evidence references"],
        )

    def evidence_need(self, **overrides):
        data = dict(
            need_id="need-1",
            goal_id="goal-1",
            question="Is the experiment premise supported?",
            why_needed="The plan step explicitly depends on this evidence need",
            blocking=False,
            evidence_refs=["ev-1"],
        )
        data.update(overrides)
        return EvidenceNeed(**data)

    def plan(self, evidence_need_ids=None):
        return PlanSnapshot(
            plan_id="plan-1",
            goal_id="goal-1",
            steps=[
                PlanStep(
                    step_id="step-1",
                    goal_id="goal-1",
                    owner_agent=BrainAgentId.CMO,
                    objective="Run the selected experiment",
                    completion_criteria=["Outcome observed"],
                    evidence_need_ids=list(evidence_need_ids or []),
                    action_intent_ids=["intent-1"],
                )
            ],
        )

    def decision(self):
        return DecisionRecord(
            decision_id="decision-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            statement="Proceed with the validated experiment",
            rationale="Canonical evidence supports the next semantic action",
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
            evidence_required=True,
        )

    def request(self, *, plan=None, evidence_needs=None):
        return CognitiveCycleRequest(
            cycle_id="cycle-1",
            goal=self.goal(),
            evidence_needs=list(evidence_needs or []),
            unknowns=[],
            plan=plan if plan is not None else self.plan(),
            decisions=[self.decision()],
            action_intents=[self.intent()],
            reflection_reports=[],
        )

    def test_missing_plan_evidence_need_reference_fails_closed(self):
        request = self.request(plan=self.plan(["need-missing"]))
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_unrelated_evidence_need_cannot_satisfy_plan_reference(self):
        request = self.request(
            plan=self.plan(["need-required"]),
            evidence_needs=[self.evidence_need(need_id="need-other")],
        )
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_valid_plan_evidence_need_reference_preserves_action_ready_semantics(self):
        request = self.request(
            plan=self.plan(["need-1"]),
            evidence_needs=[self.evidence_need()],
        )
        cycle = derive_cognitive_cycle(request)
        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.action_intent_ids, ["intent-1"])

    def test_resolved_blocking_plan_evidence_need_can_be_action_ready(self):
        request = self.request(
            plan=self.plan(["need-1"]),
            evidence_needs=[self.evidence_need(blocking=True, evidence_refs=["ev-1"])],
        )
        cycle = derive_cognitive_cycle(request)
        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)

    def test_nested_plan_reference_mutation_is_revalidated_at_derive_boundary(self):
        request = self.request(
            plan=self.plan(["need-1"]),
            evidence_needs=[self.evidence_need()],
        )
        request.plan.steps[0].evidence_need_ids = ["need-mutated-missing"]
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(request)

    def test_binding_validation_does_not_mutate_or_alias_caller_inputs(self):
        request = self.request(
            plan=self.plan(["need-1"]),
            evidence_needs=[self.evidence_need()],
        )
        before = copy.deepcopy(request.model_dump())
        cycle = derive_cognitive_cycle(request)
        self.assertEqual(request.model_dump(), before)
        cycle.goal.objective = "mutated output"
        self.assertEqual(request.goal.objective, before["goal"]["objective"])


if __name__ == "__main__":
    unittest.main()
