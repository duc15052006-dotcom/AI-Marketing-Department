"""Adversarial tests for provider-neutral Brain outcome/trajectory intelligence v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.outcomes as outcomes
from brain.contracts import BrainAgentId, GoalSpec, GoalStatus
from brain.evidence import ClaimEvidenceAssessment, ClaimVerdict
from brain.outcomes import (
    OutcomeVerdict,
    TrajectoryDisposition,
    TrajectoryEvaluationRequest,
    evaluate_trajectory,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStep, PlanStepState
from schemas.base import ValidationError


class BrainOutcomeIntelligenceV1Tests(unittest.TestCase):
    CRITERION_A = "Qualified leads increased above baseline"
    CRITERION_B = "CAC remains at or below target"

    @classmethod
    def _goal(cls, **updates) -> GoalSpec:
        values = {
            "goal_id": "G-1",
            "objective": "Improve acquisition efficiency",
            "owner_agent": BrainAgentId.CMO,
            "success_criteria": [cls.CRITERION_A, cls.CRITERION_B],
            "status": GoalStatus.OPEN,
        }
        values.update(updates)
        return GoalSpec(**values)

    @staticmethod
    def _plan(*, complete: bool = True, status: PlanStatus = PlanStatus.ACTIVE, goal_id: str = "G-1") -> PlanSnapshot:
        state = PlanStepState.COMPLETED if complete else PlanStepState.PENDING
        return PlanSnapshot(
            plan_id="PLAN-1",
            goal_id=goal_id,
            revision=1,
            status=status,
            steps=[
                PlanStep(
                    step_id="S-1",
                    goal_id=goal_id,
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    objective="Measure the target outcome",
                    completion_criteria=["Observation captured"],
                    state=state,
                )
            ],
        )

    @staticmethod
    def _assessment(
        criterion: str,
        *,
        assessment_id: str,
        verdict: ClaimVerdict = ClaimVerdict.SUPPORTED,
        goal_id: str = "G-1",
        supporting_refs=None,
        contradicting_refs=None,
    ) -> ClaimEvidenceAssessment:
        if supporting_refs is None:
            supporting_refs = [f"E-{assessment_id}"] if verdict in (ClaimVerdict.SUPPORTED, ClaimVerdict.CONTESTED) else []
        if contradicting_refs is None:
            contradicting_refs = [f"E-X-{assessment_id}"] if verdict in (ClaimVerdict.REFUTED, ClaimVerdict.CONTESTED) else []
        return ClaimEvidenceAssessment(
            assessment_id=assessment_id,
            goal_id=goal_id,
            claim_id=criterion,
            agent_id=BrainAgentId.PERFORMANCE,
            verdict=verdict,
            supporting_evidence_refs=list(supporting_refs),
            contradicting_evidence_refs=list(contradicting_refs),
            reasons=["Evidence assessment supplied by the evidence intelligence layer."],
        )

    @classmethod
    def _request(cls, assessments, **updates) -> TrajectoryEvaluationRequest:
        values = {
            "evaluation_id": "TE-1",
            "goal": cls._goal(),
            "plan": cls._plan(),
            "criterion_assessments": list(assessments),
        }
        values.update(updates)
        return TrajectoryEvaluationRequest(**values)

    def test_all_exact_success_criteria_supported_can_stop_as_satisfied(self) -> None:
        decision = evaluate_trajectory(
            self._request(
                [
                    self._assessment(self.CRITERION_A, assessment_id="A"),
                    self._assessment(self.CRITERION_B, assessment_id="B"),
                ]
            )
        )
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.SATISFIED)
        self.assertEqual(decision.disposition, TrajectoryDisposition.STOP)
        self.assertEqual(
            decision.supported_criteria,
            [self.CRITERION_A, self.CRITERION_B],
        )
        self.assertEqual(decision.unresolved_criteria, [])

    def test_completed_plan_is_not_goal_success_when_a_criterion_is_missing(self) -> None:
        decision = evaluate_trajectory(
            self._request([self._assessment(self.CRITERION_A, assessment_id="A")])
        )
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertEqual(decision.disposition, TrajectoryDisposition.REVISE)
        self.assertEqual(decision.unresolved_criteria, [self.CRITERION_B])

    def test_stale_satisfied_labels_cannot_self_certify_goal_success(self) -> None:
        goal = self._goal(status=GoalStatus.SATISFIED)
        plan = self._plan(status=PlanStatus.SATISFIED)
        decision = evaluate_trajectory(
            self._request([], goal=goal, plan=plan)
        )
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertEqual(decision.disposition, TrajectoryDisposition.REVISE)
        self.assertEqual(
            decision.unresolved_criteria,
            [self.CRITERION_A, self.CRITERION_B],
        )

    def test_cross_goal_assessment_is_ignored(self) -> None:
        wrong_goal = self._assessment(
            self.CRITERION_A,
            assessment_id="WRONG-GOAL",
            goal_id="G-OTHER",
        )
        good_b = self._assessment(self.CRITERION_B, assessment_id="B")
        decision = evaluate_trajectory(self._request([wrong_goal, good_b]))
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertIn("WRONG-GOAL", decision.ignored_assessment_ids)
        self.assertIn(self.CRITERION_A, decision.unresolved_criteria)

    def test_evidence_for_one_criterion_cannot_satisfy_another(self) -> None:
        only_a = self._assessment(self.CRITERION_A, assessment_id="A")
        unrelated = self._assessment(
            "Website traffic increased",
            assessment_id="UNRELATED",
        )
        decision = evaluate_trajectory(self._request([only_a, unrelated]))
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertIn("UNRELATED", decision.ignored_assessment_ids)
        self.assertEqual(decision.unresolved_criteria, [self.CRITERION_B])

    def test_naked_supported_verdict_without_evidence_refs_fails_closed(self) -> None:
        naked_a = self._assessment(
            self.CRITERION_A,
            assessment_id="A",
            supporting_refs=[],
        )
        good_b = self._assessment(self.CRITERION_B, assessment_id="B")
        decision = evaluate_trajectory(self._request([naked_a, good_b]))
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertIn(self.CRITERION_A, decision.unresolved_criteria)
        self.assertNotIn(self.CRITERION_A, decision.supported_criteria)

    def test_evidence_backed_refuted_success_criterion_forces_revision(self) -> None:
        refuted_a = self._assessment(
            self.CRITERION_A,
            assessment_id="A",
            verdict=ClaimVerdict.REFUTED,
        )
        good_b = self._assessment(self.CRITERION_B, assessment_id="B")
        decision = evaluate_trajectory(self._request([refuted_a, good_b]))
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.REFUTED)
        self.assertEqual(decision.disposition, TrajectoryDisposition.REVISE)
        self.assertEqual(decision.refuted_criteria, [self.CRITERION_A])

    def test_contested_success_criterion_escalates_instead_of_averaging(self) -> None:
        contested_a = self._assessment(
            self.CRITERION_A,
            assessment_id="A",
            verdict=ClaimVerdict.CONTESTED,
        )
        good_b = self._assessment(self.CRITERION_B, assessment_id="B")
        decision = evaluate_trajectory(self._request([contested_a, good_b]))
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.CONTESTED)
        self.assertEqual(decision.disposition, TrajectoryDisposition.ESCALATE)
        self.assertEqual(decision.contested_criteria, [self.CRITERION_A])

    def test_naked_refuted_verdict_cannot_masquerade_as_evidence_backed_refutation(self) -> None:
        naked_refute = self._assessment(
            self.CRITERION_A,
            assessment_id="A",
            verdict=ClaimVerdict.REFUTED,
            contradicting_refs=[],
        )
        good_b = self._assessment(self.CRITERION_B, assessment_id="B")
        decision = evaluate_trajectory(self._request([naked_refute, good_b]))
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertEqual(decision.refuted_criteria, [])
        self.assertIn(self.CRITERION_A, decision.unresolved_criteria)

    def test_duplicate_assessments_for_same_criterion_fail_closed_as_ambiguous(self) -> None:
        duplicate_a_1 = self._assessment(self.CRITERION_A, assessment_id="A-1")
        duplicate_a_2 = self._assessment(self.CRITERION_A, assessment_id="A-2")
        good_b = self._assessment(self.CRITERION_B, assessment_id="B")
        decision = evaluate_trajectory(
            self._request([duplicate_a_1, duplicate_a_2, good_b])
        )
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertIn(self.CRITERION_A, decision.ambiguous_criteria)
        self.assertIn(self.CRITERION_A, decision.unresolved_criteria)
        self.assertEqual(
            set(decision.ignored_assessment_ids),
            {"A-1", "A-2"},
        )

    def test_no_success_criteria_cannot_be_autonomously_declared_satisfied(self) -> None:
        goal = self._goal(success_criteria=[])
        decision = evaluate_trajectory(self._request([], goal=goal))
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertEqual(decision.disposition, TrajectoryDisposition.ESCALATE)

    def test_unresolved_outcome_continues_when_plan_still_has_work(self) -> None:
        decision = evaluate_trajectory(
            self._request(
                [self._assessment(self.CRITERION_A, assessment_id="A")],
                plan=self._plan(complete=False),
            )
        )
        self.assertEqual(decision.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertEqual(decision.disposition, TrajectoryDisposition.CONTINUE)

    def test_goal_and_plan_identity_must_match_exactly(self) -> None:
        with self.assertRaises(ValidationError):
            self._request([], plan=self._plan(goal_id="G-OTHER"))

    def test_outcome_policy_has_no_body_or_provider_dependency(self) -> None:
        source = inspect.getsource(outcomes)
        tree = ast.parse(source)
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "knowledge",
            "memory",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

        serialized = str(
            evaluate_trajectory(
                self._request(
                    [
                        self._assessment(self.CRITERION_A, assessment_id="A"),
                        self._assessment(self.CRITERION_B, assessment_id="B"),
                    ]
                )
            ).model_dump()
        ).lower()
        for forbidden in (
            "provider_id",
            "model_id",
            "openai",
            "astra",
            "gemini",
            "claude",
            "tool_id",
            "connector_id",
            "queue_status",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
