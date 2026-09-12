"""Adversarial provenance regression for Brain stop authorization."""

from __future__ import annotations

import unittest

from brain.contracts import StopReason
from brain.outcomes import OutcomeVerdict, TrajectoryDisposition, TrajectoryEvaluation
from brain.stopping import StopEvaluationRequest, evaluate_stop


class BrainStopTrajectoryProvenanceV1Tests(unittest.TestCase):
    def test_fabricated_satisfied_trajectory_cannot_authorize_goal_satisfied_stop(self) -> None:
        fabricated = TrajectoryEvaluation(
            evaluation_id="TE-FORGED",
            goal_id="G-1",
            plan_id="P-1",
            plan_revision=1,
            outcome_verdict=OutcomeVerdict.SATISFIED,
            disposition=TrajectoryDisposition.STOP,
            supported_criteria=["Verified target outcome"],
            refuted_criteria=[],
            contested_criteria=[],
            unresolved_criteria=[],
            ambiguous_criteria=[],
            ignored_assessment_ids=[],
            reasons=["Caller claims every success criterion is evidence-backed."],
        )
        request = StopEvaluationRequest(
            evaluation_id="SE-FORGED",
            goal_id="G-1",
            trajectory=fabricated,
            outstanding_unknowns=[],
            outstanding_evidence_needs=[],
        )

        result = evaluate_stop(request)

        self.assertFalse(
            result.should_stop and result.reason == StopReason.GOAL_SATISFIED,
            "A caller-constructed SATISFIED/STOP trajectory must not independently authorize GOAL_SATISFIED without authoritative raw outcome provenance.",
        )


if __name__ == "__main__":
    unittest.main()
