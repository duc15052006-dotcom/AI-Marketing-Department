"""Adversarial regression for stacked pull-request exact-head CI identity."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


class StackedPullRequestExactHeadCIV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_path = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "offline-regression.yml"
        )
        cls.workflow = cls.workflow_path.read_text(encoding="utf-8")

    def test_pull_request_ci_is_not_limited_to_main_base(self) -> None:
        self.assertIn("  pull_request:\n", self.workflow)
        self.assertIsNone(
            re.search(
                r"(?m)^  pull_request:\s*$\n\s+branches:\s*\[main\]\s*$",
                self.workflow,
            ),
            "stacked PR CI must not be restricted to base=main",
        )

    def test_checkout_and_identity_are_bound_to_literal_pr_head(self) -> None:
        expected_expression = "${{ github.event.pull_request.head.sha || github.sha }}"
        self.assertIn(f"ref: {expected_expression}", self.workflow)
        self.assertIn(f'$expectedHead = "{expected_expression}"', self.workflow)
        self.assertIn("$actualHead = (git rev-parse HEAD).Trim()", self.workflow)
        self.assertIn("EXACT_HEAD_MISMATCH", self.workflow)

    def test_evidence_artifact_is_named_by_literal_pr_head(self) -> None:
        self.assertIn(
            "name: offline-regression-${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
