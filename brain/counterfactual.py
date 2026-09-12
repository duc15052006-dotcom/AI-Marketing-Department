"""Provenance-safe counterfactual reasoning for the five-ASI Brain.

Counterfactuals are simulations, not observations. This module starts from one
canonical ``WorldStateSnapshot``, applies explicit hypothetical interventions,
records predicted consequences, and compares alternative scenarios to identify
outcomes worth testing. It never creates evidence, revises the canonical world
state, estimates probabilities, or selects concrete runtime tools/providers.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.world_state import BeliefStatus, WorldBelief, WorldStateSnapshot
from schemas.base import BaseModel, Field, ValidationError


class CounterfactualEpistemicStatus(str, Enum):
    """Simulation-only epistemic states; deliberately excludes OBSERVED/fact states."""

    HYPOTHETICAL = "HYPOTHETICAL"
    PREDICTED = "PREDICTED"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _enum(value: object, enum_cls: Type[E], field_name: str) -> E:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().upper())
        except ValueError:
            pass
    raise ValidationError(
        f"{field_name} must be one of: {', '.join(member.value for member in enum_cls)}"
    )


def _unique_text_list(value: object, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list of strings")
    result: List[str] = []
    seen = set()
    for raw in value:
        item = _required_text(raw, field_name)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _payload(raw: object, expected_type: type, field_name: str) -> dict:
    if isinstance(raw, expected_type):
        return copy.deepcopy(raw.model_dump())
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    raise ValidationError(
        f"{field_name} must contain only {expected_type.__name__} items or serialized mappings"
    )


def _canonical_world_state(raw: object) -> WorldStateSnapshot:
    return WorldStateSnapshot(**_payload(raw, WorldStateSnapshot, "source_state"))


def _belief_by_id(source_state: WorldStateSnapshot) -> dict[str, WorldBelief]:
    return {
        belief.proposition.proposition_id: belief
        for belief in source_state.beliefs
    }


class CounterfactualIntervention(BaseModel):
    """One explicit hypothetical override of a canonical source belief."""

    intervention_id: str
    proposition_id: str
    assumed_status: BeliefStatus
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.intervention_id = _required_text(self.intervention_id, "intervention_id")
        self.proposition_id = _required_text(self.proposition_id, "proposition_id")
        self.assumed_status = _enum(self.assumed_status, BeliefStatus, "assumed_status")
        self.rationale = _required_text(self.rationale, "rationale")


class CounterfactualPrediction(BaseModel):
    """A testable predicted consequence inside a hypothetical scenario."""

    prediction_id: str
    outcome_key: str
    predicted_value: str
    depends_on_intervention_ids: List[str]
    rationale: str
    falsification_condition: str
    epistemic_status: CounterfactualEpistemicStatus = CounterfactualEpistemicStatus.PREDICTED

    def __post_init__(self) -> None:
        super().__post_init__()
        self.prediction_id = _required_text(self.prediction_id, "prediction_id")
        self.outcome_key = _required_text(self.outcome_key, "outcome_key")
        self.predicted_value = _required_text(self.predicted_value, "predicted_value")
        self.depends_on_intervention_ids = _unique_text_list(
            self.depends_on_intervention_ids, "depends_on_intervention_ids"
        )
        if not self.depends_on_intervention_ids:
            raise ValidationError(
                "depends_on_intervention_ids must contain at least one intervention"
            )
        self.rationale = _required_text(self.rationale, "rationale")
        self.falsification_condition = _required_text(
            self.falsification_condition, "falsification_condition"
        )
        self.epistemic_status = _enum(
            self.epistemic_status,
            CounterfactualEpistemicStatus,
            "epistemic_status",
        )
        if self.epistemic_status != CounterfactualEpistemicStatus.PREDICTED:
            raise ValidationError(
                "counterfactual predictions must remain PREDICTED"
            )


def _canonical_interventions(raw_items: object) -> List[CounterfactualIntervention]:
    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationError("interventions must contain at least one item")
    return [
        CounterfactualIntervention(
            **_payload(raw, CounterfactualIntervention, "interventions")
        )
        for raw in raw_items
    ]


def _canonical_predictions(raw_items: object) -> List[CounterfactualPrediction]:
    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationError("predictions must contain at least one item")
    return [
        CounterfactualPrediction(
            **_payload(raw, CounterfactualPrediction, "predictions")
        )
        for raw in raw_items
    ]


def _validate_scenario_components(
    *,
    goal_id: str,
    agent_id: BrainAgentId,
    source_state: WorldStateSnapshot,
    interventions: List[CounterfactualIntervention],
    predictions: List[CounterfactualPrediction],
) -> None:
    if source_state.goal_id != goal_id:
        raise ValidationError("source world-state goal_id must match counterfactual goal_id")
    if source_state.agent_id != agent_id:
        raise ValidationError("source world-state agent_id must match counterfactual agent_id")

    source_beliefs = _belief_by_id(source_state)
    intervention_ids = set()
    intervention_targets = set()
    for intervention in interventions:
        if intervention.intervention_id in intervention_ids:
            raise ValidationError(
                f"duplicate intervention_id: {intervention.intervention_id}"
            )
        intervention_ids.add(intervention.intervention_id)
        if intervention.proposition_id in intervention_targets:
            raise ValidationError(
                "multiple interventions cannot override the same proposition: "
                f"{intervention.proposition_id}"
            )
        intervention_targets.add(intervention.proposition_id)

        source_belief = source_beliefs.get(intervention.proposition_id)
        if source_belief is None:
            raise ValidationError(
                "intervention references unknown source proposition: "
                f"{intervention.proposition_id}"
            )
        if source_belief.status == intervention.assumed_status:
            raise ValidationError(
                "counterfactual intervention must differ from canonical source belief: "
                f"{intervention.proposition_id}"
            )

    prediction_ids = set()
    outcome_keys = set()
    for prediction in predictions:
        if prediction.prediction_id in prediction_ids:
            raise ValidationError(
                f"duplicate prediction_id: {prediction.prediction_id}"
            )
        prediction_ids.add(prediction.prediction_id)
        if prediction.outcome_key in outcome_keys:
            raise ValidationError(
                f"duplicate predicted outcome_key: {prediction.outcome_key}"
            )
        outcome_keys.add(prediction.outcome_key)
        for intervention_id in prediction.depends_on_intervention_ids:
            if intervention_id not in intervention_ids:
                raise ValidationError(
                    "prediction references unknown intervention: "
                    f"{intervention_id}"
                )


class CounterfactualScenarioRequest(BaseModel):
    """Request to construct one hypothetical world from one canonical snapshot."""

    scenario_id: str
    goal_id: str
    agent_id: BrainAgentId
    source_state: WorldStateSnapshot
    interventions: List[CounterfactualIntervention] = Field(default_factory=list)
    predictions: List[CounterfactualPrediction] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.scenario_id = _required_text(self.scenario_id, "scenario_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.source_state = _canonical_world_state(self.source_state)
        self.interventions = _canonical_interventions(self.interventions)
        self.predictions = _canonical_predictions(self.predictions)
        _validate_scenario_components(
            goal_id=self.goal_id,
            agent_id=self.agent_id,
            source_state=self.source_state,
            interventions=self.interventions,
            predictions=self.predictions,
        )


class CounterfactualScenario(BaseModel):
    """Canonical simulation output; never a canonical WorldStateSnapshot."""

    scenario_id: str
    goal_id: str
    agent_id: BrainAgentId
    source_snapshot_id: str
    source_state: WorldStateSnapshot
    interventions: List[CounterfactualIntervention] = Field(default_factory=list)
    predictions: List[CounterfactualPrediction] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    epistemic_status: CounterfactualEpistemicStatus = CounterfactualEpistemicStatus.HYPOTHETICAL

    def __post_init__(self) -> None:
        super().__post_init__()
        self.scenario_id = _required_text(self.scenario_id, "scenario_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.source_snapshot_id = _required_text(
            self.source_snapshot_id, "source_snapshot_id"
        )
        self.source_state = _canonical_world_state(self.source_state)
        if self.source_state.snapshot_id != self.source_snapshot_id:
            raise ValidationError(
                "source_snapshot_id must match canonical source world-state snapshot_id"
            )
        self.interventions = _canonical_interventions(self.interventions)
        self.predictions = _canonical_predictions(self.predictions)
        _validate_scenario_components(
            goal_id=self.goal_id,
            agent_id=self.agent_id,
            source_state=self.source_state,
            interventions=self.interventions,
            predictions=self.predictions,
        )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one scenario reason")
        self.epistemic_status = _enum(
            self.epistemic_status,
            CounterfactualEpistemicStatus,
            "epistemic_status",
        )
        if self.epistemic_status != CounterfactualEpistemicStatus.HYPOTHETICAL:
            raise ValidationError("counterfactual scenario must remain HYPOTHETICAL")


class ScenarioPredictionView(BaseModel):
    scenario_id: str
    prediction_id: str
    predicted_value: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.scenario_id = _required_text(self.scenario_id, "scenario_id")
        self.prediction_id = _required_text(self.prediction_id, "prediction_id")
        self.predicted_value = _required_text(self.predicted_value, "predicted_value")


class CounterfactualExperimentRecommendation(BaseModel):
    """Semantic recommendation for an outcome that can discriminate scenarios."""

    outcome_key: str
    scenario_predictions: List[ScenarioPredictionView] = Field(default_factory=list)
    rationale: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.outcome_key = _required_text(self.outcome_key, "outcome_key")
        if not isinstance(self.scenario_predictions, list) or len(self.scenario_predictions) < 2:
            raise ValidationError(
                "scenario_predictions must contain at least two scenario predictions"
            )
        normalized: List[ScenarioPredictionView] = []
        scenario_ids = set()
        for raw in self.scenario_predictions:
            view = ScenarioPredictionView(
                **_payload(raw, ScenarioPredictionView, "scenario_predictions")
            )
            if view.scenario_id in scenario_ids:
                raise ValidationError(
                    f"duplicate scenario prediction: {view.scenario_id}"
                )
            scenario_ids.add(view.scenario_id)
            normalized.append(view)
        self.scenario_predictions = normalized
        if len({item.predicted_value for item in self.scenario_predictions}) < 2:
            raise ValidationError(
                "experiment recommendation requires differentiating predictions"
            )
        self.rationale = _required_text(self.rationale, "rationale")


class CounterfactualComparisonRequest(BaseModel):
    comparison_id: str
    goal_id: str
    agent_id: BrainAgentId
    scenarios: List[CounterfactualScenario] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.comparison_id = _required_text(self.comparison_id, "comparison_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        if not isinstance(self.scenarios, list) or len(self.scenarios) < 2:
            raise ValidationError("scenarios must contain at least two alternatives")

        normalized: List[CounterfactualScenario] = []
        scenario_ids = set()
        source_snapshot_id = None
        source_dump = None
        for raw in self.scenarios:
            scenario = CounterfactualScenario(
                **_payload(raw, CounterfactualScenario, "scenarios")
            )
            if scenario.scenario_id in scenario_ids:
                raise ValidationError(f"duplicate scenario_id: {scenario.scenario_id}")
            scenario_ids.add(scenario.scenario_id)
            if scenario.goal_id != self.goal_id:
                raise ValidationError("scenario goal_id must match comparison goal_id")
            if scenario.agent_id != self.agent_id:
                raise ValidationError("scenario agent_id must match comparison agent_id")
            if source_snapshot_id is None:
                source_snapshot_id = scenario.source_snapshot_id
                source_dump = scenario.source_state.model_dump()
            elif scenario.source_snapshot_id != source_snapshot_id:
                raise ValidationError(
                    "counterfactual alternatives must share one source snapshot"
                )
            elif scenario.source_state.model_dump() != source_dump:
                raise ValidationError(
                    "counterfactual alternatives must share the exact canonical source world"
                )
            normalized.append(scenario)
        self.scenarios = normalized


class CounterfactualComparison(BaseModel):
    comparison_id: str
    goal_id: str
    agent_id: BrainAgentId
    source_snapshot_id: str
    experiment_recommendations: List[CounterfactualExperimentRecommendation] = Field(
        default_factory=list
    )
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.comparison_id = _required_text(self.comparison_id, "comparison_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.source_snapshot_id = _required_text(
            self.source_snapshot_id, "source_snapshot_id"
        )
        if not isinstance(self.experiment_recommendations, list):
            raise ValidationError("experiment_recommendations must be a list")
        self.experiment_recommendations = [
            CounterfactualExperimentRecommendation(
                **_payload(
                    raw,
                    CounterfactualExperimentRecommendation,
                    "experiment_recommendations",
                )
            )
            for raw in self.experiment_recommendations
        ]
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one comparison reason")


def _canonical_scenario_request(
    request: CounterfactualScenarioRequest,
) -> CounterfactualScenarioRequest:
    if not isinstance(request, CounterfactualScenarioRequest):
        raise ValidationError("request must be a CounterfactualScenarioRequest")
    return CounterfactualScenarioRequest(**copy.deepcopy(request.model_dump()))


def _canonical_comparison_request(
    request: CounterfactualComparisonRequest,
) -> CounterfactualComparisonRequest:
    if not isinstance(request, CounterfactualComparisonRequest):
        raise ValidationError("request must be a CounterfactualComparisonRequest")
    return CounterfactualComparisonRequest(**copy.deepcopy(request.model_dump()))


def simulate_counterfactual(
    request: CounterfactualScenarioRequest,
) -> CounterfactualScenario:
    """Construct one isolated hypothetical scenario from a canonical source world."""

    request = _canonical_scenario_request(request)
    return CounterfactualScenario(
        scenario_id=request.scenario_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        source_snapshot_id=request.source_state.snapshot_id,
        source_state=request.source_state,
        interventions=request.interventions,
        predictions=request.predictions,
        reasons=[
            "scenario is a simulation derived from an explicit canonical source snapshot",
            "interventions are hypothetical overrides and predictions are not observed evidence",
        ],
        epistemic_status=CounterfactualEpistemicStatus.HYPOTHETICAL,
    )


def compare_counterfactuals(
    request: CounterfactualComparisonRequest,
) -> CounterfactualComparison:
    """Identify predicted outcomes whose disagreement merits a discriminating experiment."""

    request = _canonical_comparison_request(request)
    predictions_by_outcome: dict[str, List[ScenarioPredictionView]] = {}
    for scenario in request.scenarios:
        for prediction in scenario.predictions:
            predictions_by_outcome.setdefault(prediction.outcome_key, []).append(
                ScenarioPredictionView(
                    scenario_id=scenario.scenario_id,
                    prediction_id=prediction.prediction_id,
                    predicted_value=prediction.predicted_value,
                )
            )

    recommendations: List[CounterfactualExperimentRecommendation] = []
    for outcome_key, views in predictions_by_outcome.items():
        if len(views) < 2:
            continue
        if len({view.predicted_value for view in views}) < 2:
            continue
        recommendations.append(
            CounterfactualExperimentRecommendation(
                outcome_key=outcome_key,
                scenario_predictions=views,
                rationale=(
                    "counterfactual alternatives predict different values for this outcome; "
                    "measure it experimentally before treating either prediction as observed"
                ),
            )
        )

    reasons = [
        "comparison preserves the common canonical source world and does not revise it"
    ]
    if recommendations:
        reasons.append(
            "experiment recommendations are limited to outcomes with differentiating predictions"
        )
    else:
        reasons.append(
            "no shared outcome currently contains differentiating predictions"
        )

    return CounterfactualComparison(
        comparison_id=request.comparison_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        source_snapshot_id=request.scenarios[0].source_snapshot_id,
        experiment_recommendations=recommendations,
        reasons=reasons,
    )
