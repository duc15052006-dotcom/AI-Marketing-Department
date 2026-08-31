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
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolRequest


class CountingSecretProvider:
    def __init__(self) -> None:
        self.get_calls = 0

    def can_resolve(self, secret_ref: str) -> bool:
        return str(secret_ref).startswith("env:")

    def get(self, secret_ref: str) -> SecretValue:
        self.get_calls += 1
        return SecretValue("META-SECRET-MUST-NOT-BE-RESOLVED-IN-SANDBOX")


class MarketingGatewaySandboxV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret_provider = CountingSecretProvider()
        self.connection_manager = ConnectionManager(self.secret_provider)
        self.connection_manager.register(
            ConnectionProfile(
                connection_id="meta-main",
                provider="meta",
                display_name="Meta Main",
                secret_ref="env:META_MAIN_TOKEN",
                business_id="biz-1",
                project_ids=("proj-1",),
            )
        )

        self.connector_registry = ConnectorRegistry()
        self.connector_registry.register_connector(
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
        self.control_plane = ConnectorControlPlane(self.connector_registry, self.connection_manager)
        self.control_plane.bind("conn_meta_marketing", "meta-main")

        self.marketing_registry = MarketingConnectorRegistry(self.control_plane)
        self.marketing_registry.register(
            MarketingConnectorSpec(
                connector_id="conn_meta_marketing",
                provider="meta",
                supported_capabilities=("analytics_retrieval", "social_publishing"),
                execution_mode=MarketingExecutionMode.SANDBOX,
            )
        )
        self.policy_engine = PolicyEngine()
        self.gateway = DynamicToolGateway(
            marketing_registry=self.marketing_registry,
            policy_engine=self.policy_engine,
        )
        self.report = self.gateway.sync_all()

    @property
    def analytics_capability(self) -> str:
        return "marketing.conn_meta_marketing.analytics_retrieval"

    @property
    def publish_capability(self) -> str:
        return "marketing.conn_meta_marketing.social_publishing"

    def _read_parameters(self, **updates):
        values = {
            "connection_id": "meta-main",
            "action": "read_metrics",
            "resource_type": "campaign",
            "resource_id": "campaign-1",
            "payload": {"date_window": "last_30_days"},
        }
        values.update(updates)
        return values

    def _publish_parameters(self, **updates):
        values = {
            "connection_id": "meta-main",
            "action": "publish_post",
            "resource_type": "post",
            "idempotency_key": "idem-publish-0001",
            "payload": {"caption": "sandbox caption"},
        }
        values.update(updates)
        return values

    def test_sync_exports_namespaced_sandbox_capabilities_without_overriding_builtin(self) -> None:
        self.assertTrue(self.report.success)
        self.assertEqual(2, self.report.marketing_capabilities)
        analytics = self.gateway.get_capability(self.analytics_capability)
        publish = self.gateway.get_capability(self.publish_capability)
        self.assertIsNotNone(analytics)
        self.assertIsNotNone(publish)
        self.assertEqual("MOCK_ONLY", analytics.availability)
        self.assertEqual("marketing:conn_meta_marketing", publish.provider)
        self.assertTrue(publish.human_approval_required)
        self.assertEqual(RiskLevel.CRITICAL, publish.risk_level)

        builtin = self.gateway.get_capability("social_publishing")
        self.assertIsNotNone(builtin)
        self.assertEqual("social_publish_adapter", builtin.provider)

    def test_analytics_sandbox_executes_without_approval_or_secret_and_fabricates_no_metrics(self) -> None:
        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-READ-001",
                run_id="RUN-MKT-READ-001",
                agent_id="performance",
                capability_id=self.analytics_capability,
                parameters=self._read_parameters(),
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(ExecutionMode.SANDBOX, receipt.execution_mode)
        self.assertEqual("SANDBOX_NO_OBSERVED_DATA", receipt.data["status"])
        self.assertFalse(receipt.data["analysis_available"])
        self.assertFalse(receipt.data["provider_network_called"])
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_publish_requires_gateway_approval_then_only_simulates_side_effect(self) -> None:
        params = self._publish_parameters()
        first = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-PUB-001",
                run_id="RUN-MKT-PUB-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=params,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, first.status)
        self.assertTrue(first.approval_reference.startswith("pending_appr_"))
        self.assertEqual(0, self.secret_provider.get_calls)

        approved, approval, reason = self.policy_engine.approve_pending_action(first.approval_reference)
        self.assertTrue(approved, reason)
        self.assertIsNotNone(approval)

        second = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-PUB-001",
                run_id="RUN-MKT-PUB-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=params,
                approval_token=approval.approval_token,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.SUCCESS, second.status)
        self.assertEqual(ExecutionMode.SANDBOX, second.execution_mode)
        self.assertEqual("SANDBOX_SIMULATED_WRITE", second.data["status"])
        self.assertFalse(second.data["external_side_effect"])
        self.assertFalse(second.data["provider_network_called"])
        self.assertEqual(0, self.secret_provider.get_calls)

        third = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-PUB-REPLAY",
                run_id="RUN-MKT-PUB-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=params,
                approval_token=approval.approval_token,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertNotEqual(ExecutionStatus.SUCCESS, third.status)
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_consequential_sandbox_write_still_creates_and_finalizes_durable_intent(self) -> None:
        params = self._publish_parameters(idempotency_key="idem-publish-0002")
        pending = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-INTENT-001",
                run_id="RUN-MKT-INTENT-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=params,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        approved, approval, _ = self.policy_engine.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved)
        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-INTENT-001",
                run_id="RUN-MKT-INTENT-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=params,
                approval_token=approval.approval_token,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        intents = self.gateway.gateway.receipt_repository.list_execution_intents_for_run("RUN-MKT-INTENT-001")
        self.assertEqual(1, len(intents))
        self.assertEqual("FINALIZED", intents[0].state.value)
        self.assertEqual(receipt.execution_id, intents[0].receipt_execution_id)

    def test_model_controlled_scope_fields_are_rejected(self) -> None:
        params = self._read_parameters(business_id="biz-other")
        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-SCOPE-001",
                run_id="RUN-MKT-SCOPE-001",
                agent_id="performance",
                capability_id=self.analytics_capability,
                parameters=params,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("UNTRUSTED_SCOPE_PARAMETER", receipt.error_class)
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_brand_restricted_connection_fails_closed_until_brand_is_trusted_context(self) -> None:
        self.connection_manager.register(
            ConnectionProfile(
                connection_id="meta-brand-locked",
                provider="meta",
                display_name="Meta Brand Locked",
                secret_ref="env:META_BRAND_LOCKED_TOKEN",
                business_id="biz-1",
                project_ids=("proj-1",),
                brand_ids=("brand-locked",),
            )
        )
        self.control_plane.bind("conn_meta_marketing", "meta-brand-locked")
        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-BRAND-001",
                run_id="RUN-MKT-BRAND-001",
                agent_id="performance",
                capability_id=self.analytics_capability,
                parameters=self._read_parameters(connection_id="meta-brand-locked"),
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("MARKETING_CONNECTION_NOT_READY", receipt.error_class)
        self.assertEqual(0, self.secret_provider.get_calls)

    def test_contract_only_spec_is_not_exported(self) -> None:
        registry = MarketingConnectorRegistry(self.control_plane)
        registry.register(
            MarketingConnectorSpec(
                connector_id="conn_meta_marketing",
                provider="meta",
                supported_capabilities=("analytics_retrieval",),
                execution_mode=MarketingExecutionMode.CONTRACT_ONLY,
            )
        )
        gateway = DynamicToolGateway(marketing_registry=registry)
        report = gateway.sync_marketing()
        self.assertTrue(report.success)
        self.assertEqual(0, report.marketing_capabilities)
        self.assertIsNone(gateway.get_capability(self.analytics_capability))

    def test_live_spec_is_refused_even_if_registration_was_explicitly_opted_in(self) -> None:
        registry = MarketingConnectorRegistry(self.control_plane, allow_live_registration=True)
        registry.register(
            MarketingConnectorSpec(
                connector_id="conn_meta_marketing",
                provider="meta",
                supported_capabilities=("analytics_retrieval",),
                execution_mode=MarketingExecutionMode.LIVE,
            )
        )
        gateway = DynamicToolGateway(marketing_registry=registry)
        report = gateway.sync_marketing()
        self.assertFalse(report.success)
        self.assertIn("marketing:conn_meta_marketing", report.errors)
        self.assertIn("LIVE_MARKETING_EXECUTION_UNSUPPORTED", report.errors["marketing:conn_meta_marketing"])
        self.assertIsNone(gateway.get_capability(self.analytics_capability))

    def test_write_contract_still_requires_idempotency_before_adapter_success(self) -> None:
        params = self._publish_parameters()
        params.pop("idempotency_key")
        pending = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-IDEM-001",
                run_id="RUN-MKT-IDEM-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=params,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, pending.status)
        approved, approval, _ = self.policy_engine.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved)
        receipt = self.gateway.execute(
            ToolRequest(
                request_id="REQ-MKT-IDEM-001",
                run_id="RUN-MKT-IDEM-001",
                agent_id="cmo",
                capability_id=self.publish_capability,
                parameters=params,
                approval_token=approval.approval_token,
                business_id="biz-1",
                project_id="proj-1",
            )
        )
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("MARKETING_CONTRACT_REJECTED", receipt.error_class)
        self.assertEqual(0, self.secret_provider.get_calls)


if __name__ == "__main__":
    unittest.main()
