from __future__ import annotations

from pathlib import Path
import subprocess

BASE = "f08f85b6e7fb7b63c5b056ea0bf0070598c0267c"
subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)

path = Path("brain/hypotheses.py")
text = path.read_text(encoding="utf-8")
old = '''        self.assessments = normalized
        self.active_hypothesis_ids = _unique_text_list(
            self.active_hypothesis_ids, "active_hypothesis_ids"
        )
        self.refuted_hypothesis_ids = _unique_text_list(
            self.refuted_hypothesis_ids, "refuted_hypothesis_ids"
        )
        overlap = set(self.active_hypothesis_ids) & set(self.refuted_hypothesis_ids)
        if overlap:
            raise ValidationError("active and refuted hypotheses cannot overlap")
        if self.leading_hypothesis_id is not None:
            self.leading_hypothesis_id = _required_text(
                self.leading_hypothesis_id, "leading_hypothesis_id"
            )
            if self.leading_hypothesis_id not in self.active_hypothesis_ids:
                raise ValidationError("leading hypothesis must remain active")
'''
new = '''        self.assessments = normalized
        self.active_hypothesis_ids = _unique_text_list(
            self.active_hypothesis_ids, "active_hypothesis_ids"
        )
        self.refuted_hypothesis_ids = _unique_text_list(
            self.refuted_hypothesis_ids, "refuted_hypothesis_ids"
        )

        expected_active = {
            item.hypothesis_id
            for item in self.assessments
            if item.verdict != ClaimVerdict.REFUTED
        }
        expected_refuted = {
            item.hypothesis_id
            for item in self.assessments
            if item.verdict == ClaimVerdict.REFUTED
        }
        actual_active = set(self.active_hypothesis_ids)
        actual_refuted = set(self.refuted_hypothesis_ids)
        if actual_active != expected_active:
            raise ValidationError(
                "active_hypothesis_ids must exactly match non-refuted assessments"
            )
        if actual_refuted != expected_refuted:
            raise ValidationError(
                "refuted_hypothesis_ids must exactly match REFUTED assessments"
            )

        supported = [
            item.hypothesis_id
            for item in self.assessments
            if item.verdict == ClaimVerdict.SUPPORTED
        ]
        unresolved = [
            item.hypothesis_id
            for item in self.assessments
            if item.verdict in {ClaimVerdict.CONTESTED, ClaimVerdict.INSUFFICIENT}
        ]
        expected_leader: Optional[str] = None
        if len(supported) == 1 and not unresolved:
            candidate = supported[0]
            if all(
                item.hypothesis_id == candidate
                or item.verdict == ClaimVerdict.REFUTED
                for item in self.assessments
            ):
                expected_leader = candidate

        if self.leading_hypothesis_id is not None:
            self.leading_hypothesis_id = _required_text(
                self.leading_hypothesis_id, "leading_hypothesis_id"
            )
        if self.leading_hypothesis_id != expected_leader:
            raise ValidationError(
                "leading_hypothesis_id must match the uniquely supported hypothesis only when every competitor is refuted"
            )
'''
if text.count(old) != 1:
    raise SystemExit("semantic-state patch anchor was not unique")
path.write_text(text.replace(old, new), encoding="utf-8")

Path("tests/test_brain_hypothesis_state_consistency_v4.py").write_text('''from __future__ import annotations

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
            probes=[ResearchProbe(
                probe_id="P-V4",
                goal_id="G-V4",
                question="Discriminate H-A from H-B",
                cost=InquiryCost.LOW,
                predictions=[
                    ProbePrediction(hypothesis_id="H-A", predicted_observation="A"),
                    ProbePrediction(hypothesis_id="H-B", predicted_observation="B"),
                ],
            )],
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
        with self.assertRaises(ValidationError):
            self._agenda(portfolio)

    def test_missing_required_leader_is_rejected(self):
        with self.assertRaises(ValidationError):
            HypothesisPortfolioDecision(
                portfolio_id="HP-V4-MISSING-LEADER",
                goal_id="G-V4",
                owner_agent=BrainAgentId.CMO,
                assessments=[
                    self._assessment("H-A", ClaimVerdict.SUPPORTED),
                    self._assessment("H-B", ClaimVerdict.REFUTED),
                ],
                active_hypothesis_ids=["H-A"],
                refuted_hypothesis_ids=["H-B"],
                reasons=["leader omitted despite canonical unique support"],
            )

    def test_consistent_unresolved_portfolio_remains_usable(self):
        agenda = prioritize_research_agenda(self._agenda(self._portfolio()))
        self.assertEqual([item.probe_id for item in agenda.recommendations], ["P-V4"])


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

Path(".github/workflows/brain-hypothesis-state-consistency-apply-v1.yml").unlink()
Path(".ci/apply_hypothesis_state_consistency_v1.py").unlink()
