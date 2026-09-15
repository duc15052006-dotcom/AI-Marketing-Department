from __future__ import annotations

import unittest

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
from schemas.base import ValidationError


class BrainEvidenceUseBoundaryRevalidationV2Tests(unittest.TestCase):
    @staticmethod
    def _request() -> ClaimEvidenceRequest:
        return ClaimEvidenceRequest(
            assessment_id="EA-BOUNDARY",
            goal_id="G-BOUNDARY",
            claim_id="C-BOUNDARY",
            agent_id=BrainAgentId.INTELLIGENCE,
            evidence=[
                EvidenceSignal(
                    evidence_id="E-BOUNDARY",
                    goal_id="G-BOUNDARY",
                    claim_id="C-BOUNDARY",
                    source_id="SRC-VALID",
                    relation=EvidenceRelation.SUPPORTS,
                    strength=EvidenceStrength.STRONG,
                    origin=EvidenceOrigin.OBSERVED,
                )
            ],
        )

    def test_valid_supported_evidence_remains_supported(self) -> None:
        self.assertEqual(
            assess_claim_evidence(self._request()).verdict,
            ClaimVerdict.SUPPORTED,
        )

    def test_post_validation_empty_source_mutation_is_rejected(self) -> None:
        request = self._request()
        request.evidence[0].source_id = ""
        with self.assertRaises(ValidationError):
            assess_claim_evidence(request)

    def test_post_validation_invalid_enum_mutation_is_rejected(self) -> None:
        request = self._request()
        request.evidence[0].origin = "FORGED"  # type: ignore[assignment]
        with self.assertRaises(ValidationError):
            assess_claim_evidence(request)

    def test_post_validation_binding_mutation_cannot_gain_authority(self) -> None:
        request = self._request()
        request.evidence[0].goal_id = ""
        with self.assertRaises(ValidationError):
            assess_claim_evidence(request)


if __name__ == "__main__":
    unittest.main()
