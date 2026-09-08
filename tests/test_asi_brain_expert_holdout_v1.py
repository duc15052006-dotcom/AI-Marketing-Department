"""Expert holdout for the semantic Brain of the five permanent ASIs.

This suite intentionally tests cognitive policy, evidence discipline, and
five-ASI peer review without invoking tools, providers, or live models.
It includes two RED security/authority probes that are expected to expose any
mutable-input or caller-asserted-evidence trust gap at the Brain use boundary.
"""

from __future__ import annotations

import itertools
import unittest

from brain.collaboration import (
    CollaborationAssessment,
    CollaborationDisposition,
    PeerReview,
    evaluate_collaboration,
)
from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
    assess_claim_evidence,
)
from brain.reasoning import (
    ReasoningAssessment,
    ReasoningDepth,
    Reversibility,
    SignalLevel,
    select_reasoning_depth,
)
from schemas.base import ValidationError


AGENTS = list(BrainAgentId)
DEPTH_RANK = {
    ReasoningDepth.FAST: 0,
    ReasoningDepth.BALANCED: 1,
    ReasoningDepth.DEEP: 2,
    ReasoningDepth.VERY_DEEP: 3,
    ReasoningDepth.MAXIMUM: 4,
}
SIGNALS = [SignalLevel.LOW, SignalLevel.MEDIUM, SignalLevel.HIGH, SignalLevel.CRITICAL]
PEERS = [
    BrainAgentId.INTELLIGENCE,
    BrainAgentId.STRATEGIST,
    BrainAgentId.CREATIVE,
    BrainAgentId.PERFORMANCE,
]


def evidence(
    eid: str,
    *,
    goal: str = "G",
    claim: str = "P",
    source: str,
    relation: EvidenceRelation,
    strength: EvidenceStrength = EvidenceStrength.STRONG,
    origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
) -> EvidenceSignal:
    return EvidenceSignal(
        evidence_id=eid,
        goal_id=goal,
        claim_id=claim,
        source_id=source,
        relation=relation,
        strength=strength,
        origin=origin,
    )


def backed_review(
    review_id: str,
    reviewer: BrainAgentId,
    verdict: ClaimVerdict = ClaimVerdict.SUPPORTED,
) -> PeerReview:
    if verdict == ClaimVerdict.SUPPORTED:
        relation = EvidenceRelation.SUPPORTS
    elif verdict == ClaimVerdict.REFUTED:
        relation = EvidenceRelation.CONTRADICTS
    else:
        raise ValueError("helper supports SUPPORTED or REFUTED")
    eid = f"{review_id}-e"
    req = ClaimEvidenceRequest(
        assessment_id=f"{review_id}-ea",
        goal_id="G",
        claim_id="P",
        agent_id=reviewer,
        evidence=[
            evidence(
                eid,
                source=f"{review_id}-source",
                relation=relation,
            )
        ],
    )
    return PeerReview(
        review_id=review_id,
        goal_id="G",
        proposal_id="P",
        reviewer_agent=reviewer,
        verdict=verdict,
        rationale="independent raw-evidence review",
        evidence_refs=[eid],
        evidence_request=req,
    )


def collaboration(
    reviews,
    *,
    proposal_verdict: ClaimVerdict = ClaimVerdict.SUPPORTED,
    proposal_refs=None,
    quorum: int = 1,
) -> CollaborationAssessment:
    if proposal_refs is None:
        proposal_refs = ["proposal-evidence"]
    return CollaborationAssessment(
        assessment_id="CA",
        goal_id="G",
        proposal_id="P",
        author_agent=BrainAgentId.CMO,
        proposal_verdict=proposal_verdict,
        proposal_evidence_refs=proposal_refs,
        reviews=reviews,
        minimum_supporting_reviewers=quorum,
    )


class TestFiveASIIdentityAndReasoning(unittest.TestCase):
    def test_exactly_five_permanent_asi_identities(self):
        self.assertEqual(
            [agent.value for agent in AGENTS],
            ["CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"],
        )
        self.assertEqual(len(AGENTS), 5)

    def test_reasoning_signal_monotonicity_exhaustive_all_five_asi(self):
        """Raising any cognitive signal must never make reasoning shallower."""
        for agent in AGENTS:
            for combo in itertools.product(SIGNALS, repeat=4):
                base = ReasoningAssessment(
                    assessment_id="R",
                    goal_id="G",
                    agent_id=agent,
                    complexity=combo[0],
                    uncertainty=combo[1],
                    consequence=combo[2],
                    evidence_conflict=combo[3],
                )
                base_depth = select_reasoning_depth(base).depth
                for axis in range(4):
                    idx = SIGNALS.index(combo[axis])
                    if idx == len(SIGNALS) - 1:
                        continue
                    raised = list(combo)
                    raised[axis] = SIGNALS[idx + 1]
                    candidate = ReasoningAssessment(
                        assessment_id="R2",
                        goal_id="G",
                        agent_id=agent,
                        complexity=raised[0],
                        uncertainty=raised[1],
                        consequence=raised[2],
                        evidence_conflict=raised[3],
                    )
                    candidate_depth = select_reasoning_depth(candidate).depth
                    self.assertGreaterEqual(
                        DEPTH_RANK[candidate_depth],
                        DEPTH_RANK[base_depth],
                        msg=f"{agent.value} became shallower: {combo} -> {tuple(raised)}",
                    )

    def test_irreversible_decision_forces_maximum_for_all_five_asi(self):
        for agent in AGENTS:
            decision = select_reasoning_depth(
                ReasoningAssessment(
                    assessment_id=f"IR-{agent.value}",
                    goal_id="G",
                    agent_id=agent,
                    complexity=SignalLevel.LOW,
                    uncertainty=SignalLevel.LOW,
                    consequence=SignalLevel.LOW,
                    evidence_conflict=SignalLevel.LOW,
                    reversibility=Reversibility.IRREVERSIBLE,
                )
            )
            self.assertEqual(decision.depth, ReasoningDepth.MAXIMUM)

    def test_critical_evidence_conflict_forces_maximum_for_all_five_asi(self):
        for agent in AGENTS:
            decision = select_reasoning_depth(
                ReasoningAssessment(
                    assessment_id=f"CF-{agent.value}",
                    goal_id="G",
                    agent_id=agent,
                    evidence_conflict=SignalLevel.CRITICAL,
                )
            )
            self.assertEqual(decision.depth, ReasoningDepth.MAXIMUM)

    def test_causal_and_contradiction_floors_are_preserved(self):
        for agent in AGENTS:
            causal = select_reasoning_depth(
                ReasoningAssessment(
                    assessment_id="C",
                    goal_id="G",
                    agent_id=agent,
                    complexity=SignalLevel.LOW,
                    uncertainty=SignalLevel.LOW,
                    consequence=SignalLevel.LOW,
                    evidence_conflict=SignalLevel.LOW,
                    causal_reasoning_required=True,
                )
            )
            contradiction = select_reasoning_depth(
                ReasoningAssessment(
                    assessment_id="X",
                    goal_id="G",
                    agent_id=agent,
                    complexity=SignalLevel.LOW,
                    uncertainty=SignalLevel.LOW,
                    consequence=SignalLevel.LOW,
                    evidence_conflict=SignalLevel.LOW,
                    contradiction_resolution_required=True,
                )
            )
            self.assertGreaterEqual(DEPTH_RANK[causal.depth], DEPTH_RANK[ReasoningDepth.DEEP])
            self.assertGreaterEqual(
                DEPTH_RANK[contradiction.depth], DEPTH_RANK[ReasoningDepth.VERY_DEEP]
            )

    def test_red_mutated_reasoning_assessment_cannot_bypass_use_boundary_validation(self):
        """RED probe: mutable invalid fields must fail closed when consumed."""
        assessment = ReasoningAssessment(
            assessment_id="MUT",
            goal_id="G",
            agent_id=BrainAgentId.CMO,
            consequence=SignalLevel.CRITICAL,
        )
        assessment.consequence = "NOT_A_SIGNAL_LEVEL"
        with self.assertRaises(ValidationError):
            select_reasoning_depth(assessment)


class TestFiveASIEvidenceDiscipline(unittest.TestCase):
    def test_same_source_cannot_manufacture_corroboration(self):
        for agent in AGENTS:
            req = ClaimEvidenceRequest(
                assessment_id="E1",
                goal_id="G",
                claim_id="P",
                agent_id=agent,
                evidence=[
                    evidence(
                        "e1",
                        source="same-source",
                        relation=EvidenceRelation.SUPPORTS,
                        strength=EvidenceStrength.MODERATE,
                    ),
                    evidence(
                        "e2",
                        source="same-source",
                        relation=EvidenceRelation.SUPPORTS,
                        strength=EvidenceStrength.MODERATE,
                    ),
                ],
            )
            self.assertEqual(assess_claim_evidence(req).verdict, ClaimVerdict.INSUFFICIENT)

    def test_two_independent_observed_moderate_sources_do_support(self):
        for agent in AGENTS:
            req = ClaimEvidenceRequest(
                assessment_id="E2",
                goal_id="G",
                claim_id="P",
                agent_id=agent,
                evidence=[
                    evidence(
                        "e1",
                        source="s1",
                        relation=EvidenceRelation.SUPPORTS,
                        strength=EvidenceStrength.MODERATE,
                    ),
                    evidence(
                        "e2",
                        source="s2",
                        relation=EvidenceRelation.SUPPORTS,
                        strength=EvidenceStrength.MODERATE,
                    ),
                ],
            )
            self.assertEqual(assess_claim_evidence(req).verdict, ClaimVerdict.SUPPORTED)

    def test_derived_strong_evidence_cannot_establish_fact(self):
        for agent in AGENTS:
            req = ClaimEvidenceRequest(
                assessment_id="E3",
                goal_id="G",
                claim_id="P",
                agent_id=agent,
                evidence=[
                    evidence(
                        "e1",
                        source="derived",
                        relation=EvidenceRelation.SUPPORTS,
                        origin=EvidenceOrigin.DERIVED,
                    )
                ],
            )
            self.assertEqual(assess_claim_evidence(req).verdict, ClaimVerdict.INSUFFICIENT)

    def test_material_support_and_refutation_surface_as_contested(self):
        for agent in AGENTS:
            req = ClaimEvidenceRequest(
                assessment_id="E4",
                goal_id="G",
                claim_id="P",
                agent_id=agent,
                evidence=[
                    evidence("e1", source="support", relation=EvidenceRelation.SUPPORTS),
                    evidence("e2", source="refute", relation=EvidenceRelation.CONTRADICTS),
                ],
            )
            self.assertEqual(assess_claim_evidence(req).verdict, ClaimVerdict.CONTESTED)

    def test_conflicting_reuse_of_evidence_identity_fails_closed(self):
        req = ClaimEvidenceRequest(
            assessment_id="E5",
            goal_id="G",
            claim_id="P",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                evidence("same", source="s1", relation=EvidenceRelation.SUPPORTS),
                evidence("same", source="s2", relation=EvidenceRelation.CONTRADICTS),
            ],
        )
        with self.assertRaises(ValidationError):
            assess_claim_evidence(req)


class TestFiveASICollaborationAdversarial(unittest.TestCase):
    def test_self_review_cannot_create_independent_quorum(self):
        self_review = backed_review("self", BrainAgentId.CMO)
        result = evaluate_collaboration(collaboration([self_review]))
        self.assertEqual(result.disposition, CollaborationDisposition.INCONCLUSIVE)
        self.assertIn("self", result.ignored_review_ids)

    def test_duplicate_reviewer_identity_cannot_manufacture_quorum(self):
        r1 = backed_review("r1", BrainAgentId.INTELLIGENCE)
        r2 = backed_review("r2", BrainAgentId.INTELLIGENCE)
        result = evaluate_collaboration(collaboration([r1, r2], quorum=1))
        self.assertEqual(result.disposition, CollaborationDisposition.INCONCLUSIVE)
        self.assertEqual(set(result.ignored_review_ids), {"r1", "r2"})

    def test_four_peer_votes_cannot_upgrade_insufficient_proposal_evidence(self):
        reviews = [backed_review(f"s{i}", peer) for i, peer in enumerate(PEERS)]
        result = evaluate_collaboration(
            collaboration(
                reviews,
                proposal_verdict=ClaimVerdict.INSUFFICIENT,
                proposal_refs=[],
                quorum=4,
            )
        )
        self.assertEqual(result.disposition, CollaborationDisposition.INCONCLUSIVE)

    def test_majority_support_cannot_average_away_evidence_backed_refutation(self):
        reviews = [
            backed_review("s1", BrainAgentId.INTELLIGENCE),
            backed_review("s2", BrainAgentId.STRATEGIST),
            backed_review("s3", BrainAgentId.CREATIVE),
            backed_review("r1", BrainAgentId.PERFORMANCE, ClaimVerdict.REFUTED),
        ]
        result = evaluate_collaboration(collaboration(reviews, quorum=3))
        self.assertEqual(result.disposition, CollaborationDisposition.REVISE)
        self.assertEqual(result.dissenting_review_ids, ["r1"])

    def test_missing_proposal_evidence_lineage_blocks_acceptance(self):
        result = evaluate_collaboration(
            collaboration(
                [backed_review("s1", BrainAgentId.INTELLIGENCE)],
                proposal_refs=[],
            )
        )
        self.assertEqual(result.disposition, CollaborationDisposition.INCONCLUSIVE)

    def test_unsubstantiated_refutation_still_blocks_acceptance(self):
        support = backed_review("s1", BrainAgentId.INTELLIGENCE)
        challenge = PeerReview(
            review_id="challenge",
            goal_id="G",
            proposal_id="P",
            reviewer_agent=BrainAgentId.STRATEGIST,
            verdict=ClaimVerdict.REFUTED,
            rationale="challenge without canonical raw evidence",
            evidence_refs=[],
            evidence_request=None,
        )
        result = evaluate_collaboration(collaboration([support, challenge]))
        self.assertEqual(result.disposition, CollaborationDisposition.ESCALATE)

    def test_post_construction_peer_provenance_drift_fails_closed(self):
        support = backed_review("s1", BrainAgentId.INTELLIGENCE)
        support.evidence_refs = ["forged-after-validation"]
        result = evaluate_collaboration(collaboration([support]))
        self.assertEqual(result.disposition, CollaborationDisposition.INCONCLUSIVE)
        self.assertEqual(result.supporting_review_ids, [])

    def test_review_order_cannot_change_disposition_or_authority_sets(self):
        reviews = [
            backed_review("s1", BrainAgentId.INTELLIGENCE),
            backed_review("s2", BrainAgentId.STRATEGIST),
            backed_review("r1", BrainAgentId.CREATIVE, ClaimVerdict.REFUTED),
        ]
        baseline = evaluate_collaboration(collaboration(reviews, quorum=2))
        for perm in itertools.permutations(reviews):
            candidate = evaluate_collaboration(collaboration(list(perm), quorum=2))
            self.assertEqual(candidate.disposition, baseline.disposition)
            self.assertEqual(set(candidate.supporting_review_ids), set(baseline.supporting_review_ids))
            self.assertEqual(set(candidate.dissenting_review_ids), set(baseline.dissenting_review_ids))

    def test_red_caller_asserted_supported_proposal_cannot_become_authority_without_raw_proof(self):
        """RED probe: opaque proposal refs alone must not establish proposal authority."""
        peer = backed_review("s1", BrainAgentId.INTELLIGENCE)
        forged = collaboration(
            [peer],
            proposal_verdict=ClaimVerdict.SUPPORTED,
            proposal_refs=["fabricated-unverified-proposal-ref"],
            quorum=1,
        )
        result = evaluate_collaboration(forged)
        self.assertNotEqual(
            result.disposition,
            CollaborationDisposition.ACCEPT,
            msg="collaboration accepted caller-asserted SUPPORTED proposal without canonical raw proposal evidence",
        )


if __name__ == "__main__":
    unittest.main()
