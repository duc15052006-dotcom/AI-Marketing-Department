"""Evidence-authoritative belief and world-state reasoning for the Brain.

The world state is a semantic projection of canonical claim-evidence verdicts.
It does not estimate probabilities, select providers/tools, execute experiments,
or promote assumptions into facts. Contradiction and revision history remain
explicit so downstream five-ASI reasoning can distinguish knowledge from
uncertainty and refutation.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import List, Optional, Type, TypeVar

from brain.contracts import BrainAgentId
from brain.evidence import (
    ClaimEvidenceAssessment,
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceSignal,
    assess_claim_evidence,
)
from schemas.base import BaseModel, Field, ValidationError


class BeliefStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    CONTESTED = "CONTESTED"
    REFUTED = "REFUTED"
    UNKNOWN = "UNKNOWN"


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


def _canonical_evidence_request(raw: object) -> ClaimEvidenceRequest:
    data = _payload(raw, ClaimEvidenceRequest, "evidence_requests")
    raw_evidence = data.pop("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ValidationError("evidence request evidence must be a list")
    evidence: List[EvidenceSignal] = []
    for item in raw_evidence:
        evidence.append(EvidenceSignal(**_payload(item, EvidenceSignal, "evidence")))
    return ClaimEvidenceRequest(**data, evidence=evidence)


def _canonical_assessment(raw: object) -> ClaimEvidenceAssessment:
    return ClaimEvidenceAssessment(
        **_payload(raw, ClaimEvidenceAssessment, "assessment")
    )


def _status_for_verdict(verdict: ClaimVerdict) -> BeliefStatus:
    mapping = {
        ClaimVerdict.SUPPORTED: BeliefStatus.ESTABLISHED,
        ClaimVerdict.CONTESTED: BeliefStatus.CONTESTED,
        ClaimVerdict.REFUTED: BeliefStatus.REFUTED,
        ClaimVerdict.INSUFFICIENT: BeliefStatus.UNKNOWN,
    }
    return mapping[verdict]


class WorldProposition(BaseModel):
    """One stable semantic proposition tracked across world-state snapshots."""

    proposition_id: str
    goal_id: str
    agent_id: BrainAgentId
    statement: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.proposition_id = _required_text(self.proposition_id, "proposition_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.statement = _required_text(self.statement, "statement")


class BeliefRevision(BaseModel):
    """Append-only semantic history for one proposition's belief status."""

    revision_id: str
    snapshot_id: str
    status: BeliefStatus
    assessment: Optional[ClaimEvidenceAssessment] = None
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.revision_id = _required_text(self.revision_id, "revision_id")
        self.snapshot_id = _required_text(self.snapshot_id, "snapshot_id")
        self.status = _enum(self.status, BeliefStatus, "status")
        if self.assessment is not None:
            self.assessment = _canonical_assessment(self.assessment)
            expected = _status_for_verdict(self.assessment.verdict)
            if self.status != expected:
                raise ValidationError(
                    "belief revision status must match canonical evidence verdict"
                )
        elif self.status != BeliefStatus.UNKNOWN:
            raise ValidationError(
                "non-UNKNOWN belief revision requires canonical evidence assessment"
            )
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one revision reason")


class WorldBelief(BaseModel):
    """Current belief plus its immutable-by-ownership revision lineage."""

    proposition: WorldProposition
    status: BeliefStatus
    supporting_evidence_refs: List[str] = Field(default_factory=list)
    contradicting_evidence_refs: List[str] = Field(default_factory=list)
    ignored_evidence_refs: List[str] = Field(default_factory=list)
    revisions: List[BeliefRevision] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.proposition = WorldProposition(
            **_payload(self.proposition, WorldProposition, "proposition")
        )
        self.status = _enum(self.status, BeliefStatus, "status")
        self.supporting_evidence_refs = _unique_text_list(
            self.supporting_evidence_refs, "supporting_evidence_refs"
        )
        self.contradicting_evidence_refs = _unique_text_list(
            self.contradicting_evidence_refs, "contradicting_evidence_refs"
        )
        self.ignored_evidence_refs = _unique_text_list(
            self.ignored_evidence_refs, "ignored_evidence_refs"
        )
        if not isinstance(self.revisions, list) or not self.revisions:
            raise ValidationError("revisions must contain at least one belief revision")
        normalized: List[BeliefRevision] = []
        revision_ids = set()
        for raw in self.revisions:
            revision = BeliefRevision(
                **_payload(raw, BeliefRevision, "revisions")
            )
            if revision.revision_id in revision_ids:
                raise ValidationError(f"duplicate revision_id: {revision.revision_id}")
            revision_ids.add(revision.revision_id)
            normalized.append(revision)
        self.revisions = normalized

        latest = self.revisions[-1]
        if latest.status != self.status:
            raise ValidationError("belief status must match latest revision status")
        if latest.assessment is not None:
            if self.supporting_evidence_refs != latest.assessment.supporting_evidence_refs:
                raise ValidationError(
                    "supporting evidence refs must match latest canonical assessment"
                )
            if self.contradicting_evidence_refs != latest.assessment.contradicting_evidence_refs:
                raise ValidationError(
                    "contradicting evidence refs must match latest canonical assessment"
                )
            if self.ignored_evidence_refs != latest.assessment.ignored_evidence_refs:
                raise ValidationError(
                    "ignored evidence refs must match latest canonical assessment"
                )
        elif any(
            (
                self.supporting_evidence_refs,
                self.contradicting_evidence_refs,
                self.ignored_evidence_refs,
            )
        ):
            raise ValidationError(
                "unassessed UNKNOWN belief cannot claim canonical evidence references"
            )


class WorldStateSnapshot(BaseModel):
    """One scoped, provenance-preserving snapshot of semantic world beliefs."""

    snapshot_id: str
    goal_id: str
    agent_id: BrainAgentId
    previous_snapshot_id: Optional[str] = None
    beliefs: List[WorldBelief] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.snapshot_id = _required_text(self.snapshot_id, "snapshot_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")
        self.previous_snapshot_id = _optional_text(
            self.previous_snapshot_id, "previous_snapshot_id"
        )
        if not isinstance(self.beliefs, list) or not self.beliefs:
            raise ValidationError("beliefs must contain at least one WorldBelief")
        normalized: List[WorldBelief] = []
        proposition_ids = set()
        for raw in self.beliefs:
            belief = WorldBelief(**_payload(raw, WorldBelief, "beliefs"))
            proposition = belief.proposition
            if proposition.goal_id != self.goal_id:
                raise ValidationError("belief proposition goal_id must match world-state goal_id")
            if proposition.agent_id != self.agent_id:
                raise ValidationError("belief proposition agent_id must match world-state agent_id")
            if proposition.proposition_id in proposition_ids:
                raise ValidationError(
                    f"duplicate proposition belief: {proposition.proposition_id}"
                )
            proposition_ids.add(proposition.proposition_id)
            normalized.append(belief)
        self.beliefs = normalized
        self.reasons = _unique_text_list(self.reasons, "reasons")
        if not self.reasons:
            raise ValidationError("reasons must contain at least one world-state reason")


class WorldStateRequest(BaseModel):
    """Input for deriving one world-state snapshot from evidence and prior state."""

    snapshot_id: str
    goal_id: str
    agent_id: BrainAgentId
    propositions: List[WorldProposition] = Field(default_factory=list)
    evidence_requests: List[ClaimEvidenceRequest] = Field(default_factory=list)
    previous_state: Optional[WorldStateSnapshot] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.snapshot_id = _required_text(self.snapshot_id, "snapshot_id")
        self.goal_id = _required_text(self.goal_id, "goal_id")
        self.agent_id = _enum(self.agent_id, BrainAgentId, "agent_id")

        if not isinstance(self.propositions, list) or not self.propositions:
            raise ValidationError("propositions must contain at least one proposition")
        normalized_propositions: List[WorldProposition] = []
        proposition_ids = set()
        for raw in self.propositions:
            proposition = WorldProposition(
                **_payload(raw, WorldProposition, "propositions")
            )
            if proposition.goal_id != self.goal_id:
                raise ValidationError(
                    "proposition goal_id must match world-state request goal_id"
                )
            if proposition.agent_id != self.agent_id:
                raise ValidationError(
                    "proposition agent_id must match world-state request agent_id"
                )
            if proposition.proposition_id in proposition_ids:
                raise ValidationError(
                    f"duplicate proposition_id: {proposition.proposition_id}"
                )
            proposition_ids.add(proposition.proposition_id)
            normalized_propositions.append(proposition)
        self.propositions = normalized_propositions

        if not isinstance(self.evidence_requests, list):
            raise ValidationError("evidence_requests must be a list")
        normalized_requests: List[ClaimEvidenceRequest] = []
        assessed_claims = set()
        for raw in self.evidence_requests:
            evidence_request = _canonical_evidence_request(raw)
            if evidence_request.goal_id != self.goal_id:
                raise ValidationError(
                    "evidence request goal_id must match world-state request goal_id"
                )
            if evidence_request.agent_id != self.agent_id:
                raise ValidationError(
                    "evidence request agent_id must match world-state request agent_id"
                )
            if evidence_request.claim_id not in proposition_ids:
                raise ValidationError(
                    f"evidence request references unknown proposition: {evidence_request.claim_id}"
                )
            if evidence_request.claim_id in assessed_claims:
                raise ValidationError(
                    f"duplicate evidence request for proposition: {evidence_request.claim_id}"
                )
            assessed_claims.add(evidence_request.claim_id)
            normalized_requests.append(evidence_request)
        self.evidence_requests = normalized_requests

        if self.previous_state is not None:
            self.previous_state = WorldStateSnapshot(
                **_payload(self.previous_state, WorldStateSnapshot, "previous_state")
            )
            if self.previous_state.goal_id != self.goal_id:
                raise ValidationError(
                    "previous world-state goal_id must match current request goal_id"
                )
            if self.previous_state.agent_id != self.agent_id:
                raise ValidationError(
                    "previous world-state agent_id must match current request agent_id"
                )
            if self.previous_state.snapshot_id == self.snapshot_id:
                raise ValidationError("snapshot_id must advance from previous world state")

            current_by_id = {
                proposition.proposition_id: proposition
                for proposition in self.propositions
            }
            for previous_belief in self.previous_state.beliefs:
                previous_proposition = previous_belief.proposition
                current = current_by_id.get(previous_proposition.proposition_id)
                if current is None:
                    raise ValidationError(
                        "previous proposition cannot disappear from a subsequent world state: "
                        f"{previous_proposition.proposition_id}"
                    )
                if current.model_dump() != previous_proposition.model_dump():
                    raise ValidationError(
                        "existing proposition identity cannot be rebound or rewritten: "
                        f"{previous_proposition.proposition_id}"
                    )


def _canonical_request(request: WorldStateRequest) -> WorldStateRequest:
    if not isinstance(request, WorldStateRequest):
        raise ValidationError("request must be a WorldStateRequest")
    return WorldStateRequest(**copy.deepcopy(request.model_dump()))


def _copy_belief(belief: WorldBelief) -> WorldBelief:
    return WorldBelief(**copy.deepcopy(belief.model_dump()))


def build_world_state(request: WorldStateRequest) -> WorldStateSnapshot:
    """Build a defensive world-state snapshot from canonical evidence verdicts.

    No belief status is inferred independently of ``assess_claim_evidence``.
    Propositions without a new assessment either carry their prior belief
    forward or remain UNKNOWN. New assessments append a revision rather than
    rewriting history.
    """

    request = _canonical_request(request)
    previous_by_id = {}
    if request.previous_state is not None:
        previous_by_id = {
            belief.proposition.proposition_id: belief
            for belief in request.previous_state.beliefs
        }
    evidence_by_claim = {
        evidence_request.claim_id: evidence_request
        for evidence_request in request.evidence_requests
    }

    beliefs: List[WorldBelief] = []
    for proposition in request.propositions:
        previous = previous_by_id.get(proposition.proposition_id)
        evidence_request = evidence_by_claim.get(proposition.proposition_id)

        if evidence_request is None and previous is not None:
            beliefs.append(_copy_belief(previous))
            continue

        if evidence_request is None:
            revision = BeliefRevision(
                revision_id=f"{request.snapshot_id}:{proposition.proposition_id}:unknown",
                snapshot_id=request.snapshot_id,
                status=BeliefStatus.UNKNOWN,
                assessment=None,
                reasons=[
                    "no canonical evidence assessment was supplied for this proposition"
                ],
            )
            beliefs.append(
                WorldBelief(
                    proposition=proposition,
                    status=BeliefStatus.UNKNOWN,
                    supporting_evidence_refs=[],
                    contradicting_evidence_refs=[],
                    ignored_evidence_refs=[],
                    revisions=[revision],
                )
            )
            continue

        assessment = assess_claim_evidence(evidence_request)
        status = _status_for_verdict(assessment.verdict)
        revision = BeliefRevision(
            revision_id=(
                f"{request.snapshot_id}:{proposition.proposition_id}:"
                f"{assessment.assessment_id}"
            ),
            snapshot_id=request.snapshot_id,
            status=status,
            assessment=assessment,
            reasons=assessment.reasons,
        )
        revisions = []
        if previous is not None:
            revisions.extend(
                BeliefRevision(**copy.deepcopy(item.model_dump()))
                for item in previous.revisions
            )
        revisions.append(revision)
        beliefs.append(
            WorldBelief(
                proposition=proposition,
                status=status,
                supporting_evidence_refs=assessment.supporting_evidence_refs,
                contradicting_evidence_refs=assessment.contradicting_evidence_refs,
                ignored_evidence_refs=assessment.ignored_evidence_refs,
                revisions=revisions,
            )
        )

    reasons = [
        "belief status is derived only from canonical claim-evidence verdicts",
        "contradiction and prior revisions are preserved instead of overwritten",
    ]
    if request.previous_state is not None:
        reasons.append(
            "prior beliefs without new evidence are carried forward without fabricated reassessment"
        )

    return WorldStateSnapshot(
        snapshot_id=request.snapshot_id,
        goal_id=request.goal_id,
        agent_id=request.agent_id,
        previous_snapshot_id=(
            request.previous_state.snapshot_id
            if request.previous_state is not None
            else None
        ),
        beliefs=beliefs,
        reasons=reasons,
    )
