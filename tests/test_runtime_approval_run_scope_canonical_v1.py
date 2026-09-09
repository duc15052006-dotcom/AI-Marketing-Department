from __future__ import annotations

import unittest

from tools.capabilities import CapabilityRegistry
from tools.security import PolicyEngine


class RuntimeApprovalRunScopeCanonicalV1Tests(unittest.TestCase):
    """Consequential run authority must use one canonical, non-malformed run scope."""

    def setUp(self) -> None:
        self.parameters = {
            "platform": "linkedin",
            "content": "canonical run-scope authority",
        }

    def test_server_approval_rejects_malformed_run_scope(self) -> None:
        for malformed in ("   ", " RUN_SCOPE_ALPHA ", "RUN_SCOPE_ALPHA\t"):
            with self.subTest(run_id=repr(malformed)):
                policy = PolicyEngine()
                with self.assertRaisesRegex(ValueError, "RUN_SCOPE_INVALID"):
                    policy.create_server_approval(
                        capability_id="social_publishing",
                        parameters=self.parameters,
                        run_id=malformed,
                        approved_by="Run Scope Canonical Regression Test",
                    )

    def test_pending_approval_rejects_malformed_run_scope(self) -> None:
        for malformed in ("   ", " RUN_SCOPE_ALPHA ", "RUN_SCOPE_ALPHA\n"):
            with self.subTest(run_id=repr(malformed)):
                policy = PolicyEngine()
                with self.assertRaisesRegex(ValueError, "RUN_SCOPE_INVALID"):
                    policy.create_pending_approval(
                        capability_id="social_publishing",
                        parameters=self.parameters,
                        run_id=malformed,
                    )

    def test_policy_rejects_malformed_current_run_scope_before_authority_use(self) -> None:
        policy = PolicyEngine()
        approval = policy.create_server_approval(
            capability_id="social_publishing",
            parameters=self.parameters,
            run_id="RUN_SCOPE_ALPHA",
            approved_by="Run Scope Canonical Regression Test",
        )
        capability = CapabilityRegistry().get_capability("social_publishing")
        self.assertIsNotNone(capability)

        decision = policy.evaluate(
            agent_id="cmo",
            capability=capability,
            approval_token=approval.approval_token,
            run_id=" RUN_SCOPE_ALPHA ",
            parameters=self.parameters,
        )

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_human_approval)
        self.assertEqual("RUN_SCOPE_INVALID", decision.error_code)
        stored = policy.get_approval(approval.approval_token)
        self.assertIsNotNone(stored)
        self.assertFalse(stored.claimed)
        self.assertFalse(stored.consumed)


if __name__ == "__main__":
    unittest.main()
