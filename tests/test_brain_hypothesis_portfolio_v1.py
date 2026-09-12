from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.hypotheses import (
    HypothesisCandidate,
    HypothesisPortfolioRequest,
    InformationValue,
    InquiryCost,
    ProbePrediction,
    ResearchAgendaRequest,
    ResearchProbe,
    assess_hypothesis_portfolio,
    prioritize_research_agenda,
)
from schemas.base import ValidationError


class BrainHypothesisPortfolioV1Tests(unittest.TestCase):
    def _hypothesis(self, hypothesis_id: str) -> HypothesisCandidate:
        return HypothesisCandidate(
            hypothesis_id=hypothesis_id,
            goal_id="G-HYP",
            owner_agent=BrainAgentId.CONTENT,
            statement=f"Hypothesis {hypothesis_id}",
            differentiating_predictions=[f"Prediction {hypothesis_id}"],
        )

    def _evidence(
        self,
        hypothesis_id: str,
        relation: EvidenceRelation,
        *,
        source_id: str,
        evidence_id: str,
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=f"EA-{hypothesis_id}",
            goal_id="G-HYP",
            claim_id=hypothesis_id,
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id=evidence_id,
                    goal_id="G-HYP",
                    claim_id=hypothesis_id,
                    source_id=source_id,
                    relation=relation,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    def _portfolio(self, evidence_requests=None):
        return assess_hypothesis_portfolio(
            HypothesisPortfolioRequest(
                portfolio_id="HP-1",
                goal_id="G-HYP",
                owner_agent=BrainAgentId.CMO,
                hypotheses=[self._hypothesis("H-A"), self._hypothesis("H-B")],
                evidence_requests=list(evidence_requests or []),
            )
        )

    def test_supported_hypothesis_leads_only_when_competitor_is_refuted(self) -> None:
        decision = self._portfolio(
            [
                self._evidence(
                    "H-A",
                    EvidenceRelation.SUPPORTS,
                    source_id="SRC-A",
                    evidence_id="E-A",
                ),
                self._evidence(
                    "H-B",
                    EvidenceRelation.CONTRADICTS,
                    source_id="SRC-B",
                    evidence_id="E-B",
                ),
            ]
        )
        self.assertEqual(decision.leading_hypothesis_id, "H-A")
        self.assertEqual(decision.active_hypothesis_ids, ["H-A"])
        self.assertEqual(decision.refuted_hypothesis_ids, ["H-B"])

    def test_supported_plus_insufficient_does_not_collapse_portfolio(self) -> None:
        decision = self._portfolio(
            [
                self._evidence(
                    "H-A",
                    EvidenceRelation.SUPPORTS,
                    source_id="SRC-A",
                    evidence_id="E-A",
                )
            ]
        )
        verdicts = {item.hypothesis_id: item.verdict for item in decision.assessments}
        self.assertEqual(verdicts["H-A"], ClaimVerdict.SUPPORTED)
        self.assertEqual(verdicts["H-B"], ClaimVerdict.INSUFFICIENT)
        self.assertIsNone(decision.leading_hypothesis_id)
        self.assertEqual(set(decision.active_hypothesis_ids), {"H-A", "H-B"})

    def test_no_evidence_keeps_all_hypotheses_insufficient_and_active(self) -> None:
        decision = self._portfolio()
        self.assertTrue(
            all(item.verdict == ClaimVerdict.INSUFFICIENT for item in decision.assessments)
        )
        self.assertEqual(set(decision.active_hypothesis_ids), {"H-A", "H-B"})
        self.assertIsNone(decision.leading_hypothesis_id)

    def test_contested_hypothesis_remains_active(self) -> None:
        contested = ClaimEvidenceRequest(
            assessment_id="EA-H-A",
            goal_id="G-HYP",
            claim_id="H-A",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-A-S",
                    goal_id="G-HYP",
                    claim_id="H-A",
                    source_id="SRC-S",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                ),
                EvidenceSignal(
                    evidence_id="E-A-C",
                    goal_id="G-HYP",
                    claim_id="H-A",
                    source_id="SRC-C",
                    relation=EvidenceRelation.CONTRADICTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                ),
            ],
        )
        decision = self._portfolio([contested])
        verdicts = {item.hypothesis_id: item.verdict for item in decision.assessments}
        self.assertEqual(verdicts["H-A"], ClaimVerdict.CONTESTED)
        self.assertIn("H-A", decision.active_hypothesis_ids)
        self.assertIsNone(decision.leading_hypothesis_id)

    def test_unknown_evidence_claim_is_rejected(self) -> None:
        foreign = ClaimEvidenceRequest(
            assessment_id="EA-FOREIGN",
            goal_id="G-HYP",
            claim_id="H-UNKNOWN",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[],
        )
        with self.assertRaises(ValidationError):
            HypothesisPortfolioRequest(
                portfolio_id="HP-X",
                goal_id="G-HYP",
                owner_agent=BrainAgentId.CMO,
                hypotheses=[self._hypothesis("H-A")],
                evidence_requests=[foreign],
            )

    def test_duplicate_hypothesis_identity_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            HypothesisPortfolioRequest(
                portfolio_id="HP-DUP",
                goal_id="G-HYP",
                owner_agent=BrainAgentId.CMO,
                hypotheses=[self._hypothesis("H-A"), self._hypothesis("H-A")],
            )

    def test_post_construction_evidence_mutation_fails_closed(self) -> None:
        request = HypothesisPortfolioRequest(
            portfolio_id="HP-MUT",
            goal_id="G-HYP",
            owner_agent=BrainAgentId.CMO,
            hypotheses=[self._hypothesis("H-A")],
            evidence_requests=[
                self._evidence(
                    "H-A",
                    EvidenceRelation.SUPPORTS,
                    source_id="SRC-VALID",
                    evidence_id="E-MUT",
                )
            ],
        )
        request.evidence_requests[0].evidence[0].source_id = ""
        with self.assertRaises(ValidationError):
            assess_hypothesis_portfolio(request)

    def test_full_three_hypothesis_discrimination_has_highest_information_value(self) -> None:
        portfolio = assess_hypothesis_portfolio(
            HypothesisPortfolioRequest(
                portfolio_id="HP-3",
                goal_id="G-HYP",
                owner_agent=BrainAgentId.CMO,
                hypotheses=[
                    self._hypothesis("H-A"),
                    self._hypothesis("H-B"),
                    self._hypothesis("H-C"),
                ],
            )
        )
        agenda = prioritize_research_agenda(
            ResearchAgendaRequest(
                agenda_id="RA-3",
                goal_id="G-HYP",
                portfolio=portfolio,
                probes=[
                    ResearchProbe(
                        probe_id="P-PAIR",
                        goal_id="G-HYP",
                        question="Distinguish two explanations",
                        cost=InquiryCost.LOW,
                        predictions=[
                            ProbePrediction(hypothesis_id="H-A", predicted_observation="A"),
                            ProbePrediction(hypothesis_id="H-B", predicted_observation="B"),
                        ],
                    ),
                    ResearchProbe(
                        probe_id="P-ALL",
                        goal_id="G-HYP",
                        question="Distinguish all explanations",
                        cost=InquiryCost.HIGH,
                        predictions=[
                            ProbePrediction(hypothesis_id="H-A", predicted_observation="A"),
                            ProbePrediction(hypothesis_id="H-B", predicted_observation="B"),
                            ProbePrediction(hypothesis_id="H-C", predicted_observation="C"),
                        ],
                    ),
                ],
            )
        )
        self.assertEqual(agenda.recommendations[0].probe_id, "P-ALL")
        self.assertEqual(
            agenda.recommendations[0].information_value,
            InformationValue.HIGH,
        )

    def test_non_discriminating_probe_is_not_recommended(self) -> None:
        portfolio = self._portfolio()
        agenda = prioritize_research_agenda(
            ResearchAgendaRequest(
                agenda_id="RA-SAME",
                goal_id="G-HYP",
                portfolio=portfolio,
                probes=[
                    ResearchProbe(
                        probe_id="P-SAME",
                        goal_id="G-HYP",
                        question="Question with same prediction",
                        cost=InquiryCost.LOW,
                        predictions=[
                            ProbePrediction(hypothesis_id="H-A", predicted_observation="SAME"),
                            ProbePrediction(hypothesis_id="H-B", predicted_observation="SAME"),
                        ],
                    )
                ],
            )
        )
        self.assertEqual(agenda.recommendations, [])

    def test_lower_cost_breaks_equal_information_tie(self) -> None:
        portfolio = self._portfolio()
        probes = []
        for probe_id, cost in [("P-HIGH", InquiryCost.HIGH), ("P-LOW", InquiryCost.LOW)]:
            probes.append(
                ResearchProbe(
                    probe_id=probe_id,
                    goal_id="G-HYP",
                    question=f"{probe_id} question",
                    cost=cost,
                    predictions=[
                        ProbePrediction(hypothesis_id="H-A", predicted_observation="A"),
                        ProbePrediction(hypothesis_id="H-B", predicted_observation="B"),
                    ],
                )
            )
        agenda = prioritize_research_agenda(
            ResearchAgendaRequest(
                agenda_id="RA-COST",
                goal_id="G-HYP",
                portfolio=portfolio,
                probes=probes,
            )
        )
        self.assertEqual(
            [item.probe_id for item in agenda.recommendations],
            ["P-LOW", "P-HIGH"],
        )

    def test_probe_referencing_unknown_hypothesis_is_rejected(self) -> None:
        portfolio = self._portfolio()
        with self.assertRaises(ValidationError):
            ResearchAgendaRequest(
                agenda_id="RA-UNKNOWN",
                goal_id="G-HYP",
                portfolio=portfolio,
                probes=[
                    ResearchProbe(
                        probe_id="P-X",
                        goal_id="G-HYP",
                        question="Foreign hypothesis probe",
                        cost=InquiryCost.LOW,
                        predictions=[
                            ProbePrediction(
                                hypothesis_id="H-FOREIGN",
                                predicted_observation="X",
                            )
                        ],
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
