"""Adversarial regression for Brain memory promotion provenance."""

from __future__ import annotations

import unittest

from brain.evidence import (
    ClaimEvidenceRequest,
    ClaimVerdict,
    EvidenceOrigin,
    EvidenceRelation,
    EvidenceSignal,
    EvidenceStrength,
)
from brain.memory_policy import (
    MemoryAuthority,
    MemoryCandidate,
    MemoryDisposition,
    MemoryKind,
    MemoryScopeLevel,
    evaluate_memory_candidate,
)
from schemas.base import ValidationError


class BrainMemoryPromotionProvenanceV1Tests(unittest.TestCase):
    @staticmethod
    def _supported_runs(count: int = 3) -> list[ClaimEvidenceRequest]:
        return [
            ClaimEvidenceRequest(
                assessment_id=f"RUN-{index}",
                goal_id="G-1",
                claim_id="C-1",
                agent_id="PERFORMANCE",
                evidence=[
                    EvidenceSignal(
                        evidence_id=f"E-RUN-{index}",
                        goal_id="G-1",
                        claim_id="C-1",
                        source_id=f"SOURCE-RUN-{index}",
                        relation=EvidenceRelation.SUPPORTS,
                        strength=EvidenceStrength.STRONG,
                        origin=EvidenceOrigin.OBSERVED,
                    )
                ],
            )
            for index in range(1, count + 1)
        ]

    @staticmethod
    def _candidate(**updates) -> MemoryCandidate:
        values = {
            "candidate_id": "MC-1",
            "goal_id": "G-1",
            "claim_id": "C-1",
            "agent_id": "PERFORMANCE",
            "memory_kind": MemoryKind.EXPERIMENT,
            "authority": MemoryAuthority.OBSERVED,
            "origin_scope": MemoryScopeLevel.CAMPAIGN,
            "requested_scope": MemoryScopeLevel.CAMPAIGN,
            "evidence_verdict": ClaimVerdict.SUPPORTED,
            "evidence_refs": ["E-RUN-1", "E-RUN-2", "E-RUN-3"],
            "independent_run_count": 3,
        }
        values.update(updates)
        return MemoryCandidate(**values)

    def test_self_attested_observation_cannot_promote_without_authoritative_provenance(self) -> None:
        """A caller must not self-certify institutional learning with summary fields alone."""

        fabricated = self._candidate(evidence_refs=["FAKE-EVIDENCE-REF-1"])
        decision = evaluate_memory_candidate(fabricated)

        self.assertNotEqual(
            decision.disposition,
            MemoryDisposition.PROMOTED,
            "caller-supplied OBSERVED/SUPPORTED/evidence refs/run count must not self-authorize durable institutional learning",
        )

    def test_three_canonical_supported_runs_can_promote(self) -> None:
        decision = evaluate_memory_candidate(
            self._candidate(run_evidence_requests=self._supported_runs())
        )
        self.assertEqual(decision.disposition, MemoryDisposition.PROMOTED)

    def test_fabricated_summary_refs_cannot_override_canonical_run_refs(self) -> None:
        with self.assertRaises(ValidationError):
            evaluate_memory_candidate(
                self._candidate(
                    evidence_refs=["FAKE-EVIDENCE-REF-1"],
                    run_evidence_requests=self._supported_runs(),
                )
            )

    def test_inflated_run_count_cannot_override_authoritative_run_count(self) -> None:
        with self.assertRaises(ValidationError):
            evaluate_memory_candidate(
                self._candidate(
                    independent_run_count=99,
                    run_evidence_requests=self._supported_runs(),
                )
            )


if __name__ == "__main__":
    unittest.main()
