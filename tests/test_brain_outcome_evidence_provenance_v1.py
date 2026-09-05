"""Adversarial regression for outcome success evidence provenance."""

from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId, GoalSpec, GoalStatus
from brain.evidence import ClaimEvidenceAssessment, ClaimVerdict
from brain.outcomes import (
    OutcomeVerdict,
    TrajectoryDisposition,
    TrajectoryEvaluationRequest,
    evaluate_trajectory,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStep, PlanStepState


class BrainOutcomeEvidenceProvenanceV1Tests(unittest.TestCase):
    def test_fabricated_supported_assessment_cannot_self_certify_goal_success(self) -> None:
        criterion = "Observed qualified leads increased above baseline"
        goal = GoalSpec(
            goal_id="G-OUTCOME-PROV",
            objective="Improve acquisition quality",
            owner_agent=BrainAgentId.CMO,
            success_criteria=[criterion],
            status=GoalStatus.OPEN,
        )
        plan = PlanSnapshot(
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
        fabricated = ClaimEvidenceAssessment(
            assessment_id="EA-OUTCOME-FORGED",
            goal_id="G-OUTCOME-PROV",
            claim_id=criterion,
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
                evaluation_id="TE-OUTCOME-PROV",
                goal=goal,
                plan=plan,
                criterion_assessments=[fabricated],
            )
        )

        self.assertFalse(
            result.outcome_verdict == OutcomeVerdict.SATISFIED
            and result.disposition == TrajectoryDisposition.STOP,
            "Caller-constructed ClaimEvidenceAssessment objects must not self-certify goal success without the raw criterion evidence that canonically produced them.",
        )


if __name__ == "__main__":
    unittest.main()
