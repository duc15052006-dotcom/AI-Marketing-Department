from __future__ import annotations

import unittest

import brain
import brain.hypotheses as hypotheses


class BrainHypothesisPublicApiV1Tests(unittest.TestCase):
    def test_hypothesis_portfolio_capability_is_exported_from_brain_package(self) -> None:
        public_names = [
            "HypothesisAssessment",
            "HypothesisCandidate",
            "HypothesisPortfolioDecision",
            "HypothesisPortfolioRequest",
            "InformationValue",
            "InquiryCost",
            "ProbePrediction",
            "ResearchAgenda",
            "ResearchAgendaRequest",
            "ResearchProbe",
            "ResearchRecommendation",
            "assess_hypothesis_portfolio",
            "prioritize_research_agenda",
        ]

        for name in public_names:
            with self.subTest(name=name):
                self.assertIn(name, brain.__all__)
                self.assertTrue(hasattr(brain, name))
                self.assertIs(getattr(brain, name), getattr(hypotheses, name))


if __name__ == "__main__":
    unittest.main()
