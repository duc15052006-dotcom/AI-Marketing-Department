from __future__ import annotations

import unittest

import brain
from brain.contracts import BrainAgentId, DecisionRecord
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.hypotheses import HypothesisCandidate, HypothesisPortfolioRequest
from brain.world_state import BeliefStatus, WorldProposition, WorldStateRequest, build_world_state
from schemas.base import ValidationError

try:
    from brain.reflection import (
        CognitiveReflectionReport,
        CognitiveReflectionRequest,
        DecisionPremise,
        ReflectionDirective,
        ReflectionFinding,
        ReflectionFindingKind,
        reflect_on_decision,
    )

    REFLECTION_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability does not exist yet.
    REFLECTION_IMPORT_ERROR = exc


class BrainCognitiveReflectionV1Tests(unittest.TestCase):
    def _require_capability(self) -> None:
        if REFLECTION_IMPORT_ERROR is not None:
            self.fail(
                "COGNITIVE_REFLECTION_CAPABILITY_MISSING: "
                f"{REFLECTION_IMPORT_ERROR}"
            )

    def _signal(
        self,
        *,
        evidence_id: str,
        claim_id: str = "claim-demand",
        goal_id: str = "goal-growth",
        source_id: str = "source-demand-study",
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        agent_id: BrainAgentId = BrainAgentId.STRATEGIST,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
    ) -> EvidenceSignal:
        # agent_id is accepted for helper symmetry; EvidenceSignal authority is goal/claim/source.
        del agent_id
        return EvidenceSignal(
            evidence_id=evidence_id,
            goal_id=goal_id,
            claim_id=claim_id,
            source_id=source_id,
            relation=relation,
            strength=EvidenceStrength.STRONG,
            origin=origin,
        )

    def _evidence_request(
        self,
        *,
        assessment_id: str,
        claim_id: str = "claim-demand",
        agent_id: BrainAgentId = BrainAgentId.STRATEGIST,
        signals=None,
        goal_id: str = "goal-growth",
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id=goal_id,
            claim_id=claim_id,
            agent_id=agent_id,
            evidence=signals or [],
        )

    def _world_state(
        self,
        *,
        status: BeliefStatus = BeliefStatus.ESTABLISHED,
        snapshot_id: str = "world-reflection-1",
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.STRATEGIST,
    ):
        proposition = WorldProposition(
            proposition_id="claim-demand",
            goal_id=goal_id,
            agent_id=agent_id,
            statement="Market demand is increasing",
        )
        evidence_requests = []
        if status == BeliefStatus.ESTABLISHED:
            evidence_requests = [
                self._evidence_request(
                    assessment_id="assessment-demand",
                    goal_id=goal_id,
                    agent_id=agent_id,
                    signals=[
                        self._signal(
                            evidence_id="e-demand-support",
                            goal_id=goal_id,
                        )
                    ],
                )
            ]
        elif status == BeliefStatus.CONTESTED:
            evidence_requests = [
                self._evidence_request(
                    assessment_id="assessment-demand",
                    goal_id=goal_id,
                    agent_id=agent_id,
                    signals=[
                        self._signal(
                            evidence_id="e-demand-support",
                            goal_id=goal_id,
                        ),
                        self._signal(
                            evidence_id="e-demand-contradict",
                            goal_id=goal_id,
                            source_id="source-demand-counter",
                            relation=EvidenceRelation.CONTRADICTS,
                        ),
                    ],
                )
            ]
        elif status == BeliefStatus.REFUTED:
            evidence_requests = [
                self._evidence_request(
                    assessment_id="assessment-demand",
                    goal_id=goal_id,
                    agent_id=agent_id,
                    signals=[
                        self._signal(
                            evidence_id="e-demand-contradict",
                            goal_id=goal_id,
                            source_id="source-demand-counter",
                            relation=EvidenceRelation.CONTRADICTS,
                        )
                    ],
                )
            ]

        return build_world_state(
            WorldStateRequest(
                snapshot_id=snapshot_id,
                goal_id=goal_id,
                agent_id=agent_id,
                propositions=[proposition],
                evidence_requests=evidence_requests,
            )
        )

    def _decision(
        self,
        *,
        evidence_refs=None,
        confidence=None,
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.STRATEGIST,
    ) -> DecisionRecord:
        return DecisionRecord(
            decision_id="decision-growth",
            goal_id=goal_id,
            agent_id=agent_id,
            statement="Increase acquisition investment",
            rationale="Demand evidence supports expansion",
            evidence_refs=evidence_refs or ["e-demand-support"],
            confidence=confidence,
        )

    def _premise(
        self,
        *,
        proposition_id: str = "claim-demand",
        expected_status: BeliefStatus = BeliefStatus.ESTABLISHED,
    ):
        self._require_capability()
        return DecisionPremise(
            premise_id="premise-demand",
            decision_id="decision-growth",
            proposition_id=proposition_id,
            expected_status=expected_status,
            rationale="The decision relies on demand direction",
        )

    def _portfolio(
        self,
        *,
        second_refuted: bool = False,
        first_predictions=None,
        goal_id: str = "goal-growth",
    ) -> HypothesisPortfolioRequest:
        hypotheses = [
            HypothesisCandidate(
                hypothesis_id="h-demand",
                goal_id=goal_id,
                owner_agent=BrainAgentId.STRATEGIST,
                statement="Demand is the dominant growth driver",
                differentiating_predictions=first_predictions or [],
            ),
            HypothesisCandidate(
                hypothesis_id="h-price",
                goal_id=goal_id,
                owner_agent=BrainAgentId.STRATEGIST,
                statement="Price is the dominant growth driver",
                differentiating_predictions=["Price test produces material lift"],
            ),
        ]
        evidence_requests = [
            self._evidence_request(
                assessment_id="assessment-h-demand",
                claim_id="h-demand",
                signals=[
                    self._signal(
                        evidence_id="e-h-demand",
                        claim_id="h-demand",
                        source_id="experiment-demand",
                    )
                ],
            )
        ]
        if second_refuted:
            evidence_requests.append(
                self._evidence_request(
                    assessment_id="assessment-h-price",
                    claim_id="h-price",
                    signals=[
                        self._signal(
                            evidence_id="e-h-price-refute",
                            claim_id="h-price",
                            source_id="experiment-price",
                            relation=EvidenceRelation.CONTRADICTS,
                        )
                    ],
                )
            )
        return HypothesisPortfolioRequest(
            portfolio_id="portfolio-growth",
            goal_id=goal_id,
            owner_agent=BrainAgentId.STRATEGIST,
            hypotheses=hypotheses,
            evidence_requests=evidence_requests,
        )

    def _request(
        self,
        *,
        source_state=None,
        decision=None,
        premises=None,
        evidence_requests=None,
        portfolio_request=None,
        selected_hypothesis_id=None,
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.STRATEGIST,
    ):
        self._require_capability()
        return CognitiveReflectionRequest(
            reflection_id="reflection-growth",
            goal_id=goal_id,
            agent_id=agent_id,
            decision=decision or self._decision(goal_id=goal_id, agent_id=agent_id),
            source_state=source_state or self._world_state(goal_id=goal_id, agent_id=agent_id),
            premises=premises or [self._premise()],
            evidence_requests=evidence_requests or [],
            portfolio_request=portfolio_request,
            selected_hypothesis_id=selected_hypothesis_id,
        )

    @staticmethod
    def _kinds(report: CognitiveReflectionReport):
        return {finding.kind for finding in report.findings}

    @staticmethod
    def _directives(report: CognitiveReflectionReport):
        return set(report.directives)

    def test_established_premise_with_complete_lineage_is_clear(self) -> None:
        self._require_capability()
        report = reflect_on_decision(self._request())
        self.assertIsInstance(report, CognitiveReflectionReport)
        self.assertEqual(report.findings, [])
        self.assertEqual(report.directives, [])
        self.assertEqual(report.source_snapshot_id, "world-reflection-1")

    def test_unknown_premise_is_explicit_unsupported_assumption(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(source_state=self._world_state(status=BeliefStatus.UNKNOWN))
        )
        self.assertIn(ReflectionFindingKind.UNSUPPORTED_ASSUMPTION, self._kinds(report))
        self.assertIn(ReflectionDirective.RESEARCH_PREMISE, self._directives(report))

    def test_contested_premise_is_preserved_and_requires_resolution(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(
                source_state=self._world_state(status=BeliefStatus.CONTESTED),
                decision=self._decision(
                    evidence_refs=["e-demand-support", "e-demand-contradict"]
                ),
            )
        )
        self.assertIn(ReflectionFindingKind.CONTESTED_PREMISE, self._kinds(report))
        self.assertIn(
            ReflectionDirective.RESOLVE_CONTRADICTION,
            self._directives(report),
        )

    def test_refuted_expected_premise_requires_decision_revision(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(
                source_state=self._world_state(status=BeliefStatus.REFUTED),
                decision=self._decision(evidence_refs=["e-demand-contradict"]),
            )
        )
        self.assertIn(ReflectionFindingKind.REFUTED_PREMISE, self._kinds(report))
        self.assertIn(ReflectionDirective.REVISE_DECISION, self._directives(report))

    def test_expected_refutation_can_be_a_valid_premise(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(
                source_state=self._world_state(status=BeliefStatus.REFUTED),
                decision=self._decision(evidence_refs=["e-demand-contradict"]),
                premises=[self._premise(expected_status=BeliefStatus.REFUTED)],
            )
        )
        self.assertNotIn(ReflectionFindingKind.REFUTED_PREMISE, self._kinds(report))
        self.assertNotIn(ReflectionFindingKind.UNSUPPORTED_ASSUMPTION, self._kinds(report))

    def test_ignored_contradicting_evidence_is_reported_from_canonical_world(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(
                source_state=self._world_state(status=BeliefStatus.CONTESTED),
                decision=self._decision(evidence_refs=["e-demand-support"]),
            )
        )
        finding = next(
            item
            for item in report.findings
            if item.kind == ReflectionFindingKind.IGNORED_CONTRADICTING_EVIDENCE
        )
        self.assertIn("e-demand-contradict", finding.evidence_refs)
        self.assertIn(ReflectionDirective.REVIEW_IGNORED_EVIDENCE, self._directives(report))

    def test_numeric_confidence_is_not_treated_as_evidence_authority(self) -> None:
        self._require_capability()
        report = reflect_on_decision(self._request(decision=self._decision(confidence=0.91)))
        self.assertIn(
            ReflectionFindingKind.UNSUPPORTED_NUMERIC_CONFIDENCE,
            self._kinds(report),
        )
        self.assertIn(
            ReflectionDirective.REMOVE_UNSUPPORTED_CONFIDENCE,
            self._directives(report),
        )

    def test_cross_asi_common_source_is_reported_as_dependence(self) -> None:
        self._require_capability()
        intelligence = self._evidence_request(
            assessment_id="assessment-intelligence",
            agent_id=BrainAgentId.INTELLIGENCE,
            signals=[
                self._signal(
                    evidence_id="e-intelligence-source",
                    source_id="shared-market-report",
                )
            ],
        )
        strategist = self._evidence_request(
            assessment_id="assessment-strategist",
            agent_id=BrainAgentId.STRATEGIST,
            signals=[
                self._signal(
                    evidence_id="e-strategist-source",
                    source_id="shared-market-report",
                )
            ],
        )
        report = reflect_on_decision(
            self._request(evidence_requests=[intelligence, strategist])
        )
        finding = next(
            item
            for item in report.findings
            if item.kind == ReflectionFindingKind.SHARED_SOURCE_DEPENDENCE
        )
        self.assertEqual(finding.source_ids, ["shared-market-report"])
        self.assertEqual(
            set(finding.agent_ids),
            {BrainAgentId.INTELLIGENCE, BrainAgentId.STRATEGIST},
        )
        self.assertIn(ReflectionDirective.DIVERSIFY_SOURCES, self._directives(report))

    def test_repeated_source_within_one_asi_does_not_fake_cross_asi_dependence(self) -> None:
        self._require_capability()
        first = self._evidence_request(
            assessment_id="assessment-a",
            signals=[
                self._signal(
                    evidence_id="e-a",
                    source_id="same-source",
                )
            ],
        )
        second = self._evidence_request(
            assessment_id="assessment-b",
            signals=[
                self._signal(
                    evidence_id="e-b",
                    source_id="same-source",
                )
            ],
        )
        report = reflect_on_decision(self._request(evidence_requests=[first, second]))
        self.assertNotIn(ReflectionFindingKind.SHARED_SOURCE_DEPENDENCE, self._kinds(report))

    def test_supported_plus_insufficient_selected_hypothesis_is_premature(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(
                portfolio_request=self._portfolio(first_predictions=["Demand-led test wins"]),
                selected_hypothesis_id="h-demand",
            )
        )
        self.assertIn(ReflectionFindingKind.PREMATURE_CONVERGENCE, self._kinds(report))
        self.assertIn(ReflectionDirective.REOPEN_HYPOTHESES, self._directives(report))

    def test_canonical_unique_leader_is_not_flagged_as_premature(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(
                portfolio_request=self._portfolio(
                    second_refuted=True,
                    first_predictions=["Demand-led test wins"],
                ),
                selected_hypothesis_id="h-demand",
            )
        )
        self.assertNotIn(ReflectionFindingKind.PREMATURE_CONVERGENCE, self._kinds(report))

    def test_selected_hypothesis_without_discriminating_prediction_needs_falsification_test(self) -> None:
        self._require_capability()
        report = reflect_on_decision(
            self._request(
                portfolio_request=self._portfolio(second_refuted=True),
                selected_hypothesis_id="h-demand",
            )
        )
        self.assertIn(ReflectionFindingKind.MISSING_FALSIFICATION_TEST, self._kinds(report))
        self.assertIn(
            ReflectionDirective.DEFINE_FALSIFICATION_TEST,
            self._directives(report),
        )

    def test_unknown_selected_hypothesis_fails_closed(self) -> None:
        self._require_capability()
        with self.assertRaises(ValidationError):
            reflect_on_decision(
                self._request(
                    portfolio_request=self._portfolio(),
                    selected_hypothesis_id="h-unknown",
                )
            )

    def test_goal_and_agent_scope_mismatch_fail_closed(self) -> None:
        self._require_capability()
        source = self._world_state()
        with self.assertRaises(ValidationError):
            self._request(goal_id="goal-other", source_state=source)
        with self.assertRaises(ValidationError):
            self._request(agent_id=BrainAgentId.CREATIVE, source_state=source)

    def test_nested_world_state_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.source_state.goal_id = "goal-hijacked"
        with self.assertRaises(ValidationError):
            reflect_on_decision(request)

    def test_nested_premise_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.premises[0].proposition_id = "claim-hijacked"
        with self.assertRaises(ValidationError):
            reflect_on_decision(request)

    def test_nested_evidence_signal_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        telemetry = self._evidence_request(
            assessment_id="assessment-telemetry",
            signals=[self._signal(evidence_id="e-telemetry")],
        )
        request = self._request(evidence_requests=[telemetry])
        request.evidence_requests[0].evidence[0].goal_id = "goal-hijacked"
        with self.assertRaises(ValidationError):
            reflect_on_decision(request)

    def test_nested_portfolio_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request(
            portfolio_request=self._portfolio(first_predictions=["Demand-led test wins"]),
            selected_hypothesis_id="h-demand",
        )
        request.portfolio_request.evidence_requests[0].claim_id = "h-hijacked"
        with self.assertRaises(ValidationError):
            reflect_on_decision(request)

    def test_serialized_request_reconstructs_canonical_runtime_types(self) -> None:
        self._require_capability()
        request = CognitiveReflectionRequest(**self._request().model_dump())
        report = reflect_on_decision(request)
        self.assertIsInstance(report, CognitiveReflectionReport)
        self.assertIsInstance(request.premises[0], DecisionPremise)
        self.assertEqual(report.decision_id, "decision-growth")

    def test_reflection_does_not_mutate_or_alias_caller_inputs(self) -> None:
        self._require_capability()
        request = self._request()
        before = request.model_dump()
        report = reflect_on_decision(request)
        self.assertEqual(request.model_dump(), before)
        report.reasons.append("caller mutation")
        self.assertEqual(request.model_dump(), before)

    def test_public_brain_api_exports_reflection_capability(self) -> None:
        self._require_capability()
        expected = {
            "CognitiveReflectionReport",
            "CognitiveReflectionRequest",
            "DecisionPremise",
            "ReflectionDirective",
            "ReflectionFinding",
            "ReflectionFindingKind",
            "reflect_on_decision",
        }
        self.assertTrue(expected.issubset(set(brain.__all__)))
        for name in expected:
            self.assertTrue(hasattr(brain, name), name)


if __name__ == "__main__":
    unittest.main()
