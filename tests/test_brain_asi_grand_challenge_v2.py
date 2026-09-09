from __future__ import annotations

import copy
import unittest

from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.learning import (
    LearningClaimKind,
    LearningDisposition,
    LearningEpisode,
    LearningMethod,
    analyze_learning_episode,
)
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
    assess_metacognition,
)
from schemas.base import ValidationError


class BrainASIGrandChallengeV2Tests(unittest.TestCase):
    """Future-ASI-style hidden holdout for semantic authority and self-learning.

    The suite deliberately mutates already-validated objects, composes cross-layer
    state, and attacks causal/meta-learning authority boundaries. A robust Brain
    may either reject the mutation or preserve the pre-mutation semantic result,
    but it must never silently upgrade forged state into stronger knowledge.
    """

    @staticmethod
    def _evidence_request(
        *,
        goal_id: str = "G-FRONTIER",
        claim_id: str = "H-FRONTIER",
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-FRONTIER",
            goal_id=goal_id,
            claim_id=claim_id,
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-FRONTIER",
                    goal_id=goal_id,
                    claim_id=claim_id,
                    source_id="SRC-FRONTIER",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    @classmethod
    def _learning_episode(
        cls,
        *,
        claim_kind: LearningClaimKind = LearningClaimKind.CAUSAL,
        method: LearningMethod = LearningMethod.OBSERVATION,
        intervention_id: str | None = None,
        control_ref: str | None = None,
    ) -> LearningEpisode:
        return LearningEpisode(
            episode_id="LE-FRONTIER",
            goal_id="G-FRONTIER",
            agent_id=BrainAgentId.STRATEGIST,
            hypothesis_id="H-FRONTIER",
            claim_kind=claim_kind,
            method=method,
            hypothesis="Changing creative A causes conversion quality to improve.",
            prediction="Intervening on creative A should improve conversion quality.",
            evidence_request=cls._evidence_request(),
            intervention_id=intervention_id,
            control_ref=control_ref,
        )

    @staticmethod
    def _meta_request(assessment_id: str, gap_count: int) -> MetacognitionRequest:
        return MetacognitionRequest(
            assessment_id=assessment_id,
            goal_id="G-META-FRONTIER",
            agent_id=BrainAgentId.INTELLIGENCE,
            gaps=[
                KnowledgeGap(
                    gap_id=f"GAP-{assessment_id}-{index}",
                    goal_id="G-META-FRONTIER",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    kind=KnowledgeGapKind.UNKNOWN,
                    question=f"Unknown {index}",
                    consequence="The uncertainty must be reduced before policy confidence rises.",
                    blocking=index == 0 and gap_count > 1,
                )
                for index in range(gap_count)
            ],
        )

    @classmethod
    def _trial(
        cls,
        trial_id: str,
        strategy: LearningStrategy,
        before_gaps: int,
        after_gaps: int,
    ) -> StrategyTrial:
        return StrategyTrial(
            trial_id=trial_id,
            problem_family_id="PF-FRONTIER",
            strategy=strategy,
            before_request=cls._meta_request(f"B-{trial_id}", before_gaps),
            after_request=cls._meta_request(f"A-{trial_id}", after_gaps),
        )

    @classmethod
    def _meta_learning_request(cls) -> MetaLearningRequest:
        return MetaLearningRequest(
            assessment_id="ML-FRONTIER",
            problem_family_id="PF-FRONTIER",
            policy_owner_agent=BrainAgentId.CMO,
            trials=[
                cls._trial("T-1", LearningStrategy.RESEARCH, 2, 0),
                cls._trial("T-2", LearningStrategy.RESEARCH, 1, 0),
                cls._trial("T-3", LearningStrategy.RESEARCH, 3, 1),
            ],
        )

    def test_exactly_five_permanent_asi_identities_exist(self) -> None:
        self.assertEqual(
            {member.value for member in BrainAgentId},
            {"CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"},
        )

    def test_metacognition_nested_boolean_mutation_fails_closed(self) -> None:
        request = self._meta_request("META-BOOL", 2)
        request.gaps[0].blocking = 0
        with self.assertRaises(ValidationError):
            assess_metacognition(request)

    def test_metacognition_cross_goal_mutation_fails_closed(self) -> None:
        request = self._meta_request("META-GOAL", 1)
        request.gaps[0].goal_id = "G-FOREIGN"
        with self.assertRaises(ValidationError):
            assess_metacognition(request)

    def test_observational_causal_support_remains_noncausal(self) -> None:
        result = analyze_learning_episode(self._learning_episode())
        self.assertEqual(result.disposition, LearningDisposition.TEST_CAUSALLY)
        self.assertIsNone(result.lesson_candidate)

    def test_claim_kind_mutation_cannot_launder_correlation_into_fact(self) -> None:
        episode = self._learning_episode()
        episode.claim_kind = LearningClaimKind.FACTUAL
        try:
            result = analyze_learning_episode(episode)
        except ValidationError:
            return
        self.assertNotEqual(
            result.disposition,
            LearningDisposition.CANDIDATE_LESSON,
            "Post-validation claim-kind mutation must not convert observational causal support into a durable-looking lesson candidate.",
        )

    def test_method_and_control_mutation_cannot_forge_causal_experiment(self) -> None:
        episode = self._learning_episode()
        episode.method = LearningMethod.EXPERIMENT
        episode.intervention_id = "INT-FORGED"
        episode.control_ref = "CTRL-FORGED"
        try:
            result = analyze_learning_episode(episode)
        except ValidationError:
            return
        self.assertNotEqual(
            result.disposition,
            LearningDisposition.CANDIDATE_LESSON,
            "Construction-time observational evidence must not become causal proof by mutating experiment metadata later.",
        )

    def test_hypothesis_binding_mutation_cannot_rebind_evidence(self) -> None:
        episode = self._learning_episode(claim_kind=LearningClaimKind.FACTUAL)
        episode.hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            analyze_learning_episode(episode)

    def test_removing_control_after_validation_cannot_preserve_causal_candidate(self) -> None:
        episode = self._learning_episode(
            method=LearningMethod.EXPERIMENT,
            intervention_id="INT-REAL",
            control_ref="CTRL-REAL",
        )
        self.assertEqual(
            analyze_learning_episode(episode).disposition,
            LearningDisposition.CANDIDATE_LESSON,
        )
        episode.control_ref = None
        result = analyze_learning_episode(episode)
        self.assertEqual(result.disposition, LearningDisposition.TEST_CAUSALLY)

    def test_meta_learning_baseline_prefers_repeated_safe_research(self) -> None:
        result = evaluate_meta_learning(self._meta_learning_request())
        self.assertEqual(result.disposition, MetaLearningDisposition.PREFER_STRATEGY)
        self.assertEqual(result.preferred_strategy, LearningStrategy.RESEARCH)

    def test_meta_learning_strategy_mutation_cannot_poison_policy(self) -> None:
        request = self._meta_learning_request()
        baseline = evaluate_meta_learning(copy.deepcopy(request))
        for trial in request.trials:
            trial.strategy = LearningStrategy.EXPERIMENT
        try:
            mutated = evaluate_meta_learning(request)
        except ValidationError:
            return
        self.assertEqual(
            mutated.preferred_strategy,
            baseline.preferred_strategy,
            "A validated trial history must not be relabeled into another strategy after construction.",
        )

    def test_meta_learning_problem_family_mutation_fails_closed(self) -> None:
        request = self._meta_learning_request()
        request.trials[0].problem_family_id = "PF-FOREIGN"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_meta_learning_duplicate_trial_id_mutation_fails_closed(self) -> None:
        request = self._meta_learning_request()
        request.trials[1].trial_id = request.trials[0].trial_id
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_meta_learning_nested_goal_mutation_fails_closed(self) -> None:
        request = self._meta_learning_request()
        request.trials[0].before_request.goal_id = "G-FOREIGN"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)

    def test_meta_learning_invalid_strategy_mutation_fails_closed(self) -> None:
        request = self._meta_learning_request()
        request.trials[0].strategy = "FAKE_SUPER_STRATEGY"
        with self.assertRaises(ValidationError):
            evaluate_meta_learning(request)


if __name__ == "__main__":
    unittest.main()
