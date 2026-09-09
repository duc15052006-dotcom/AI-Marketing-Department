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
from brain.learning import LearningClaimKind, LearningEpisode, LearningMethod
from brain.world_state import (
    BeliefStatus,
    WorldProposition,
    WorldStateRequest,
    WorldStateSnapshot,
    build_world_state,
)
from schemas.base import ValidationError

try:
    from brain.temporal_world_model import (
        BeliefTransition,
        CausalLink,
        CausalRelationSpec,
        TemporalCausalWorldModel,
        TemporalCausalWorldModelRequest,
        TemporalChangeKind,
        TemporalFrame,
        build_temporal_causal_world_model,
    )

    TEMPORAL_MODEL_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability does not exist yet.
    TEMPORAL_MODEL_IMPORT_ERROR = exc


class BrainTemporalCausalWorldModelV1Tests(unittest.TestCase):
    def _require_capability(self) -> None:
        if TEMPORAL_MODEL_IMPORT_ERROR is not None:
            self.fail(
                "TEMPORAL_CAUSAL_WORLD_MODEL_CAPABILITY_MISSING: "
                f"{TEMPORAL_MODEL_IMPORT_ERROR}"
            )

    def _proposition(
        self,
        proposition_id: str,
        statement: str,
        *,
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
    ) -> WorldProposition:
        return WorldProposition(
            proposition_id=proposition_id,
            goal_id=goal_id,
            agent_id=agent_id,
            statement=statement,
        )

    def _signal(
        self,
        evidence_id: str,
        claim_id: str,
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        *,
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
        claim_id: str,
        evidence,
        *,
        assessment_id: str,
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
    ) -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id=assessment_id,
            goal_id=goal_id,
            claim_id=claim_id,
            agent_id=agent_id,
            evidence=evidence,
        )

    def _states(self):
        demand = self._proposition("p-demand", "Demand is increasing")
        conversion = self._proposition("p-conversion", "Conversion rate is increasing")
        first = build_world_state(
            WorldStateRequest(
                snapshot_id="world-1",
                goal_id="goal-growth",
                agent_id=BrainAgentId.INTELLIGENCE,
                propositions=[demand, conversion],
                evidence_requests=[],
            )
        )
        second = build_world_state(
            WorldStateRequest(
                snapshot_id="world-2",
                goal_id="goal-growth",
                agent_id=BrainAgentId.INTELLIGENCE,
                propositions=[demand, conversion],
                previous_state=first,
                evidence_requests=[
                    self._evidence_request(
                        "p-demand",
                        [self._signal("e-demand", "p-demand")],
                        assessment_id="a-demand",
                    ),
                    self._evidence_request(
                        "p-conversion",
                        [self._signal("e-conversion", "p-conversion")],
                        assessment_id="a-conversion",
                    ),
                ],
            )
        )
        return first, second

    def _frames(self):
        self._require_capability()
        first, second = self._states()
        return [
            TemporalFrame(frame_id="frame-1", position=1, state=first),
            TemporalFrame(frame_id="frame-2", position=2, state=second),
        ]

    def _causal_episode(
        self,
        *,
        claim_kind: LearningClaimKind = LearningClaimKind.CAUSAL,
        method: LearningMethod = LearningMethod.EXPERIMENT,
        context_refs=None,
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.INTELLIGENCE,
    ) -> LearningEpisode:
        hypothesis_id = "h-demand-causes-conversion"
        intervention_id = "intervention-demand" if method == LearningMethod.EXPERIMENT else None
        control_ref = "control-demand" if method == LearningMethod.EXPERIMENT else None
        return LearningEpisode(
            episode_id="episode-causal-1",
            goal_id=goal_id,
            agent_id=agent_id,
            hypothesis_id=hypothesis_id,
            claim_kind=claim_kind,
            method=method,
            hypothesis="Increasing qualified demand causes conversion rate to increase",
            prediction="Conversion rate increases under the intervention relative to control",
            evidence_request=self._evidence_request(
                hypothesis_id,
                [self._signal("e-causal", hypothesis_id)],
                assessment_id="a-causal",
                goal_id=goal_id,
                agent_id=agent_id,
            ),
            intervention_id=intervention_id,
            control_ref=control_ref,
            context_refs=(
                context_refs
                if context_refs is not None
                else ["p-demand", "p-conversion"]
            ),
        )

    def _causal_spec(self, **episode_kwargs):
        self._require_capability()
        return CausalRelationSpec(
            causal_link_id="cause-1",
            cause_proposition_id="p-demand",
            effect_proposition_id="p-conversion",
            learning_episode=self._causal_episode(**episode_kwargs),
        )

    def _request(self, *, frames=None, causal_specs=None):
        self._require_capability()
        return TemporalCausalWorldModelRequest(
            model_id="temporal-model-1",
            goal_id="goal-growth",
            agent_id=BrainAgentId.INTELLIGENCE,
            frames=frames if frames is not None else self._frames(),
            causal_specs=causal_specs if causal_specs is not None else [],
        )

    def test_two_snapshot_chain_derives_temporal_transitions(self) -> None:
        model = build_temporal_causal_world_model(self._request())
        by_id = {item.proposition_id: item for item in model.transitions}
        self.assertEqual(by_id["p-demand"].from_status, BeliefStatus.UNKNOWN)
        self.assertEqual(by_id["p-demand"].to_status, BeliefStatus.ESTABLISHED)
        self.assertEqual(
            by_id["p-demand"].change_kind,
            TemporalChangeKind.ESTABLISHED,
        )
        self.assertEqual(by_id["p-demand"].new_supporting_evidence_refs, ["e-demand"])

    def test_temporal_cochange_never_manufactures_causal_links(self) -> None:
        model = build_temporal_causal_world_model(self._request())
        changed = [
            item for item in model.transitions
            if item.change_kind != TemporalChangeKind.STABLE
        ]
        self.assertGreaterEqual(len(changed), 2)
        self.assertEqual(model.causal_links, [])

    def test_controlled_causal_learning_can_authorize_explicit_link(self) -> None:
        model = build_temporal_causal_world_model(
            self._request(causal_specs=[self._causal_spec()])
        )
        self.assertEqual(len(model.causal_links), 1)
        link = model.causal_links[0]
        self.assertEqual(link.cause_proposition_id, "p-demand")
        self.assertEqual(link.effect_proposition_id, "p-conversion")
        self.assertEqual(link.hypothesis_id, "h-demand-causes-conversion")
        self.assertEqual(link.evidence_refs, ["e-causal"])
        self.assertEqual(link.intervention_id, "intervention-demand")
        self.assertEqual(link.control_ref, "control-demand")

    def test_observational_support_cannot_become_causal_link(self) -> None:
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(
                self._request(
                    causal_specs=[
                        self._causal_spec(method=LearningMethod.OBSERVATION)
                    ]
                )
            )

    def test_noncausal_learning_candidate_cannot_become_causal_link(self) -> None:
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(
                self._request(
                    causal_specs=[
                        self._causal_spec(claim_kind=LearningClaimKind.FACTUAL)
                    ]
                )
            )

    def test_causal_link_requires_explicit_context_binding(self) -> None:
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(
                self._request(
                    causal_specs=[
                        self._causal_spec(context_refs=["p-demand"])
                    ]
                )
            )

    def test_causal_link_endpoints_must_exist_in_latest_world_state(self) -> None:
        spec = self._causal_spec()
        spec.effect_proposition_id = "p-missing"
        request = self._request(causal_specs=[spec])
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(request)

    def test_frames_must_form_exact_world_state_lineage(self) -> None:
        first, second = self._states()
        second.previous_snapshot_id = "world-foreign"
        with self.assertRaises(ValidationError):
            TemporalCausalWorldModelRequest(
                model_id="temporal-model-1",
                goal_id="goal-growth",
                agent_id=BrainAgentId.INTELLIGENCE,
                frames=[
                    TemporalFrame(frame_id="frame-1", position=1, state=first),
                    TemporalFrame(frame_id="frame-2", position=2, state=second),
                ],
                causal_specs=[],
            )

    def test_frame_positions_are_strict_and_unique(self) -> None:
        first, second = self._states()
        with self.assertRaises(ValidationError):
            TemporalCausalWorldModelRequest(
                model_id="temporal-model-1",
                goal_id="goal-growth",
                agent_id=BrainAgentId.INTELLIGENCE,
                frames=[
                    TemporalFrame(frame_id="frame-1", position=2, state=first),
                    TemporalFrame(frame_id="frame-2", position=2, state=second),
                ],
                causal_specs=[],
            )

    def test_cross_goal_or_agent_frame_is_rejected(self) -> None:
        frames = self._frames()
        frames[1].state.goal_id = "goal-other"
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(self._request(frames=frames))

        frames = self._frames()
        frames[1].state.agent_id = BrainAgentId.CREATIVE
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(self._request(frames=frames))

    def test_duplicate_causal_identity_or_hypothesis_fails_closed(self) -> None:
        first = self._causal_spec()
        second = self._causal_spec()
        second.causal_link_id = "cause-2"
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(
                self._request(causal_specs=[first, second])
            )

    def test_post_construction_semantic_mutation_fails_closed(self) -> None:
        request = self._request(causal_specs=[self._causal_spec()])
        request.frames[1].position = 99
        with self.assertRaises(ValidationError):
            build_temporal_causal_world_model(request)

    def test_result_does_not_alias_caller_owned_inputs(self) -> None:
        request = self._request(causal_specs=[self._causal_spec()])
        model = build_temporal_causal_world_model(request)
        request.frames[1].state.beliefs[0].proposition.statement = "tampered"
        request.causal_specs[0].learning_episode.context_refs.clear()
        self.assertEqual(
            model.frames[1].state.beliefs[0].proposition.statement,
            "Demand is increasing",
        )
        self.assertEqual(model.causal_links[0].cause_proposition_id, "p-demand")

    def test_serialized_model_reconstructs_canonical_runtime_types(self) -> None:
        model = build_temporal_causal_world_model(
            self._request(causal_specs=[self._causal_spec()])
        )
        rebuilt = TemporalCausalWorldModel(**model.model_dump())
        self.assertIsInstance(rebuilt.agent_id, BrainAgentId)
        self.assertIsInstance(rebuilt.frames[0], TemporalFrame)
        self.assertIsInstance(rebuilt.frames[0].state, WorldStateSnapshot)
        self.assertIsInstance(rebuilt.transitions[0], BeliefTransition)
        self.assertIsInstance(rebuilt.causal_links[0], CausalLink)
        self.assertEqual(rebuilt.model_dump(), model.model_dump())

    def test_temporal_world_model_is_exported_from_brain_package(self) -> None:
        self._require_capability()
        import brain.temporal_world_model as temporal_world_model

        public_names = [
            "BeliefTransition",
            "CausalLink",
            "CausalRelationSpec",
            "TemporalCausalWorldModel",
            "TemporalCausalWorldModelRequest",
            "TemporalChangeKind",
            "TemporalFrame",
            "build_temporal_causal_world_model",
        ]
        for name in public_names:
            with self.subTest(name=name):
                self.assertIn(name, brain.__all__)
                self.assertTrue(hasattr(brain, name))
                self.assertIs(
                    getattr(brain, name),
                    getattr(temporal_world_model, name),
                )


if __name__ == "__main__":
    unittest.main()
