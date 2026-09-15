from __future__ import annotations

import unittest

from connections.manager import ConnectionManager
from connections.models import ConnectionProfile
from connections.secrets import SecretValue
from connectors.control_plane import ConnectorControlPlane
from connectors.marketing import (
    MarketingConnectorRegistry,
    MarketingConnectorSpec,
    MarketingExecutionMode,
)
from connectors.models import AuthenticationType, ConnectorDescriptor, ReadWriteMode
from connectors.registry import ConnectorRegistry
from tools.capabilities import RiskLevel
from tools.dynamic_gateway.gateway import DynamicToolGateway
from tools.receipts import ExecutionStatus
from tools.security import PolicyEngine, compute_request_fingerprint
from tools.tool_gateway import ToolRequest


class CountingSecretProvider:
    def __init__(self) -> None:
        self.get_calls = 0

    def can_resolve(self, secret_ref: str) -> bool:
        return str(secret_ref).startswith("env:")

    def get(self, secret_ref: str) -> SecretValue:
        self.get_calls += 1
        return SecretValue("SECRET-MUST-NOT-BE-RESOLVED-IN-SANDBOX")


class TrustedMarketingScopeV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret_provider = CountingSecretProvider()
        self.connection_manager = ConnectionManager(self.secret_provider)
        self.connection_manager.register(
            ConnectionProfile(
                connection_id="meta-brand-scoped",
                provider="meta",
                display_name="Meta Brand Scoped",
                secret_ref="env:META_BRAND_SCOPED_TOKEN",
                business_id="biz-1",
                project_ids=("proj-1", "proj-2"),
                brand_ids=("brand-a", "brand-b"),
            )
        )

        connector_registry = ConnectorRegistry()
        connector_registry.register_connector(
            ConnectorDescriptor(
                connector_id="conn_meta_marketing",
                provider="meta",
                capability_ids=["analytics_retrieval", "social_publishing"],
                authentication_type=AuthenticationType.BEARER_TOKEN,
                read_write_mode=ReadWriteMode.READ_WRITE,
                risk_level=RiskLevel.CRITICAL,
                supported_operations=["read_metrics", "publish_post"],
            )
        )
        control_plane = ConnectorControlPlane(connector_registry, self.connection_manager)
        control_plane.bind("conn_meta_marketing", "meta-brand-scoped")

        marketing_registry = MarketingConnectorRegistry(control_plane)
        marketing_registry.register(
            MarketingConnectorSpec(
                connector_id="conn_meta_marketing",
                provider="meta",
                supported_capabilities=("analytics_retrieval", "social_publishing"),
                execution_mode=MarketingExecutionMode.SANDBOX,
            )
        )

        self.policy_engine = PolicyEngine()
        self.gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            policy_engine=self.policy_engine,
        )
        report = self.gateway.sync_all()
        self.assertTrue(report.success)

    @property
    def analytics_capability(self) -> str:
        return "marketing.conn_meta_marketing.analytics_retrieval"

    @property
    def publish_capability(self) -> str:
        return "marketing.conn_meta_marketing.social_publishing"

    def _read_parameters(self, **updates):
        values = {
            "connection_id": "meta-brand-scoped",
            "action": "read_metrics",
            "resource_type": "campaign",
            "resource_id": "campaign-1",
            "payload": {"date_window": "last_30_days"},
        }
        values.update(updates)
        return values

    def _publish_parameters(self, **updates):
        values = {
            "connection_id": "meta-brand-scoped",
            "action": "publish_post",
            "resource_type": "post",
            "idempotency_key": "idem-trusted-scope-001",
            "payload": {"caption": "sandbox only"},
        }
        values.update(updates)
        return values

    def _pending_publish(self, *, project_id: str = "proj-1", brand_id: str = "brand-a"):
        return self.gateway.execute(
            ToolRequest(
                request_id="REQ-SCOPE-PENDING-001",
                run_id="RUN-SCOPE-PENDING-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=self._publish_parameters(),
                business_id="biz-1",
                project_id=project_id,
                brand_id=brand_id,
            )
        )

    def test_fingerprint_binds_project_and_brand(self) -> None:
        kwargs = {
            "capability_id": self.publish_capability,
            "parameters": self._publish_parameters(),
            "run_id": "RUN-FP-001",
            "business_id": "biz-1",
        }
        fp_a = compute_request_fingerprint(**kwargs, project_id="proj-1", brand_id="brand-a")
        fp_b = compute_request_fingerprint(**kwargs, project_id="proj-1", brand_id="brand-b")
        fp_project = compute_request_fingerprint(**kwargs, project_id="proj-2", brand_id="brand-a")
        self.assertNotEqual(fp_a, fp_b)
        self.assertNotEqual(fp_a, fp_project)
        self.assertEqual(
            fp_a,
            compute_request_fingerprint(**kwargs, project_id="proj-1", brand_id="brand-a"),
        )

    def test_pending_and_issued_approval_carry_exact_project_and_brand(self) -> None:
        pending_receipt = self._pending_publish()
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, pending_receipt.status)
        pending = self.policy_engine.get_pending_approval(pending_receipt.approval_reference)
        self.assertIsNotNone(pending)
        self.assertEqual("proj-1", pending.project_id)
        self.assertEqual("brand-a", pending.brand_id)

        approved, approval, reason = self.policy_engine.approve_pending_action(
            pending_receipt.approval_reference
        )
        self.assertTrue(approved, reason)
        self.assertEqual("proj-1", approval.project_id)
        self.assertEqual("brand-a", approval.brand_id)
        self.assertEqual(pending.request_fingerprint, approval.request_fingerprint)

    def test_brand_scoped_connection_accepts_only_trusted_tool_request_brand(self) -> None:
        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-SCOPE-READ-001",
                run_id="RUN-SCOPE-READ-001",
                agent_id="performance",
                capability_id=self.analytics_capability,
                parameters=self._read_parameters(),
                business_id="biz-1",
                project_id="proj-1",
                brand_id="brand-a",
            )
        )
        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual("SANDBOX_NO_OBSERVED_DATA", receipt.data["status"])
        self.assertEqual("brand-a", receipt.data["brand_id"])
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_model_controlled_brand_cannot_replace_trusted_brand_context(self) -> None:
        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-SCOPE-INJECT-001",
                run_id="RUN-SCOPE-INJECT-001",
                agent_id="performance",
                capability_id=self.analytics_capability,
                parameters=self._read_parameters(brand_id="brand-b"),
                business_id="biz-1",
                project_id="proj-1",
                brand_id="brand-a",
            )
        )
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("UNTRUSTED_SCOPE_PARAMETER", receipt.error_class)
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_approval_for_brand_a_cannot_authorize_brand_b(self) -> None:
        pending = self._pending_publish(brand_id="brand-a")
        approved, approval, reason = self.policy_engine.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved, reason)

        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-SCOPE-BRAND-MISMATCH",
                run_id="RUN-SCOPE-PENDING-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=self._publish_parameters(),
                approval_token=approval.approval_token,
                business_id="biz-1",
                project_id="proj-1",
                brand_id="brand-b",
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, receipt.status)
        self.assertEqual("APPROVAL_BRAND_MISMATCH", receipt.error_class)
        self.assertFalse(approval.claimed)
        self.assertFalse(approval.consumed)
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_approval_for_project_one_cannot_authorize_project_two(self) -> None:
        pending = self._pending_publish(project_id="proj-1", brand_id="brand-a")
        approved, approval, reason = self.policy_engine.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved, reason)

        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-SCOPE-PROJECT-MISMATCH",
                run_id="RUN-SCOPE-PENDING-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=self._publish_parameters(),
                approval_token=approval.approval_token,
                business_id="biz-1",
                project_id="proj-2",
                brand_id="brand-a",
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, receipt.status)
        self.assertEqual("APPROVAL_PROJECT_MISMATCH", receipt.error_class)
        self.assertFalse(approval.claimed)
        self.assertFalse(approval.consumed)

    def test_approved_scope_can_restore_omitted_project_and_brand(self) -> None:
        pending = self._pending_publish(project_id="proj-1", brand_id="brand-a")
        approved, approval, reason = self.policy_engine.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved, reason)

        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-SCOPE-INFER-001",
                run_id="RUN-SCOPE-PENDING-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=self._publish_parameters(),
                approval_token=approval.approval_token,
                business_id="biz-1",
            )
        )
        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual("proj-1", receipt.project_id)
        self.assertEqual("brand-a", receipt.data["brand_id"])
        self.assertFalse(receipt.data["external_side_effect"])
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_request_hash_is_scope_bound_for_project_and_brand(self) -> None:
        common = dict(
            request_id="REQ-HASH-001",
            run_id="RUN-HASH-001",
            agent_id="performance",
            capability_id=self.analytics_capability,
            parameters=self._read_parameters(),
            business_id="biz-1",
        )
        brand_a = ToolRequest(**common, project_id="proj-1", brand_id="brand-a")
        brand_b = ToolRequest(**common, project_id="proj-1", brand_id="brand-b")
        project_two = ToolRequest(**common, project_id="proj-2", brand_id="brand-a")
        self.assertNotEqual(brand_a.calculate_request_hash(), brand_b.calculate_request_hash())
        self.assertNotEqual(brand_a.calculate_request_hash(), project_two.calculate_request_hash())


if __name__ == "__main__":
    unittest.main()
