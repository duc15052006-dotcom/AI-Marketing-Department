"""Adversarial tests for provider-neutral Brain stop intelligence v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.stopping as stopping
from brain.contracts import EvidenceNeed, StopReason, UnknownRecord
from brain.outcomes import OutcomeVerdict, TrajectoryDisposition, TrajectoryEvaluation
from brain.stopping import StopEvaluationRequest, evaluate_stop
from schemas.base import ValidationError


class BrainStopIntelligenceV1Tests(unittest.TestCase):
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
    def _request(cls, **updates) -> StopEvaluationRequest:
        values = {
            "evaluation_id": "SE-1",
            "goal_id": "G-1",
            "trajectory": cls._trajectory(),
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
        result = evaluate_stop(
            self._request(outstanding_unknowns=[self._unknown()])
        )
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
        result = evaluate_stop(
            self._request(
                trajectory=self._trajectory(
                    outcome_verdict=OutcomeVerdict.INCONCLUSIVE,
                    disposition=TrajectoryDisposition.CONTINUE,
                    supported_criteria=[],
                    unresolved_criteria=["Verified target outcome"],
                )
            )
        )
        self.assertFalse(result.should_stop)
        self.assertEqual(result.reason, StopReason.CONTINUE)

    def test_refuted_trajectory_stops_current_path_for_revision(self) -> None:
        result = evaluate_stop(
            self._request(
                trajectory=self._trajectory(
                    outcome_verdict=OutcomeVerdict.REFUTED,
                    disposition=TrajectoryDisposition.REVISE,
                    supported_criteria=[],
                    refuted_criteria=["Verified target outcome"],
                )
            )
        )
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.INSUFFICIENT_EVIDENCE)

    def test_inconclusive_revision_stops_current_path(self) -> None:
        result = evaluate_stop(
            self._request(
                trajectory=self._trajectory(
                    outcome_verdict=OutcomeVerdict.INCONCLUSIVE,
                    disposition=TrajectoryDisposition.REVISE,
                    supported_criteria=[],
                    unresolved_criteria=["Verified target outcome"],
                )
            )
        )
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.INSUFFICIENT_EVIDENCE)

    def test_contested_trajectory_escalates_to_human_decision(self) -> None:
        result = evaluate_stop(
            self._request(
                trajectory=self._trajectory(
                    outcome_verdict=OutcomeVerdict.CONTESTED,
                    disposition=TrajectoryDisposition.ESCALATE,
                    supported_criteria=[],
                    contested_criteria=["Verified target outcome"],
                )
            )
        )
        self.assertTrue(result.should_stop)
        self.assertEqual(result.reason, StopReason.HUMAN_DECISION_REQUIRED)

    def test_inconclusive_escalation_requires_human_decision(self) -> None:
        result = evaluate_stop(
            self._request(
                trajectory=self._trajectory(
                    outcome_verdict=OutcomeVerdict.INCONCLUSIVE,
                    disposition=TrajectoryDisposition.ESCALATE,
                    supported_criteria=[],
                    unresolved_criteria=["Verified target outcome"],
                )
            )
        )
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
                        trajectory=self._trajectory(
                            outcome_verdict=verdict,
                            disposition=disposition,
                        )
                    )

    def test_satisfied_stop_with_unresolved_or_contradicted_criteria_fails_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                trajectory=self._trajectory(
                    unresolved_criteria=["Still unresolved"]
                )
            )
        with self.assertRaises(ValidationError):
            self._request(
                trajectory=self._trajectory(
                    refuted_criteria=["Actually refuted"]
                )
            )
        with self.assertRaises(ValidationError):
            self._request(
                trajectory=self._trajectory(
                    contested_criteria=["Actually contested"]
                )
            )

    def test_satisfied_stop_requires_at_least_one_supported_criterion(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(trajectory=self._trajectory(supported_criteria=[]))

    def test_cross_goal_trajectory_unknown_and_need_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(trajectory=self._trajectory(goal_id="G-OTHER"))
        with self.assertRaises(ValidationError):
            self._request(outstanding_unknowns=[self._unknown(goal_id="G-OTHER")])
        with self.assertRaises(ValidationError):
            self._request(
                outstanding_evidence_needs=[self._need(goal_id="G-OTHER")]
            )

    def test_duplicate_outstanding_identities_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                outstanding_unknowns=[self._unknown(), self._unknown()]
            )
        with self.assertRaises(ValidationError):
            self._request(
                outstanding_evidence_needs=[self._need(), self._need()]
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
