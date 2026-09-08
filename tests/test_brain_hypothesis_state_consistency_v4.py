from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId
from brain.hypotheses import (
    HypothesisAssessment,
    HypothesisPortfolioDecision,
    InquiryCost,
    ProbePrediction,
    ResearchAgendaRequest,
    ResearchProbe,
    prioritize_research_agenda,
)
from brain.evidence import ClaimVerdict
from schemas.base import ValidationError


class BrainHypothesisStateConsistencyV4Tests(unittest.TestCase):
    """Future-ASI holdout for semantic consistency of derived hypothesis state."""

    def _assessment(self, hypothesis_id: str, verdict: ClaimVerdict) -> HypothesisAssessment:
        return HypothesisAssessment(
            hypothesis_id=hypothesis_id,
            verdict=verdict,
            reasons=[f"canonical verdict for {hypothesis_id}"],
        )

    def _portfolio(self) -> HypothesisPortfolioDecision:
        return HypothesisPortfolioDecision(
            portfolio_id="HP-V4",
            goal_id="G-V4",
            owner_agent=BrainAgentId.CMO,
            assessments=[
                self._assessment("H-A", ClaimVerdict.INSUFFICIENT),
                self._assessment("H-B", ClaimVerdict.INSUFFICIENT),
            ],
            active_hypothesis_ids=["H-A", "H-B"],
            refuted_hypothesis_ids=[],
            reasons=["both hypotheses remain unresolved"],
        )

    def _agenda(self, portfolio: HypothesisPortfolioDecision) -> ResearchAgendaRequest:
        return ResearchAgendaRequest(
            agenda_id="RA-V4",
            goal_id="G-V4",
            portfolio=portfolio,
            probes=[
                ResearchProbe(
                    probe_id="P-V4",
                    goal_id="G-V4",
                    question="Discriminate H-A from H-B",
                    cost=InquiryCost.LOW,
                    predictions=[
                        ProbePrediction(hypothesis_id="H-A", predicted_observation="A"),
                        ProbePrediction(hypothesis_id="H-B", predicted_observation="B"),
                    ],
                )
            ],
        )

    def test_ghost_active_hypothesis_cannot_survive_canonical_revalidation(self):
        request = self._agenda(self._portfolio())
        request.portfolio.active_hypothesis_ids.append("H-GHOST")
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_ghost_refuted_hypothesis_cannot_survive_canonical_revalidation(self):
        request = self._agenda(self._portfolio())
        request.portfolio.refuted_hypothesis_ids.append("H-GHOST")
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_non_refuted_assessment_cannot_be_silently_removed_from_active_set(self):
        request = self._agenda(self._portfolio())
        request.portfolio.active_hypothesis_ids.remove("H-B")
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_insufficient_assessment_cannot_be_relabelled_as_refuted_by_index_lists(self):
        request = self._agenda(self._portfolio())
        request.portfolio.active_hypothesis_ids.remove("H-B")
        request.portfolio.refuted_hypothesis_ids.append("H-B")
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_forged_leader_cannot_exist_while_competitor_is_unresolved(self):
        portfolio = HypothesisPortfolioDecision(
            portfolio_id="HP-V4-LEADER",
            goal_id="G-V4",
            owner_agent=BrainAgentId.CMO,
            assessments=[
                self._assessment("H-A", ClaimVerdict.SUPPORTED),
                self._assessment("H-B", ClaimVerdict.INSUFFICIENT),
            ],
            active_hypothesis_ids=["H-A", "H-B"],
            refuted_hypothesis_ids=[],
            leading_hypothesis_id="H-A",
            reasons=["forged leader despite unresolved competitor"],
        )
        request = self._agenda(portfolio)
        with self.assertRaises(ValidationError):
            prioritize_research_agenda(request)

    def test_consistent_unresolved_portfolio_remains_usable(self):
        agenda = prioritize_research_agenda(self._agenda(self._portfolio()))
        self.assertEqual([item.probe_id for item in agenda.recommendations], ["P-V4"])


if __name__ == "__main__":
    unittest.main()
