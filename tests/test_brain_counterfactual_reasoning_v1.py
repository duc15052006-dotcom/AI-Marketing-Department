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
from brain.world_state import BeliefStatus, WorldProposition, WorldStateRequest, build_world_state
from schemas.base import ValidationError

try:
    from brain.counterfactual import (
        CounterfactualComparisonRequest,
        CounterfactualEpistemicStatus,
        CounterfactualIntervention,
        CounterfactualPrediction,
        CounterfactualScenario,
        CounterfactualScenarioRequest,
        compare_counterfactuals,
        simulate_counterfactual,
    )

    COUNTERFACTUAL_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability does not exist yet.
    COUNTERFACTUAL_IMPORT_ERROR = exc


class BrainCounterfactualReasoningV1Tests(unittest.TestCase):
    def _require_capability(self) -> None:
        if COUNTERFACTUAL_IMPORT_ERROR is not None:
            self.fail(
                "COUNTERFACTUAL_REASONING_CAPABILITY_MISSING: "
                f"{COUNTERFACTUAL_IMPORT_ERROR}"
            )

    def _source_state(
        self,
        *,
        snapshot_id: str = "world-1",
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.STRATEGIST,
        status: BeliefStatus = BeliefStatus.ESTABLISHED,
    ):
        proposition = WorldProposition(
            proposition_id="claim-price-bottleneck",
            goal_id=goal_id,
            agent_id=agent_id,
            statement="Price is the primary conversion bottleneck",
        )
        evidence = []
        if status == BeliefStatus.ESTABLISHED:
            evidence = [
                EvidenceSignal(
                    evidence_id="e-price-support",
                    goal_id=goal_id,
                    claim_id=proposition.proposition_id,
                    source_id="experiment-price",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ]
        elif status == BeliefStatus.REFUTED:
            evidence = [
                EvidenceSignal(
                    evidence_id="e-price-refute",
                    goal_id=goal_id,
                    claim_id=proposition.proposition_id,
                    source_id="experiment-price",
                    relation=EvidenceRelation.CONTRADICTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ]

        requests = []
        if evidence:
            requests = [
                ClaimEvidenceRequest(
                    assessment_id="assessment-price",
                    goal_id=goal_id,
                    claim_id=proposition.proposition_id,
                    agent_id=agent_id,
                    evidence=evidence,
                )
            ]
        return build_world_state(
            WorldStateRequest(
                snapshot_id=snapshot_id,
                goal_id=goal_id,
                agent_id=agent_id,
                propositions=[proposition],
                evidence_requests=requests,
            )
        )

    def _intervention(
        self,
        *,
        intervention_id: str = "intervention-price-not-bottleneck",
        proposition_id: str = "claim-price-bottleneck",
        assumed_status: BeliefStatus = BeliefStatus.REFUTED,
    ):
        self._require_capability()
        return CounterfactualIntervention(
            intervention_id=intervention_id,
            proposition_id=proposition_id,
            assumed_status=assumed_status,
            rationale="Test the world in which price is not the primary bottleneck",
        )

    def _prediction(
        self,
        *,
        prediction_id: str = "prediction-cvr",
        outcome_key: str = "conversion_response_to_price_change",
        predicted_value: str = "limited improvement",
        depends_on_intervention_ids=None,
    ):
        self._require_capability()
        return CounterfactualPrediction(
            prediction_id=prediction_id,
            outcome_key=outcome_key,
            predicted_value=predicted_value,
            depends_on_intervention_ids=depends_on_intervention_ids
            or ["intervention-price-not-bottleneck"],
            rationale="If price is not causal, reducing it should not materially lift conversion",
            falsification_condition="A controlled price change materially lifts conversion",
        )

    def _request(
        self,
        *,
        scenario_id: str = "scenario-price-counterfactual",
        goal_id: str = "goal-growth",
        agent_id: BrainAgentId = BrainAgentId.STRATEGIST,
        source_state=None,
        interventions=None,
        predictions=None,
    ):
        self._require_capability()
        return CounterfactualScenarioRequest(
            scenario_id=scenario_id,
            goal_id=goal_id,
            agent_id=agent_id,
            source_state=source_state or self._source_state(goal_id=goal_id, agent_id=agent_id),
            interventions=interventions or [self._intervention()],
            predictions=predictions or [self._prediction()],
        )

    def test_simulation_is_hypothetical_and_predictions_are_predicted(self) -> None:
        self._require_capability()
        scenario = simulate_counterfactual(self._request())
        self.assertEqual(scenario.epistemic_status, CounterfactualEpistemicStatus.HYPOTHETICAL)
        self.assertEqual(
            scenario.predictions[0].epistemic_status,
            CounterfactualEpistemicStatus.PREDICTED,
        )
        self.assertEqual(scenario.source_snapshot_id, "world-1")

    def test_counterfactual_epistemic_enum_has_no_observed_state(self) -> None:
        self._require_capability()
        self.assertNotIn("OBSERVED", {item.value for item in CounterfactualEpistemicStatus})
        self.assertNotIn("ESTABLISHED", {item.value for item in CounterfactualEpistemicStatus})

    def test_simulation_does_not_mutate_or_alias_source_world_state(self) -> None:
        self._require_capability()
        source = self._source_state()
        before = source.model_dump()
        scenario = simulate_counterfactual(self._request(source_state=source))
        self.assertEqual(source.model_dump(), before)
        scenario.source_state.beliefs[0].status = BeliefStatus.REFUTED
        self.assertEqual(source.model_dump(), before)

    def test_intervention_must_target_existing_source_proposition(self) -> None:
        self._require_capability()
        with self.assertRaises(ValidationError):
            simulate_counterfactual(
                self._request(
                    interventions=[self._intervention(proposition_id="claim-unknown")]
                )
            )

    def test_intervention_must_change_the_source_belief_status(self) -> None:
        self._require_capability()
        with self.assertRaises(ValidationError):
            simulate_counterfactual(
                self._request(
                    interventions=[self._intervention(assumed_status=BeliefStatus.ESTABLISHED)]
                )
            )

    def test_duplicate_intervention_id_or_target_fails_closed(self) -> None:
        self._require_capability()
        first = self._intervention(intervention_id="i-1")
        with self.assertRaises(ValidationError):
            simulate_counterfactual(
                self._request(
                    interventions=[first, self._intervention(intervention_id="i-1")]
                )
            )
        with self.assertRaises(ValidationError):
            simulate_counterfactual(
                self._request(
                    interventions=[first, self._intervention(intervention_id="i-2")]
                )
            )

    def test_prediction_must_bind_to_known_intervention(self) -> None:
        self._require_capability()
        with self.assertRaises(ValidationError):
            simulate_counterfactual(
                self._request(
                    predictions=[
                        self._prediction(depends_on_intervention_ids=["missing-intervention"])
                    ]
                )
            )

    def test_goal_and_agent_scope_mismatch_fail_closed(self) -> None:
        self._require_capability()
        source = self._source_state()
        with self.assertRaises(ValidationError):
            simulate_counterfactual(self._request(goal_id="goal-other", source_state=source))
        with self.assertRaises(ValidationError):
            simulate_counterfactual(
                self._request(agent_id=BrainAgentId.CREATIVE, source_state=source)
            )

    def test_nested_source_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.source_state.goal_id = "goal-hijacked"
        with self.assertRaises(ValidationError):
            simulate_counterfactual(request)

    def test_nested_intervention_mutation_is_revalidated_at_use_boundary(self) -> None:
        self._require_capability()
        request = self._request()
        request.interventions[0].proposition_id = "claim-hijacked"
        with self.assertRaises(ValidationError):
            simulate_counterfactual(request)

    def test_serialized_request_reconstructs_canonical_runtime_types(self) -> None:
        self._require_capability()
        request = CounterfactualScenarioRequest(**self._request().model_dump())
        scenario = simulate_counterfactual(request)
        self.assertIsInstance(scenario, CounterfactualScenario)
        self.assertEqual(scenario.source_state.goal_id, request.goal_id)
        self.assertEqual(scenario.interventions[0].proposition_id, "claim-price-bottleneck")

    def test_comparison_recommends_experiment_for_differentiating_outcome(self) -> None:
        self._require_capability()
        source = self._source_state()
        first = simulate_counterfactual(
            self._request(
                scenario_id="scenario-a",
                source_state=source,
                predictions=[self._prediction(predicted_value="limited improvement")],
            )
        )
        second = simulate_counterfactual(
            self._request(
                scenario_id="scenario-b",
                source_state=source,
                predictions=[self._prediction(predicted_value="material improvement")],
            )
        )
        comparison = compare_counterfactuals(
            CounterfactualComparisonRequest(
                comparison_id="comparison-price",
                goal_id="goal-growth",
                agent_id=BrainAgentId.STRATEGIST,
                scenarios=[first, second],
            )
        )
        self.assertEqual(len(comparison.experiment_recommendations), 1)
        recommendation = comparison.experiment_recommendations[0]
        self.assertEqual(
            recommendation.outcome_key,
            "conversion_response_to_price_change",
        )
        self.assertEqual(
            {item.predicted_value for item in recommendation.scenario_predictions},
            {"limited improvement", "material improvement"},
        )

    def test_comparison_does_not_invent_experiment_when_predictions_agree(self) -> None:
        self._require_capability()
        source = self._source_state()
        first = simulate_counterfactual(self._request(scenario_id="scenario-a", source_state=source))
        second = simulate_counterfactual(self._request(scenario_id="scenario-b", source_state=source))
        comparison = compare_counterfactuals(
            CounterfactualComparisonRequest(
                comparison_id="comparison-price",
                goal_id="goal-growth",
                agent_id=BrainAgentId.STRATEGIST,
                scenarios=[first, second],
            )
        )
        self.assertEqual(comparison.experiment_recommendations, [])

    def test_comparison_requires_same_canonical_source_world(self) -> None:
        self._require_capability()
        first = simulate_counterfactual(self._request(scenario_id="scenario-a"))
        second = simulate_counterfactual(
            self._request(
                scenario_id="scenario-b",
                source_state=self._source_state(snapshot_id="world-2"),
            )
        )
        with self.assertRaises(ValidationError):
            compare_counterfactuals(
                CounterfactualComparisonRequest(
                    comparison_id="comparison-price",
                    goal_id="goal-growth",
                    agent_id=BrainAgentId.STRATEGIST,
                    scenarios=[first, second],
                )
            )

    def test_comparison_nested_scenario_mutation_fails_closed(self) -> None:
        self._require_capability()
        source = self._source_state()
        first = simulate_counterfactual(self._request(scenario_id="scenario-a", source_state=source))
        second = simulate_counterfactual(self._request(scenario_id="scenario-b", source_state=source))
        request = CounterfactualComparisonRequest(
            comparison_id="comparison-price",
            goal_id="goal-growth",
            agent_id=BrainAgentId.STRATEGIST,
            scenarios=[first, second],
        )
        request.scenarios[0].source_state.agent_id = BrainAgentId.CREATIVE
        with self.assertRaises(ValidationError):
            compare_counterfactuals(request)

    def test_public_brain_api_exports_counterfactual_capability(self) -> None:
        self._require_capability()
        expected = {
            "CounterfactualComparisonRequest",
            "CounterfactualEpistemicStatus",
            "CounterfactualExperimentRecommendation",
            "CounterfactualIntervention",
            "CounterfactualPrediction",
            "CounterfactualScenario",
            "CounterfactualScenarioRequest",
            "ScenarioPredictionView",
            "compare_counterfactuals",
            "simulate_counterfactual",
        }
        self.assertTrue(expected.issubset(set(brain.__all__)))
        for name in expected:
            self.assertTrue(hasattr(brain, name), name)


if __name__ == "__main__":
    unittest.main()
