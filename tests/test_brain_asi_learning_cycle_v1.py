from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId, EvidenceNeed, GoalSpec, UnknownRecord
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.learning import (
    ExperimentDesign,
    ExperimentRisk,
    Hypothesis,
    KnowledgeGapAssessment,
    KnowledgeState,
    LearningAction,
    LearningEpisode,
    LessonDisposition,
    LessonRecord,
    assess_knowledge_state,
    choose_learning_action,
    derive_lesson,
    derive_meta_learning_signal,
    research_directives_for_gaps,
)
from schemas.base import ValidationError


class BrainASILearningCycleV1Tests(unittest.TestCase):
    def _goal(self) -> GoalSpec:
        return GoalSpec(
            goal_id="G-LEARN",
            objective="Learn which campaign strategy causally improves qualified conversions.",
            owner_agent=BrainAgentId.STRATEGIST,
            success_criteria=["A supported causal strategy is identified"],
        )

    def _hypothesis(self, confidence: float = 0.5) -> Hypothesis:
        return Hypothesis(
            hypothesis_id="H-1",
            goal_id="G-LEARN",
            owner_agent=BrainAgentId.STRATEGIST,
            statement="A proof-led creative increases qualified conversion rate.",
            prediction="Qualified conversion rate increases under the proof-led creative.",
            falsification_criteria=[
                "qualified conversion rate does not improve",
                "the observed lift disappears after controlling for audience mix",
            ],
            prior_confidence=confidence,
        )

    def _evidence_request(
        self,
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-LEARN",
            goal_id="G-LEARN",
            claim_id="H-1",
            agent_id=BrainAgentId.STRATEGIST,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-LEARN-1",
                    goal_id="G-LEARN",
                    claim_id="H-1",
                    source_id="SRC-EXPERIMENT-1",
                    relation=relation,
                    strength=EvidenceStrength.STRONG,
                    origin=origin,
                )
            ],
        )

    def _episode(
        self,
        *,
        matched: bool,
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
        episode_id: str = "EP-1",
    ) -> LearningEpisode:
        return LearningEpisode(
            episode_id=episode_id,
            goal_id="G-LEARN",
            owner_agent=BrainAgentId.STRATEGIST,
            hypothesis=self._hypothesis(),
            expected_outcome="Qualified conversion rate rises by a material amount.",
            observed_outcome=(
                "Qualified conversion rate rose in the controlled test."
                if matched
                else "Qualified conversion rate did not rise as predicted."
            ),
            causal_explanation=(
                "The controlled intervention isolates the creative treatment from the baseline."
            ),
            evidence_request=self._evidence_request(relation=relation, origin=origin),
            experiment_id="EXP-1",
            prediction_matched=matched,
        )

    def test_no_unknowns_means_knowledge_is_sufficient(self) -> None:
        assessment = assess_knowledge_state(
            self._goal(), unknowns=[], evidence_needs=[]
        )
        self.assertEqual(assessment.state, KnowledgeState.SUFFICIENT)
        self.assertEqual(assessment.recommended_action, LearningAction.ACT)
        self.assertEqual(research_directives_for_gaps(assessment), [])

    def test_blocking_unknown_forces_research(self) -> None:
        unknown = UnknownRecord(
            unknown_id="U-1",
            goal_id="G-LEARN",
            question="Is the conversion lift causal rather than audience mix?",
            consequence="Acting without this answer can scale a false strategy.",
            blocking=True,
        )
        need = EvidenceNeed(
            need_id="EN-1",
            goal_id="G-LEARN",
            question=unknown.question,
            why_needed="Causal attribution is required before scaling.",
            blocking=True,
        )
        assessment = assess_knowledge_state(
            self._goal(), unknowns=[unknown], evidence_needs=[need]
        )
        self.assertEqual(assessment.state, KnowledgeState.BLOCKED)
        self.assertEqual(choose_learning_action(knowledge=assessment), LearningAction.RESEARCH)
        directives = research_directives_for_gaps(assessment)
        self.assertEqual(len(directives), 1)
        self.assertEqual(directives[0].required_evidence, ["EN-1"])
        self.assertGreaterEqual(len(directives[0].stop_when), 3)

    def test_nonblocking_unknown_is_still_explicit_gap(self) -> None:
        assessment = assess_knowledge_state(
            self._goal(),
            unknowns=[
                UnknownRecord(
                    unknown_id="U-2",
                    goal_id="G-LEARN",
                    question="Does the effect transfer to another audience?",
                    consequence="Scope may be narrower than assumed.",
                    blocking=False,
                )
            ],
            evidence_needs=[],
        )
        self.assertEqual(assessment.state, KnowledgeState.GAP)
        self.assertEqual(assessment.recommended_action, LearningAction.RESEARCH)

    def test_hypothesis_must_be_falsifiable(self) -> None:
        with self.assertRaises(ValidationError):
            Hypothesis(
                hypothesis_id="H-BAD",
                goal_id="G-LEARN",
                owner_agent=BrainAgentId.STRATEGIST,
                statement="Everything will work.",
                prediction="Success.",
                falsification_criteria=[],
            )

    def test_sufficient_knowledge_with_hypothesis_requests_experiment(self) -> None:
        knowledge = KnowledgeGapAssessment(
            goal_id="G-LEARN",
            state=KnowledgeState.SUFFICIENT,
            gaps=[],
            recommended_action=LearningAction.ACT,
            rationale="No unresolved gap.",
        )
        self.assertEqual(
            choose_learning_action(knowledge=knowledge, hypothesis=self._hypothesis()),
            LearningAction.EXPERIMENT,
        )

    def test_critical_experiment_is_held(self) -> None:
        knowledge = KnowledgeGapAssessment(
            goal_id="G-LEARN",
            state=KnowledgeState.SUFFICIENT,
            gaps=[],
            recommended_action=LearningAction.ACT,
            rationale="No unresolved gap.",
        )
        experiment = ExperimentDesign(
            experiment_id="EXP-CRIT",
            goal_id="G-LEARN",
            hypothesis_id="H-1",
            owner_agent=BrainAgentId.STRATEGIST,
            intervention="Perform a consequential irreversible market intervention.",
            expected_observation="Observe causal response.",
            success_signal="Predefined success threshold is met.",
            failure_signal="Predefined failure threshold is met.",
            risk=ExperimentRisk.CRITICAL,
            reversible=False,
        )
        self.assertEqual(
            choose_learning_action(
                knowledge=knowledge,
                hypothesis=self._hypothesis(),
                experiment=experiment,
            ),
            LearningAction.HOLD,
        )

    def test_verified_prediction_becomes_verified_lesson(self) -> None:
        lesson = derive_lesson(self._episode(matched=True))
        self.assertEqual(lesson.disposition, LessonDisposition.VERIFIED)
        self.assertTrue(lesson.prediction_matched)
        self.assertGreater(lesson.posterior_confidence, 0.5)
        self.assertEqual(lesson.evidence_refs, ["E-LEARN-1"])

    def test_supported_evidence_with_prediction_miss_revises_confidence(self) -> None:
        lesson = derive_lesson(self._episode(matched=False))
        self.assertEqual(lesson.disposition, LessonDisposition.VERIFIED)
        self.assertFalse(lesson.prediction_matched)
        self.assertLess(lesson.posterior_confidence, 0.5)
        self.assertIn("revise the causal model", lesson.lesson)

    def test_refuted_hypothesis_is_rejected_as_valid_lesson(self) -> None:
        lesson = derive_lesson(
            self._episode(matched=False, relation=EvidenceRelation.CONTRADICTS)
        )
        self.assertEqual(lesson.disposition, LessonDisposition.REJECTED)
        self.assertLess(lesson.posterior_confidence, 0.5)

    def test_derived_only_evidence_cannot_verify_learning(self) -> None:
        lesson = derive_lesson(
            self._episode(
                matched=True,
                relation=EvidenceRelation.SUPPORTS,
                origin=EvidenceOrigin.DERIVED,
            )
        )
        self.assertEqual(lesson.disposition, LessonDisposition.CANDIDATE)
        self.assertEqual(lesson.posterior_confidence, 0.5)

    def test_meta_learning_changes_strategy_after_repeated_verified_misses(self) -> None:
        lessons = [
            derive_lesson(self._episode(matched=False, episode_id="EP-1")),
            derive_lesson(self._episode(matched=False, episode_id="EP-2")),
            derive_lesson(self._episode(matched=True, episode_id="EP-3")),
        ]
        signal = derive_meta_learning_signal(
            signal_id="META-1",
            owner_agent=BrainAgentId.STRATEGIST,
            lessons=lessons,
        )
        self.assertIn("prediction error", signal.pattern)
        self.assertIn("disconfirming evidence", signal.recommended_change)
        self.assertEqual(len(signal.supporting_lesson_ids), 3)
        self.assertGreater(signal.confidence, 0.5)

    def test_meta_learning_rejects_unverified_only_history(self) -> None:
        candidate = LessonRecord(
            lesson_id="LESSON-CANDIDATE",
            goal_id="G-LEARN",
            owner_agent=BrainAgentId.STRATEGIST,
            episode_id="EP-C",
            hypothesis_id="H-1",
            lesson="More evidence is required.",
            causal_explanation="No causal conclusion yet.",
            prediction_matched=False,
            posterior_confidence=0.5,
            evidence_refs=[],
            disposition=LessonDisposition.CANDIDATE,
        )
        with self.assertRaises(ValidationError):
            derive_meta_learning_signal(
                signal_id="META-BAD",
                owner_agent=BrainAgentId.STRATEGIST,
                lessons=[candidate],
            )


if __name__ == "__main__":
    unittest.main()
