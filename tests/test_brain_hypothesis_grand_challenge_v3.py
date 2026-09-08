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
from brain.hypotheses import (
    HypothesisCandidate,
    HypothesisPortfolioRequest,
    InquiryCost,
    ProbePrediction,
    ResearchAgendaRequest,
    ResearchProbe,
    assess_hypothesis_portfolio,
    prioritize_research_agenda,
)
from schemas.base import ValidationError


class BrainHypothesisGrandChallengeV3(unittest.TestCase):
    """Tests-only future-ASI holdout for hypothesis/research authority.

    RED is intentional evidence. Do not weaken an assertion merely to make CI green.
    """

    def _hypothesis(self, hypothesis_id: str) -> HypothesisCandidate:
        return HypothesisCandidate(
            hypothesis_id=hypothesis_id,
            goal_id="G-FRONTIER",
            owner_agent=BrainAgentId.STRATEGIST,
            statement=f"Competing explanation {hypothesis_id}",
            differentiating_predictions=[f"prediction-{hypothesis_id}"],
        )

    def _evidence(
        self,
        hypothesis_id: str,
        relation: EvidenceRelation,
        suffix: str,
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=f"EA-{hypothesis_id}-{suffix}",
            goal_id="G-FRONTIER",
            claim_id=hypothesis_id,
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id=f"E-{hypothesis_id}-{suffix}",
                    goal_id="G-FRONTIER",
                    claim_id=hypothesis_id,
                    source_id=f"SRC-{hypothesis_id}-{suffix}",
                    relation=relation,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    def _portfolio(self, evidence_requests=None, reverse: bool = False):
        hypotheses = [self._hypothesis("H-A"), self._hypothesis("H-B")]
        evidence = list(evidence_requests or [])
        if reverse:
            hypotheses.reverse()
            evidence.reverse()
        return assess_hypothesis_portfolio(
            HypothesisPortfolioRequest(
                portfolio_id="HP-FRONTIER",
                goal_id="G-FRONTIER",
                owner_agent=BrainAgentId.CMO,
                hypotheses=hypotheses,
                evidence_requests=evidence,
            )
        )

    def _probe(self, probe_id: str = "P-DISC") -> ResearchProbe:
        return ResearchProbe(
            probe_id=probe_id,
            goal_id="G-FRONTIER",
            question="Which competing explanation predicts the observed outcome?",
            cost=InquiryCost.LOW,
            predictions=[
                ProbePrediction(hypothesis_id="H-A", predicted_observation="OUTCOME-A"),
                ProbePrediction(hypothesis_id="H-B", predicted_observation="OUTCOME-B"),
            ],
        )

    def _agenda_request(self, portfolio=None, probes=None) -> ResearchAgendaRequest:
        return ResearchAgendaRequest(
            agenda_id="RA-FRONTIER",
            goal_id="G-FRONTIER",
            portfolio=portfolio or self._portfolio(),
            probes=list(probes or [self._probe()]),
        )

    # Use-boundary / TOCTOU authority attacks.

    def test_mutated_probe_goal_cannot_cross_research_agenda_use_boundary(self):
        request = self._agenda_request()
        request.probes[0].goal_id = "G-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_mutated_prediction_cannot_reference_foreign_hypothesis(self):
        request = self._agenda_request()
        request.probes[0].predictions[1].hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_refuted_hypothesis_cannot_be_resurrected_by_active_set_mutation(self):
        portfolio = self._portfolio(
            [
                self._evidence("H-A", EvidenceRelation.SUPPORTS, "support"),
                self._evidence("H-B", EvidenceRelation.CONTRADICTS, "refute"),
            ]
        )
        self.assertEqual(portfolio.active_hypothesis_ids, ["H-A"])
        self.assertEqual(portfolio.refuted_hypothesis_ids, ["H-B"])
        request = self._agenda_request(portfolio=portfolio)
        request.portfolio.active_hypothesis_ids.append("H-B")
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_unknown_active_hypothesis_cannot_be_injected_after_validation(self):
        request = self._agenda_request()
        request.portfolio.active_hypothesis_ids.append("H-FOREIGN")
        request.probes[0].predictions.append(
            ProbePrediction(hypothesis_id="H-A", predicted_observation="temporary")
        )
        request.probes[0].predictions[-1].hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_duplicate_probe_identity_cannot_be_created_after_validation(self):
        request = self._agenda_request(probes=[self._probe("P-1"), self._probe("P-2")])
        request.probes[1].probe_id = "P-1"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_duplicate_hypothesis_prediction_cannot_manufacture_discrimination(self):
        request = self._agenda_request()
        request.probes[0].predictions[1].hypothesis_id = "H-A"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_invalid_leader_identity_mutation_fails_closed(self):
        request = self._agenda_request()
        request.portfolio.leading_hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    # High-level cognitive invariants / controls.

    def test_delayed_contradiction_can_demote_old_candidate_and_promote_rival(self):
        before = self._portfolio(
            [self._evidence("H-A", EvidenceRelation.SUPPORTS, "t1")]
        )
        self.assertIsNone(before.leading_hypothesis_id)

        after = self._portfolio(
            [
                self._evidence("H-A", EvidenceRelation.CONTRADICTS, "t2"),
                self._evidence("H-B", EvidenceRelation.SUPPORTS, "t2"),
            ]
        )
        self.assertEqual(after.leading_hypothesis_id, "H-B")
        self.assertEqual(after.refuted_hypothesis_ids, ["H-A"])

    def test_hypothesis_and_evidence_permutation_cannot_change_epistemic_conclusion(self):
        evidence = [
            self._evidence("H-A", EvidenceRelation.SUPPORTS, "perm"),
            self._evidence("H-B", EvidenceRelation.CONTRADICTS, "perm"),
        ]
        normal = self._portfolio(evidence, reverse=False)
        reversed_order = self._portfolio(evidence, reverse=True)
        self.assertEqual(normal.leading_hypothesis_id, reversed_order.leading_hypothesis_id)
        self.assertEqual(set(normal.active_hypothesis_ids), set(reversed_order.active_hypothesis_ids))
        self.assertEqual(set(normal.refuted_hypothesis_ids), set(reversed_order.refuted_hypothesis_ids))

    def test_non_discriminating_common_prediction_remains_unrecommended(self):
        probe = ResearchProbe(
            probe_id="P-ECHO",
            goal_id="G-FRONTIER",
            question="Common-mode observation",
            cost=InquiryCost.LOW,
            predictions=[
                ProbePrediction(hypothesis_id="H-A", predicted_observation="SAME"),
                ProbePrediction(hypothesis_id="H-B", predicted_observation="SAME"),
            ],
        )
        agenda = prioritize_research_agenda(self._agenda_request(probes=[probe]))
        self.assertEqual(agenda.recommendations, [])


if __name__ == "__main__":
    unittest.main()
