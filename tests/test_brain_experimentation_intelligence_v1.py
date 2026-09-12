from __future__ import annotations

import ast
from pathlib import Path
import unittest

import brain
from brain.contracts import BrainAgentId
from brain.counterfactual import (
    CounterfactualComparisonRequest,
    CounterfactualIntervention,
    CounterfactualPrediction,
    CounterfactualScenario,
    CounterfactualScenarioRequest,
    simulate_counterfactual,
)
from brain.evidence import (
    ClaimEvidenceRequest,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.world_state import WorldProposition, WorldStateRequest, build_world_state
from schemas.base import ValidationError

try:
    from brain.experimentation import (
        ExperimentArm,
        ExperimentArmKind,
        ExperimentDesign,
        ExperimentDesignDisposition,
        ExperimentDesignRequest,
        ExperimentProtocol,
        design_experiments,
    )

    EXPERIMENTATION_IMPORT_ERROR = None
except Exception as exc:  # RED sentinel: capability intentionally absent first.
    EXPERIMENTATION_IMPORT_ERROR = exc


class BrainExperimentationIntelligenceV1Tests(unittest.TestCase):
    def _require_capability(self) -> None:
        if EXPERIMENTATION_IMPORT_ERROR is not None:
            self.fail(
                "EXPERIMENTATION_INTELLIGENCE_CAPABILITY_MISSING: "
                f"{EXPERIMENTATION_IMPORT_ERROR}"
            )

    def _source_state(self):
        proposition = WorldProposition(
            proposition_id="p-offer-strength",
            goal_id="goal-growth",
            agent_id=BrainAgentId.CONTENT,
            statement="The current offer strength is sufficient",
        )
        evidence = EvidenceSignal(
            evidence_id="e-offer-baseline",
            goal_id="goal-growth",
            claim_id="p-offer-strength",
            source_id="analytics-baseline",
            relation=EvidenceRelation.SUPPORTS,
            strength=EvidenceStrength.STRONG,
            origin=EvidenceOrigin.OBSERVED,
        )
        return build_world_state(
            WorldStateRequest(
                snapshot_id="world-baseline",
                goal_id="goal-growth",
                agent_id=BrainAgentId.CONTENT,
                propositions=[proposition],
                evidence_requests=[
                    ClaimEvidenceRequest(
                        assessment_id="a-offer-baseline",
                        goal_id="goal-growth",
                        claim_id="p-offer-strength",
                        agent_id=BrainAgentId.CONTENT,
                        evidence=[evidence],
                    )
                ],
            )
        )

    def _scenario(
        self,
        *,
        scenario_id: str,
        intervention_id: str,
        predicted_conversion: str,
        predicted_revenue: str = "UNCHANGED",
        rationale_suffix: str = "",
    ) -> CounterfactualScenario:
        source = self._source_state()
        return simulate_counterfactual(
            CounterfactualScenarioRequest(
                scenario_id=scenario_id,
                goal_id="goal-growth",
                agent_id=BrainAgentId.CONTENT,
                source_state=source,
                interventions=[
                    CounterfactualIntervention(
                        intervention_id=intervention_id,
                        proposition_id="p-offer-strength",
                        assumed_status="REFUTED",
                        rationale=f"Test alternative offer treatment {rationale_suffix}".strip(),
                    )
                ],
                predictions=[
                    CounterfactualPrediction(
                        prediction_id=f"pred-conversion-{scenario_id}",
                        outcome_key="conversion_rate",
                        predicted_value=predicted_conversion,
                        depends_on_intervention_ids=[intervention_id],
                        rationale=f"Scenario predicts conversion {rationale_suffix}".strip(),
                        falsification_condition=(
                            f"conversion_rate does not match {predicted_conversion}"
                        ),
                    ),
                    CounterfactualPrediction(
                        prediction_id=f"pred-revenue-{scenario_id}",
                        outcome_key="revenue_per_visitor",
                        predicted_value=predicted_revenue,
                        depends_on_intervention_ids=[intervention_id],
                        rationale=f"Scenario predicts revenue {rationale_suffix}".strip(),
                        falsification_condition=(
                            f"revenue_per_visitor does not match {predicted_revenue}"
                        ),
                    ),
                ],
            )
        )

    def _comparison_request(
        self,
        *,
        second_conversion: str = "DOWN",
        second_revenue: str = "UNCHANGED",
    ) -> CounterfactualComparisonRequest:
        return CounterfactualComparisonRequest(
            comparison_id="comparison-1",
            goal_id="goal-growth",
            agent_id=BrainAgentId.CONTENT,
            scenarios=[
                self._scenario(
                    scenario_id="scenario-a",
                    intervention_id="intervention-a",
                    predicted_conversion="UP",
                    predicted_revenue="UNCHANGED",
                    rationale_suffix="A",
                ),
                self._scenario(
                    scenario_id="scenario-b",
                    intervention_id="intervention-b",
                    predicted_conversion=second_conversion,
                    predicted_revenue=second_revenue,
                    rationale_suffix="B",
                ),
            ],
        )

    def _request(self, *, comparison_request=None):
        self._require_capability()
        return ExperimentDesignRequest(
            design_id="experiment-design-1",
            goal_id="goal-growth",
            agent_id=BrainAgentId.CONTENT,
            comparison_request=(
                comparison_request
                if comparison_request is not None
                else self._comparison_request()
            ),
        )

    def test_differentiating_counterfactuals_create_ready_protocol(self) -> None:
        design = design_experiments(self._request())
        self.assertEqual(design.disposition, ExperimentDesignDisposition.READY)
        self.assertEqual(len(design.protocols), 1)
        protocol = design.protocols[0]
        self.assertEqual(protocol.outcome_key, "conversion_rate")
        self.assertEqual(protocol.source_snapshot_id, "world-baseline")
        self.assertEqual(len(protocol.intervention_arms), 2)

    def test_protocol_has_explicit_canonical_control_arm(self) -> None:
        design = design_experiments(self._request())
        control = design.protocols[0].control_arm
        self.assertEqual(control.kind, ExperimentArmKind.CONTROL)
        self.assertEqual(control.source_snapshot_id, "world-baseline")
        self.assertIsNone(control.scenario_id)
        self.assertEqual(control.intervention_ids, [])
        self.assertIsNone(control.predicted_value)
        self.assertEqual(control.falsification_conditions, [])

    def test_intervention_arms_preserve_exact_counterfactual_provenance(self) -> None:
        design = design_experiments(self._request())
        by_scenario = {
            arm.scenario_id: arm for arm in design.protocols[0].intervention_arms
        }
        self.assertEqual(by_scenario["scenario-a"].intervention_ids, ["intervention-a"])
        self.assertEqual(by_scenario["scenario-a"].predicted_value, "UP")
        self.assertEqual(
            by_scenario["scenario-a"].prediction_id,
            "pred-conversion-scenario-a",
        )
        self.assertEqual(
            by_scenario["scenario-a"].falsification_conditions,
            ["conversion_rate does not match UP"],
        )
        self.assertEqual(by_scenario["scenario-b"].intervention_ids, ["intervention-b"])
        self.assertEqual(by_scenario["scenario-b"].predicted_value, "DOWN")

    def test_common_mode_predictions_do_not_manufacture_experiment(self) -> None:
        design = design_experiments(
            self._request(
                comparison_request=self._comparison_request(second_conversion="UP")
            )
        )
        self.assertEqual(
            design.disposition,
            ExperimentDesignDisposition.NO_DISCRIMINATING_OUTCOME,
        )
        self.assertEqual(design.protocols, [])

    def test_multiple_discriminating_outcomes_create_separate_protocols(self) -> None:
        design = design_experiments(
            self._request(
                comparison_request=self._comparison_request(
                    second_conversion="DOWN",
                    second_revenue="DOWN",
                )
            )
        )
        self.assertEqual(design.disposition, ExperimentDesignDisposition.READY)
        self.assertEqual(
            [protocol.outcome_key for protocol in design.protocols],
            ["conversion_rate", "revenue_per_visitor"],
        )
        self.assertEqual(len({p.protocol_id for p in design.protocols}), 2)

    def test_protocol_does_not_invent_probability_or_observed_evidence(self) -> None:
        design = design_experiments(self._request())
        payload = design.model_dump()
        forbidden_keys = {
            "confidence",
            "probability",
            "sample_size",
            "p_value",
            "observed_evidence",
            "evidence_refs",
            "provider",
            "tool",
            "endpoint",
        }

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(key, forbidden_keys)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)

    def test_post_construction_prediction_mutation_fails_closed(self) -> None:
        request = self._request()
        request.comparison_request.scenarios[0].predictions[0].predicted_value = "FORGED"
        with self.assertRaises(ValidationError):
            design_experiments(request)

    def test_post_construction_intervention_injection_fails_closed(self) -> None:
        request = self._request()
        request.comparison_request.scenarios[0].interventions[0].intervention_id = "forged"
        with self.assertRaises(ValidationError):
            design_experiments(request)

    def test_post_construction_scope_mutation_fails_closed(self) -> None:
        request = self._request()
        request.comparison_request.goal_id = "goal-foreign"
        with self.assertRaises(ValidationError):
            design_experiments(request)

    def test_result_does_not_alias_caller_owned_inputs(self) -> None:
        request = self._request()
        design = design_experiments(request)
        request.comparison_request.scenarios[0].interventions[0].intervention_id = "tampered"
        request.comparison_request.scenarios[0].predictions[0].predicted_value = "tampered"
        first_arm = design.protocols[0].intervention_arms[0]
        self.assertEqual(first_arm.intervention_ids, ["intervention-a"])
        self.assertEqual(first_arm.predicted_value, "UP")

    def test_serialized_design_reconstructs_canonical_runtime_types(self) -> None:
        design = design_experiments(self._request())
        rebuilt = ExperimentDesign(**design.model_dump())
        self.assertIsInstance(rebuilt.agent_id, BrainAgentId)
        self.assertIsInstance(rebuilt.disposition, ExperimentDesignDisposition)
        self.assertIsInstance(rebuilt.protocols[0], ExperimentProtocol)
        self.assertIsInstance(rebuilt.protocols[0].control_arm, ExperimentArm)
        self.assertIsInstance(
            rebuilt.protocols[0].intervention_arms[0],
            ExperimentArm,
        )
        self.assertEqual(rebuilt.model_dump(), design.model_dump())

    def test_experimentation_module_is_semantic_only(self) -> None:
        self._require_capability()
        source = Path(__file__).resolve().parents[1] / "brain" / "experimentation.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "providers",
            "memory",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden_roots)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], forbidden_roots)

    def test_experimentation_api_is_exported_from_brain_package(self) -> None:
        self._require_capability()
        import brain.experimentation as experimentation

        public_names = [
            "ExperimentArm",
            "ExperimentArmKind",
            "ExperimentDesign",
            "ExperimentDesignDisposition",
            "ExperimentDesignRequest",
            "ExperimentProtocol",
            "design_experiments",
        ]
        for name in public_names:
            with self.subTest(name=name):
                self.assertIn(name, brain.__all__)
                self.assertTrue(hasattr(brain, name))
                self.assertIs(getattr(brain, name), getattr(experimentation, name))


if __name__ == "__main__":
    unittest.main()
