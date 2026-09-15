"""Platform Batch #6: approval/security hardening regressions."""

import unittest

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class CapturePublishingAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.invocations = 0
        self.last_business_id = None

    @property
    def adapter_name(self) -> str:
        return "capture_publish_adapter"

    def execute(
        self,
        capability_id,
        parameters,
        timeout_seconds=30.0,
        *,
        run_id="",
        business_id="",
        project_id="",
    ) -> AdapterResult:
        self.invocations += 1
        self.last_business_id = business_id
        return AdapterResult(
            success=True,
            data={"published": True},
            execution_mode=ExecutionMode.SANDBOX,
        )


class TestPlatformApprovalSecurityV1(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.policy = PolicyEngine()
        self.receipts = ExecutionReceiptRepository()
        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=self.policy,
            receipt_repository=self.receipts,
        )
        self.adapter = CapturePublishingAdapter()
        self.gateway.register_adapter(self.adapter, aliases=["social_publish_adapter"])
        self.capability = self.registry.get_capability("social_publishing")
        self.params = {"platform": "linkedin", "content": "approved content"}

    def _approval(self, *, run_id="RUN-APPROVAL-1", business_id="BIZ-A", ttl_seconds=300):
        return self.policy.create_server_approval(
            capability_id="social_publishing",
            parameters=self.params,
            run_id=run_id,
            business_id=business_id,
            ttl_seconds=ttl_seconds,
        )

    def test_gateway_rejects_cross_business_approval(self):
        approval = self._approval(business_id="BIZ-A")
        receipt = self.gateway.execute(
            ToolRequest(
                run_id="RUN-APPROVAL-1",
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=self.params,
                approval_token=approval.approval_token,
                business_id="BIZ-B",
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_BUSINESS_MISMATCH")
        self.assertEqual(self.adapter.invocations, 0)

    def test_gateway_pins_omitted_business_to_server_approval_scope(self):
        approval = self._approval(business_id="BIZ-A")
        receipt = self.gateway.execute(
            ToolRequest(
                run_id="RUN-APPROVAL-1",
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=self.params,
                approval_token=approval.approval_token,
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.business_id, "BIZ-A")
        self.assertEqual(self.adapter.last_business_id, "BIZ-A")

    def test_direct_policy_requires_bound_business_context(self):
        approval = self._approval(business_id="BIZ-A")
        decision = self.policy.evaluate(
            agent_id="cmo",
            capability=self.capability,
            approval_token=approval.approval_token,
            run_id="RUN-APPROVAL-1",
            business_id=None,
            parameters=self.params,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_BUSINESS_CONTEXT_REQUIRED")

    def test_direct_policy_requires_bound_run_context(self):
        approval = self._approval(run_id="RUN-APPROVAL-1", business_id=None)
        decision = self.policy.evaluate(
            agent_id="cmo",
            capability=self.capability,
            approval_token=approval.approval_token,
            run_id=None,
            business_id=None,
            parameters=self.params,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_RUN_CONTEXT_REQUIRED")

    def test_fingerprint_cannot_backfill_missing_parameters(self):
        approval = self._approval(run_id="", business_id=None)
        decision = self.policy.evaluate(
            agent_id="cmo",
            capability=self.capability,
            approval_token=approval.approval_token,
            parameters=None,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_PARAMETERS_REQUIRED")

    def test_expired_token_cannot_be_claimed(self):
        approval = self._approval(run_id="", business_id=None, ttl_seconds=-1)
        self.assertFalse(self.policy.claim_approval(approval.approval_token))
        self.assertFalse(approval.claimed)

    def test_unclaimed_token_cannot_be_consumed(self):
        approval = self._approval(run_id="", business_id=None)
        self.assertFalse(self.policy.consume_approval(approval.approval_token))
        self.assertFalse(approval.consumed)

    def test_invalid_token_is_not_echoed_in_policy_reason_or_receipt(self):
        attacker_token = "ATTACKER-SECRET-APPROVAL-TOKEN"
        receipt = self.gateway.execute(
            ToolRequest(
                run_id="RUN-APPROVAL-1",
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=self.params,
                approval_token=attacker_token,
                business_id="BIZ-A",
            )
        )
        self.assertEqual(receipt.error_class, "INVALID_APPROVAL_TOKEN")
        self.assertNotIn(attacker_token, receipt.error_message or "")
        self.assertNotEqual(receipt.approval_reference, attacker_token)
        self.assertTrue((receipt.approval_reference or "").startswith("approval_ref_"))

    def test_success_receipt_contains_non_replayable_approval_reference(self):
        approval = self._approval(business_id="BIZ-A")
        receipt = self.gateway.execute(
            ToolRequest(
                run_id="RUN-APPROVAL-1",
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=self.params,
                approval_token=approval.approval_token,
                business_id="BIZ-A",
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertNotEqual(receipt.approval_reference, approval.approval_token)
        self.assertTrue((receipt.approval_reference or "").startswith("approval_ref_"))


if __name__ == "__main__":
    unittest.main()
