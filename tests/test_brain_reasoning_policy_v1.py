"""Adversarial tests for provider-neutral adaptive reasoning policy v1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.reasoning as reasoning
from brain.reasoning import (
    ReasoningAssessment,
    ReasoningDepth,
    Reversibility,
    SignalLevel,
    select_reasoning_depth,
)
from schemas.base import ValidationError


class BrainReasoningPolicyV1Tests(unittest.TestCase):
    @staticmethod
    def _assessment(**updates) -> ReasoningAssessment:
        values = {
            "assessment_id": "RA-1",
            "goal_id": "G-1",
            "agent_id": "STRATEGIST",
            "complexity": SignalLevel.LOW,
            "uncertainty": SignalLevel.LOW,
            "consequence": SignalLevel.LOW,
            "evidence_conflict": SignalLevel.LOW,
            "reversibility": Reversibility.REVERSIBLE,
        }
        values.update(updates)
        return ReasoningAssessment(**values)

    def test_trivial_low_signal_task_can_remain_fast(self) -> None:
        decision = select_reasoning_depth(self._assessment())
        self.assertEqual(decision.depth, ReasoningDepth.FAST)

    def test_nontrivial_default_signals_are_balanced(self) -> None:
        decision = select_reasoning_depth(
            self._assessment(complexity="MEDIUM", uncertainty="MEDIUM")
        )
        self.assertEqual(decision.depth, ReasoningDepth.BALANCED)

    def test_high_signal_and_causal_work_raise_reasoning_floor(self) -> None:
        high = select_reasoning_depth(
            self._assessment(complexity=SignalLevel.HIGH)
        )
        self.assertEqual(high.depth, ReasoningDepth.DEEP)

        causal = select_reasoning_depth(
            self._assessment(causal_reasoning_required=True)
        )
        self.assertEqual(causal.depth, ReasoningDepth.DEEP)

    def test_any_critical_signal_has_at_least_very_deep_floor(self) -> None:
        critical_complexity = select_reasoning_depth(
            self._assessment(complexity=SignalLevel.CRITICAL)
        )
        self.assertEqual(critical_complexity.depth, ReasoningDepth.VERY_DEEP)

        critical_uncertainty = select_reasoning_depth(
            self._assessment(uncertainty=SignalLevel.CRITICAL)
        )
        self.assertEqual(critical_uncertainty.depth, ReasoningDepth.VERY_DEEP)

    def test_interacting_high_signals_raise_to_very_deep(self) -> None:
        decision = select_reasoning_depth(
            self._assessment(
                complexity=SignalLevel.HIGH,
                uncertainty=SignalLevel.HIGH,
            )
        )
        self.assertEqual(decision.depth, ReasoningDepth.VERY_DEEP)

    def test_evidence_conflict_has_stronger_scrutiny_floor(self) -> None:
        high = select_reasoning_depth(
            self._assessment(evidence_conflict=SignalLevel.HIGH)
        )
        self.assertEqual(high.depth, ReasoningDepth.VERY_DEEP)

        critical = select_reasoning_depth(
            self._assessment(evidence_conflict=SignalLevel.CRITICAL)
        )
        self.assertEqual(critical.depth, ReasoningDepth.MAXIMUM)

    def test_critical_or_irreversible_decision_requires_maximum(self) -> None:
        critical = select_reasoning_depth(
            self._assessment(consequence=SignalLevel.CRITICAL)
        )
        self.assertEqual(critical.depth, ReasoningDepth.MAXIMUM)

        irreversible = select_reasoning_depth(
            self._assessment(reversibility=Reversibility.IRREVERSIBLE)
        )
        self.assertEqual(irreversible.depth, ReasoningDepth.MAXIMUM)

    def test_minimum_depth_can_only_raise_never_weaken_policy(self) -> None:
        raised = select_reasoning_depth(
            self._assessment(minimum_depth=ReasoningDepth.VERY_DEEP)
        )
        self.assertEqual(raised.depth, ReasoningDepth.VERY_DEEP)

        cannot_lower = select_reasoning_depth(
            self._assessment(
                consequence=SignalLevel.CRITICAL,
                minimum_depth=ReasoningDepth.FAST,
            )
        )
        self.assertEqual(cannot_lower.depth, ReasoningDepth.MAXIMUM)

    def test_boolean_and_enum_inputs_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self._assessment(causal_reasoning_required="true")
        with self.assertRaises(ValidationError):
            self._assessment(agent_id="AGENT_6")
        with self.assertRaises(ValidationError):
            self._assessment(minimum_depth="XHIGH")

    def test_reasoning_policy_has_no_provider_or_body_dependency(self) -> None:
        source = inspect.getsource(reasoning)
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

        dumped = select_reasoning_depth(self._assessment()).model_dump()
        serialized = str(dumped).lower()
        for forbidden in (
            "provider_id",
            "model_id",
            "reasoning_effort",
            "token_budget",
            "gpt",
            "astra",
            "gemini",
            "claude",
            "xhigh",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
