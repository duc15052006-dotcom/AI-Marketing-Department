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


class BrainMetaLearningPolicyV1Tests(unittest.TestCase):
    def _request(self, assessment_id: str, gap_count: int) -> MetacognitionRequest:
        gaps = [
            KnowledgeGap(
                gap_id=f"GAP-{assessment_id}-{index}",
                goal_id="G-METALEARN",
                owner_agent=BrainAgentId.INTELLIGENCE,
                kind=KnowledgeGapKind.UNKNOWN,
                question=f"Unknown {index}",
                consequence="Knowledge gap must be reduced.",
                blocking=index == 0 and gap_count > 1,
            )
            for index in range(gap_count)
        ]
        return MetacognitionRequest(
            assessment_id=assessment_id,
            goal_id="G-METALEARN",
            agent_id=BrainAgentId.INTELLIGENCE,
            gaps=gaps,
        )

    def _trial(
        self,
        trial_id: str,
        strategy: LearningStrategy,
        before_gaps: int,
        after_gaps: int,
    ) -> StrategyTrial:
        return StrategyTrial(
            trial_id=trial_id,
            problem_family_id="PF-MARKET-RESEARCH",
            strategy=strategy,
            before_request=self._request(f"B-{trial_id}", before_gaps),
            after_request=self._request(f"A-{trial_id}", after_gaps),
        )

    def test_fewer_than_three_trials_cannot_update_policy(self) -> None:
        decision = evaluate_meta_learning(
            MetaLearningRequest(
                assessment_id="ML-1",
                problem_family_id="PF-MARKET-RESEARCH",
                policy_owner_agent=BrainAgentId.CMO,
                trials=[
                    self._trial("T-1", LearningStrategy.RESEARCH, 2, 0),
                    self._trial("T-2", LearningStrategy.RESEARCH, 1, 0),
                ],
            )
        )
        self.assertEqual(
            decision.disposition,
            MetaLearningDisposition.INSUFFICIENT_EVIDENCE,
        )
        self.assertIsNone(decision.preferred_strategy)

    def test_repeated_safe_improvement_can_prefer_strategy(self) -> None:
        decision = evaluate_meta_learning(
            MetaLearningRequest(
                assessment_id="ML-2",
                problem_family_id="PF-MARKET-RESEARCH",
                policy_owner_agent=BrainAgentId.CMO,
                trials=[
                    self._trial("T-1", LearningStrategy.RESEARCH, 2, 0),
                    self._trial("T-2", LearningStrategy.RESEARCH, 1, 0),
                    self._trial("T-3", LearningStrategy.RESEARCH, 3, 1),
                ],
            )
        )
        self.assertEqual(
            decision.disposition,
            MetaLearningDisposition.PREFER_STRATEGY,
        )
        self.assertEqual(
            decision.preferred_strategy,
            LearningStrategy.RESEARCH,
        )

    def test_unique_better_strategy_wins_over_regressing_alternative(self) -> None:
        trials = [
            self._trial("R-1", LearningStrategy.RESEARCH, 2, 0),
            self._trial("R-2", LearningStrategy.RESEARCH, 1, 0),
            self._trial("R-3", LearningStrategy.RESEARCH, 3, 1),
            self._trial("E-1", LearningStrategy.EXPERIMENT, 1, 2),
            self._trial("E-2", LearningStrategy.EXPERIMENT, 2, 3),
            self._trial("E-3", LearningStrategy.EXPERIMENT, 2, 2),
        ]
        decision = evaluate_meta_learning(
            MetaLearningRequest(
                assessment_id="ML-3",
                problem_family_id="PF-MARKET-RESEARCH",
                policy_owner_agent=BrainAgentId.CMO,
                trials=trials,
            )
        )
        self.assertEqual(
            decision.disposition,
            MetaLearningDisposition.PREFER_STRATEGY,
        )
        self.assertEqual(decision.preferred_strategy, LearningStrategy.RESEARCH)

    def test_tied_strategies_retain_policy(self) -> None:
        trials = [
            self._trial("R-1", LearningStrategy.RESEARCH, 1, 0),
            self._trial("R-2", LearningStrategy.RESEARCH, 2, 0),
            self._trial("R-3", LearningStrategy.RESEARCH, 3, 1),
            self._trial("E-1", LearningStrategy.EXPERIMENT, 1, 0),
            self._trial("E-2", LearningStrategy.EXPERIMENT, 2, 0),
            self._trial("E-3", LearningStrategy.EXPERIMENT, 3, 1),
        ]
        decision = evaluate_meta_learning(
            MetaLearningRequest(
                assessment_id="ML-4",
                problem_family_id="PF-MARKET-RESEARCH",
                policy_owner_agent=BrainAgentId.CMO,
                trials=trials,
            )
        )
        self.assertEqual(
            decision.disposition,
            MetaLearningDisposition.RETAIN_POLICY,
        )
        self.assertIsNone(decision.preferred_strategy)

    def test_consistently_regressing_strategies_require_policy_revision(self) -> None:
        trials = [
            self._trial("R-1", LearningStrategy.RESEARCH, 0, 1),
            self._trial("R-2", LearningStrategy.RESEARCH, 1, 2),
            self._trial("R-3", LearningStrategy.RESEARCH, 1, 1),
        ]
        decision = evaluate_meta_learning(
            MetaLearningRequest(
                assessment_id="ML-5",
                problem_family_id="PF-MARKET-RESEARCH",
                policy_owner_agent=BrainAgentId.CMO,
                trials=trials,
            )
        )
        self.assertEqual(
            decision.disposition,
            MetaLearningDisposition.REVISE_POLICY,
        )

    def test_trial_before_after_must_bind_same_goal(self) -> None:
        before = self._request("B-X", 1)
        after = MetacognitionRequest(
            assessment_id="A-X",
            goal_id="G-OTHER",
            agent_id=BrainAgentId.INTELLIGENCE,
        )
        with self.assertRaises(ValidationError):
            StrategyTrial(
                trial_id="T-X",
                problem_family_id="PF-MARKET-RESEARCH",
                strategy=LearningStrategy.RESEARCH,
                before_request=before,
                after_request=after,
            )

    def test_none_is_not_a_learning_strategy_trial(self) -> None:
        with self.assertRaises(ValidationError):
            StrategyTrial(
                trial_id="T-NONE",
                problem_family_id="PF-MARKET-RESEARCH",
                strategy=LearningStrategy.NONE,
                before_request=self._request("B-NONE", 1),
                after_request=self._request("A-NONE", 0),
            )

    def test_post_construction_request_scope_mutation_fails_closed(self) -> None:
        request = MetaLearningRequest(
            assessment_id="ML-MUT-SCOPE",
            problem_family_id="PF-MARKET-RESEARCH",
            policy_owner_agent=BrainAgentId.CMO,
            trials=[
                self._trial("M-1", LearningStrategy.RESEARCH, 2, 0),
                self._trial("M-2", LearningStrategy.RESEARCH, 1, 0),
                self._trial("M-3", LearningStrategy.RESEARCH, 3, 1),
            ],
        )
        request.problem_family_id = "PF-MUTATED"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_post_construction_trial_scope_mutation_fails_closed(self) -> None:
        request = MetaLearningRequest(
            assessment_id="ML-MUT-TRIAL-SCOPE",
            problem_family_id="PF-MARKET-RESEARCH",
            policy_owner_agent=BrainAgentId.CMO,
            trials=[
                self._trial("S-1", LearningStrategy.RESEARCH, 2, 0),
                self._trial("S-2", LearningStrategy.RESEARCH, 1, 0),
                self._trial("S-3", LearningStrategy.RESEARCH, 3, 1),
            ],
        )
        request.trials[0].problem_family_id = "PF-MUTATED"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_post_construction_duplicate_trial_id_mutation_fails_closed(self) -> None:
        request = MetaLearningRequest(
            assessment_id="ML-MUT-DUPLICATE",
            problem_family_id="PF-MARKET-RESEARCH",
            policy_owner_agent=BrainAgentId.CMO,
            trials=[
                self._trial("D-1", LearningStrategy.RESEARCH, 2, 0),
                self._trial("D-2", LearningStrategy.RESEARCH, 1, 0),
                self._trial("D-3", LearningStrategy.RESEARCH, 3, 1),
            ],
        )
        request.trials[1].trial_id = request.trials[0].trial_id
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)


if __name__ == "__main__":
    unittest.main()
