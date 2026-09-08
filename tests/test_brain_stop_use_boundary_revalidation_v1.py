from __future__ import annotations

import unittest

from brain.contracts import StopReason, UnknownRecord
from brain.outcomes import OutcomeVerdict, TrajectoryDisposition, TrajectoryEvaluation
from brain.stopping import StopEvaluationRequest, evaluate_stop
from schemas.base import ValidationError


class BrainStopUseBoundaryRevalidationV1Tests(unittest.TestCase):
    @staticmethod
    def _request() -> StopEvaluationRequest:
        return StopEvaluationRequest(
            evaluation_id="SE-BOUNDARY",
            goal_id="G-BOUNDARY",
            trajectory=TrajectoryEvaluation(
                evaluation_id="TE-AUDIT",
                goal_id="G-BOUNDARY",
                plan_id="P-BOUNDARY",
                plan_revision=1,
                outcome_verdict=OutcomeVerdict.SATISFIED,
                disposition=TrajectoryDisposition.STOP,
                supported_criteria=["Verified criterion"],
                reasons=["Audit trajectory is internally canonical."],
            ),
            outstanding_unknowns=[
                UnknownRecord(
                    unknown_id="U-BLOCK",
                    goal_id="G-BOUNDARY",
                    question="Is the high-consequence unknown resolved?",
                    consequence="Unsafe stop if unresolved.",
                    blocking=True,
                )
            ],
        )

    def test_valid_blocker_still_dominates(self) -> None:
        decision = evaluate_stop(self._request())
        self.assertTrue(decision.should_stop)
        self.assertEqual(decision.reason, StopReason.BLOCKED)

    def test_post_validation_blocking_integer_mutation_is_rejected(self) -> None:
        request = self._request()
        request.outstanding_unknowns[0].blocking = 0  # type: ignore[assignment]
        with self.assertRaises(ValidationError):
            evaluate_stop(request)

    def test_post_validation_blocker_goal_mutation_is_rejected(self) -> None:
        request = self._request()
        request.outstanding_unknowns[0].goal_id = "OTHER-GOAL"
        with self.assertRaises(ValidationError):
            evaluate_stop(request)


if __name__ == "__main__":
    unittest.main()
