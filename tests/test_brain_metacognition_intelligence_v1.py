from __future__ import annotations

import unittest

from brain.contracts import BrainAgentId, EvidenceNeed, UnknownRecord
from brain.evidence import ClaimEvidenceAssessment, ClaimVerdict
from brain.metacognition import (
    KnowledgeGap,
    KnowledgeGapKind,
    KnowledgeState,
    LearningStrategy,
    MetacognitionRequest,
    assess_metacognition,
    derive_knowledge_gaps,
)
from schemas.base import ValidationError


class BrainMetacognitionIntelligenceV1Tests(unittest.TestCase):
    def _assessment(
        self,
        assessment_id: str,
        claim_id: str,
        verdict: ClaimVerdict,
    ) -> ClaimEvidenceAssessment:
        return ClaimEvidenceAssessment(
            assessment_id=assessment_id,
            goal_id="G-META",
            claim_id=claim_id,
            agent_id=BrainAgentId.INTELLIGENCE,
            verdict=verdict,
            supporting_evidence_refs=["E-S"] if verdict == ClaimVerdict.SUPPORTED else [],
            contradicting_evidence_refs=["E-C"] if verdict == ClaimVerdict.REFUTED else [],
            reasons=["canonical evidence assessment"],
        )

    def test_derives_explicit_unknowns_and_evidence_needs_into_gaps(self) -> None:
        gaps = derive_knowledge_gaps(
            goal_id="G-META",
            owner_agent=BrainAgentId.INTELLIGENCE,
            unknowns=[
                UnknownRecord(
                    unknown_id="U-1",
                    goal_id="G-META",
                    question="What is the true conversion driver?",
                    consequence="A wrong driver would distort strategy.",
                    blocking=True,
                )
            ],
            evidence_needs=[
                EvidenceNeed(
                    need_id="N-1",
                    goal_id="G-META",
                    question="Which cohort changed?",
                    why_needed="Cohort evidence is needed to localize the effect.",
                    blocking=False,
                    evidence_refs=["E-COHORT"],
                )
            ],
        )

        self.assertEqual([gap.gap_id for gap in gaps], ["UNKNOWN:U-1", "EVIDENCE:N-1"])
        self.assertEqual(gaps[0].kind, KnowledgeGapKind.UNKNOWN)
        self.assertTrue(gaps[0].blocking)
        self.assertEqual(gaps[1].kind, KnowledgeGapKind.EVIDENCE)
        self.assertEqual(gaps[1].evidence_refs, ["E-COHORT"])

    def test_blocking_unknown_forces_blocked_research_state(self) -> None:
        request = MetacognitionRequest(
            assessment_id="META-1",
            goal_id="G-META",
            agent_id=BrainAgentId.CMO,
            gaps=[
                KnowledgeGap(
                    gap_id="GAP-BLOCK",
                    goal_id="G-META",
                    owner_agent=BrainAgentId.CMO,
                    kind=KnowledgeGapKind.UNKNOWN,
                    question="Is the key assumption true?",
                    consequence="Proceeding blindly could invalidate the campaign.",
                    blocking=True,
                )
            ],
        )

        decision = assess_metacognition(request)
        self.assertEqual(decision.knowledge_state, KnowledgeState.BLOCKED)
        self.assertEqual(decision.next_strategy, LearningStrategy.RESEARCH)
        self.assertEqual(decision.blocking_gap_ids, ["GAP-BLOCK"])

    def test_testable_causal_gap_prefers_experiment(self) -> None:
        request = MetacognitionRequest(
            assessment_id="META-2",
            goal_id="G-META",
            agent_id=BrainAgentId.PERFORMANCE,
            gaps=[
                KnowledgeGap(
                    gap_id="GAP-CAUSE",
                    goal_id="G-META",
                    owner_agent=BrainAgentId.PERFORMANCE,
                    kind=KnowledgeGapKind.CAUSAL,
                    question="Did creative A cause the lift?",
                    consequence="Attribution determines the next budget allocation.",
                    testable=True,
                )
            ],
        )

        decision = assess_metacognition(request)
        self.assertEqual(decision.knowledge_state, KnowledgeState.INCOMPLETE)
        self.assertEqual(decision.next_strategy, LearningStrategy.EXPERIMENT)
        self.assertEqual(decision.directives[0].strategy, LearningStrategy.EXPERIMENT)

    def test_procedural_gap_prefers_decomposition(self) -> None:
        request = MetacognitionRequest(
            assessment_id="META-3",
            goal_id="G-META",
            agent_id=BrainAgentId.CONTENT,
            gaps=[
                KnowledgeGap(
                    gap_id="GAP-PROC",
                    goal_id="G-META",
                    owner_agent=BrainAgentId.CONTENT,
                    kind=KnowledgeGapKind.PROCEDURAL,
                    question="How should the launch be sequenced?",
                    consequence="The plan cannot be executed safely without a procedure.",
                )
            ],
        )

        decision = assess_metacognition(request)
        self.assertEqual(decision.next_strategy, LearningStrategy.DECOMPOSE)

    def test_contested_evidence_forces_contradiction_resolution(self) -> None:
        contested = ClaimEvidenceAssessment(
            assessment_id="EA-CONTEST",
            goal_id="G-META",
            claim_id="CLAIM-X",
            agent_id=BrainAgentId.INTELLIGENCE,
            verdict=ClaimVerdict.CONTESTED,
            supporting_evidence_refs=["E-S"],
            contradicting_evidence_refs=["E-C"],
            reasons=["independent observed evidence conflicts"],
        )
        request = MetacognitionRequest(
            assessment_id="META-4",
            goal_id="G-META",
            agent_id=BrainAgentId.CMO,
            evidence_assessments=[contested],
        )

        decision = assess_metacognition(request)
        self.assertEqual(decision.knowledge_state, KnowledgeState.CONTESTED)
        self.assertEqual(
            decision.next_strategy,
            LearningStrategy.RESOLVE_CONTRADICTION,
        )
        self.assertEqual(decision.contested_claim_ids, ["CLAIM-X"])

    def test_insufficient_evidence_creates_research_directive(self) -> None:
        insufficient = ClaimEvidenceAssessment(
            assessment_id="EA-INSUFFICIENT",
            goal_id="G-META",
            claim_id="CLAIM-Y",
            agent_id=BrainAgentId.INTELLIGENCE,
            verdict=ClaimVerdict.INSUFFICIENT,
            reasons=["not enough independent observed evidence"],
        )
        decision = assess_metacognition(
            MetacognitionRequest(
                assessment_id="META-5",
                goal_id="G-META",
                agent_id=BrainAgentId.INTELLIGENCE,
                evidence_assessments=[insufficient],
            )
        )
        self.assertEqual(decision.knowledge_state, KnowledgeState.INCOMPLETE)
        self.assertEqual(decision.next_strategy, LearningStrategy.RESEARCH)
        self.assertEqual(decision.insufficient_claim_ids, ["CLAIM-Y"])

    def test_resolved_supported_or_refuted_claims_can_be_sufficient(self) -> None:
        supported = self._assessment("EA-S", "CLAIM-S", ClaimVerdict.SUPPORTED)
        refuted = self._assessment("EA-R", "CLAIM-R", ClaimVerdict.REFUTED)
        decision = assess_metacognition(
            MetacognitionRequest(
                assessment_id="META-6",
                goal_id="G-META",
                agent_id=BrainAgentId.CMO,
                evidence_assessments=[supported, refuted],
            )
        )
        self.assertEqual(decision.knowledge_state, KnowledgeState.SUFFICIENT)
        self.assertEqual(decision.next_strategy, LearningStrategy.NONE)
        self.assertEqual(decision.directives, [])

    def test_cross_goal_gap_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            MetacognitionRequest(
                assessment_id="META-7",
                goal_id="G-META",
                agent_id=BrainAgentId.CMO,
                gaps=[
                    KnowledgeGap(
                        gap_id="GAP-FOREIGN",
                        goal_id="G-OTHER",
                        owner_agent=BrainAgentId.CMO,
                        kind=KnowledgeGapKind.UNKNOWN,
                        question="Foreign question",
                        consequence="Must not contaminate this goal.",
                    )
                ],
            )

    def test_post_construction_gap_mutation_fails_closed(self) -> None:
        request = MetacognitionRequest(
            assessment_id="META-8",
            goal_id="G-META",
            agent_id=BrainAgentId.CMO,
            gaps=[
                KnowledgeGap(
                    gap_id="GAP-MUT",
                    goal_id="G-META",
                    owner_agent=BrainAgentId.CMO,
                    kind=KnowledgeGapKind.UNKNOWN,
                    question="Still valid?",
                    consequence="Mutation must not become authority.",
                )
            ],
        )
        request.gaps[0].kind = "NOT_A_KIND"
        with self.assertRaises(ValidationError):
            assess_metacognition(request)


if __name__ == "__main__":
    unittest.main()
