"""RED-only adversarial regression for Brain memory promotion provenance."""

from __future__ import annotations

import unittest

from brain.evidence import ClaimVerdict
from brain.memory_policy import (
    MemoryAuthority,
    MemoryCandidate,
    MemoryDisposition,
    MemoryKind,
    MemoryScopeLevel,
    evaluate_memory_candidate,
)


class BrainMemoryPromotionProvenanceV1Tests(unittest.TestCase):
    def test_self_attested_observation_cannot_promote_without_authoritative_provenance(self) -> None:
        """A caller must not self-certify institutional learning with summary fields alone."""

        fabricated = MemoryCandidate(
            candidate_id="MC-FABRICATED-1",
            goal_id="G-1",
            claim_id="C-FABRICATED-1",
            agent_id="PERFORMANCE",
            memory_kind=MemoryKind.EXPERIMENT,
            authority=MemoryAuthority.OBSERVED,
            origin_scope=MemoryScopeLevel.CAMPAIGN,
            requested_scope=MemoryScopeLevel.CAMPAIGN,
            evidence_verdict=ClaimVerdict.SUPPORTED,
            evidence_refs=["FAKE-EVIDENCE-REF-1"],
            independent_run_count=3,
        )

        decision = evaluate_memory_candidate(fabricated)

        self.assertNotEqual(
            decision.disposition,
            MemoryDisposition.PROMOTED,
            "caller-supplied OBSERVED/SUPPORTED/evidence refs/run count must not self-authorize durable institutional learning",
        )


if __name__ == "__main__":
    unittest.main()
