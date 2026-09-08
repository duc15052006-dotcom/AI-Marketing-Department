from __future__ import annotations

import unittest

import brain
from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from schemas.base import ValidationError

try:
    from brain.world_state import (
        BeliefStatus,
        WorldBelief,
        WorldProposition,
        WorldStateRequest,
        WorldStateSnapshot,
        build_world_state,
    )

    WORLD_STATE_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability does not exist yet.
    WORLD_STATE_IMPORT_ERROR = exc


class BrainWorldStateReasoningV1Tests(unittest.TestCase):
    def _require_capability(self) -> None:
        if WORLD_STATE_IMPORT_ERROR is not None:
            self.fail(
                "WORLD_STATE_REASONING_CAPABILITY_MISSING: "
                f"{WORLD_STATE_IMPORT_ERROR}"
            )

    def _proposition(
        self,
        proposition_id: str = "claim-demand",
        *,
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
        statement: str = "Demand for the product is increasing",
    ):
        self._require_capability()
        return WorldProposition(
            proposition_id=proposition_id,
            goal_id=goal_id,
            agent_id=agent_id,
            statement=statement,
        )

    def _signal(
        self,
        evidence_id: str,
        relation: EvidenceRelation,
        *,
        claim_id: str = "claim-demand",
        goal_id: str = "goal-growth",
        source_id: str = "analytics-primary",
        strength: EvidenceStrength = EvidenceStrength.STRONG,
        origin: EvidenceOrigin = EvidenceOrigin.OBSERVED,
    ) -> EvidenceSignal:
        return EvidenceSignal(
            evidence_id=evidence_id,
            goal_id=goal_id,
            claim_id=claim_id,
            source_id=source_id,
            relation=relation,
            strength=strength,
            origin=origin,
        )

    def _evidence_request(
        self,
        evidence,
        *,
        claim_id: str = "claim-demand",
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
        assessment_id: str = "assessment-demand",
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id=goal_id,
            claim_id=claim_id,
            agent_id=agent_id,
            evidence=evidence,
        )

    def _request(
        self,
        *,
        propositions=None,
        evidence_requests=None,
        previous_state=None,
        snapshot_id: str = "world-1",
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
    ):
        self._require_capability()
        return WorldStateRequest(
            snapshot_id=snapshot_id,
            goal_id=goal_id,
            agent_id=agent_id,
            propositions=propositions or [self._proposition(goal_id=goal_id, agent_id=agent_id)],
            evidence_requests=evidence_requests or [],
            previous_state=previous_state,
        )

    def test_observed_support_establishes_belief(self) -> None:
        self._require_capability()
        request = self._request(
            evidence_requests=[
                self._evidence_request(
                    [self._signal("e-support", EvidenceRelation.SUPPORTS)]
                )
            ]
        )
        state = build_world_state(request)
        self.assertEqual(state.beliefs[0].status, BeliefStatus.ESTABLISHED)
        self.assertEqual(state.beliefs[0].supporting_evidence_refs, ["e-support"])

    def test_qualifying_support_and_contradiction_remain_contested(self) -> None:
        self._require_capability()
        request = self._request(
            evidence_requests=[
                self._evidence_request(
                    [
                        self._signal("e-support", EvidenceRelation.SUPPORTS),
                        self._signal(
                            "e-contradict",
                            EvidenceRelation.CONTRADICTS,
                            source_id="analytics-independent",
                        ),
                    ]
                )
            ]
        )
        belief = build_world_state(request).beliefs[0]
        self.assertEqual(belief.status, BeliefStatus.CONTESTED)
        self.assertEqual(belief.supporting_evidence_refs, ["e-support"])
        self.assertEqual(belief.contradicting_evidence_refs, ["e-contradict"])

    def test_observed_contradiction_refutes_belief(self) -> None:
        self._require_capability()
        request = self._request(
            evidence_requests=[
                self._evidence_request(
                    [self._signal("e-refute", EvidenceRelation.CONTRADICTS)]
                )
            ]
        )
        self.assertEqual(
            build_world_state(request).beliefs[0].status,
            BeliefStatus.REFUTED,
        )

    def test_insufficient_or_derived_evidence_cannot_become_fact(self) -> None:
        self._require_capability()
        request = self._request(
            evidence_requests=[
                self._evidence_request(
                    [
                        self._signal(
                            "e-derived",
                            EvidenceRelation.SUPPORTS,
                            origin=EvidenceOrigin.DERIVED,
                        )
                    ]
                )
            ]
        )
        belief = build_world_state(request).beliefs[0]
        self.assertEqual(belief.status, BeliefStatus.UNKNOWN)
        self.assertIn("e-derived", belief.supporting_evidence_refs)

    def test_empty_evidence_starts_unknown(self) -> None:
        self._require_capability()
        state = build_world_state(self._request())
        self.assertEqual(state.beliefs[0].status, BeliefStatus.UNKNOWN)

    def test_foreign_goal_or_agent_authority_is_rejected(self) -> None:
        self._require_capability()
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(
                    propositions=[self._proposition(goal_id="goal-other")]
                )
            )
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(
                    propositions=[self._proposition(agent_id=BrainAgentId.CREATIVE)]
                )
            )
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(
                    evidence_requests=[
                        self._evidence_request([], goal_id="goal-other")
                    ]
                )
            )
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(
                    evidence_requests=[
                        self._evidence_request([], agent_id=BrainAgentId.CREATIVE)
                    ]
                )
            )

    def test_duplicate_or_unknown_proposition_bindings_fail_closed(self) -> None:
        self._require_capability()
        proposition = self._proposition()
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(propositions=[proposition, self._proposition()])
            )
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(
                    evidence_requests=[
                        self._evidence_request([], claim_id="claim-unknown")
                    ]
                )
            )

    def test_multiple_assessments_for_same_proposition_are_rejected(self) -> None:
        self._require_capability()
        first = self._evidence_request([], assessment_id="assessment-1")
        second = self._evidence_request([], assessment_id="assessment-2")
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(evidence_requests=[first, second])
            )

    def test_previous_proposition_cannot_disappear_or_rebind(self) -> None:
        self._require_capability()
        previous = build_world_state(self._request())
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(
                    propositions=[
                        self._proposition(
                            proposition_id="claim-new",
                            statement="A new claim",
                        )
                    ],
                    previous_state=previous,
                    snapshot_id="world-2",
                )
            )
        with self.assertRaises(ValidationError):
            build_world_state(
                self._request(
                    propositions=[self._proposition(statement="Changed statement")],
                    previous_state=previous,
                    snapshot_id="world-2",
                )
            )

    def test_previous_belief_carries_forward_without_new_evidence(self) -> None:
        self._require_capability()
        first = build_world_state(
            self._request(
                evidence_requests=[
                    self._evidence_request(
                        [self._signal("e-support", EvidenceRelation.SUPPORTS)]
                    )
                ]
            )
        )
        second = build_world_state(
            self._request(previous_state=first, snapshot_id="world-2")
        )
        self.assertEqual(second.previous_snapshot_id, "world-1")
        self.assertEqual(second.beliefs[0].status, BeliefStatus.ESTABLISHED)
        self.assertEqual(
            second.beliefs[0].supporting_evidence_refs,
            ["e-support"],
        )
        self.assertEqual(len(second.beliefs[0].revisions), 1)

    def test_new_evidence_revises_belief_and_preserves_history(self) -> None:
        self._require_capability()
        first = build_world_state(
            self._request(
                evidence_requests=[
                    self._evidence_request(
                        [self._signal("e-support", EvidenceRelation.SUPPORTS)],
                        assessment_id="assessment-1",
                    )
                ]
            )
        )
        second = build_world_state(
            self._request(
                previous_state=first,
                snapshot_id="world-2",
                evidence_requests=[
                    self._evidence_request(
                        [self._signal("e-refute", EvidenceRelation.CONTRADICTS)],
                        assessment_id="assessment-2",
                    )
                ],
            )
        )
        belief = second.beliefs[0]
        self.assertEqual(belief.status, BeliefStatus.REFUTED)
        self.assertEqual(len(belief.revisions), 2)
        self.assertEqual(belief.revisions[0].status, BeliefStatus.ESTABLISHED)
        self.assertEqual(belief.revisions[1].status, BeliefStatus.REFUTED)

    def test_build_does_not_mutate_or_alias_nested_inputs(self) -> None:
        self._require_capability()
        proposition = self._proposition()
        signal = self._signal("e-support", EvidenceRelation.SUPPORTS)
        evidence_request = self._evidence_request([signal])
        request = self._request(
            propositions=[proposition], evidence_requests=[evidence_request]
        )
        state = build_world_state(request)

        proposition.statement = "tampered proposition"
        signal.source_id = "tampered-source"
        evidence_request.evidence.append(
            self._signal("e-extra", EvidenceRelation.CONTRADICTS)
        )
        request.propositions.clear()

        self.assertEqual(
            state.beliefs[0].proposition.statement,
            "Demand for the product is increasing",
        )
        self.assertEqual(state.beliefs[0].supporting_evidence_refs, ["e-support"])

    def test_previous_snapshot_is_not_mutated_or_aliased(self) -> None:
        self._require_capability()
        previous = build_world_state(self._request())
        previous_dump = previous.model_dump()
        current = build_world_state(
            self._request(previous_state=previous, snapshot_id="world-2")
        )
        current.beliefs[0].proposition.statement = "tampered current"
        current.beliefs[0].revisions[0].reasons.append("tampered current")
        self.assertEqual(previous.model_dump(), previous_dump)

    def test_serialized_snapshot_reconstructs_canonical_runtime_types(self) -> None:
        self._require_capability()
        state = build_world_state(
            self._request(
                evidence_requests=[
                    self._evidence_request(
                        [self._signal("e-support", EvidenceRelation.SUPPORTS)]
                    )
                ]
            )
        )
        rebuilt = WorldStateSnapshot(**state.model_dump())
        self.assertIsInstance(rebuilt.agent_id, BrainAgentId)
        self.assertIsInstance(rebuilt.beliefs[0], WorldBelief)
        self.assertIsInstance(rebuilt.beliefs[0].status, BeliefStatus)
        self.assertIsInstance(rebuilt.beliefs[0].proposition, WorldProposition)
        self.assertIsInstance(rebuilt.beliefs[0].revisions[0].status, BeliefStatus)
        self.assertEqual(rebuilt.model_dump(), state.model_dump())

    def test_world_state_capability_is_exported_from_brain_package(self) -> None:
        self._require_capability()
        import brain.world_state as world_state

        public_names = [
            "BeliefStatus",
            "WorldBelief",
            "WorldProposition",
            "WorldStateRequest",
            "WorldStateSnapshot",
            "build_world_state",
        ]
        for name in public_names:
            with self.subTest(name=name):
                self.assertIn(name, brain.__all__)
                self.assertTrue(hasattr(brain, name))
                self.assertIs(getattr(brain, name), getattr(world_state, name))


if __name__ == "__main__":
    unittest.main()
