import copy
import inspect
import unittest

from schemas.base import ValidationError
from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    EvidenceNeed,
    GoalSpec,
    GoalStatus,
    UnknownRecord,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStep, PlanStepState
from brain.reflection import CognitiveReflectionReport, ReflectionDirective
from brain.cognitive_loop import (
    CognitiveDirectiveKind,
    CognitivePhase,
    CognitiveCycleRequest,
    derive_cognitive_cycle,
)


class UnifiedCognitiveLoopV1Tests(unittest.TestCase):
    def goal(self, **overrides):
        data = dict(
            goal_id="goal-1",
            objective="Increase qualified demand without inventing facts",
            owner_agent=BrainAgentId.CMO,
            success_criteria=["Validated growth opportunity"],
            constraints=["Evidence grounded"],
        )
        data.update(overrides)
        return GoalSpec(**data)

    def plan(self, **overrides):
        step = PlanStep(
            step_id="step-1",
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            objective="Choose evidence-grounded next action",
            completion_criteria=["Decision recorded"],
            action_intent_ids=["intent-1"],
        )
        data = dict(plan_id="plan-1", goal_id="goal-1", steps=[step])
        data.update(overrides)
        return PlanSnapshot(**data)

    def decision(self, **overrides):
        data = dict(
            decision_id="decision-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            statement="Proceed with the validated experiment",
            rationale="Canonical evidence supports the next semantic action",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["ev-1"],
        )
        data.update(overrides)
        return DecisionRecord(**data)

    def intent(self, **overrides):
        data = dict(
            intent_id="intent-1",
            goal_id="goal-1",
            owner_agent=BrainAgentId.CMO,
            purpose="Run the selected experiment",
            capability_need="MARKET_EXPERIMENT",
            expected_observation="Observed experiment outcome",
            decision_id="decision-1",
            evidence_required=True,
        )
        data.update(overrides)
        return ActionIntent(**data)

    def request(self, **overrides):
        data = dict(
            cycle_id="cycle-1",
            goal=self.goal(),
            evidence_needs=[],
            unknowns=[],
            plan=self.plan(),
            decisions=[self.decision()],
            action_intents=[self.intent()],
            reflection_reports=[],
        )
        data.update(overrides)
        return CognitiveCycleRequest(**data)

    def reflection(self, directives):
        return CognitiveReflectionReport(
            reflection_id="reflection-1",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            decision_id="decision-1",
            source_snapshot_id="world-1",
            directives=directives,
            reasons=["advisory scrutiny"],
        )

    def test_blocking_unknown_routes_to_research(self):
        req = self.request(
            unknowns=[UnknownRecord(
                unknown_id="unknown-1",
                goal_id="goal-1",
                question="Which segment converts?",
                consequence="Decision could target the wrong segment",
                blocking=True,
            )]
        )
        cycle = derive_cognitive_cycle(req)
        self.assertEqual(cycle.phase, CognitivePhase.RESEARCH)
        self.assertIn(CognitiveDirectiveKind.RESEARCH, [d.kind for d in cycle.directives])
        self.assertNotIn(CognitiveDirectiveKind.PREPARE_ACTION, [d.kind for d in cycle.directives])

    def test_unresolved_blocking_evidence_need_routes_to_research(self):
        need = EvidenceNeed(
            need_id="need-1",
            goal_id="goal-1",
            question="Is the claim supported?",
            why_needed="It is a decision premise",
            blocking=True,
            evidence_refs=[],
        )
        cycle = derive_cognitive_cycle(self.request(evidence_needs=[need]))
        self.assertEqual(cycle.phase, CognitivePhase.RESEARCH)
        self.assertEqual(cycle.directives[0].target_ids, ["need-1"])

    def test_resolved_blocking_evidence_need_does_not_block(self):
        need = EvidenceNeed(
            need_id="need-1",
            goal_id="goal-1",
            question="Is the claim supported?",
            why_needed="It is a decision premise",
            blocking=True,
            evidence_refs=["ev-1"],
        )
        cycle = derive_cognitive_cycle(self.request(evidence_needs=[need]))
        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)

    def test_missing_plan_routes_to_planning(self):
        cycle = derive_cognitive_cycle(self.request(plan=None, action_intents=[]))
        self.assertEqual(cycle.phase, CognitivePhase.PLANNING)
        self.assertEqual(cycle.directives[0].kind, CognitiveDirectiveKind.BUILD_PLAN)

    def test_plan_needs_revision_routes_to_replanning(self):
        plan = self.plan(status=PlanStatus.NEEDS_REVISION)
        cycle = derive_cognitive_cycle(self.request(plan=plan))
        self.assertEqual(cycle.phase, CognitivePhase.REPLANNING)
        self.assertEqual(cycle.directives[0].kind, CognitiveDirectiveKind.REPLAN)

    def test_missing_decision_routes_to_decision(self):
        cycle = derive_cognitive_cycle(self.request(decisions=[], action_intents=[]))
        self.assertEqual(cycle.phase, CognitivePhase.DECISION)
        self.assertEqual(cycle.directives[0].kind, CognitiveDirectiveKind.MAKE_DECISION)

    def test_reflection_research_directive_can_only_increase_scrutiny(self):
        report = self.reflection([ReflectionDirective.RESEARCH_PREMISE])
        cycle = derive_cognitive_cycle(self.request(reflection_reports=[report]))
        self.assertEqual(cycle.phase, CognitivePhase.RESEARCH)
        self.assertNotIn(CognitiveDirectiveKind.PREPARE_ACTION, [d.kind for d in cycle.directives])

    def test_reflection_revise_decision_blocks_action(self):
        report = self.reflection([ReflectionDirective.REVISE_DECISION])
        cycle = derive_cognitive_cycle(self.request(reflection_reports=[report]))
        self.assertEqual(cycle.phase, CognitivePhase.DECISION)
        self.assertIn(CognitiveDirectiveKind.REVISE_DECISION, [d.kind for d in cycle.directives])

    def test_clean_bound_artifacts_are_action_ready_but_not_executed(self):
        cycle = derive_cognitive_cycle(self.request())
        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual([d.kind for d in cycle.directives], [CognitiveDirectiveKind.PREPARE_ACTION])
        self.assertEqual(cycle.action_intent_ids, ["intent-1"])
        self.assertFalse(hasattr(cycle, "executed"))
        self.assertFalse(hasattr(cycle, "provider_id"))
        self.assertFalse(hasattr(cycle, "tool_id"))

    def test_blocked_goal_routes_to_replanning_without_action_authority(self):
        cycle = derive_cognitive_cycle(
            self.request(goal=self.goal(status=GoalStatus.BLOCKED))
        )
        self.assertEqual(cycle.phase, CognitivePhase.REPLANNING)
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.REPLAN],
        )
        self.assertEqual(cycle.directives[0].target_ids, ["goal-1"])
        self.assertEqual(cycle.action_intent_ids, [])
        self.assertNotIn(
            CognitiveDirectiveKind.PREPARE_ACTION,
            [directive.kind for directive in cycle.directives],
        )

    def test_post_construction_goal_status_mutation_to_blocked_fails_closed(self):
        req = self.request()
        req.goal.status = GoalStatus.BLOCKED
        cycle = derive_cognitive_cycle(req)
        self.assertEqual(cycle.phase, CognitivePhase.REPLANNING)
        self.assertEqual(
            [directive.kind for directive in cycle.directives],
            [CognitiveDirectiveKind.REPLAN],
        )
        self.assertEqual(cycle.directives[0].target_ids, ["goal-1"])
        self.assertEqual(cycle.action_intent_ids, [])

    def test_satisfied_goal_stops_without_action_authority(self):
        cycle = derive_cognitive_cycle(self.request(
            goal=self.goal(status=GoalStatus.SATISFIED),
            plan=self.plan(
                status=PlanStatus.SATISFIED,
                steps=[PlanStep(
                    step_id="step-1",
                    goal_id="goal-1",
                    owner_agent=BrainAgentId.CMO,
                    objective="Done",
                    completion_criteria=["Done"],
                    state=PlanStepState.COMPLETED,
                )],
            ),
            action_intents=[],
        ))
        self.assertEqual(cycle.phase, CognitivePhase.COMPLETE)
        self.assertEqual(cycle.directives[0].kind, CognitiveDirectiveKind.STOP)

    def test_abandoned_goal_stops(self):
        cycle = derive_cognitive_cycle(self.request(
            goal=self.goal(status=GoalStatus.ABANDONED),
            plan=None,
            decisions=[],
            action_intents=[],
        ))
        self.assertEqual(cycle.phase, CognitivePhase.COMPLETE)

    def test_cross_goal_evidence_is_rejected(self):
        need = EvidenceNeed(
            need_id="need-x",
            goal_id="other-goal",
            question="Question",
            why_needed="Reason",
            blocking=True,
        )
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(evidence_needs=[need]))

    def test_cross_goal_plan_is_rejected(self):
        foreign_step = PlanStep(
            step_id="foreign-step",
            goal_id="other-goal",
            owner_agent=BrainAgentId.CMO,
            objective="Foreign",
        )
        foreign_plan = PlanSnapshot(
            plan_id="foreign-plan",
            goal_id="other-goal",
            steps=[foreign_step],
        )
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(plan=foreign_plan, action_intents=[]))

    def test_cross_goal_decision_is_rejected(self):
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(decisions=[self.decision(goal_id="other-goal")]))

    def test_action_intent_requires_matching_decision_provenance(self):
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(action_intents=[self.intent(decision_id=None)]))
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(action_intents=[self.intent(decision_id="unknown-decision")]))

    def test_plan_action_intent_bindings_are_reused_not_reimplemented_loosely(self):
        bad_intent = self.intent(owner_agent=BrainAgentId.STRATEGIST)
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(action_intents=[bad_intent]))

    def test_duplicate_semantic_ids_fail_closed(self):
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(decisions=[self.decision(), self.decision()]))
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(self.request(action_intents=[self.intent(), self.intent()]))

    def test_serialized_request_reconstructs_canonical_types(self):
        raw = self.request().model_dump()
        cycle = derive_cognitive_cycle(raw)
        self.assertEqual(cycle.phase, CognitivePhase.ACTION_READY)
        self.assertEqual(cycle.goal.goal_id, "goal-1")
        self.assertIsInstance(cycle.goal.owner_agent, BrainAgentId)

    def test_nested_post_construction_mutation_is_revalidated_at_use_boundary(self):
        req = self.request()
        req.goal.owner_agent = "SIXTH_AGENT"
        with self.assertRaises(ValidationError):
            derive_cognitive_cycle(req)

    def test_caller_inputs_are_not_mutated_or_aliased(self):
        req = self.request()
        before = copy.deepcopy(req.model_dump())
        cycle = derive_cognitive_cycle(req)
        self.assertEqual(req.model_dump(), before)
        cycle.goal.objective = "mutated output"
        self.assertEqual(req.goal.objective, before["goal"]["objective"])

    def test_directive_order_is_deterministic(self):
        req = self.request(
            unknowns=[
                UnknownRecord(unknown_id="u-b", goal_id="goal-1", question="B?", consequence="B", blocking=True),
                UnknownRecord(unknown_id="u-a", goal_id="goal-1", question="A?", consequence="A", blocking=True),
            ],
            evidence_needs=[
                EvidenceNeed(need_id="n-b", goal_id="goal-1", question="B?", why_needed="B", blocking=True),
                EvidenceNeed(need_id="n-a", goal_id="goal-1", question="A?", why_needed="A", blocking=True),
            ],
        )
        first = derive_cognitive_cycle(req).model_dump()
        second = derive_cognitive_cycle(req).model_dump()
        self.assertEqual(first, second)
        self.assertEqual(first["directives"][0]["target_ids"], ["n-a", "n-b", "u-a", "u-b"])

    def test_module_has_no_runtime_provider_tool_or_probability_authority(self):
        import brain.cognitive_loop as module
        source = inspect.getsource(module)
        forbidden = [
            "providers.", "provider_id", "tool_id", "runtime.", "subprocess",
            "requests.", "httpx", "confidence=", "probability",
        ]
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
