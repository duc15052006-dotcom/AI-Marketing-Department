"""Regression tests for durable receipts and consequential side-effect recovery.

PLATFORM-DURABLE-RECEIPTS-RECONCILIATION-V1
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import (
    ExecutionIntentState,
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreError,
    ReceiptStoreIntegrityError,
    ReconciliationOutcome,
)
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class JournalAwareAdapter(BaseCapabilityAdapter):
    def __init__(
        self,
        repository: ExecutionReceiptRepository,
        outcome: Any,
        *,
        name: str = "durable_publish_adapter",
    ) -> None:
        self.repository = repository
        self.outcome = outcome
        self._name = name
        self.call_count = 0
        self.state_seen_during_dispatch = None

    @property
    def adapter_name(self) -> str:
        return self._name

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return ExecutionMode.REAL

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        self.call_count += 1
        intents = self.repository.list_execution_intents_for_run(run_id)
        if intents:
            self.state_seen_during_dispatch = intents[-1].state
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FailingDispatchJournalRepository(ExecutionReceiptRepository):
    def mark_execution_intent_dispatching(self, intent_id: str):
        raise ReceiptStoreError("simulated durable journal failure")


class DurableReceiptsReconciliationV1Tests(unittest.TestCase):
    def _receipt(self, *, execution_id: str = "EXEC-DURABLE-001") -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id=execution_id,
            run_id="RUN-DURABLE-001",
            agent_id="intelligence",
            capability_id="web_search",
            provider="search_adapter",
            request_hash="req-hash-durable-001",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            data={"ok": True},
        )

    @staticmethod
    def _register_publish(
        gateway: ToolGateway,
        registry: CapabilityRegistry,
        adapter: BaseCapabilityAdapter,
    ) -> None:
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id="durable_publish",
                name="Durable Publish",
                category=CapabilityCategory.PUBLISH,
                description="Consequential external-write durability regression.",
                provider=adapter.adapter_name,
                supported_agents=["cmo"],
                required_permissions=[
                    PermissionLevel.EXTERNAL_WRITE,
                    PermissionLevel.PUBLISH,
                ],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                retry_policy={
                    "max_retries": 2,
                    "backoff_seconds": 0.0,
                    "retryable_errors": ["NETWORK_ERROR", "TIMEOUT"],
                },
            )
        )

    @staticmethod
    def _approved_request(
        policy: PolicyEngine,
        *,
        parameters: Dict[str, Any] | None = None,
        run_id: str = "RUN-PUBLISH-DURABLE-001",
    ) -> ToolRequest:
        params = parameters or {"message": "publish once"}
        approval = policy.create_server_approval(
            capability_id="durable_publish",
            parameters=params,
            run_id=run_id,
            approved_by="durable receipt regression",
            risk_level=RiskLevel.CRITICAL,
        )
        return ToolRequest(
            request_id="REQ-PUBLISH-DURABLE-001",
            run_id=run_id,
            agent_id="cmo",
            capability_id="durable_publish",
            parameters=params,
            approval_token=approval.approval_token,
        )

    def test_sqlite_receipt_survives_restart_and_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "receipts.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db_path)
            saved = repo.save_receipt(self._receipt())
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db_path)
            loaded = reopened.get_receipt(saved.execution_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.data, {"ok": True})
            reopened.close()

            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "UPDATE execution_receipts SET payload_json=? WHERE execution_id=?",
                ('{"execution_id":"EXEC-DURABLE-001","tampered":true}', saved.execution_id),
            )
            conn.commit()
            conn.close()

            tampered = ExecutionReceiptRepository(database_path=db_path)
            with self.assertRaises(ReceiptStoreIntegrityError):
                tampered.get_receipt(saved.execution_id)
            tampered.close()

    def test_sqlite_receipt_index_column_tamper_is_detected(self) -> None:
        tamper_cases = (
            ("run_id", "RUN-TAMPERED"),
            ("agent_id", "creative"),
            ("capability_id", "publish_social"),
            ("status", ExecutionStatus.ERROR.value),
        )
        for column, tampered_value in tamper_cases:
            with self.subTest(column=column):
                with tempfile.TemporaryDirectory() as tmp:
                    db_path = Path(tmp) / "index-tamper.sqlite3"
                    repo = ExecutionReceiptRepository(database_path=db_path)
                    saved = repo.save_receipt(self._receipt())
                    repo.close()

                    conn = sqlite3.connect(str(db_path))
                    conn.execute(
                        f"UPDATE execution_receipts SET {column}=? WHERE execution_id=?",
                        (tampered_value, saved.execution_id),
                    )
                    conn.commit()
                    conn.close()

                    tampered = ExecutionReceiptRepository(database_path=db_path)
                    with self.assertRaises(ReceiptStoreIntegrityError):
                        tampered.get_receipt(saved.execution_id)
                    tampered.close()

    def test_prepared_intent_proves_dispatch_had_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "intent.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db_path)
            intent = repo.prepare_execution_intent(
                request_id="REQ-PREPARED",
                run_id="RUN-PREPARED",
                agent_id="cmo",
                capability_id="durable_publish",
                provider="durable_publish_adapter",
                request_hash="hash-prepared",
            )
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db_path)
            assessment = reopened.assess_execution_intent(intent.intent_id)
            self.assertEqual(assessment.outcome, ReconciliationOutcome.NOT_DISPATCHED)
            current = reopened.get_execution_intent(intent.intent_id)
            self.assertEqual(current.state, ExecutionIntentState.PREPARED)
            self.assertEqual(current.dispatch_count, 0)
            reopened.close()

    def test_dispatching_without_receipt_becomes_ambiguous_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ambiguous.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db_path)
            intent = repo.prepare_execution_intent(
                request_id="REQ-AMBIGUOUS",
                run_id="RUN-AMBIGUOUS",
                agent_id="cmo",
                capability_id="durable_publish",
                provider="durable_publish_adapter",
                request_hash="hash-ambiguous",
            )
            repo.mark_execution_intent_dispatching(intent.intent_id)
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db_path)
            assessments = reopened.reconcile_unfinished_intents()
            self.assertEqual(len(assessments), 1)
            self.assertEqual(
                assessments[0].outcome,
                ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME,
            )
            current = reopened.get_execution_intent(intent.intent_id)
            self.assertEqual(current.state, ExecutionIntentState.AMBIGUOUS)
            self.assertEqual(current.dispatch_count, 1)
            self.assertIsNone(current.receipt_execution_id)
            reopened.close()

    def test_gateway_persists_dispatching_before_adapter_and_finalizes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "gateway.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db_path)
            registry = CapabilityRegistry()
            policy = PolicyEngine()
            gateway = ToolGateway(
                capability_registry=registry,
                policy_engine=policy,
                receipt_repository=repo,
            )
            adapter = JournalAwareAdapter(
                repo,
                AdapterResult(success=True, data={"published": True}),
            )
            self._register_publish(gateway, registry, adapter)
            request = self._approved_request(policy)

            receipt = gateway.execute(request)

            self.assertEqual(adapter.call_count, 1)
            self.assertEqual(
                adapter.state_seen_during_dispatch,
                ExecutionIntentState.DISPATCHING,
            )
            intents = repo.list_execution_intents_for_run(request.run_id)
            self.assertEqual(len(intents), 1)
            self.assertEqual(intents[0].state, ExecutionIntentState.FINALIZED)
            self.assertEqual(intents[0].receipt_execution_id, receipt.execution_id)
            assessment = repo.assess_execution_intent(intents[0].intent_id)
            self.assertEqual(
                assessment.outcome,
                ReconciliationOutcome.CONFIRMED_FINALIZED,
            )
            repo.close()

            reopened = ExecutionReceiptRepository(database_path=db_path)
            persisted = reopened.get_receipt(receipt.execution_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.status, ExecutionStatus.SUCCESS)
            reopened.close()

    def test_consequential_exception_is_persisted_ambiguous_and_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = ExecutionReceiptRepository(
                database_path=Path(tmp) / "exception.sqlite3"
            )
            registry = CapabilityRegistry()
            policy = PolicyEngine()
            gateway = ToolGateway(
                capability_registry=registry,
                policy_engine=policy,
                receipt_repository=repo,
            )
            adapter = JournalAwareAdapter(
                repo,
                TimeoutError("remote response lost after dispatch"),
            )
            self._register_publish(gateway, registry, adapter)
            request = self._approved_request(policy, run_id="RUN-AMBIG-PUBLISH")

            receipt = gateway.execute(request)

            self.assertEqual(adapter.call_count, 1)
            self.assertEqual(
                receipt.error_class,
                "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME",
            )
            intents = repo.list_execution_intents_for_run(request.run_id)
            self.assertEqual(intents[0].state, ExecutionIntentState.AMBIGUOUS)
            assessment = repo.assess_execution_intent(intents[0].intent_id)
            self.assertEqual(
                assessment.outcome,
                ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME,
            )
            repo.close()

    def test_journal_failure_blocks_external_dispatch(self) -> None:
        repo = FailingDispatchJournalRepository()
        registry = CapabilityRegistry()
        policy = PolicyEngine()
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=repo,
        )
        adapter = JournalAwareAdapter(
            repo,
            AdapterResult(success=True, data={"published": True}),
        )
        self._register_publish(gateway, registry, adapter)
        request = self._approved_request(policy, run_id="RUN-JOURNAL-FAIL")

        with self.assertRaises(ReceiptStoreError):
            gateway.execute(request)

        self.assertEqual(adapter.call_count, 0)

    def test_raw_request_secret_is_not_written_to_durable_journal(self) -> None:
        secret = "SUPER-SECRET-API-KEY-987654321"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "redaction.sqlite3"
            repo = ExecutionReceiptRepository(database_path=db_path)
            registry = CapabilityRegistry()
            policy = PolicyEngine()
            gateway = ToolGateway(
                capability_registry=registry,
                policy_engine=policy,
                receipt_repository=repo,
            )
            adapter = JournalAwareAdapter(
                repo,
                AdapterResult(success=True, data={"published": True}),
            )
            self._register_publish(gateway, registry, adapter)
            request = self._approved_request(
                policy,
                parameters={"message": "publish", "api_key": secret},
                run_id="RUN-SECRET-JOURNAL",
            )

            gateway.execute(request)
            repo.close()

            conn = sqlite3.connect(str(db_path))
            intent_rows = conn.execute(
                "SELECT request_hash, approval_reference, last_error_message "
                "FROM execution_intents"
            ).fetchall()
            receipt_rows = conn.execute(
                "SELECT payload_json FROM execution_receipts"
            ).fetchall()
            conn.close()
            persisted_text = repr(intent_rows) + repr(receipt_rows)
            self.assertNotIn(secret, persisted_text)
            self.assertNotIn(request.approval_token, persisted_text)


if __name__ == "__main__":
    unittest.main()
