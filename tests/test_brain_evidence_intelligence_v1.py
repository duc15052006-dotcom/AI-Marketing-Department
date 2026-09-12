"""Adversarial tests for provider-neutral Brain evidence intelligence v1."""

from __future__ import annotations

import ast
import inspect
import unittest
from itertools import permutations

import brain.evidence as evidence
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


class BrainEvidenceIntelligenceV1Tests(unittest.TestCase):
    @staticmethod
    def _signal(**updates) -> EvidenceSignal:
        values = {
            "evidence_id": "E-1",
            "goal_id": "G-1",
            "claim_id": "C-1",
            "source_id": "SRC-1",
            "relation": EvidenceRelation.SUPPORTS,
            "strength": EvidenceStrength.STRONG,
            "origin": EvidenceOrigin.OBSERVED,
        }
        values.update(updates)
        return EvidenceSignal(**values)

    @staticmethod
    def _request(signals, **updates) -> ClaimEvidenceRequest:
        values = {
            "assessment_id": "EA-1",
            "goal_id": "G-1",
            "claim_id": "C-1",
            "agent_id": "INTELLIGENCE",
            "evidence": list(signals),
        }
        values.update(updates)
        return ClaimEvidenceRequest(**values)

    def test_strong_observed_support_can_support_exact_claim(self) -> None:
        result = assess_claim_evidence(self._request([self._signal()]))
        self.assertEqual(result.verdict, ClaimVerdict.SUPPORTED)
        self.assertEqual(result.supporting_evidence_refs, ["E-1"])

    def test_cross_claim_or_cross_goal_evidence_cannot_be_laundered(self) -> None:
        wrong_claim = self._signal(evidence_id="E-X", claim_id="C-OTHER")
        wrong_goal = self._signal(evidence_id="E-Y", goal_id="G-OTHER")
        result = assess_claim_evidence(self._request([wrong_claim, wrong_goal]))
        self.assertEqual(result.verdict, ClaimVerdict.INSUFFICIENT)
        self.assertEqual(set(result.ignored_evidence_refs), {"E-X", "E-Y"})
        self.assertEqual(result.supporting_evidence_refs, [])

    def test_derived_or_weak_evidence_cannot_establish_strong_claim(self) -> None:
        derived = self._signal(origin=EvidenceOrigin.DERIVED)
        weak = self._signal(
            evidence_id="E-2",
            source_id="SRC-2",
            strength=EvidenceStrength.WEAK,
        )
        result = assess_claim_evidence(self._request([derived, weak]))
        self.assertEqual(result.verdict, ClaimVerdict.INSUFFICIENT)

    def test_two_independent_moderate_observations_can_support(self) -> None:
        one = self._signal(strength=EvidenceStrength.MODERATE)
        two = self._signal(
            evidence_id="E-2",
            source_id="SRC-2",
            strength=EvidenceStrength.MODERATE,
        )
        result = assess_claim_evidence(self._request([one, two]))
        self.assertEqual(result.verdict, ClaimVerdict.SUPPORTED)

    def test_duplicate_same_source_does_not_fake_independence(self) -> None:
        one = self._signal(strength=EvidenceStrength.MODERATE)
        duplicate_source = self._signal(
            evidence_id="E-2",
            source_id="SRC-1",
            strength=EvidenceStrength.MODERATE,
        )
        result = assess_claim_evidence(self._request([one, duplicate_source]))
        self.assertEqual(result.verdict, ClaimVerdict.INSUFFICIENT)

    def test_observed_support_and_contradiction_are_contested(self) -> None:
        support = self._signal()
        contradiction = self._signal(
            evidence_id="E-2",
            source_id="SRC-2",
            relation=EvidenceRelation.CONTRADICTS,
        )
        result = assess_claim_evidence(self._request([support, contradiction]))
        self.assertEqual(result.verdict, ClaimVerdict.CONTESTED)
        self.assertEqual(result.contradicting_evidence_refs, ["E-2"])

    def test_strong_observed_contradiction_without_support_refutes(self) -> None:
        contradiction = self._signal(relation=EvidenceRelation.CONTRADICTS)
        result = assess_claim_evidence(self._request([contradiction]))
        self.assertEqual(result.verdict, ClaimVerdict.REFUTED)

    def test_duplicate_evidence_id_is_counted_once(self) -> None:
        first = self._signal(strength=EvidenceStrength.MODERATE)
        duplicate = self._signal(strength=EvidenceStrength.MODERATE)
        result = assess_claim_evidence(self._request([first, duplicate]))
        self.assertEqual(result.verdict, ClaimVerdict.INSUFFICIENT)
        self.assertEqual(result.supporting_evidence_refs, ["E-1"])

    def test_conflicting_evidence_identity_fails_closed_in_both_orders(self) -> None:
        changes = {
            "goal_id": "G-OTHER",
            "claim_id": "C-OTHER",
            "source_id": "SRC-OTHER",
            "relation": EvidenceRelation.CONTRADICTS,
            "strength": EvidenceStrength.WEAK,
            "origin": EvidenceOrigin.DERIVED,
        }
        for field_name, value in changes.items():
            first = self._signal()
            conflicting = self._signal(**{field_name: value})
            for signals in ((first, conflicting), (conflicting, first)):
                with self.subTest(field=field_name, first=signals[0].model_dump()):
                    with self.assertRaisesRegex(
                        ValidationError, "conflicting evidence_id: E-1"
                    ):
                        assess_claim_evidence(self._request(signals))

    def test_extra_support_and_replay_cannot_hide_identity_conflict(self) -> None:
        support = self._signal()
        contradiction = self._signal(relation=EvidenceRelation.CONTRADICTS)
        independent = self._signal(evidence_id="E-2", source_id="SRC-2")
        for signals in permutations((support, contradiction, independent)):
            with self.subTest(order=[s.model_dump() for s in signals]):
                # A repeated first record must not short-circuit later validation.
                replayed = [signals[0], signals[0].model_copy(deep=True), *signals[1:]]
                with self.assertRaisesRegex(
                    ValidationError, "conflicting evidence_id: E-1"
                ):
                    assess_claim_evidence(self._request(replayed))

    def test_normalized_identical_replay_retains_one_supporting_reference(self) -> None:
        first = self._signal()
        replay = self._signal(
            evidence_id=" E-1 ",
            goal_id=" G-1 ",
            claim_id=" C-1 ",
            source_id=" SRC-1 ",
            relation=" supports ",
            strength=" strong ",
            origin=" observed ",
        )
        for signals in ((first, replay), (replay, first)):
            result = assess_claim_evidence(self._request(signals))
            self.assertEqual(result.verdict, ClaimVerdict.SUPPORTED)
            self.assertEqual(result.supporting_evidence_refs, ["E-1"])

    def test_identical_replay_preserves_independent_corroboration(self) -> None:
        first = self._signal(strength=EvidenceStrength.MODERATE)
        replay = self._signal(strength=EvidenceStrength.MODERATE)
        independent = self._signal(
            evidence_id="E-2",
            source_id="SRC-2",
            strength=EvidenceStrength.MODERATE,
        )
        for signals in permutations((first, replay, independent)):
            result = assess_claim_evidence(self._request(signals))
            self.assertEqual(result.verdict, ClaimVerdict.SUPPORTED)
            self.assertEqual(set(result.supporting_evidence_refs), {"E-1", "E-2"})
            self.assertEqual(len(result.supporting_evidence_refs), 2)

    def test_invalid_agent_enum_and_evidence_type_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._request([self._signal()], agent_id="AGENT_6")
        with self.assertRaises(ValidationError):
            self._request([{"evidence_id": "E-RAW"}])

    def test_evidence_policy_has_no_provider_or_body_dependency(self) -> None:
        source = inspect.getsource(evidence)
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

        serialized = str(
            assess_claim_evidence(self._request([self._signal()])).model_dump()
        ).lower()
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
