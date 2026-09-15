"""Adversarial tests for provider-neutral Brain stop intelligence v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.stopping as stopping
from brain.contracts import BrainAgentId, EvidenceNeed, GoalSpec, GoalStatus, StopReason, UnknownRecord
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.outcomes import (
    OutcomeVerdict,
    TrajectoryDisposition,
    TrajectoryEvaluation,
    TrajectoryEvaluationRequest,
    evaluate_trajectory,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStep, PlanStepState
from brain.stopping import StopEvaluationRequest, evaluate_stop
from schemas.base import ValidationError


class BrainStopIntelligenceV1Tests(unittest.TestCase):
    CRITERION = "Verified target outcome"

    @classmethod
    def _goal(cls, *, goal_id: str = "G-1", success_criteria=None) -> GoalSpec:
        if success_criteria is None:
            success_criteria = [cls.CRITERION]
        return GoalSpec(
            goal_id=goal_id,
            objective="Verify the target outcome",
            owner_agent=BrainAgentId.CMO,
            success_criteria=list(success_criteria),
            status=GoalStatus.OPEN,
        )

    @staticmethod
    def _plan(
        *,
        goal_id: str = "G-1",
        complete: bool = True,
        status: PlanStatus = PlanStatus.ACTIVE,
    ) -> PlanSnapshot:
        return PlanSnapshot(
            plan_id="P-1",
            goal_id=goal_id,
            revision=1,
            status=status,
            steps=[
                PlanStep(
                    step_id="S-1",
                    goal_id=goal_id,
                    owner_agent=BrainAgentId.PERFORMANCE,
                    objective="Measure the target outcome",
                    completion_criteria=["Observation captured"],
                    state=PlanStepState.COMPLETED if complete else PlanStepState.PENDING,
                )
            ],
        )

    @classmethod
    def _raw_evidence_request(cls, mode: str = "supported") -> ClaimEvidenceRequest:
        evidence = []
        if mode in {"supported", "contested"}:
            evidence.append(
                EvidenceSignal(
                    evidence_id="E-SUPPORT",
                    goal_id="G-1",
                    claim_id=cls.CRITERION,
                    source_id="SRC-SUPPORT",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            )
        if mode in {"refuted", "contested"}:
            evidence.append(
                EvidenceSignal(
                    evidence_id="E-CONTRADICT",
                    goal_id="G-1",
                    claim_id=cls.CRITERION,
                    source_id="SRC-CONTRADICT",
                    relation=EvidenceRelation.CONTRADICTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            )
        return ClaimEvidenceRequest(
            assessment_id=f"EA-{mode.upper()}",
            goal_id="G-1",
            claim_id=cls.CRITERION,
            agent_id=BrainAgentId.PERFORMANCE,
            evidence=evidence,
        )

    @classmethod
    def _trajectory_request(cls, mode: str = "supported") -> TrajectoryEvaluationRequest:
        if mode == "continue":
            return TrajectoryEvaluationRequest(
                evaluation_id="TE-CONTINUE",
                goal=cls._goal(),
                plan=cls._plan(complete=False),
                criterion_evidence_requests=[],
            )
        if mode == "revise":
            return TrajectoryEvaluationRequest(
                evaluation_id="TE-REVISE",
                goal=cls._goal(),
                plan=cls._plan(complete=True),
                criterion_evidence_requests=[],
            )
        if mode == "escalate":
            return TrajectoryEvaluationRequest(
                evaluation_id="TE-ESCALATE",
                goal=cls._goal(),
                plan=cls._plan(complete=True, status=PlanStatus.ABANDONED),
                criterion_evidence_requests=[],
            )
        if mode not in {"supported", "refuted", "contested"}:
            raise AssertionError(f"unsupported fixture mode: {mode}")
        return TrajectoryEvaluationRequest(
            evaluation_id=f"TE-{mode.upper()}",
            goal=cls._goal(),
            plan=cls._plan(complete=True),
            criterion_evidence_requests=[cls._raw_evidence_request(mode)],
        )

    @staticmethod
    def _trajectory(**updates) -> TrajectoryEvaluation:
        values = {
            "evaluation_id": "TE-1",
            "goal_id": "G-1",
            "plan_id": "P-1",
            "plan_revision": 1,
            "outcome_verdict": OutcomeVerdict.SATISFIED,
            "disposition": TrajectoryDisposition.STOP,
            "supported_criteria": ["Verified target outcome"],
            "refuted_criteria": [],
            "contested_criteria": [],
            "unresolved_criteria": [],
            "ambiguous_criteria": [],
            "ignored_assessment_ids": [],
            "reasons": ["Every success criterion is evidence-backed."],
        }
        values.update(updates)
        return TrajectoryEvaluation(**values)

    @staticmethod
    def _unknown(**updates) -> UnknownRecord:
        values = {
            "unknown_id": "U-1",
            "goal_id": "G-1",
            "question": "Is the conversion baseline verified?",
            "consequence": "A wrong baseline could invalidate the decision.",
            "blocking": True,
        }
        values.update(updates)
        return UnknownRecord(**values)

    @staticmethod
    def _need(**updates) -> EvidenceNeed:
        values = {
            "need_id": "N-1",
            "goal_id": "G-1",
            "question": "What is the observed conversion baseline?",
            "why_needed": "The goal depends on measured performance.",
            "blocking": True,
            "evidence_refs": [],
        }
        values.update(updates)
        return EvidenceNeed(**values)

    @classmethod
    def _request(cls, mode: str = "supported", **updates) -> StopEvaluationRequest:
        raw = cls._trajectory_request(mode)
        values = {
            "evaluation_id": "SE-1",
            "goal_id": "G-1",
            "trajectory_request": raw,
            "trajectory": evaluate_trajectory(raw),
            "outstanding_unknowns": [],
            "outstanding_evidence_needs": [],
        }
        values.update(updates)
        return StopEvaluationRequest(**values)

    def test_satisfied_trajectory_without_blockers_stops_as_goal_satisfied(self) -> None:
        result = evaluate_stop(self._request())
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.GOAL_SATISFIED)
        self.assertEqual(result.unresolved_questions, [])

    def test_blocking_unknown_overrides_goal_satisfied_stop(self) -> None:
        result = evaluate_stop(self._request(outstanding_unknowns=[self._unknown()]))
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.BLOCKED)
        self.assertIn("Is the conversion baseline verified?", result.unresolved_questions)

    def test_blocking_evidence_need_overrides_goal_satisfied_stop(self) -> None:
        result = evaluate_stop(
            self._request(outstanding_evidence_needs=[self._need()])
        )
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.BLOCKED)
        self.assertIn(
            "What is the observed conversion baseline?", result.unresolved_questions
        )

    def test_evidence_refs_do_not_auto_clear_outstanding_blocking_need(self) -> None:
        result = evaluate_stop(
            self._request(
                outstanding_evidence_needs=[self._need(evidence_refs=["E-1"])]
            )
        )
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.BLOCKED)

    def test_nonblocking_open_questions_are_surfaced_without_forging_blocker(self) -> None:
        result = evaluate_stop(
            self._request(
                outstanding_unknowns=[self._unknown(blocking=False)],
                outstanding_evidence_needs=[self._need(blocking=False)],
            )
        )
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.GOAL_SATISFIED)
        self.assertEqual(
            result.unresolved_questions,
            [
                "Is the conversion baseline verified?",
                "What is the observed conversion baseline?",
            ],
        )

    def test_inconclusive_active_trajectory_continues(self) -> None:
        result = evaluate_stop(self._request(mode="continue"))
        self.assertFalse(result.should_stop)
        self.assertEqual(result.reason, StopReason.CONTINUE)

    def test_refuted_trajectory_stops_current_path_for_revision(self) -> None:
        result = evaluate_stop(self._request(mode="refuted"))
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.INSUFFICIENT_EVIDENCE)

    def test_inconclusive_revision_stops_current_path(self) -> None:
        result = evaluate_stop(self._request(mode="revise"))
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.INSUFFICIENT_EVIDENCE)

    def test_contested_trajectory_escalates_to_human_decision(self) -> None:
        result = evaluate_stop(self._request(mode="contested"))
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.HUMAN_DECISION_REQUIRED)

    def test_inconclusive_escalation_requires_human_decision(self) -> None:
        result = evaluate_stop(self._request(mode="escalate"))
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.HUMAN_DECISION_REQUIRED)

    def test_forged_trajectory_verdict_disposition_pairs_are_rejected(self) -> None:
        forged = [
            (OutcomeVerdict.SATISFIED, TrajectoryDisposition.CONTINUE),
            (OutcomeVerdict.SATISFIED, TrajectoryDisposition.REVISE),
            (OutcomeVerdict.REFUTED, TrajectoryDisposition.STOP),
            (OutcomeVerdict.REFUTED, TrajectoryDisposition.CONTINUE),
            (OutcomeVerdict.CONTESTED, TrajectoryDisposition.STOP),
            (OutcomeVerdict.CONTESTED, TrajectoryDisposition.REVISE),
            (OutcomeVerdict.INCONCLUSIVE, TrajectoryDisposition.STOP),
        ]
        for verdict, disposition in forged:
            with self.subTest(verdict=verdict, disposition=disposition):
                with self.assertRaises(ValidationError):
                    self._request(
                        trajectory_request=None,
                        trajectory=self._trajectory(
                            outcome_verdict=verdict,
                            disposition=disposition,
                        ),
                    )

    def test_satisfied_stop_with_unresolved_or_contradicted_criteria_fails_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                trajectory_request=None,
                trajectory=self._trajectory(unresolved_criteria=["Still unresolved"]),
            )
        with self.assertRaises(ValidationError):
            self._request(
                trajectory_request=None,
                trajectory=self._trajectory(refuted_criteria=["Actually refuted"]),
            )
        with self.assertRaises(ValidationError):
            self._request(
                trajectory_request=None,
                trajectory=self._trajectory(contested_criteria=["Actually contested"]),
            )

    def test_satisfied_stop_requires_at_least_one_supported_criterion(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                trajectory_request=None,
                trajectory=self._trajectory(supported_criteria=[]),
            )

    def test_cross_goal_trajectory_unknown_need_and_raw_request_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                trajectory_request=None,
                trajectory=self._trajectory(goal_id="G-OTHER"),
            )
        with self.assertRaises(ValidationError):
            self._request(outstanding_unknowns=[self._unknown(goal_id="G-OTHER")])
        with self.assertRaises(ValidationError):
            self._request(
                outstanding_evidence_needs=[self._need(goal_id="G-OTHER")]
            )
        wrong_raw = TrajectoryEvaluationRequest(
            evaluation_id="TE-WRONG-GOAL",
            goal=self._goal(goal_id="G-OTHER"),
            plan=self._plan(goal_id="G-OTHER"),
            criterion_evidence_requests=[],
        )
        with self.assertRaises(ValidationError):
            self._request(trajectory=None, trajectory_request=wrong_raw)

    def test_duplicate_outstanding_identities_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(outstanding_unknowns=[self._unknown(), self._unknown()])
        with self.assertRaises(ValidationError):
            self._request(outstanding_evidence_needs=[self._need(), self._need()])

    def test_missing_raw_trajectory_provenance_cannot_authorize_audit_snapshot(self) -> None:
        result = evaluate_stop(
            self._request(trajectory_request=None, trajectory=self._trajectory())
        )
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.INSUFFICIENT_EVIDENCE)

    def test_audit_trajectory_must_match_canonical_raw_evaluation(self) -> None:
        with self.assertRaises(ValidationError):
            evaluate_stop(
                self._request(
                    trajectory=self._trajectory(
                        evaluation_id="TE-FORGED-AUDIT",
                        reasons=["Caller supplied a conflicting audit snapshot."],
                    )
                )
            )

    def test_stop_policy_has_no_body_or_provider_dependency(self) -> None:
        source = inspect.getsource(stopping)
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

        serialized = str(evaluate_stop(self._request()).model_dump()).lower()
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
