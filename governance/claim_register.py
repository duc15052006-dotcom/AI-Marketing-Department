"""Persistent Claim Register and Inter-Agent Provenance State.

Maintains the authoritative registry of all MaterialClaim records across
the 6-stage Five-Agent execution lifecycle:
CMO Initial -> Intelligence -> Strategist -> Creative -> Performance -> CMO Final.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Set
from schemas.base import BaseModel, Field
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    ClaimStatusUpgradeRecord,
    MaterialClaim,
    NumericStatus,
    SourceType,
    StatusAwareNumeric,
    SupportStatus,
)


class ClaimRegisterVersion(BaseModel):
    """Snapshot of claim register state after a specific agent stage."""
    version_id: str
    stage_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claim_count: int
    claim_ids: List[str]
    claims_snapshot: List[MaterialClaim]


class ClaimRegister:
    """Authoritative persistent registry of all claims created or modified during execution."""

    def __init__(self, register_id: str = "REGISTER-001"):
        self.register_id = register_id
        self._claims: Dict[str, MaterialClaim] = {}
        self._versions: List[ClaimRegisterVersion] = []

    def register_claim(self, claim: MaterialClaim) -> MaterialClaim:
        """Register a new material claim or update existing claim provenance."""
        self._claims[claim.claim_id] = claim
        return claim

    def get_claim(self, claim_id: str) -> Optional[MaterialClaim]:
        """Retrieve a claim by its ID."""
        return self._claims.get(claim_id)

    def get_all_claims(self) -> List[MaterialClaim]:
        """Return all registered claims in insertion order."""
        return list(self._claims.values())

    def filter_by_usage(self, allowed_usages: List[AllowedUsage]) -> List[MaterialClaim]:
        """Filter claims permitted for specific usage boundaries (e.g. for Creative consumption)."""
        return [c for c in self._claims.values() if c.allowed_usage in allowed_usages]

    def get_allowed_claims(self) -> List[MaterialClaim]:
        """Return claims that are SUPPORTED and permitted for usage."""
        return [c for c in self._claims.values() if c.support_status == SupportStatus.SUPPORTED and c.allowed_usage in (AllowedUsage.PUBLIC_CLAIM, AllowedUsage.INTERNAL_PLANNING)]

    def get_unsupported_claims(self) -> List[MaterialClaim]:
        """Return claims marked UNSUPPORTED."""
        return [c for c in self._claims.values() if c.support_status == SupportStatus.UNSUPPORTED]

    def get_unverified_claims(self) -> List[MaterialClaim]:
        """Return claims marked UNKNOWN or PARTIALLY_SUPPORTED."""
        return [c for c in self._claims.values() if c.support_status in (SupportStatus.UNKNOWN, SupportStatus.PARTIALLY_SUPPORTED)]

    def filter_by_class(self, claim_classes: List[ClaimClass]) -> List[MaterialClaim]:
        """Filter claims by epistemic class."""
        return [c for c in self._claims.values() if c.claim_class in claim_classes]

    def modify_claim(
        self,
        claim_id: str,
        new_status: SupportStatus,
        new_usage: AllowedUsage,
        reason: str,
        agent_id: str,
        upgrade_source: SourceType = SourceType.HUMAN_BUSINESS_INPUT,
        authorized_by: Optional[str] = None,
    ) -> MaterialClaim:
        """Modify status/usage of a claim with auditable upgrade record."""
        claim = self._claims.get(claim_id)
        if not claim:
            raise KeyError(f"Claim {claim_id} not found in register.")

        rec = ClaimStatusUpgradeRecord(
            previous_status=claim.support_status.value,
            new_status=new_status.value,
            upgrade_source=upgrade_source,
            upgrade_reason=reason,
            authorized_by=authorized_by or agent_id,
        )
        claim.upgrade_history.append(rec)
        claim.support_status = new_status
        claim.allowed_usage = new_usage
        return claim

    def create_snapshot(self, stage_name: str) -> ClaimRegisterVersion:
        """Create an immutable snapshot after an agent stage completes."""
        v_id = f"VER-{len(self._versions) + 1:03d}-{stage_name}"
        version = ClaimRegisterVersion(
            version_id=v_id,
            stage_name=stage_name,
            claim_count=len(self._claims),
            claim_ids=list(self._claims.keys()),
            claims_snapshot=[c.model_copy(deep=True) for c in self._claims.values()],
        )
        self._versions.append(version)
        return version

    def extract_and_register_from_stage_output(
        self,
        agent_id: str,
        output: Dict[str, Any],
        evidence_ids: Optional[List[str]] = None,
    ) -> List[MaterialClaim]:
        """Extract explicit and implicit material claims from an agent stage output."""
        extracted: List[MaterialClaim] = []
        ev_ids = evidence_ids or []

        # 1. Check for explicit claims array in output
        if "claims_created" in output and isinstance(output["claims_created"], list):
            for c_dict in output["claims_created"]:
                if isinstance(c_dict, dict) and "claim_text" in c_dict:
                    cid = c_dict.get("claim_id", f"CLM-{agent_id.upper()[:4]}-{len(self._claims) + 1:03d}")
                    c_obj = MaterialClaim(
                        claim_id=cid,
                        claim_text=c_dict["claim_text"],
                        claim_class=c_dict.get("claim_class", ClaimClass.INFERENCE),
                        source_type=c_dict.get("source_type", SourceType.AGENT_INFERENCE),
                        source_ids=c_dict.get("source_ids", ev_ids),
                        origin_agent=agent_id,
                        support_status=c_dict.get("support_status", SupportStatus.SUPPORTED),
                        allowed_usage=c_dict.get("allowed_usage", AllowedUsage.INTERNAL_PLANNING),
                    )
                    self.register_claim(c_obj)
                    extracted.append(c_obj)

        # 2. Extract domain findings
        if "validated_findings" in output and isinstance(output["validated_findings"], list):
            for idx, finding in enumerate(output["validated_findings"], 1):
                if isinstance(finding, str) and finding.strip():
                    cid = f"CLM-INTEL-FINDING-{idx:03d}"
                    c_obj = MaterialClaim(
                        claim_id=cid,
                        claim_text=finding,
                        claim_class=ClaimClass.MARKET_OBSERVATION,
                        source_type=SourceType.VERIFIED_EVIDENCE,
                        source_ids=ev_ids,
                        origin_agent=agent_id,
                        support_status=SupportStatus.SUPPORTED,
                        allowed_usage=AllowedUsage.PUBLIC_CLAIM,
                    )
                    self.register_claim(c_obj)
                    extracted.append(c_obj)

        # 3. Extract hypotheses
        if "hypotheses" in output and isinstance(output["hypotheses"], list):
            for idx, hypo in enumerate(output["hypotheses"], 1):
                if isinstance(hypo, str) and hypo.strip():
                    cid = f"CLM-HYPO-{idx:03d}"
                    c_obj = MaterialClaim(
                        claim_id=cid,
                        claim_text=hypo,
                        claim_class=ClaimClass.HYPOTHESIS,
                        source_type=SourceType.AGENT_HYPOTHESIS,
                        source_ids=ev_ids,
                        origin_agent=agent_id,
                        support_status=SupportStatus.PARTIALLY_SUPPORTED,
                        allowed_usage=AllowedUsage.HYPOTHESIS_ONLY,
                    )
                    self.register_claim(c_obj)
                    extracted.append(c_obj)

        # 4. Extract unknowns
        if "known_unknowns" in output and isinstance(output["known_unknowns"], list):
            for idx, unk in enumerate(output["known_unknowns"], 1):
                if isinstance(unk, str) and unk.strip():
                    cid = f"CLM-UNKNOWN-{idx:03d}"
                    c_obj = MaterialClaim(
                        claim_id=cid,
                        claim_text=unk,
                        claim_class=ClaimClass.UNKNOWN,
                        source_type=SourceType.UNSUPPORTED_INVENTION,
                        source_ids=[],
                        origin_agent=agent_id,
                        support_status=SupportStatus.UNKNOWN,
                        allowed_usage=AllowedUsage.INTERNAL_PLANNING,
                    )
                    self.register_claim(c_obj)
                    extracted.append(c_obj)

        return extracted

    def to_dict(self) -> Dict[str, Any]:
        """Serialize claim register to structured dictionary."""
        return {
            "register_id": self.register_id,
            "claims": [c.model_dump(mode="json") for c in self._claims.values()],
            "versions": [v.model_dump(mode="json") for v in self._versions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ClaimRegister:
        """Deserialize claim register from dictionary."""
        reg = cls(register_id=data.get("register_id", "REGISTER-001"))
        for c_dict in data.get("claims", []):
            claim = MaterialClaim(**c_dict)
            reg.register_claim(claim)
        for v_dict in data.get("versions", []):
            version = ClaimRegisterVersion(**v_dict)
            reg._versions.append(version)
        return reg
