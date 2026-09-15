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
from tools.dynamic_gateway.marketing_live import (
    MarketingLiveExecutorProviderMismatchError,
    MarketingLiveExecutorRegistry,
    MarketingLiveExecutorResult,
)
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolRequest


class CountingSecretProvider:
    def __init__(self, secret: str = "LIVE-META-SECRET-DO-NOT-LEAK") -> None:
        self.secret = secret
        self.get_calls = 0

    def can_resolve(self, secret_ref: str) -> bool:
        return str(secret_ref).startswith("env:")

    def get(self, secret_ref: str) -> SecretValue:
        self.get_calls += 1
        return SecretValue(self.secret)


class RecordingLiveExecutor:
    executor_name = "recording-meta-live-executor"
    provider = "meta"

    def __init__(self, receipt_repository: ExecutionReceiptRepository, *, behavior: str = "success") -> None:
        self.receipt_repository = receipt_repository
        self.behavior = behavior
        self.calls = 0
        self.intent_states_seen = []
        self.credential_types = []

    def execute(self, *, prepared, request, credential, timeout_seconds):
        self.calls += 1
        self.credential_types.append(type(credential).__name__ if credential is not None else None)
        intents = self.receipt_repository.list_execution_intents_for_run(request.run_id)
        self.intent_states_seen.append([intent.state.value for intent in intents])
        secret = credential.reveal() if credential is not None else ""

        if self.behavior == "raise_uncertain":
            raise RuntimeError(f"provider outcome uncertain after Bearer {secret}")
        if self.behavior == "definite_failure":
            return MarketingLiveExecutorResult(
                success=False,
                error_code="PROVIDER_REJECTED",
                error_message=f"provider rejected request; token={secret}",
                data={"diagnostic": f"credential={secret}"},
            )
        return MarketingLiveExecutorResult(
            success=True,
            data={
                "status": "LIVE_EXECUTED",
                "provider_network_called": True,
                "external_side_effect": request.policy.is_write,
                "echo_for_redaction_test": f"Bearer {secret}",
                "prepared_fingerprint": prepared.request_fingerprint,
            },
            cost_or_tokens={"provider_note": f"api_key={secret}"},
            artifact_refs=(f"provider://artifact/{secret}",),
        )


class WrongProviderExecutor(RecordingLiveExecutor):
    provider = "tiktok"


class MarketingLiveBoundaryV1Tests(unittest.TestCase):
    def _build_components(self, *, behavior: str = "success", brand_locked: bool = False):
        secret_provider = CountingSecretProvider()
        connection_manager = ConnectionManager(secret_provider)
        connection_manager.register(
            ConnectionProfile(
                connection_id="meta-live-main",
                provider="meta",
                display_name="Meta Live Main",
                secret_ref="env:META_LIVE_TOKEN",
                business_id="biz-live",
                project_ids=("proj-live",),
                brand_ids=("brand-live",) if brand_locked else (),
            )
        )

        connector_registry = ConnectorRegistry()
        connector_registry.register_connector(
            ConnectorDescriptor(
                connector_id="conn_meta_live",
                provider="meta",
                capability_ids=["analytics_retrieval", "social_publishing"],
                authentication_type=AuthenticationType.BEARER_TOKEN,
                read_write_mode=ReadWriteMode.READ_WRITE,
                risk_level=RiskLevel.CRITICAL,
                supported_operations=["read_metrics", "publish_post"],
            )
        )
        control_plane = ConnectorControlPlane(connector_registry, connection_manager)
        control_plane.bind("conn_meta_live", "meta-live-main")

        marketing_registry = MarketingConnectorRegistry(control_plane, allow_live_registration=True)
        marketing_registry.register(
            MarketingConnectorSpec(
                connector_id="conn_meta_live",
                provider="meta",
                supported_capabilities=("analytics_retrieval", "social_publishing"),
                execution_mode=MarketingExecutionMode.LIVE,
            )
        )
        receipt_repository = ExecutionReceiptRepository()
        executor_registry = MarketingLiveExecutorRegistry(marketing_registry)
        executor = RecordingLiveExecutor(receipt_repository, behavior=behavior)
        return secret_provider, marketing_registry, receipt_repository, executor_registry, executor

    @staticmethod
    def _publish_parameters():
        return {
            "connection_id": "meta-live-main",
            "action": "publish_post",
            "resource_type": "post",
            "idempotency_key": "idem-live-publish-0001",
            "payload": {"caption": "governed live caption"},
        }

    @staticmethod
    def _read_parameters():
        return {
            "connection_id": "meta-live-main",
            "action": "read_metrics",
            "resource_type": "campaign",
            "resource_id": "campaign-live-1",
            "payload": {"date_window": "last_7_days"},
        }

    @staticmethod
    def _publish_capability():
        return "marketing.conn_meta_live.social_publishing"

    @staticmethod
    def _read_capability():
        return "marketing.conn_meta_live.analytics_retrieval"

    def test_live_sync_is_default_deny_even_with_registered_executor(self) -> None:
        secret_provider, marketing_registry, receipts, executor_registry, executor = self._build_components()
        executor_registry.bind("conn_meta_live", executor)
        gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            marketing_live_executor_registry=executor_registry,
            receipt_repository=receipts,
        )
        report = gateway.sync_marketing()
        self.assertFalse(report.success)
        self.assertIn("marketing:conn_meta_live", report.errors)
        self.assertIn("LIVE_MARKETING_EXECUTION_DISABLED", report.errors["marketing:conn_meta_live"])
        self.assertIsNone(gateway.get_capability(self._publish_capability()))
        self.assertEqual(0, secret_provider.get_calls)
        self.assertEqual(0, executor.calls)

    def test_live_sync_requires_exact_trusted_executor_binding(self) -> None:
        secret_provider, marketing_registry, receipts, executor_registry, executor = self._build_components()
        gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            marketing_live_executor_registry=executor_registry,
            allow_live_marketing_execution=True,
            receipt_repository=receipts,
        )
        report = gateway.sync_marketing()
        self.assertFalse(report.success)
        self.assertIn("LIVE_MARKETING_EXECUTOR_NOT_BOUND", report.errors["marketing:conn_meta_live"])
        self.assertIsNone(gateway.get_capability(self._read_capability()))
        self.assertEqual(0, secret_provider.get_calls)
        self.assertEqual(0, executor.calls)

    def test_executor_provider_mismatch_is_rejected_at_binding(self) -> None:
        _, marketing_registry, receipts, executor_registry, _ = self._build_components()
        with self.assertRaises(MarketingLiveExecutorProviderMismatchError):
            executor_registry.bind("conn_meta_live", WrongProviderExecutor(receipts))

    def test_live_read_resolves_secret_only_at_execution_boundary_and_redacts_output(self) -> None:
        secret_provider, marketing_registry, receipts, executor_registry, executor = self._build_components()
        executor_registry.bind("conn_meta_live", executor)
        gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            marketing_live_executor_registry=executor_registry,
            allow_live_marketing_execution=True,
            receipt_repository=receipts,
        )
        report = gateway.sync_all()
        self.assertTrue(report.success, report.errors)
        self.assertEqual(0, secret_provider.get_calls)

        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-LIVE-READ-001",
                run_id="RUN-LIVE-READ-001",
                agent_id="performance",
                capability_id=self._read_capability(),
                parameters=self._read_parameters(),
                business_id="biz-live",
                project_id="proj-live",
            )
        )
        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(ExecutionMode.REAL, receipt.execution_mode)
        self.assertEqual(1, secret_provider.get_calls)
        self.assertEqual(1, executor.calls)
        self.assertEqual(["SecretValue"], executor.credential_types)
        self.assertNotIn(secret_provider.secret, repr(receipt.model_dump()))

    def test_live_write_requires_approval_and_intent_is_dispatching_before_executor(self) -> None:
        secret_provider, marketing_registry, receipts, executor_registry, executor = self._build_components(brand_locked=True)
        executor_registry.bind("conn_meta_live", executor)
        policy_engine = PolicyEngine()
        gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            marketing_live_executor_registry=executor_registry,
            allow_live_marketing_execution=True,
            policy_engine=policy_engine,
            receipt_repository=receipts,
        )
        report = gateway.sync_all()
        self.assertTrue(report.success, report.errors)
        params = self._publish_parameters()

        first = gateway.execute(
            ToolRequest(
                request_id="REQ-LIVE-PUB-001",
                run_id="RUN-LIVE-PUB-001",
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=params,
                business_id="biz-live",
                project_id="proj-live",
                brand_id="brand-live",
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, first.status)
        self.assertEqual(0, secret_provider.get_calls)
        self.assertEqual(0, executor.calls)

        approved, approval, reason = policy_engine.approve_pending_action(first.approval_reference)
        self.assertTrue(approved, reason)
        second = gateway.execute(
            ToolRequest(
                request_id="REQ-LIVE-PUB-001",
                run_id="RUN-LIVE-PUB-001",
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=params,
                approval_token=approval.approval_token,
                business_id="biz-live",
                project_id="proj-live",
                brand_id="brand-live",
            )
        )
        self.assertEqual(ExecutionStatus.SUCCESS, second.status)
        self.assertEqual(ExecutionMode.REAL, second.execution_mode)
        self.assertEqual(1, secret_provider.get_calls)
        self.assertEqual(1, executor.calls)
        self.assertIn("DISPATCHING", executor.intent_states_seen[0])
        intents = receipts.list_execution_intents_for_run("RUN-LIVE-PUB-001")
        self.assertEqual(1, len(intents))
        self.assertEqual("FINALIZED", intents[0].state.value)
        self.assertEqual(second.execution_id, intents[0].receipt_execution_id)
        self.assertNotIn(secret_provider.secret, repr(second.model_dump()))

    def test_uncertain_live_write_exception_becomes_ambiguous_and_never_leaks_secret(self) -> None:
        secret_provider, marketing_registry, receipts, executor_registry, executor = self._build_components(behavior="raise_uncertain")
        executor_registry.bind("conn_meta_live", executor)
        policy_engine = PolicyEngine()
        gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            marketing_live_executor_registry=executor_registry,
            allow_live_marketing_execution=True,
            policy_engine=policy_engine,
            receipt_repository=receipts,
        )
        self.assertTrue(gateway.sync_all().success)
        params = self._publish_parameters()
        pending = gateway.execute(
            ToolRequest(
                request_id="REQ-LIVE-AMB-001",
                run_id="RUN-LIVE-AMB-001",
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=params,
                business_id="biz-live",
                project_id="proj-live",
            )
        )
        approved, approval, _ = policy_engine.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved)
        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-LIVE-AMB-001",
                run_id="RUN-LIVE-AMB-001",
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=params,
                approval_token=approval.approval_token,
                business_id="biz-live",
                project_id="proj-live",
            )
        )
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("AMBIGUOUS_EXTERNAL_ACTION_OUTCOME", receipt.error_class)
        self.assertEqual(1, executor.calls)
        intents = receipts.list_execution_intents_for_run("RUN-LIVE-AMB-001")
        self.assertEqual(1, len(intents))
        self.assertEqual("AMBIGUOUS", intents[0].state.value)
        self.assertNotIn(secret_provider.secret, repr(receipt.model_dump()))

    def test_definite_provider_rejection_finalizes_without_claiming_ambiguity(self) -> None:
        secret_provider, marketing_registry, receipts, executor_registry, executor = self._build_components(behavior="definite_failure")
        executor_registry.bind("conn_meta_live", executor)
        policy_engine = PolicyEngine()
        gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            marketing_live_executor_registry=executor_registry,
            allow_live_marketing_execution=True,
            policy_engine=policy_engine,
            receipt_repository=receipts,
        )
        self.assertTrue(gateway.sync_all().success)
        params = self._publish_parameters()
        pending = gateway.execute(
            ToolRequest(
                request_id="REQ-LIVE-REJECT-001",
                run_id="RUN-LIVE-REJECT-001",
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=params,
                business_id="biz-live",
                project_id="proj-live",
            )
        )
        approved, approval, _ = policy_engine.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved)
        receipt = gateway.execute(
            ToolRequest(
                request_id="REQ-LIVE-REJECT-001",
                run_id="RUN-LIVE-REJECT-001",
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=params,
                approval_token=approval.approval_token,
                business_id="biz-live",
                project_id="proj-live",
            )
        )
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("PROVIDER_REJECTED", receipt.error_class)
        self.assertNotEqual("AMBIGUOUS_EXTERNAL_ACTION_OUTCOME", receipt.error_class)
        intents = receipts.list_execution_intents_for_run("RUN-LIVE-REJECT-001")
        self.assertEqual("FINALIZED", intents[0].state.value)
        self.assertNotIn(secret_provider.secret, repr(receipt.model_dump()))


if __name__ == "__main__":
    unittest.main()
