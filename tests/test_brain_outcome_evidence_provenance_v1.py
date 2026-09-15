"""Adversarial regression for outcome success evidence provenance."""

from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId, GoalSpec, GoalStatus
from brain.evidence import (
    ClaimEvidenceAssessment,
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
    assess_claim_evidence,
)
from brain.outcomes import (
    OutcomeVerdict,
    TrajectoryDisposition,
    TrajectoryEvaluationRequest,
    evaluate_trajectory,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStep, PlanStepState
from schemas.base import ValidationError


class BrainOutcomeEvidenceProvenanceV1Tests(unittest.TestCase):
    CRITERION = "Observed qualified leads increased above baseline"

    @classmethod
    def _goal(cls) -> GoalSpec:
        return GoalSpec(
            goal_id="G-OUTCOME-PROV",
            objective="Improve acquisition quality",
            owner_agent=BrainAgentId.CMO,
            success_criteria=[cls.CRITERION],
            status=GoalStatus.OPEN,
        )

    @staticmethod
    def _plan() -> PlanSnapshot:
        return PlanSnapshot(
            plan_id="PLAN-OUTCOME-PROV",
            goal_id="G-OUTCOME-PROV",
            revision=1,
            status=PlanStatus.ACTIVE,
            steps=[
                PlanStep(
                    step_id="S-OUTCOME-PROV",
                    goal_id="G-OUTCOME-PROV",
                    owner_agent=BrainAgentId.PERFORMANCE,
                    objective="Measure the target outcome",
                    completion_criteria=["Observation captured"],
                    state=PlanStepState.COMPLETED,
                )
            ],
        )

    @classmethod
    def _raw_request(
        cls, *, strength: EvidenceStrength = EvidenceStrength.STRONG
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-OUTCOME-PROV",
            goal_id="G-OUTCOME-PROV",
            claim_id=cls.CRITERION,
            agent_id=BrainAgentId.PERFORMANCE,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-OUTCOME-PROV",
                    goal_id="G-OUTCOME-PROV",
                    claim_id=cls.CRITERION,
                    source_id="SRC-OUTCOME-PROV",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=strength,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    def test_fabricated_supported_assessment_cannot_self_certify_goal_success(self) -> None:
        fabricated = ClaimEvidenceAssessment(
            assessment_id="EA-OUTCOME-FORGED",
            goal_id="G-OUTCOME-PROV",
            claim_id=self.CRITERION,
            agent_id=BrainAgentId.PERFORMANCE,
            verdict=ClaimVerdict.SUPPORTED,
            supporting_evidence_refs=["E-OUTCOME-FORGED"],
            contradicting_evidence_refs=[],
            ignored_evidence_refs=[],
            reasons=[
                "Caller fabricated a structurally valid SUPPORTED assessment without raw evidence."
            ],
        )

        result = evaluate_trajectory(
            TrajectoryEvaluationRequest(
                evaluation_id="TE-OUTCOME-FORGED",
                goal=self._goal(),
                plan=self._plan(),
                criterion_assessments=[fabricated],
            )
        )

        self.assertFalse(
            result.outcome_verdict == OutcomeVerdict.SATISFIED
            and result.disposition == TrajectoryDisposition.STOP,
            "Caller-constructed ClaimEvidenceAssessment objects must not self-certify goal success without the raw criterion evidence that canonically produced them.",
        )
        self.assertEqual(result.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)

    def test_fabricated_supported_audit_cannot_override_weak_raw_evidence(self) -> None:
        weak_raw = self._raw_request(strength=EvidenceStrength.WEAK)
        fabricated = ClaimEvidenceAssessment(
            assessment_id=weak_raw.assessment_id,
            goal_id=weak_raw.goal_id,
            claim_id=weak_raw.claim_id,
            agent_id=weak_raw.agent_id,
            verdict=ClaimVerdict.SUPPORTED,
            supporting_evidence_refs=["E-OUTCOME-PROV"],
            contradicting_evidence_refs=[],
            ignored_evidence_refs=[],
            reasons=["Caller tries to upgrade weak raw evidence to SUPPORTED."],
        )

        with self.assertRaises(ValidationError):
            evaluate_trajectory(
                TrajectoryEvaluationRequest(
                    evaluation_id="TE-OUTCOME-MISMATCH",
                    goal=self._goal(),
                    plan=self._plan(),
                    criterion_assessments=[fabricated],
                    criterion_evidence_requests=[weak_raw],
                )
            )

    def test_canonical_strong_raw_evidence_can_still_certify_goal_success(self) -> None:
        raw = self._raw_request()
        canonical = assess_claim_evidence(raw)
        result = evaluate_trajectory(
            TrajectoryEvaluationRequest(
                evaluation_id="TE-OUTCOME-CANONICAL",
                goal=self._goal(),
                plan=self._plan(),
                criterion_assessments=[canonical],
                criterion_evidence_requests=[raw],
            )
        )

        self.assertEqual(result.outcome_verdict, OutcomeVerdict.SATISFIED)
        self.assertEqual(result.disposition, TrajectoryDisposition.STOP)
        self.assertEqual(result.supported_criteria, [self.CRITERION])


if __name__ == "__main__":
    unittest.main()
