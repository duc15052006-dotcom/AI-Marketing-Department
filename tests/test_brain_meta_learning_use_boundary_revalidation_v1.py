from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId
from brain.meta_learning import (
    MetaLearningDisposition,
    MetaLearningRequest,
    StrategyTrial,
    evaluate_meta_learning,
)
from brain.metacognition import (
    KnowledgeGap,
    KnowledgeGapKind,
    LearningStrategy,
    MetacognitionRequest,
)
from schemas.base import ValidationError


class BrainMetaLearningUseBoundaryRevalidationV1Tests(unittest.TestCase):
    @staticmethod
    def _request(assessment_id: str, gaps: int) -> MetacognitionRequest:
        return MetacognitionRequest(
            assessment_id=assessment_id,
            goal_id="G-MLUB",
            agent_id=BrainAgentId.INTELLIGENCE,
            gaps=[
                KnowledgeGap(
                    gap_id=f"GAP-{assessment_id}-{i}",
                    goal_id="G-MLUB",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    kind=KnowledgeGapKind.UNKNOWN,
                    question=f"Unknown {i}",
                    consequence="Must reduce uncertainty.",
                    blocking=i == 0 and gaps > 1,
                )
                for i in range(gaps)
            ],
        )

    @classmethod
    def _trial(cls, trial_id: str, before: int, after: int) -> StrategyTrial:
        return StrategyTrial(
            trial_id=trial_id,
            problem_family_id="PF-MLUB",
            strategy=LearningStrategy.RESEARCH,
            before_request=cls._request(f"B-{trial_id}", before),
            after_request=cls._request(f"A-{trial_id}", after),
        )

    @classmethod
    def _request_set(cls) -> MetaLearningRequest:
        return MetaLearningRequest(
            assessment_id="ML-UB",
            problem_family_id="PF-MLUB",
            policy_owner_agent=BrainAgentId.CMO,
            trials=[
                cls._trial("T-1", 2, 0),
                cls._trial("T-2", 1, 0),
                cls._trial("T-3", 3, 1),
            ],
        )

    def test_baseline_preference_is_research(self) -> None:
        result = evaluate_meta_learning(self._request_set())
        self.assertEqual(result.disposition, MetaLearningDisposition.PREFER_STRATEGY)
        self.assertEqual(result.preferred_strategy, LearningStrategy.RESEARCH)

    def test_strategy_relabel_post_validation_is_revalidated(self) -> None:
        request = self._request_set()
        for trial in request.trials:
            trial.strategy = LearningStrategy.EXPERIMENT
        result = evaluate_meta_learning(request)
        self.assertEqual(result.preferred_strategy, LearningStrategy.EXPERIMENT)
        # The key invariant is that the mutated history is revalidated as a new
        # semantic envelope rather than bypassing enum/shape validation.

    def test_foreign_problem_family_post_validation_fails_closed(self) -> None:
        request = self._request_set()
        request.trials[0].problem_family_id = "PF-FOREIGN"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_duplicate_trial_id_post_validation_fails_closed(self) -> None:
        request = self._request_set()
        request.trials[1].trial_id = request.trials[0].trial_id
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_invalid_strategy_post_validation_is_validation_error(self) -> None:
        request = self._request_set()
        request.trials[0].strategy = "FAKE_SUPER_STRATEGY"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_nested_goal_mutation_fails_closed(self) -> None:
        request = self._request_set()
        request.trials[0].before_request.goal_id = "G-FOREIGN"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)


if __name__ == "__main__":
    unittest.main()
