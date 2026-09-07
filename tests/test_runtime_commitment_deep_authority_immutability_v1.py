"""Adversarial RED regressions for deep Commitment authority immutability.

Invariant: mutable authority containers inside an existing Commitment snapshot
must not provide an in-place mutation or external-alias path around the
field-level revision boundary.
"""

from __future__ import annotations

import unittest

from runtime.mission import CommitmentRecord


class CommitmentDeepAuthorityImmutabilityV1Tests(unittest.TestCase):
    def _commitment(self, *, budget_limits=None, stop_conditions=None) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id="COMMIT-DEEP-001",
            mission_id="MISSION-DEEP-001",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            authority_mode="OPERATOR_APPROVED",
            budget_limits=(
                {"spend_usd": 100.0}
                if budget_limits is None
                else budget_limits
            ),
            stop_conditions=(
                ["OPERATOR_CANCEL"]
                if stop_conditions is None
                else stop_conditions
            ),
        )

    def test_budget_item_assignment_cannot_mutate_snapshot(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.budget_limits["spend_usd"] = 25.0
        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})

    def test_budget_update_cannot_mutate_snapshot(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.budget_limits.update({"daily_usd": 10.0})
        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})

    def test_budget_pop_cannot_mutate_snapshot(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.budget_limits.pop("spend_usd")
        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})

    def test_stop_condition_append_cannot_mutate_snapshot(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.stop_conditions.append("BUDGET_EXHAUSTED")
        self.assertEqual(commitment.stop_conditions, ["OPERATOR_CANCEL"])

    def test_stop_condition_item_assignment_cannot_mutate_snapshot(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.stop_conditions[0] = "BUDGET_EXHAUSTED"
        self.assertEqual(commitment.stop_conditions, ["OPERATOR_CANCEL"])

    def test_stop_condition_extend_cannot_mutate_snapshot(self):
        commitment = self._commitment()
        with self.assertRaises(ValueError):
            commitment.stop_conditions.extend(["BUDGET_EXHAUSTED"])
        self.assertEqual(commitment.stop_conditions, ["OPERATOR_CANCEL"])

    def test_constructor_budget_alias_cannot_mutate_snapshot(self):
        budget = {"spend_usd": 100.0}
        commitment = self._commitment(budget_limits=budget)
        budget["spend_usd"] = 1.0
        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})

    def test_constructor_stop_condition_alias_cannot_mutate_snapshot(self):
        stops = ["OPERATOR_CANCEL"]
        commitment = self._commitment(stop_conditions=stops)
        stops.append("BUDGET_EXHAUSTED")
        self.assertEqual(commitment.stop_conditions, ["OPERATOR_CANCEL"])

    def test_model_dump_returns_detached_plain_containers_control(self):
        commitment = self._commitment()
        dumped = commitment.model_dump()

        self.assertIs(type(dumped["budget_limits"]), dict)
        self.assertIs(type(dumped["stop_conditions"]), list)
        dumped["budget_limits"]["spend_usd"] = 1.0
        dumped["stop_conditions"].append("BUDGET_EXHAUSTED")

        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})
        self.assertEqual(commitment.stop_conditions, ["OPERATOR_CANCEL"])

    def test_revision_input_aliases_are_detached_control(self):
        commitment = self._commitment()
        revised_budget = {"spend_usd": 25.0}
        revised_stops = ["BUDGET_EXHAUSTED"]

        revised = commitment.revise(
            new_commitment_id="COMMIT-DEEP-002",
            budget_limits=revised_budget,
            stop_conditions=revised_stops,
        )
        revised_budget["spend_usd"] = 1.0
        revised_stops.append("OPERATOR_CANCEL")

        self.assertEqual(revised.budget_limits, {"spend_usd": 25.0})
        self.assertEqual(revised.stop_conditions, ["BUDGET_EXHAUSTED"])
        self.assertEqual(commitment.budget_limits, {"spend_usd": 100.0})
        self.assertEqual(commitment.stop_conditions, ["OPERATOR_CANCEL"])


if __name__ == "__main__":
    unittest.main()
