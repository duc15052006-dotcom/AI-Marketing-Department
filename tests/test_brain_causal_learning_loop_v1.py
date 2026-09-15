from __future__ import annotations

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
from brain.metacognition import LearningStrategy
from schemas.base import ValidationError


class BrainCausalLearningLoopV1Tests(unittest.TestCase):
    def _request(
        self,
        *,
        relation: EvidenceRelation,
        source_id: str = "SRC-1",
        second_relation: EvidenceRelation | None = None,
    ) -> ClaimEvidenceRequest:
        evidence = [
            EvidenceSignal(
                evidence_id="E-1",
                goal_id="G-LEARN",
                claim_id="H-1",
                source_id=source_id,
                relation=relation,
                strength=EvidenceStrength.STRONG,
                origin=EvidenceOrigin.OBSERVED,
            )
        ]
        if second_relation is not None:
            evidence.append(
                EvidenceSignal(
                    evidence_id="E-2",
                    goal_id="G-LEARN",
                    claim_id="H-1",
                    source_id="SRC-2",
                    relation=second_relation,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            )
        return ClaimEvidenceRequest(
            assessment_id="EA-LEARN",
            goal_id="G-LEARN",
            claim_id="H-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=evidence,
        )

    def _episode(
        self,
        *,
        claim_kind: LearningClaimKind = LearningClaimKind.FACTUAL,
        method: LearningMethod = LearningMethod.OBSERVATION,
        evidence_request: ClaimEvidenceRequest | None = None,
        intervention_id: str | None = None,
        control_ref: str | None = None,
    ) -> LearningEpisode:
        return LearningEpisode(
            episode_id="LE-1",
            goal_id="G-LEARN",
            agent_id=BrainAgentId.CONTENT,
            hypothesis_id="H-1",
            claim_kind=claim_kind,
            method=method,
            hypothesis="Creative A improves conversion quality.",
            prediction="If the hypothesis is true, conversion quality should improve.",
            evidence_request=evidence_request
            or self._request(relation=EvidenceRelation.SUPPORTS),
            intervention_id=intervention_id,
            control_ref=control_ref,
        )

    def test_supported_factual_hypothesis_becomes_candidate_lesson(self) -> None:
        decision = analyze_learning_episode(self._episode())
        self.assertEqual(
            decision.disposition,
            LearningDisposition.CANDIDATE_LESSON,
        )
        self.assertEqual(decision.next_strategy, LearningStrategy.NONE)
        self.assertEqual(
            decision.lesson_candidate,
            "Creative A improves conversion quality.",
        )

    def test_observational_support_cannot_become_causal_lesson(self) -> None:
        decision = analyze_learning_episode(
            self._episode(claim_kind=LearningClaimKind.CAUSAL)
        )
        self.assertEqual(decision.disposition, LearningDisposition.TEST_CAUSALLY)
        self.assertEqual(decision.next_strategy, LearningStrategy.EXPERIMENT)
        self.assertIsNone(decision.lesson_candidate)

    def test_controlled_supported_experiment_can_create_causal_candidate(self) -> None:
        decision = analyze_learning_episode(
            self._episode(
                claim_kind=LearningClaimKind.CAUSAL,
                method=LearningMethod.EXPERIMENT,
                intervention_id="INT-A",
                control_ref="CTRL-B",
            )
        )
        self.assertEqual(
            decision.disposition,
            LearningDisposition.CANDIDATE_LESSON,
        )
        self.assertEqual(decision.next_strategy, LearningStrategy.NONE)

    def test_refuted_hypothesis_requires_revision(self) -> None:
        decision = analyze_learning_episode(
            self._episode(
                evidence_request=self._request(
                    relation=EvidenceRelation.CONTRADICTS
                )
            )
        )
        self.assertEqual(
            decision.disposition,
            LearningDisposition.REVISE_HYPOTHESIS,
        )
        self.assertEqual(decision.next_strategy, LearningStrategy.RESEARCH)

    def test_contested_hypothesis_requires_contradiction_resolution(self) -> None:
        decision = analyze_learning_episode(
            self._episode(
                evidence_request=self._request(
                    relation=EvidenceRelation.SUPPORTS,
                    second_relation=EvidenceRelation.CONTRADICTS,
                )
            )
        )
        self.assertEqual(
            decision.disposition,
            LearningDisposition.RESOLVE_CONTRADICTION,
        )
        self.assertEqual(
            decision.next_strategy,
            LearningStrategy.RESOLVE_CONTRADICTION,
        )

    def test_insufficient_hypothesis_requires_more_evidence(self) -> None:
        request = ClaimEvidenceRequest(
            assessment_id="EA-EMPTY",
            goal_id="G-LEARN",
            claim_id="H-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[],
        )
        decision = analyze_learning_episode(
            self._episode(evidence_request=request)
        )
        self.assertEqual(
            decision.disposition,
            LearningDisposition.GATHER_EVIDENCE,
        )
        self.assertEqual(decision.next_strategy, LearningStrategy.RESEARCH)

    def test_evidence_must_bind_to_exact_goal_and_hypothesis(self) -> None:
        foreign = ClaimEvidenceRequest(
            assessment_id="EA-FOREIGN",
            goal_id="G-OTHER",
            claim_id="H-OTHER",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[],
        )
        with self.assertRaises(ValidationError):
            self._episode(evidence_request=foreign)

    def test_non_experiment_cannot_claim_intervention_metadata(self) -> None:
        with self.assertRaises(ValidationError):
            self._episode(
                method=LearningMethod.OBSERVATION,
                intervention_id="INT-FORGED",
            )

    def test_post_construction_evidence_mutation_fails_closed(self) -> None:
        episode = self._episode()
        episode.evidence_request.evidence[0].source_id = ""
        with self.assertRaises(ValidationError):
            analyze_learning_episode(episode)


if __name__ == "__main__":
    unittest.main()
