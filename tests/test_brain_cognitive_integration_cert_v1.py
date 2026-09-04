"""Cross-module certification for the provider-neutral Brain semantic core."""

from __future__ import annotations

import unittest

from brain.agent_dna import get_agent_profile, resolve_permanent_agent
from brain.collaboration import CollaborationAssessment, PeerReview
from brain.contracts import (
    BrainAgentId,
    DecisionDisposition,
    DecisionRecord,
    EvidenceNeed,
    GoalSpec,
    StopReason,
    UnknownRecord,
)
from brain.decisions import DecisionEvaluationRequest, evaluate_decision
from brain.evidence import ClaimEvidenceAssessment, ClaimVerdict
from brain.memory_policy import (
    MemoryAuthority,
    MemoryCandidate,
    MemoryDisposition,
    MemoryKind,
    MemoryScopeLevel,
    evaluate_memory_candidate,
)
from brain.outcomes import (
    OutcomeVerdict,
    TrajectoryDisposition,
    TrajectoryEvaluationRequest,
    evaluate_trajectory,
)
from brain.planning import PlanSnapshot, PlanStatus, PlanStep, PlanStepState
from brain.reasoning import (
    ReasoningAssessment,
    ReasoningDepth,
    Reversibility,
    SignalLevel,
    select_reasoning_depth,
)
from brain.stopping import StopEvaluationRequest, evaluate_stop
from schemas.base import ValidationError


GOAL_ID = "G-GROWTH-1"
SUCCESS_CRITERION = "CAC <= 20 after at least 30 verified conversions"


class BrainCognitiveIntegrationCertificationV1(unittest.TestCase):
    @staticmethod
    def _goal() -> GoalSpec:
        return GoalSpec(
            goal_id=GOAL_ID,
            objective="Validate a profitable acquisition path before scaling spend",
            owner_agent=BrainAgentId.CMO,
            success_criteria=[SUCCESS_CRITERION],
            constraints=["Use evidence-backed claims", "Do not scale unverified economics"],
        )

    @staticmethod
    def _completed_marketing_plan() -> PlanSnapshot:
        steps = [
            PlanStep(
                step_id="S-INTEL",
                goal_id=GOAL_ID,
                owner_agent=BrainAgentId.INTELLIGENCE,
                objective="Establish market and customer evidence",
                completion_criteria=["Verified evidence bundle exists"],
                state=PlanStepState.COMPLETED,
            ),
            PlanStep(
                step_id="S-STRATEGY",
                goal_id=GOAL_ID,
                owner_agent=BrainAgentId.STRATEGIST,
                objective="Choose a bounded acquisition hypothesis",
                depends_on=["S-INTEL"],
                completion_criteria=["Falsifiable strategy decision exists"],
                state=PlanStepState.COMPLETED,
            ),
            PlanStep(
                step_id="S-CREATIVE",
                goal_id=GOAL_ID,
                owner_agent=BrainAgentId.CREATIVE,
                objective="Translate strategy into truthful test creative",
                depends_on=["S-STRATEGY"],
                completion_criteria=["Creative test specification exists"],
                state=PlanStepState.COMPLETED,
            ),
            PlanStep(
                step_id="S-PERF",
                goal_id=GOAL_ID,
                owner_agent=BrainAgentId.PERFORMANCE,
                objective="Measure the bounded experiment against the KPI",
                depends_on=["S-CREATIVE"],
                completion_criteria=["Measurement result is evaluated"],
                state=PlanStepState.COMPLETED,
            ),
        ]
        return PlanSnapshot(
            plan_id="P-1",
            goal_id=GOAL_ID,
            revision=1,
            steps=steps,
            status=PlanStatus.SATISFIED,
        )

    @staticmethod
    def _strategy_decision() -> DecisionRecord:
        return DecisionRecord(
            decision_id="D-PILOT",
            goal_id=GOAL_ID,
            agent_id=BrainAgentId.STRATEGIST,
            statement="Proceed with a bounded acquisition experiment",
            rationale="Verified market evidence supports testing the hypothesis.",
            disposition=DecisionDisposition.PROCEED,
            evidence_refs=["E-MARKET-1"],
            confidence=1.0,
        )

    @staticmethod
    def _decision_evidence(verdict: ClaimVerdict = ClaimVerdict.SUPPORTED) -> ClaimEvidenceAssessment:
        support = ["E-MARKET-1"] if verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTESTED} else []
        contradict = ["E-MARKET-X"] if verdict in {ClaimVerdict.REFUTED, ClaimVerdict.CONTESTED} else []
        return ClaimEvidenceAssessment(
            assessment_id=f"EA-{verdict.value}",
            goal_id=GOAL_ID,
            claim_id="D-PILOT",
            agent_id=BrainAgentId.INTELLIGENCE,
            verdict=verdict,
            supporting_evidence_refs=support,
            contradicting_evidence_refs=contradict,
            reasons=["Exact market evidence was assessed against the strategy decision."],
        )

    @staticmethod
    def _reasoning(**updates) -> ReasoningAssessment:
        values = {
            "assessment_id": "RA-STRATEGY",
            "goal_id": GOAL_ID,
            "agent_id": BrainAgentId.STRATEGIST,
            "complexity": SignalLevel.LOW,
            "uncertainty": SignalLevel.LOW,
            "consequence": SignalLevel.LOW,
            "evidence_conflict": SignalLevel.LOW,
            "reversibility": Reversibility.REVERSIBLE,
            "causal_reasoning_required": False,
            "contradiction_resolution_required": False,
        }
        values.update(updates)
        return ReasoningAssessment(**values)

    @staticmethod
    def _criterion_assessment(verdict: ClaimVerdict) -> ClaimEvidenceAssessment:
        support = ["E-PERF-RESULT"] if verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTESTED} else []
        contradict = ["E-PERF-CONTRA"] if verdict in {ClaimVerdict.REFUTED, ClaimVerdict.CONTESTED} else []
        return ClaimEvidenceAssessment(
            assessment_id=f"EA-KPI-{verdict.value}",
            goal_id=GOAL_ID,
            claim_id=SUCCESS_CRITERION,
            agent_id=BrainAgentId.PERFORMANCE,
            verdict=verdict,
            supporting_evidence_refs=support,
            contradicting_evidence_refs=contradict,
            reasons=["Performance evidence was bound to the exact declared success criterion."],
        )

    def test_evidence_backed_marketing_loop_can_reach_goal_satisfied_stop(self) -> None:
        decision = evaluate_decision(
            DecisionEvaluationRequest(
                evaluation_id="DE-1",
                decision=self._strategy_decision(),
                reasoning_assessment=self._reasoning(),
                evidence_assessment=self._decision_evidence(),
            )
        )
        self.assertEqual(decision.disposition, DecisionDisposition.PROCEED)

        trajectory = evaluate_trajectory(
            TrajectoryEvaluationRequest(
                evaluation_id="TE-1",
                goal=self._goal(),
                plan=self._completed_marketing_plan(),
                criterion_assessments=[self._criterion_assessment(ClaimVerdict.SUPPORTED)],
            )
        )
        self.assertEqual(trajectory.outcome_verdict, OutcomeVerdict.SATISFIED)
        self.assertEqual(trajectory.disposition, TrajectoryDisposition.STOP)

        stop = evaluate_stop(
            StopEvaluationRequest(
                evaluation_id="SE-1",
                goal_id=GOAL_ID,
                trajectory=trajectory,
            )
        )
        self.assertTrue(stop.should_stop)
        self.assertEqual(stop.reason, StopReason.GOAL_SATISFIED)

    def test_completed_plan_and_confident_proceed_do_not_fabricate_goal_success(self) -> None:
        decision = evaluate_decision(
            DecisionEvaluationRequest(
                evaluation_id="DE-2",
                decision=self._strategy_decision(),
                reasoning_assessment=self._reasoning(),
                evidence_assessment=self._decision_evidence(),
            )
        )
        self.assertEqual(decision.disposition, DecisionDisposition.PROCEED)

        trajectory = evaluate_trajectory(
            TrajectoryEvaluationRequest(
                evaluation_id="TE-2",
                goal=self._goal(),
                plan=self._completed_marketing_plan(),
                criterion_assessments=[self._criterion_assessment(ClaimVerdict.INSUFFICIENT)],
            )
        )
        self.assertEqual(trajectory.outcome_verdict, OutcomeVerdict.INCONCLUSIVE)
        self.assertEqual(trajectory.disposition, TrajectoryDisposition.REVISE)

        stop = evaluate_stop(
            StopEvaluationRequest(
                evaluation_id="SE-2",
                goal_id=GOAL_ID,
                trajectory=trajectory,
            )
        )
        self.assertTrue(stop.should_stop)
        self.assertEqual(stop.reason, StopReason.INSUFFICIENT_EVIDENCE)

    def test_high_risk_scale_decision_requires_max_reasoning_and_independent_review(self) -> None:
        reasoning = self._reasoning(
            consequence=SignalLevel.HIGH,
            reversibility=Reversibility.IRREVERSIBLE,
        )
        depth = select_reasoning_depth(reasoning)
        self.assertEqual(depth.depth, ReasoningDepth.MAXIMUM)

        without_peer = evaluate_decision(
            DecisionEvaluationRequest(
                evaluation_id="DE-HIGH-NO-PEER",
                decision=self._strategy_decision(),
                reasoning_assessment=reasoning,
                evidence_assessment=self._decision_evidence(),
            )
        )
        self.assertEqual(without_peer.disposition, DecisionDisposition.ESCALATE)
        self.assertTrue(without_peer.peer_review_required)

        peer = PeerReview(
            review_id="PR-INTEL",
            goal_id=GOAL_ID,
            proposal_id="D-PILOT",
            reviewer_agent=BrainAgentId.INTELLIGENCE,
            verdict=ClaimVerdict.SUPPORTED,
            rationale="Independent evidence review supports only the bounded test decision.",
            evidence_refs=["E-PEER-1"],
        )
        collaboration = CollaborationAssessment(
            assessment_id="CA-HIGH",
            goal_id=GOAL_ID,
            proposal_id="D-PILOT",
            author_agent=BrainAgentId.STRATEGIST,
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_evidence_refs=["E-MARKET-1"],
            reviews=[peer],
            minimum_supporting_reviewers=1,
        )
        with_peer = evaluate_decision(
            DecisionEvaluationRequest(
                evaluation_id="DE-HIGH-PEER",
                decision=self._strategy_decision(),
                reasoning_assessment=reasoning,
                evidence_assessment=self._decision_evidence(),
                collaboration_assessment=collaboration,
            )
        )
        self.assertEqual(with_peer.disposition, DecisionDisposition.PROCEED)

    def test_contested_evidence_survives_to_decision_escalation(self) -> None:
        decision = evaluate_decision(
            DecisionEvaluationRequest(
                evaluation_id="DE-CONTESTED",
                decision=self._strategy_decision(),
                reasoning_assessment=self._reasoning(evidence_conflict=SignalLevel.HIGH),
                evidence_assessment=self._decision_evidence(ClaimVerdict.CONTESTED),
            )
        )
        self.assertEqual(decision.disposition, DecisionDisposition.ESCALATE)

    def test_blocking_research_gap_overrides_nominally_satisfied_goal(self) -> None:
        trajectory = evaluate_trajectory(
            TrajectoryEvaluationRequest(
                evaluation_id="TE-BLOCKED",
                goal=self._goal(),
                plan=self._completed_marketing_plan(),
                criterion_assessments=[self._criterion_assessment(ClaimVerdict.SUPPORTED)],
            )
        )
        blocking_need = EvidenceNeed(
            need_id="EN-LEGAL",
            goal_id=GOAL_ID,
            question="Is the proposed claim compliant in the target market?",
            why_needed="A compliance uncertainty can invalidate the creative and offer.",
            blocking=True,
            evidence_refs=["E-PARTIAL"],
        )
        stop = evaluate_stop(
            StopEvaluationRequest(
                evaluation_id="SE-BLOCKED",
                goal_id=GOAL_ID,
                trajectory=trajectory,
                outstanding_evidence_needs=[blocking_need],
            )
        )
        self.assertTrue(stop.should_stop)
        self.assertEqual(stop.reason, StopReason.BLOCKED)

    def test_blocking_unknown_cannot_be_hidden_by_success_evidence(self) -> None:
        trajectory = evaluate_trajectory(
            TrajectoryEvaluationRequest(
                evaluation_id="TE-UNKNOWN",
                goal=self._goal(),
                plan=self._completed_marketing_plan(),
                criterion_assessments=[self._criterion_assessment(ClaimVerdict.SUPPORTED)],
            )
        )
        unknown = UnknownRecord(
            unknown_id="U-1",
            goal_id=GOAL_ID,
            question="Was conversion tracking complete for the whole measurement window?",
            consequence="If not, the success criterion may be a false positive.",
            blocking=True,
        )
        stop = evaluate_stop(
            StopEvaluationRequest(
                evaluation_id="SE-UNKNOWN",
                goal_id=GOAL_ID,
                trajectory=trajectory,
                outstanding_unknowns=[unknown],
            )
        )
        self.assertEqual(stop.reason, StopReason.BLOCKED)

    def test_learning_is_scoped_and_single_success_does_not_become_institutional_truth(self) -> None:
        base = {
            "goal_id": GOAL_ID,
            "claim_id": "The bounded acquisition hypothesis repeatedly met its KPI",
            "agent_id": BrainAgentId.PERFORMANCE,
            "memory_kind": MemoryKind.SUCCESS_FAILURE,
            "authority": MemoryAuthority.OBSERVED,
            "origin_scope": MemoryScopeLevel.CAMPAIGN,
            "requested_scope": MemoryScopeLevel.CAMPAIGN,
            "evidence_verdict": ClaimVerdict.SUPPORTED,
            "evidence_refs": ["E-PERF-RESULT"],
        }
        one_run = evaluate_memory_candidate(
            MemoryCandidate(candidate_id="MC-1", **base, independent_run_count=1)
        )
        repeated = evaluate_memory_candidate(
            MemoryCandidate(candidate_id="MC-3", **base, independent_run_count=3)
        )
        self.assertEqual(one_run.disposition, MemoryDisposition.CANDIDATE)
        self.assertEqual(repeated.disposition, MemoryDisposition.PROMOTED)
        self.assertEqual(repeated.effective_scope, MemoryScopeLevel.CAMPAIGN)

    def test_five_agent_authority_survives_cross_module_flow_without_live_execution(self) -> None:
        cmo = get_agent_profile(BrainAgentId.CMO)
        intelligence = get_agent_profile(BrainAgentId.INTELLIGENCE)
        strategist = get_agent_profile(BrainAgentId.STRATEGIST)
        creative = get_agent_profile(BrainAgentId.CREATIVE)
        performance = get_agent_profile(BrainAgentId.PERFORMANCE)

        self.assertTrue(cmo.commercial_signoff_authority)
        self.assertFalse(intelligence.commercial_signoff_authority)
        self.assertFalse(strategist.commercial_signoff_authority)
        self.assertFalse(creative.commercial_signoff_authority)
        self.assertFalse(performance.commercial_signoff_authority)
        self.assertTrue(
            all(
                not profile.live_execution_authority
                for profile in (cmo, intelligence, strategist, creative, performance)
            )
        )

        with self.assertRaises(ValidationError):
            resolve_permanent_agent("agent_6")


if __name__ == "__main__":
    unittest.main()
