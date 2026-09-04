"""Adversarial contract tests for BRAIN-1 cognitive primitives."""

from __future__ import annotations

import ast
import inspect
import math
import unittest

import brain.contracts as contracts
from brain.contracts import (
    ActionIntent,
    BrainAgentId,
    DecisionRecord,
    GoalSpec,
    StopDecision,
    StopReason,
)
from schemas.base import ValidationError


class BrainCognitiveContractV1Tests(unittest.TestCase):
    def test_exactly_five_permanent_agents_exist(self) -> None:
        self.assertEqual(
            [agent.value for agent in BrainAgentId],
            ["CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"],
        )
        with self.assertRaises(ValueError):
            BrainAgentId("AGENT_6")

    def test_goal_rejects_invalid_agent_blank_identity_and_self_parent(self) -> None:
        with self.assertRaises(ValidationError):
            GoalSpec(goal_id=" ", objective="Grow revenue", owner_agent="CMO")
        with self.assertRaises(ValidationError):
            GoalSpec(goal_id="G-1", objective="Grow revenue", owner_agent="AGENT_6")
        with self.assertRaises(ValidationError):
            GoalSpec(
                goal_id="G-1",
                objective="Grow revenue",
                owner_agent="CMO",
                parent_goal_id="G-1",
            )

    def test_goal_normalizes_semantics_without_body_metadata(self) -> None:
        goal = GoalSpec(
            goal_id=" G-1 ",
            objective=" Improve qualified revenue ",
            owner_agent="strategist",
            success_criteria=["Evidence-backed strategy", "Evidence-backed strategy"],
            constraints=["No fabricated metrics"],
        )
        dumped = goal.model_dump()
        self.assertEqual(goal.goal_id, "G-1")
        self.assertEqual(goal.owner_agent, BrainAgentId.STRATEGIST)
        self.assertEqual(goal.success_criteria, ["Evidence-backed strategy"])
        for forbidden in ("provider_id", "model_id", "tool_id", "queue_id", "connector_id"):
            self.assertNotIn(forbidden, dumped)

    def test_action_intent_is_capability_level_not_execution_instruction(self) -> None:
        intent = ActionIntent(
            intent_id="I-1",
            goal_id="G-1",
            owner_agent="INTELLIGENCE",
            purpose="Reduce uncertainty about competitor offers",
            capability_need="market_research",
            expected_observation="Current competitor offer evidence",
            evidence_required=True,
        )
        self.assertEqual(intent.capability_need, "MARKET_RESEARCH")
        dumped = intent.model_dump()
        for forbidden in (
            "tool_id",
            "tool_name",
            "provider_id",
            "connector_id",
            "endpoint",
            "api_key",
            "execution_mode",
        ):
            self.assertNotIn(forbidden, dumped)

        with self.assertRaises(ValidationError):
            ActionIntent(
                intent_id="I-2",
                goal_id="G-1",
                owner_agent="INTELLIGENCE",
                purpose="Research",
                capability_need="web.search/provider-x",
                expected_observation="Evidence",
            )

    def test_confidence_is_strict_finite_and_bounded(self) -> None:
        good = DecisionRecord(
            decision_id="D-1",
            goal_id="G-1",
            agent_id="CMO",
            statement="Proceed to a bounded pilot",
            rationale="Evidence is sufficient for a reversible test",
            confidence=0.7,
        )
        self.assertEqual(good.confidence, 0.7)

        for bad in (True, -0.1, 1.1, math.nan, math.inf):
            with self.subTest(confidence=bad):
                with self.assertRaises(ValidationError):
                    DecisionRecord(
                        decision_id="D-X",
                        goal_id="G-1",
                        agent_id="CMO",
                        statement="Decision",
                        rationale="Reason",
                        confidence=bad,
                    )

    def test_stop_contract_cannot_contradict_itself(self) -> None:
        continuing = StopDecision(
            should_stop=False,
            reason=StopReason.CONTINUE,
            rationale="More evidence is required",
            unresolved_questions=["What is the verified conversion baseline?"],
        )
        self.assertFalse(continuing.should_stop)

        with self.assertRaises(ValidationError):
            StopDecision(
                should_stop=True,
                reason=StopReason.CONTINUE,
                rationale="Contradictory stop",
            )
        with self.assertRaises(ValidationError):
            StopDecision(
                should_stop=False,
                reason=StopReason.GOAL_SATISFIED,
                rationale="Contradictory continue",
            )

    def test_brain_contracts_do_not_import_body_layers(self) -> None:
        source = inspect.getsource(contracts)
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


if __name__ == "__main__":
    unittest.main()
