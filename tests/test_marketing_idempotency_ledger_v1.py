from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
    MarketingLiveExecutorRegistry,
    MarketingLiveExecutorResult,
)
from tools.idempotency import IdempotencyLedger, IdempotencyState
from tools.receipts import ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolRequest


class CountingSecretProvider:
    def __init__(self, secret: str = "IDEMPOTENCY-LIVE-SECRET") -> None:
        self.secret = secret
        self.get_calls = 0

    def can_resolve(self, secret_ref: str) -> bool:
        return str(secret_ref).startswith("env:")

    def get(self, secret_ref: str) -> SecretValue:
        self.get_calls += 1
        return SecretValue(self.secret)


class CountingLiveExecutor:
    executor_name = "counting-idempotency-live-executor"
    provider = "meta"

    def __init__(self, *, behavior: str = "success") -> None:
        self.behavior = behavior
        self.calls = 0

    def execute(self, *, prepared, request, credential, timeout_seconds):
        self.calls += 1
        secret = credential.reveal() if credential is not None else ""
        if self.behavior == "raise_uncertain":
            raise RuntimeError(f"provider outcome uncertain after credential={secret}")
        return MarketingLiveExecutorResult(
            success=True,
            data={
                "status": "LIVE_EXECUTED",
                "provider_network_called": True,
                "external_side_effect": True,
                "request_fingerprint": prepared.request_fingerprint,
            },
        )


class MarketingIdempotencyLedgerV1Tests(unittest.TestCase):
    @staticmethod
    def _publish_capability() -> str:
        return "marketing.conn_meta_idem.social_publishing"

    @staticmethod
    def _parameters(*, key: str = "idem-durable-live-0001", caption: str = "first caption"):
        return {
            "connection_id": "meta-idem-main",
            "action": "publish_post",
            "resource_type": "post",
            "idempotency_key": key,
            "payload": {"caption": caption},
        }

    def _build(self, *, database_path=None, behavior: str = "success"):
        secret_provider = CountingSecretProvider()
        connection_manager = ConnectionManager(secret_provider)
        connection_manager.register(
            ConnectionProfile(
                connection_id="meta-idem-main",
                provider="meta",
                display_name="Meta Idempotency Main",
                secret_ref="env:META_IDEMPOTENCY_TOKEN",
                business_id="biz-idem",
                project_ids=("proj-idem",),
            )
        )

        connector_registry = ConnectorRegistry()
        connector_registry.register_connector(
            ConnectorDescriptor(
                connector_id="conn_meta_idem",
                provider="meta",
                capability_ids=["social_publishing"],
                authentication_type=AuthenticationType.BEARER_TOKEN,
                read_write_mode=ReadWriteMode.READ_WRITE,
                risk_level=RiskLevel.CRITICAL,
                supported_operations=["publish_post"],
            )
        )
        control_plane = ConnectorControlPlane(connector_registry, connection_manager)
        control_plane.bind("conn_meta_idem", "meta-idem-main")

        marketing_registry = MarketingConnectorRegistry(
            control_plane,
            allow_live_registration=True,
        )
        marketing_registry.register(
            MarketingConnectorSpec(
                connector_id="conn_meta_idem",
                provider="meta",
                supported_capabilities=("social_publishing",),
                execution_mode=MarketingExecutionMode.LIVE,
            )
        )

        receipts = ExecutionReceiptRepository(database_path=database_path)
        executor_registry = MarketingLiveExecutorRegistry(marketing_registry)
        executor = CountingLiveExecutor(behavior=behavior)
        executor_registry.bind("conn_meta_idem", executor)
        policy = PolicyEngine()
        gateway = DynamicToolGateway(
            marketing_registry=marketing_registry,
            marketing_live_executor_registry=executor_registry,
            allow_live_marketing_execution=True,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        report = gateway.sync_all()
        self.assertTrue(report.success, report.errors)
        return secret_provider, receipts, executor, policy, gateway

    def _approved_execute(self, gateway, policy, *, run_id: str, parameters):
        pending = gateway.execute(
            ToolRequest(
                request_id=f"REQ-{run_id}",
                run_id=run_id,
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=parameters,
                business_id="biz-idem",
                project_id="proj-idem",
            )
        )
        self.assertEqual(ExecutionStatus.APPROVAL_REQUIRED, pending.status)
        approved, approval, reason = policy.approve_pending_action(pending.approval_reference)
        self.assertTrue(approved, reason)
        return gateway.execute(
            ToolRequest(
                request_id=f"REQ-{run_id}",
                run_id=run_id,
                agent_id="cmo",
                capability_id=self._publish_capability(),
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id="biz-idem",
                project_id="proj-idem",
            )
        )

    def test_same_key_same_action_is_blocked_across_new_run_and_new_approval(self) -> None:
        secret_provider, _, executor, policy, gateway = self._build()
        params = self._parameters()

        first = self._approved_execute(gateway, policy, run_id="RUN-IDEM-001", parameters=params)
        self.assertEqual(ExecutionStatus.SUCCESS, first.status)
        second = self._approved_execute(gateway, policy, run_id="RUN-IDEM-002", parameters=params)

        self.assertEqual(ExecutionStatus.BLOCKED, second.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
        self.assertEqual(1, executor.calls)
        self.assertEqual(1, secret_provider.get_calls)
        records = gateway.gateway.idempotency_ledger.list_records()
        self.assertEqual(1, len(records))
        self.assertEqual(IdempotencyState.FINALIZED, records[0].state)
        self.assertNotIn(params["idempotency_key"], repr(records[0]))

    def test_same_key_with_changed_payload_is_conflict_not_second_dispatch(self) -> None:
        _, _, executor, policy, gateway = self._build()
        first = self._approved_execute(
            gateway,
            policy,
            run_id="RUN-IDEM-CONFLICT-001",
            parameters=self._parameters(caption="payload A"),
        )
        self.assertEqual(ExecutionStatus.SUCCESS, first.status)

        second = self._approved_execute(
            gateway,
            policy,
            run_id="RUN-IDEM-CONFLICT-002",
            parameters=self._parameters(caption="payload B"),
        )
        self.assertEqual(ExecutionStatus.BLOCKED, second.status)
        self.assertEqual("IDEMPOTENCY_KEY_CONFLICT", second.error_class)
        self.assertEqual(1, executor.calls)

    def test_ambiguous_provider_outcome_keeps_key_blocked(self) -> None:
        _, _, executor, policy, gateway = self._build(behavior="raise_uncertain")
        params = self._parameters(key="idem-ambiguous-live-0001")

        first = self._approved_execute(
            gateway,
            policy,
            run_id="RUN-IDEM-AMB-001",
            parameters=params,
        )
        self.assertEqual(ExecutionStatus.ERROR, first.status)
        self.assertEqual("AMBIGUOUS_EXTERNAL_ACTION_OUTCOME", first.error_class)
        records = gateway.gateway.idempotency_ledger.list_records()
        self.assertEqual(IdempotencyState.AMBIGUOUS, records[0].state)

        second = self._approved_execute(
            gateway,
            policy,
            run_id="RUN-IDEM-AMB-002",
            parameters=params,
        )
        self.assertEqual(ExecutionStatus.BLOCKED, second.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
        self.assertEqual(1, executor.calls)

    def test_file_backed_ledger_blocks_replay_after_process_style_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "tool-evidence.sqlite3"
            _, receipts1, executor1, policy1, gateway1 = self._build(
                database_path=database_path
            )
            params = self._parameters(key="idem-restart-live-0001")
            first = self._approved_execute(
                gateway1,
                policy1,
                run_id="RUN-IDEM-RESTART-001",
                parameters=params,
            )
            self.assertEqual(ExecutionStatus.SUCCESS, first.status)
            self.assertEqual(1, executor1.calls)
            receipts1.close()

            secret_provider2, receipts2, executor2, policy2, gateway2 = self._build(
                database_path=database_path
            )
            second = self._approved_execute(
                gateway2,
                policy2,
                run_id="RUN-IDEM-RESTART-002",
                parameters=params,
            )
            self.assertEqual(ExecutionStatus.BLOCKED, second.status)
            self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
            self.assertEqual(0, executor2.calls)
            self.assertEqual(0, secret_provider2.get_calls)
            records = gateway2.gateway.idempotency_ledger.list_records()
            self.assertEqual(1, len(records))
            self.assertEqual(IdempotencyState.FINALIZED, records[0].state)
            receipts2.close()

    def test_raw_idempotency_key_is_not_persisted_in_durable_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "tool-evidence.sqlite3"
            raw_key = "idem-never-persist-raw-0001"
            _, receipts, _, policy, gateway = self._build(database_path=database_path)
            result = self._approved_execute(
                gateway,
                policy,
                run_id="RUN-IDEM-RAW-001",
                parameters=self._parameters(key=raw_key),
            )
            self.assertEqual(ExecutionStatus.SUCCESS, result.status)
            records = gateway.gateway.idempotency_ledger.list_records()
            self.assertEqual(1, len(records))
            self.assertNotIn(raw_key, repr(records[0]))
            receipts.close()
            self.assertNotIn(raw_key.encode("utf-8"), database_path.read_bytes())

    def test_same_literal_key_is_namespaced_by_connection(self) -> None:
        ledger = IdempotencyLedger()
        params = self._parameters(key="idem-namespace-live-0001")
        first = ledger.reserve(
            capability_id=self._publish_capability(),
            provider="marketing-live:conn_meta_idem",
            idempotency_key=params["idempotency_key"],
            connection_id="meta-idem-main",
            parameters=params,
            business_id="biz-idem",
            project_id="proj-idem",
            brand_id=None,
        )
        second_params = dict(params)
        second_params["connection_id"] = "meta-idem-alt"
        second = ledger.reserve(
            capability_id=self._publish_capability(),
            provider="marketing-live:conn_meta_idem",
            idempotency_key=params["idempotency_key"],
            connection_id="meta-idem-alt",
            parameters=second_params,
            business_id="biz-idem",
            project_id="proj-idem",
            brand_id=None,
        )
        self.assertNotEqual(first.reservation_id, second.reservation_id)
        self.assertEqual(2, len(ledger.list_records()))


if __name__ == "__main__":
    unittest.main()
