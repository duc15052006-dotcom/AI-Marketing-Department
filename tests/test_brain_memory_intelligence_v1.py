"""Adversarial tests for provider-neutral Brain memory intelligence v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.memory_policy as memory_policy
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


class BrainMemoryIntelligenceV1Tests(unittest.TestCase):
    @staticmethod
    def _supported_runs(
        count: int,
        *,
        goal_id: str = "G-1",
        claim_id: str = "C-1",
        agent_id: str = "PERFORMANCE",
    ) -> list[ClaimEvidenceRequest]:
        return [
            ClaimEvidenceRequest(
                assessment_id=f"RUN-{index}",
                goal_id=goal_id,
                claim_id=claim_id,
                agent_id=agent_id,
                evidence=[
                    EvidenceSignal(
                        evidence_id=f"E-RUN-{index}",
                        goal_id=goal_id,
                        claim_id=claim_id,
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
            "evidence_refs": ["E-1"],
            "independent_run_count": 1,
        }
        values.update(updates)
        return MemoryCandidate(**values)

    def test_single_supported_run_is_candidate_not_durable_learning(self) -> None:
        decision = evaluate_memory_candidate(self._candidate())
        self.assertEqual(decision.disposition, MemoryDisposition.CANDIDATE)

    def test_repeated_supported_observation_can_be_verified_then_promoted(self) -> None:
        verified = evaluate_memory_candidate(self._candidate(independent_run_count=2))
        promoted = evaluate_memory_candidate(
            self._candidate(
                independent_run_count=3,
                evidence_refs=["E-RUN-1", "E-RUN-2", "E-RUN-3"],
                run_evidence_requests=self._supported_runs(3),
            )
        )
        self.assertEqual(verified.disposition, MemoryDisposition.VERIFIED)
        self.assertEqual(promoted.disposition, MemoryDisposition.PROMOTED)

    def test_contested_or_insufficient_claim_cannot_become_durable_memory(self) -> None:
        for verdict in (ClaimVerdict.CONTESTED, ClaimVerdict.INSUFFICIENT):
            decision = evaluate_memory_candidate(
                self._candidate(evidence_verdict=verdict, independent_run_count=10)
            )
            self.assertEqual(decision.disposition, MemoryDisposition.EPHEMERAL)

    def test_refuted_claim_is_rejected_even_with_many_runs(self) -> None:
        decision = evaluate_memory_candidate(
            self._candidate(
                evidence_verdict=ClaimVerdict.REFUTED,
                independent_run_count=50,
            )
        )
        self.assertEqual(decision.disposition, MemoryDisposition.REJECTED)

    def test_observed_memory_without_evidence_refs_fails_closed(self) -> None:
        decision = evaluate_memory_candidate(
            self._candidate(evidence_refs=[], independent_run_count=5)
        )
        self.assertEqual(decision.disposition, MemoryDisposition.EPHEMERAL)

    def test_scope_cannot_be_broadened_automatically(self) -> None:
        decision = evaluate_memory_candidate(
            self._candidate(
                origin_scope=MemoryScopeLevel.CAMPAIGN,
                requested_scope=MemoryScopeLevel.GLOBAL,
                independent_run_count=20,
            )
        )
        self.assertEqual(decision.disposition, MemoryDisposition.REJECTED)
        self.assertEqual(decision.effective_scope, MemoryScopeLevel.CAMPAIGN)

    def test_same_or_narrower_scope_is_allowed(self) -> None:
        provenance = self._supported_runs(3)
        refs = ["E-RUN-1", "E-RUN-2", "E-RUN-3"]
        same = evaluate_memory_candidate(
            self._candidate(
                origin_scope=MemoryScopeLevel.BRAND,
                requested_scope=MemoryScopeLevel.BRAND,
                independent_run_count=3,
                evidence_refs=refs,
                run_evidence_requests=provenance,
            )
        )
        narrower = evaluate_memory_candidate(
            self._candidate(
                origin_scope=MemoryScopeLevel.BRAND,
                requested_scope=MemoryScopeLevel.PRODUCT,
                independent_run_count=3,
                evidence_refs=refs,
                run_evidence_requests=provenance,
            )
        )
        self.assertEqual(same.disposition, MemoryDisposition.PROMOTED)
        self.assertEqual(narrower.disposition, MemoryDisposition.PROMOTED)
        self.assertEqual(narrower.effective_scope, MemoryScopeLevel.PRODUCT)

    def test_user_confirmed_preference_may_be_promoted_without_empirical_receipt(self) -> None:
        decision = evaluate_memory_candidate(
            self._candidate(
                memory_kind=MemoryKind.USER_BRAND_PREFERENCE,
                authority=MemoryAuthority.USER_CONFIRMED,
                origin_scope=MemoryScopeLevel.BRAND,
                requested_scope=MemoryScopeLevel.BRAND,
                evidence_verdict=ClaimVerdict.INSUFFICIENT,
                evidence_refs=[],
            )
        )
        self.assertEqual(decision.disposition, MemoryDisposition.PROMOTED)

    def test_agent_inferred_user_preference_never_becomes_durable_authority(self) -> None:
        decision = evaluate_memory_candidate(
            self._candidate(
                memory_kind=MemoryKind.USER_BRAND_PREFERENCE,
                authority=MemoryAuthority.AGENT_INFERRED,
                origin_scope=MemoryScopeLevel.BRAND,
                requested_scope=MemoryScopeLevel.BRAND,
                independent_run_count=99,
            )
        )
        self.assertEqual(decision.disposition, MemoryDisposition.EPHEMERAL)

    def test_working_memory_is_always_ephemeral(self) -> None:
        decision = evaluate_memory_candidate(
            self._candidate(memory_kind=MemoryKind.WORKING, independent_run_count=99)
        )
        self.assertEqual(decision.disposition, MemoryDisposition.EPHEMERAL)

    def test_invalid_agent_and_run_count_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._candidate(agent_id="AGENT_6")
        with self.assertRaises(ValidationError):
            self._candidate(independent_run_count=0)

    def test_memory_policy_has_no_body_or_provider_dependency(self) -> None:
        source = inspect.getsource(memory_policy)
        tree = ast.parse(source)
        forbidden_roots = {
            "runtime",
            "tools",
            "integrations",
            "connectors",
            "knowledge",
            "memory",
        }
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots & forbidden_roots, set())

        serialized = str(evaluate_memory_candidate(self._candidate()).model_dump()).lower()
        for forbidden in (
            "provider_id",
            "model_id",
            "openai",
            "astra",
            "gemini",
            "claude",
            "tool_id",
            "connector_id",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
