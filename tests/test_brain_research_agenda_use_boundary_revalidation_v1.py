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


class BrainResearchAgendaUseBoundaryRevalidationV1Tests(unittest.TestCase):
    def _hypothesis(self, hypothesis_id: str) -> HypothesisCandidate:
        return HypothesisCandidate(
            hypothesis_id=hypothesis_id,
            goal_id="G-RA",
            owner_agent=BrainAgentId.STRATEGIST,
            statement=f"Hypothesis {hypothesis_id}",
            differentiating_predictions=[f"prediction-{hypothesis_id}"],
        )

    def _evidence(
        self, hypothesis_id: str, relation: EvidenceRelation
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=f"EA-{hypothesis_id}",
            goal_id="G-RA",
            claim_id=hypothesis_id,
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id=f"E-{hypothesis_id}",
                    goal_id="G-RA",
                    claim_id=hypothesis_id,
                    source_id=f"SRC-{hypothesis_id}",
                    relation=relation,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    def _portfolio(self, evidence_requests=None):
        return assess_hypothesis_portfolio(
            HypothesisPortfolioRequest(
                portfolio_id="HP-RA",
                goal_id="G-RA",
                owner_agent=BrainAgentId.CMO,
                hypotheses=[self._hypothesis("H-A"), self._hypothesis("H-B")],
                evidence_requests=list(evidence_requests or []),
            )
        )

    def _probe(self, probe_id: str = "P-1") -> ResearchProbe:
        return ResearchProbe(
            probe_id=probe_id,
            goal_id="G-RA",
            question="Discriminate H-A from H-B",
            cost=InquiryCost.LOW,
            predictions=[
                ProbePrediction(hypothesis_id="H-A", predicted_observation="A"),
                ProbePrediction(hypothesis_id="H-B", predicted_observation="B"),
            ],
        )

    def _request(self, *, portfolio=None, probes=None) -> ResearchAgendaRequest:
        return ResearchAgendaRequest(
            agenda_id="RA-1",
            goal_id="G-RA",
            portfolio=portfolio or self._portfolio(),
            probes=list(probes or [self._probe()]),
        )

    def test_post_validation_probe_goal_mutation_fails_closed(self):
        request = self._request()
        request.probes[0].goal_id = "G-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_post_validation_foreign_prediction_mutation_fails_closed(self):
        request = self._request()
        request.probes[0].predictions[1].hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_post_validation_refuted_hypothesis_resurrection_fails_closed(self):
        portfolio = self._portfolio(
            [
                self._evidence("H-A", EvidenceRelation.SUPPORTS),
                self._evidence("H-B", EvidenceRelation.CONTRADICTS),
            ]
        )
        request = self._request(portfolio=portfolio)
        request.portfolio.active_hypothesis_ids.append("H-B")
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_post_validation_unknown_active_hypothesis_injection_fails_closed(self):
        request = self._request()
        request.portfolio.active_hypothesis_ids.append("H-FOREIGN")
        request.probes[0].predictions.append(
            ProbePrediction(hypothesis_id="H-A", predicted_observation="temporary")
        )
        request.probes[0].predictions[-1].hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_post_validation_duplicate_probe_identity_fails_closed(self):
        request = self._request(probes=[self._probe("P-1"), self._probe("P-2")])
        request.probes[1].probe_id = "P-1"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_post_validation_duplicate_hypothesis_prediction_fails_closed(self):
        request = self._request()
        request.probes[0].predictions[1].hypothesis_id = "H-A"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_post_validation_invalid_leader_identity_fails_closed(self):
        request = self._request()
        request.portfolio.leading_hypothesis_id = "H-FOREIGN"
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_valid_discriminating_agenda_still_produces_recommendation(self):
        agenda = prioritize_research_agenda(self._request())
        self.assertEqual([item.probe_id for item in agenda.recommendations], ["P-1"])


if __name__ == "__main__":
    unittest.main()
