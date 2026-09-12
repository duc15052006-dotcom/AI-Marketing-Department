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
from schemas.base import ValidationError


class BrainLearningUseBoundaryRevalidationV1Tests(unittest.TestCase):
    @staticmethod
    def _evidence() -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-LUB",
            goal_id="G-LUB",
            claim_id="H-LUB",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-LUB",
                    goal_id="G-LUB",
                    claim_id="H-LUB",
                    source_id="SRC-LUB",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    @classmethod
    def _observational_causal(cls) -> LearningEpisode:
        return LearningEpisode(
            episode_id="LE-LUB",
            goal_id="G-LUB",
            agent_id=BrainAgentId.CONTENT,
            hypothesis_id="H-LUB",
            claim_kind=LearningClaimKind.CAUSAL,
            method=LearningMethod.OBSERVATION,
            hypothesis="Creative A causes conversion quality to improve.",
            prediction="Intervening on A should improve conversion quality.",
            evidence_request=cls._evidence(),
        )

    def test_claim_kind_post_validation_mutation_fails_closed(self) -> None:
        episode = self._observational_causal()
        episode.claim_kind = LearningClaimKind.FACTUAL
        with self.assertRaises(ValidationError):
            analyze_learning_episode(episode)

    def test_forged_experiment_metadata_post_validation_fails_closed(self) -> None:
        episode = self._observational_causal()
        episode.method = LearningMethod.EXPERIMENT
        episode.intervention_id = "INT-FORGED"
        episode.control_ref = "CTRL-FORGED"
        with self.assertRaises(ValidationError):
            analyze_learning_episode(episode)

    def test_hypothesis_binding_post_validation_mutation_fails_closed(self) -> None:
        episode = LearningEpisode(
            episode_id="LE-BIND",
            goal_id="G-LUB",
            agent_id=BrainAgentId.CONTENT,
            hypothesis_id="H-LUB",
            claim_kind=LearningClaimKind.FACTUAL,
            method=LearningMethod.OBSERVATION,
            hypothesis="Creative A improves conversion quality.",
            prediction="Conversion quality should improve.",
            evidence_request=self._evidence(),
        )
        episode.hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            analyze_learning_episode(episode)

    def test_valid_controlled_causal_experiment_still_creates_candidate(self) -> None:
        episode = LearningEpisode(
            episode_id="LE-VALID",
            goal_id="G-LUB",
            agent_id=BrainAgentId.CONTENT,
            hypothesis_id="H-LUB",
            claim_kind=LearningClaimKind.CAUSAL,
            method=LearningMethod.EXPERIMENT,
            hypothesis="Creative A causes conversion quality to improve.",
            prediction="Intervening on A should improve conversion quality.",
            evidence_request=self._evidence(),
            intervention_id="INT-REAL",
            control_ref="CTRL-REAL",
        )
        result = analyze_learning_episode(episode)
        self.assertEqual(result.disposition, LearningDisposition.CANDIDATE_LESSON)


if __name__ == "__main__":
    unittest.main()
