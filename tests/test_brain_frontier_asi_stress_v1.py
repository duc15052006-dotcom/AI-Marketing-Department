from __future__ import annotations

import unittest

from brain.collaboration import (
    CollaborationAssessment,
    CollaborationDisposition,
    PeerReview,
    evaluate_collaboration,
)
from brain.contracts import (
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    GoalSpec,
    GoalStatus,
    StopReason,
    UnknownRecord,
)
from brain.decisions import DecisionEvaluationRequest, evaluate_decision
from brain.evidence import (
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
    TrajectoryEvaluationRequest,
    evaluate_trajectory,
)
from brain.planning import (
    PlanSnapshot,
    PlanStatus,
    PlanStep,
    PlanStepState,
    ready_step_ids,
)
from brain.reasoning import ReasoningAssessment, Reversibility, SignalLevel
from brain.stopping import StopEvaluationRequest, evaluate_stop
from schemas.base import ValidationError


class BrainFrontierASIStressV1Tests(unittest.TestCase):
    """Hidden-style adversarial probes for authority, provenance and state drift.

    These tests intentionally compose individually-valid Brain objects and then
    attack the gaps between construction-time validation and authority-bearing
    use boundaries. They are not capability demos; they are fail-closed holdouts.
    """

    @staticmethod
    def _signal(
        evidence_id: str,
        *,
        source_id: str,
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
        goal_id: str = "G-ASI",
        claim_id: str = "D-ASI",
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        strength: EvidenceStrength = EvidenceStrength.STRONG,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
    ) -> EvidenceSignal:
        del agent_id
        return EvidenceSignal(
            evidence_id=evidence_id,
            goal_id=goal_id,
            claim_id=claim_id,
            source_id=source_id,
            relation=relation,
            strength=strength,
            origin=origin,
        )

    @classmethod
    def _raw(
        cls,
        assessment_id: str,
        evidence_id: str,
        source_id: str,
        *,
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
        goal_id: str = "G-ASI",
        claim_id: str = "D-ASI",
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id=goal_id,
            claim_id=claim_id,
            agent_id=agent_id,
            evidence=[
                cls._signal(
                    evidence_id,
                    source_id=source_id,
                    goal_id=goal_id,
                    claim_id=claim_id,
                    relation=relation,
                    origin=origin,
                )
            ],
        )

    @classmethod
    def _proposal(cls, *, reviews=None, quorum: int = 1) -> CollaborationAssessment:
        raw = cls._raw("EA-P", "E-P", "SRC-P")
        return CollaborationAssessment(
            assessment_id="CA-ASI",
            goal_id="G-ASI",
            proposal_id="D-ASI",
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-P"],
            proposal_evidence_request=raw,
            reviews=list(reviews or []),
            minimum_supporting_reviewers=quorum,
        )

    @classmethod
    def _peer(
        cls,
        reviewer: BrainAgentId,
        *,
        review_id: str,
        evidence_id: str,
        source_id: str,
    ) -> PeerReview:
        raw = cls._raw(
            f"EA-{review_id}",
            evidence_id,
            source_id,
            agent_id=reviewer,
        )
        return PeerReview(
            review_id=review_id,
            goal_id="G-ASI",
            proposal_id="D-ASI",
            reviewer_agent=reviewer,
            verdict=ClaimVerdict.SUPPORTED,
            rationale="Independent reviewer reports canonical support.",
            evidence_refs=[evidence_id],
            evidence_request=raw,
        )

    @staticmethod
    def _reasoning() -> ReasoningAssessment:
        return ReasoningAssessment(
            assessment_id="RA-ASI",
            goal_id="G-ASI",
            agent_id=BrainAgentId.STRATEGIST,
            complexity=SignalLevel.HIGH,
            uncertainty=SignalLevel.HIGH,
            consequence=SignalLevel.CRITICAL,
            evidence_conflict=SignalLevel.LOW,
            reversibility=Reversibility.IRREVERSIBLE,
            causal_reasoning_required=True,
            contradiction_resolution_required=False,
        )

    @classmethod
    def _decision_request(cls, collaboration: CollaborationAssessment) -> DecisionEvaluationRequest:
        raw = cls._raw("EA-P", "E-P", "SRC-P")
        return DecisionEvaluationRequest(
            evaluation_id="DE-ASI",
            decision=DecisionRecord(
                decision_id="D-ASI",
                goal_id="G-ASI",
                agent_id=BrainAgentId.STRATEGIST,
                statement="Execute a consequential irreversible decision.",
                rationale="Only canonical evidence and independent review may authorize this.",
                disposition=DecisionDisposition.PROCEED,
                evidence_refs=["E-P"],
                confidence=1.0,
            ),
            reasoning_assessment=cls._reasoning(),
            evidence_request=raw,
            evidence_assessment=assess_claim_evidence(raw),
            collaboration_assessment=collaboration,
        )

    def test_quorum_post_validation_mutation_cannot_create_accept(self) -> None:
        assessment = self._proposal(reviews=[], quorum=1)
        assessment.minimum_supporting_reviewers = 0
        with self.assertRaises(ValidationError):
            evaluate_collaboration(assessment)

    def test_irreversible_decision_cannot_proceed_after_quorum_mutation(self) -> None:
        collaboration = self._proposal(reviews=[], quorum=1)
        request = self._decision_request(collaboration)
        request.collaboration_assessment.minimum_supporting_reviewers = 0
        result = evaluate_decision(request)
        self.assertNotEqual(
            result.disposition,
            DecisionDisposition.PROCEED,
            "A post-validation quorum mutation must never turn zero peer reviews into authority.",
        )

    def test_invalid_nested_evidence_source_mutation_fails_closed(self) -> None:
        raw = self._raw("EA-MUT", "E-MUT", "SRC-VALID")
        raw.evidence[0].source_id = ""
        with self.assertRaises(ValidationError):
            assess_claim_evidence(raw)

    def test_invalid_nested_evidence_cannot_satisfy_goal(self) -> None:
        criterion = "Verified frontier criterion"
        raw = self._raw(
            "EA-GOAL",
            "E-GOAL",
            "SRC-VALID",
            goal_id="G-OUTCOME",
            claim_id=criterion,
        )
        request = TrajectoryEvaluationRequest(
            evaluation_id="TE-ASI",
            goal=GoalSpec(
                goal_id="G-OUTCOME",
                objective="Establish the frontier criterion",
                owner_agent=BrainAgentId.CMO,
                success_criteria=[criterion],
                status=GoalStatus.OPEN,
            ),
            plan=PlanSnapshot(
                plan_id="P-OUTCOME",
                goal_id="G-OUTCOME",
                status=PlanStatus.ACTIVE,
                steps=[
                    PlanStep(
                        step_id="S-OUTCOME",
                        goal_id="G-OUTCOME",
                        owner_agent=BrainAgentId.INTELLIGENCE,
                        objective="Observe outcome",
                        state=PlanStepState.COMPLETED,
                    )
                ],
            ),
            criterion_evidence_requests=[raw],
        )
        request.criterion_evidence_requests[0].evidence[0].source_id = ""
        with self.assertRaises(ValidationError):
            evaluate_trajectory(request)

    def test_stop_blocker_post_validation_type_mutation_cannot_disappear(self) -> None:
        criterion = "Verified stop criterion"
        raw = self._raw(
            "EA-STOP",
            "E-STOP",
            "SRC-STOP",
            goal_id="G-STOP",
            claim_id=criterion,
        )
        trajectory_request = TrajectoryEvaluationRequest(
            evaluation_id="TE-STOP",
            goal=GoalSpec(
                goal_id="G-STOP",
                objective="Verify safe stopping",
                owner_agent=BrainAgentId.CMO,
                success_criteria=[criterion],
                status=GoalStatus.OPEN,
            ),
            plan=PlanSnapshot(
                plan_id="P-STOP",
                goal_id="G-STOP",
                status=PlanStatus.ACTIVE,
                steps=[
                    PlanStep(
                        step_id="S-STOP",
                        goal_id="G-STOP",
                        owner_agent=BrainAgentId.PERFORMANCE,
                        objective="Measure stop criterion",
                        state=PlanStepState.COMPLETED,
                    )
                ],
            ),
            criterion_evidence_requests=[raw],
        )
        stop_request = StopEvaluationRequest(
            evaluation_id="SE-ASI",
            goal_id="G-STOP",
            trajectory_request=trajectory_request,
            trajectory=evaluate_trajectory(trajectory_request),
            outstanding_unknowns=[
                UnknownRecord(
                    unknown_id="U-BLOCK",
                    goal_id="G-STOP",
                    question="Is a catastrophic side effect unresolved?",
                    consequence="Stopping despite this unknown may be unsafe.",
                    blocking=True,
                )
            ],
        )
        stop_request.outstanding_unknowns[0].blocking = 0
        with self.assertRaises(ValidationError):
            evaluate_stop(stop_request)

    def test_plan_snapshot_dependency_mutation_cannot_unlock_blocked_step(self) -> None:
        plan = PlanSnapshot(
            plan_id="P-DAG",
            goal_id="G-DAG",
            status=PlanStatus.ACTIVE,
            steps=[
                PlanStep(
                    step_id="S-ROOT",
                    goal_id="G-DAG",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    objective="Establish prerequisite",
                    state=PlanStepState.PENDING,
                ),
                PlanStep(
                    step_id="S-CHILD",
                    goal_id="G-DAG",
                    owner_agent=BrainAgentId.STRATEGIST,
                    objective="Act only after prerequisite",
                    depends_on=["S-ROOT"],
                    state=PlanStepState.PENDING,
                ),
            ],
        )
        self.assertNotIn("S-CHILD", ready_step_ids(plan))
        plan.steps[1].depends_on = []
        self.assertNotIn(
            "S-CHILD",
            ready_step_ids(plan),
            "A cognitive PlanSnapshot must not silently lose dependency authority after validation.",
        )

    def test_common_mode_single_source_cannot_masquerade_as_independent_review(self) -> None:
        proposal_raw = self._raw("EA-P-SHARED", "E-P-SHARED", "SRC-SHARED")
        peer = self._peer(
            BrainAgentId.INTELLIGENCE,
            review_id="R-SHARED",
            evidence_id="E-R-SHARED",
            source_id="SRC-SHARED",
        )
        assessment = CollaborationAssessment(
            assessment_id="CA-SHARED",
            goal_id="G-ASI",
            proposal_id="D-ASI",
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-P-SHARED"],
            proposal_evidence_request=proposal_raw,
            reviews=[peer],
            minimum_supporting_reviewers=1,
        )
        decision = evaluate_collaboration(assessment)
        self.assertNotEqual(
            decision.disposition,
            CollaborationDisposition.ACCEPT,
            "Reviewer identity independence must not be confused with evidence-source independence.",
        )

    def test_derived_evidence_and_self_review_still_fail_closed(self) -> None:
        derived = self._raw(
            "EA-DERIVED",
            "E-DERIVED",
            "SRC-DERIVED",
            origin=EvidenceOrigin.DERIVED,
        )
        self.assertEqual(
            assess_claim_evidence(derived).verdict,
            ClaimVerdict.INSUFFICIENT,
        )
        self_review = self._peer(
            BrainAgentId.STRATEGIST,
            review_id="R-SELF",
            evidence_id="E-SELF",
            source_id="SRC-SELF",
        )
        result = evaluate_collaboration(self._proposal(reviews=[self_review], quorum=1))
        self.assertNotEqual(result.disposition, CollaborationDisposition.ACCEPT)


if __name__ == "__main__":
    unittest.main()
