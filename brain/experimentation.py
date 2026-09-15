"""Semantic experiment-design intelligence for the five-ASI Brain.

This module converts canonical counterfactual disagreement into explicit,
falsifiable experiment protocols. It deliberately designs experiments without
executing them: there is no provider, tool, runtime, persistence, sampling,
probability, or observed-evidence authority here.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.counterfactual import (
    CounterfactualComparison,
    CounterfactualComparisonRequest,
    CounterfactualPrediction,
    CounterfactualScenario,
    compare_counterfactuals,
)
from schemas.base import BaseModel, Field, ValidationError


class ExperimentArmKind(str, Enum):
    CONTROL = "CONTROL"
    INTERVENTION = "INTERVENTION"


class ExperimentDesignDisposition(str, Enum):
    READY = "READY"
    NO_DISCRIMINATING_OUTCOME = "NO_DISCRIMINATING_OUTCOME"


E = TypeVar("E", bound=Enum)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return _required_text(value, field_name)


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
        if item in seen:
            raise ValidationError(f"duplicate {field_name} value: {item}")
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


def _canonical_comparison_request(raw: object) -> CounterfactualComparisonRequest:
    data = _payload(raw, CounterfactualComparisonRequest, "comparison_request")
    return CounterfactualComparisonRequest(**data)


class ExperimentArm(BaseModel):
    """One semantic arm of an experiment protocol."""

    arm_id: str
    kind: ExperimentArmKind
    source_snapshot_id: str
    scenario_id: Optional[str] = None
    intervention_ids: List[str] = Field(default_factory=list)
    prediction_id: Optional[str] = None
    predicted_value: Optional[str] = None
    falsification_conditions: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.arm_id = _required_text(self.arm_id, "arm_id")
        self.kind = _enum(self.kind, ExperimentArmKind, "kind")
        self.source_snapshot_id = _required_text(
            self.source_snapshot_id, "source_snapshot_id"
        )
        self.scenario_id = _optional_text(self.scenario_id, "scenario_id")
        self.intervention_ids = _unique_text_list(
            self.intervention_ids, "intervention_ids"
        )
        self.prediction_id = _optional_text(self.prediction_id, "prediction_id")
        self.predicted_value = _optional_text(self.predicted_value, "predicted_value")
        self.falsification_conditions = _unique_text_list(
            self.falsification_conditions, "falsification_conditions"
        )

        if self.kind == ExperimentArmKind.CONTROL:
            if self.scenario_id is not None:
                raise ValidationError("control arm cannot bind a counterfactual scenario")
            if self.intervention_ids:
                raise ValidationError("control arm cannot contain interventions")
            if self.prediction_id is not None or self.predicted_value is not None:
                raise ValidationError("control arm cannot claim a counterfactual prediction")
            if self.falsification_conditions:
                raise ValidationError("control arm cannot claim counterfactual falsification")
        else:
            if self.scenario_id is None:
                raise ValidationError("intervention arm requires scenario_id")
            if not self.intervention_ids:
                raise ValidationError("intervention arm requires intervention provenance")
            if self.prediction_id is None:
                raise ValidationError("intervention arm requires prediction_id")
            if self.predicted_value is None:
                raise ValidationError("intervention arm requires predicted_value")
            if not self.falsification_conditions:
                raise ValidationError(
                    "intervention arm requires explicit falsification conditions"
                )


class ExperimentProtocol(BaseModel):
    """A semantic protocol for one differentiating counterfactual outcome."""

    protocol_id: str
    outcome_key: str
    source_snapshot_id: str
    control_arm: ExperimentArm
    intervention_arms: List[ExperimentArm] = Field(default_factory=list)
    compared_scenario_ids: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.protocol_id = _required_text(self.protocol_id, "protocol_id")
        self.outcome_key = _required_text(self.outcome_key, "outcome_key")
        self.source_snapshot_id = _required_text(
            self.source_snapshot_id, "source_snapshot_id"
        )
        self.control_arm = ExperimentArm(
            **_payload(self.control_arm, ExperimentArm, "control_arm")
        )
        if self.control_arm.kind != ExperimentArmKind.CONTROL:
            raise ValidationError("control_arm must be a CONTROL arm")
        if self.control_arm.source_snapshot_id != self.source_snapshot_id:
            raise ValidationError("control arm must bind protocol source snapshot")

        if not isinstance(self.intervention_arms, list) or len(self.intervention_arms) < 2:
            raise ValidationError(
                "intervention_arms must contain at least two discriminating alternatives"
            )
        normalized_arms: List[ExperimentArm] = []
        arm_ids = {self.control_arm.arm_id}
        scenario_ids = set()
        predicted_values = set()
        for raw in self.intervention_arms:
            arm = ExperimentArm(**_payload(raw, ExperimentArm, "intervention_arms"))
            if arm.kind != ExperimentArmKind.INTERVENTION:
                raise ValidationError("intervention_arms must contain INTERVENTION arms")
            if arm.source_snapshot_id != self.source_snapshot_id:
                raise ValidationError("all experiment arms must share one source snapshot")
            if arm.arm_id in arm_ids:
                raise ValidationError(f"duplicate experiment arm_id: {arm.arm_id}")
            arm_ids.add(arm.arm_id)
            if arm.scenario_id in scenario_ids:
                raise ValidationError(f"duplicate experiment scenario_id: {arm.scenario_id}")
            scenario_ids.add(arm.scenario_id)
            predicted_values.add(arm.predicted_value)
            normalized_arms.append(arm)
        if len(predicted_values) < 2:
            raise ValidationError(
                "experiment protocol requires differentiating predicted values"
            )
        self.intervention_arms = normalized_arms

        self.compared_scenario_ids = _unique_text_list(
            self.compared_scenario_ids, "compared_scenario_ids"
        )
        if self.compared_scenario_ids != [
            arm.scenario_id for arm in self.intervention_arms
        ]:
            raise ValidationError(
                "compared_scenario_ids must exactly match intervention arm provenance"
            )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one protocol reason")


class ExperimentDesignRequest(BaseModel):
    """Authority-bearing request to design experiments from counterfactuals."""

    design_id: str
    goal_id: str
    agent_id: BrainAgentId
    comparison_request: CounterfactualComparisonRequest

    def __post_init__(self) -> None:
        super().__post_init__()
        self.design_id = _required_text(self.design_id, "design_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.comparison_request = _canonical_comparison_request(
            self.comparison_request
        )
        if self.comparison_request.goal_id != self.goal_id:
            raise ValidationError("comparison goal_id must match experiment design goal_id")
        if self.comparison_request.agent_id != self.agent_id:
            raise ValidationError("comparison agent_id must match experiment design agent_id")
        self._semantic_snapshot = copy.deepcopy(self.model_dump())


class ExperimentDesign(BaseModel):
    """Semantic experiment design; never execution authority."""

    design_id: str
    goal_id: str
    agent_id: BrainAgentId
    source_snapshot_id: str
    disposition: ExperimentDesignDisposition
    protocols: List[ExperimentProtocol] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.design_id = _required_text(self.design_id, "design_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.source_snapshot_id = _required_text(
            self.source_snapshot_id, "source_snapshot_id"
        )
        self.disposition = _enum(
            self.disposition, ExperimentDesignDisposition, "disposition"
        )
        if not isinstance(self.protocols, list):
            raise ValidationError("protocols must be a list")
        normalized: List[ExperimentProtocol] = []
        protocol_ids = set()
        outcome_keys = set()
        for raw in self.protocols:
            protocol = ExperimentProtocol(
                **_payload(raw, ExperimentProtocol, "protocols")
            )
            if protocol.protocol_id in protocol_ids:
                raise ValidationError(
                    f"duplicate experiment protocol_id: {protocol.protocol_id}"
                )
            if protocol.outcome_key in outcome_keys:
                raise ValidationError(
                    f"duplicate experiment outcome_key: {protocol.outcome_key}"
                )
            if protocol.source_snapshot_id != self.source_snapshot_id:
                raise ValidationError("all protocols must share design source snapshot")
            protocol_ids.add(protocol.protocol_id)
            outcome_keys.add(protocol.outcome_key)
            normalized.append(protocol)
        self.protocols = normalized
        if self.disposition == ExperimentDesignDisposition.READY:
            if not self.protocols:
                raise ValidationError("READY experiment design requires protocols")
        elif self.protocols:
            raise ValidationError(
                "NO_DISCRIMINATING_OUTCOME design cannot contain protocols"
            )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one design reason")


def _canonical_request(request: ExperimentDesignRequest) -> ExperimentDesignRequest:
    if not isinstance(request, ExperimentDesignRequest):
        raise ValidationError("request must be an ExperimentDesignRequest")
    construction_snapshot = getattr(request, "_semantic_snapshot", None)
    current_snapshot = copy.deepcopy(request.model_dump())
    if construction_snapshot is None or current_snapshot != construction_snapshot:
        raise ValidationError("experiment design request changed after validation")
    return ExperimentDesignRequest(**current_snapshot)


def _scenario_by_id(
    request: CounterfactualComparisonRequest,
) -> dict[str, CounterfactualScenario]:
    return {scenario.scenario_id: scenario for scenario in request.scenarios}


def _prediction_for_view(
    scenario: CounterfactualScenario,
    *,
    prediction_id: str,
    outcome_key: str,
) -> CounterfactualPrediction:
    matches = [
        prediction
        for prediction in scenario.predictions
        if prediction.prediction_id == prediction_id
        and prediction.outcome_key == outcome_key
    ]
    if len(matches) != 1:
        raise ValidationError(
            "counterfactual recommendation must resolve to one exact scenario prediction"
        )
    return matches[0]


def _protocol_from_recommendation(
    *,
    design_id: str,
    comparison: CounterfactualComparison,
    comparison_request: CounterfactualComparisonRequest,
    outcome_key: str,
    scenario_predictions: list,
) -> ExperimentProtocol:
    scenarios = _scenario_by_id(comparison_request)
    source_snapshot_id = comparison.source_snapshot_id
    intervention_arms: List[ExperimentArm] = []

    for view in scenario_predictions:
        scenario = scenarios.get(view.scenario_id)
        if scenario is None:
            raise ValidationError(
                f"experiment recommendation references unknown scenario: {view.scenario_id}"
            )
        if scenario.source_snapshot_id != source_snapshot_id:
            raise ValidationError("scenario source snapshot differs from comparison source")
        prediction = _prediction_for_view(
            scenario,
            prediction_id=view.prediction_id,
            outcome_key=outcome_key,
        )
        if prediction.predicted_value != view.predicted_value:
            raise ValidationError(
                "recommendation predicted value must match canonical scenario prediction"
            )
        intervention_ids = list(prediction.depends_on_intervention_ids)
        known_intervention_ids = {
            intervention.intervention_id for intervention in scenario.interventions
        }
        if any(item not in known_intervention_ids for item in intervention_ids):
            raise ValidationError(
                "prediction intervention provenance must resolve inside its scenario"
            )
        intervention_arms.append(
            ExperimentArm(
                arm_id=f"{design_id}:{outcome_key}:{scenario.scenario_id}",
                kind=ExperimentArmKind.INTERVENTION,
                source_snapshot_id=source_snapshot_id,
                scenario_id=scenario.scenario_id,
                intervention_ids=intervention_ids,
                prediction_id=prediction.prediction_id,
                predicted_value=prediction.predicted_value,
                falsification_conditions=[prediction.falsification_condition],
            )
        )

    return ExperimentProtocol(
        protocol_id=f"{design_id}:{outcome_key}",
        outcome_key=outcome_key,
        source_snapshot_id=source_snapshot_id,
        control_arm=ExperimentArm(
            arm_id=f"{design_id}:{outcome_key}:control",
            kind=ExperimentArmKind.CONTROL,
            source_snapshot_id=source_snapshot_id,
        ),
        intervention_arms=intervention_arms,
        compared_scenario_ids=[arm.scenario_id for arm in intervention_arms],
        reasons=[
            "control arm preserves the canonical source snapshot without hypothetical intervention",
            "intervention arms preserve exact counterfactual prediction and falsification provenance",
        ],
    )


def design_experiments(request: ExperimentDesignRequest) -> ExperimentDesign:
    """Derive falsifiable semantic experiment protocols from counterfactual disagreement."""

    request = _canonical_request(request)
    comparison = compare_counterfactuals(request.comparison_request)

    if not comparison.experiment_recommendations:
        return ExperimentDesign(
            design_id=request.design_id,
            goal_id=request.goal_id,
            agent_id=request.agent_id,
            source_snapshot_id=comparison.source_snapshot_id,
            disposition=ExperimentDesignDisposition.NO_DISCRIMINATING_OUTCOME,
            protocols=[],
            reasons=[
                "counterfactual alternatives contain no shared outcome with differentiating predictions",
                "no experiment is manufactured from common-mode predictions",
            ],
        )

    protocols = [
        _protocol_from_recommendation(
            design_id=request.design_id,
            comparison=comparison,
            comparison_request=request.comparison_request,
            outcome_key=recommendation.outcome_key,
            scenario_predictions=recommendation.scenario_predictions,
        )
        for recommendation in comparison.experiment_recommendations
    ]

    return ExperimentDesign(
        design_id=request.design_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        source_snapshot_id=comparison.source_snapshot_id,
        disposition=ExperimentDesignDisposition.READY,
        protocols=protocols,
        reasons=[
            "protocols are derived only from canonical counterfactual disagreement",
            "design remains semantic and requires a separate governed runtime boundary for any execution",
        ],
    )
