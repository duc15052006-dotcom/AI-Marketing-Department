from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId
from brain.reasoning import (
    ReasoningAssessment,
    ReasoningDepth,
    SignalLevel,
    select_reasoning_depth,
)
from schemas.base import ValidationError


class TestBrainReasoningUseBoundaryRevalidationV1(unittest.TestCase):
    def _assessment(self) -> ReasoningAssessment:
        return ReasoningAssessment(
            assessment_id="reasoning-use-boundary",
            goal_id="goal-1",
            agent_id=BrainAgentId.CMO,
            consequence=SignalLevel.CRITICAL,
        )

    def test_post_construction_invalid_enum_mutation_fails_closed(self):
        assessment = self._assessment()
        assessment.consequence = "NOT_A_SIGNAL_LEVEL"
        with self.assertRaises(ValidationError):
            select_reasoning_depth(assessment)

    def test_post_construction_invalid_boolean_mutation_fails_closed(self):
        assessment = self._assessment()
        assessment.causal_reasoning_required = 1
        with self.assertRaises(ValidationError):
            select_reasoning_depth(assessment)

    def test_post_construction_invalid_agent_mutation_fails_closed(self):
        assessment = self._assessment()
        assessment.agent_id = "SIXTH_ASI"
        with self.assertRaises(ValidationError):
            select_reasoning_depth(assessment)

    def test_valid_critical_assessment_retains_maximum_depth(self):
        decision = select_reasoning_depth(self._assessment())
        self.assertEqual(decision.depth, ReasoningDepth.MAXIMUM)
        self.assertEqual(decision.agent_id, BrainAgentId.CMO)


if __name__ == "__main__":
    unittest.main()
