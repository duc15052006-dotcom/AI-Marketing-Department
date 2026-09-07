"""Adversarial RED for canonical Brain ActionIntent -> durable ExecutionIntent provenance.

Invariant: once ToolGateway validates canonical semantic ActionIntent authority for a
consequential capability, the pre-dispatch journal must bind that exact
ActionIntent.intent_id before adapter execution. The binding must survive SQLite
restart, participate in the intent integrity hash, preserve historical schema-v1
rows, and agree with the final ExecutionReceipt semantic provenance.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from brain.action_policy import ActionAuthorization, ActionDisposition
from tests.test_brain_canonical_action_intent_tool_gateway_v1 import (
    BrainCanonicalActionIntentToolGatewayV1Tests as CanonicalGatewayContract,
)
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    RiskLevel,
)
from tools.receipts import (
    ExecutionIntent,
    ExecutionIntentState,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ReceiptStoreIntegrityError,
)
from tools.tool_gateway import ToolGateway, ToolRequest


class ObservingConsequentialAdapter(BaseCapabilityAdapter):
    def __init__(self, before_return: Optional[Callable[[], None]] = None) -> None:
        self.before_return = before_return
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "action_intent_journal_adapter"

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
        if self.before_return is not None:
            self.before_return()
        return AdapterResult(success=True, data={"ok": True, "call_count": self.call_count})


class MismatchingReceiptRepository(ExecutionReceiptRepository):
    """Adversarial repository that corrupts only receipt semantic provenance."""

    def finalize_execution_intent(
        self,
        intent_id: str,
        receipt: ExecutionReceipt,
        *,
        ambiguous: bool = False,
    ) -> ExecutionReceipt:
        payload = receipt.model_dump()
        payload["action_intent_id"] = "AI-FOREIGN"
        return super().finalize_execution_intent(
            intent_id,
            ExecutionReceipt(**payload),
            ambiguous=ambiguous,
        )


class BrainActionIntentExecutionIntentProvenanceV1Tests(unittest.TestCase):
    CAPABILITY_ID = "semantic_consequential_journal_test"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "receipts.sqlite3"
        self.repo = ExecutionReceiptRepository(database_path=self.db_path)

    def tearDown(self) -> None:
        try:
            self.repo.close()
        except Exception:
            pass
        self._tmp.cleanup()

    @staticmethod
    def _structural_allow(intent):
        return ActionAuthorization(
            intent_id=intent.intent_id,
            disposition=ActionDisposition.ALLOW,
            reason="test structural allow after canonical semantic validation",
        )

    def _gateway(
        self,
        *,
        repo: Optional[ExecutionReceiptRepository] = None,
        adapter: Optional[BaseCapabilityAdapter] = None,
    ) -> tuple[ToolGateway, BaseCapabilityAdapter]:
        repository = repo or self.repo
        registry = CapabilityRegistry()
        adapter = adapter or ObservingConsequentialAdapter()
        gateway = ToolGateway(
            capability_registry=registry,
            receipt_repository=repository,
            action_authorizer=self._structural_allow,
        )
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Semantic consequential journal regression capability",
                category=CapabilityCategory.PUBLISH,
                description="Test-only consequential capability for semantic journal provenance.",
                provider=adapter.adapter_name,
                supported_agents=["strategist"],
                required_permissions=[],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                retry_policy={
                    "max_retries": 0,
                    "backoff_seconds": 0.0,
                    "retryable_errors": [],
                },
                semantic_needs=["MARKET_RESEARCH"],
            )
        )
        return gateway, adapter

    @classmethod
    def _request(cls, run_id: str, *, approval_token: Optional[str] = None) -> ToolRequest:
        return ToolRequest(
            request_id=f"REQ-{run_id}",
            run_id=run_id,
            agent_id="strategist",
            capability_id=cls.CAPABILITY_ID,
            parameters={"payload": "semantic journal provenance"},
            approval_token=approval_token,
        )

    def _execute_semantic(self, gateway: ToolGateway, run_id: str):
        unsigned_request = self._request(run_id)
        approval = gateway.policy_engine.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=unsigned_request.parameters,
            run_id=run_id,
            approved_by="semantic journal provenance regression",
            risk_level=RiskLevel.LOW,
        )
        return gateway.execute(
            self._request(run_id, approval_token=approval.approval_token),
            action_intent=CanonicalGatewayContract._intent(),
            decision_request=CanonicalGatewayContract._decision_request(),
        )

    def test_action_intent_id_is_journaled_before_adapter_dispatch(self) -> None:
        observed = []

        def observe_pre_dispatch_journal() -> None:
            intents = self.repo.list_execution_intents_for_run("RUN-JOURNAL-SEM-001")
            self.assertEqual(1, len(intents))
            observed.append(intents[0])

        adapter = ObservingConsequentialAdapter(observe_pre_dispatch_journal)
        gateway, _ = self._gateway(adapter=adapter)
        receipt = self._execute_semantic(gateway, "RUN-JOURNAL-SEM-001")

        self.assertEqual(1, adapter.call_count)
        self.assertEqual(1, len(observed))
        self.assertEqual(ExecutionIntentState.DISPATCHING, observed[0].state)
        self.assertEqual(
            "AI-GW-1",
            getattr(observed[0], "action_intent_id", None),
            "STILL_PRESENT: pre-dispatch ExecutionIntent loses canonical ActionIntent provenance.",
        )
        self.assertEqual("AI-GW-1", receipt.action_intent_id)

    def test_sqlite_restart_preserves_action_intent_journal_provenance(self) -> None:
        gateway, _ = self._gateway()
        self._execute_semantic(gateway, "RUN-JOURNAL-SEM-002")
        self.repo.close()

        reopened = ExecutionReceiptRepository(database_path=self.db_path)
        try:
            intents = reopened.list_execution_intents_for_run("RUN-JOURNAL-SEM-002")
            self.assertEqual(1, len(intents))
            self.assertEqual(
                "AI-GW-1",
                getattr(intents[0], "action_intent_id", None),
                "STILL_PRESENT: SQLite restart loses ActionIntent journal provenance.",
            )
        finally:
            reopened.close()

    def test_semantic_journal_tamper_is_detected_by_record_hash(self) -> None:
        gateway, _ = self._gateway()
        self._execute_semantic(gateway, "RUN-JOURNAL-SEM-003")
        self.repo.close()

        conn = sqlite3.connect(self.db_path)
        try:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(execution_intents)").fetchall()
            }
            self.assertIn(
                "action_intent_id",
                columns,
                "STILL_PRESENT: durable ExecutionIntent schema has no ActionIntent provenance column.",
            )
            conn.execute(
                "UPDATE execution_intents SET action_intent_id=? WHERE run_id=?",
                ("AI-TAMPERED", "RUN-JOURNAL-SEM-003"),
            )
            conn.commit()
        finally:
            conn.close()

        reopened = ExecutionReceiptRepository(database_path=self.db_path)
        try:
            with self.assertRaises(
                ReceiptStoreIntegrityError,
                msg="STILL_PRESENT: ActionIntent journal provenance is outside record_hash integrity.",
            ):
                reopened.list_execution_intents_for_run("RUN-JOURNAL-SEM-003")
        finally:
            reopened.close()

    def test_finalization_rejects_receipt_with_foreign_action_intent_provenance(self) -> None:
        bad_repo = MismatchingReceiptRepository(database_path=Path(self._tmp.name) / "bad.sqlite3")
        try:
            gateway, adapter = self._gateway(repo=bad_repo)
            with self.assertRaises(
                ReceiptStoreIntegrityError,
                msg="STILL_PRESENT: journal and receipt can disagree on canonical ActionIntent provenance.",
            ):
                self._execute_semantic(gateway, "RUN-JOURNAL-SEM-004")
            self.assertEqual(1, adapter.call_count)
        finally:
            bad_repo.close()

    def test_historical_schema_v1_database_migrates_without_rehashing_old_record(self) -> None:
        historical_path = Path(self._tmp.name) / "historical-v1.sqlite3"
        historical = ExecutionIntent(
            intent_id="INTENT-HIST-V1",
            request_id="REQ-HIST-V1",
            run_id="RUN-HIST-V1",
            agent_id="cmo",
            capability_id="social_publishing",
            provider="historical-provider",
            request_hash="h" * 64,
            schema_version=1,
        ).normalized()

        conn = sqlite3.connect(historical_path)
        try:
            conn.executescript(
                """
                CREATE TABLE execution_receipts (
                    execution_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TABLE execution_intents (
                    intent_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    business_id TEXT,
                    project_id TEXT,
                    chat_id TEXT,
                    approval_reference TEXT,
                    dispatch_count INTEGER NOT NULL DEFAULT 0,
                    receipt_execution_id TEXT,
                    last_error_class TEXT,
                    last_error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    record_hash TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO execution_intents(
                    intent_id, request_id, run_id, agent_id, capability_id, provider,
                    request_hash, state, business_id, project_id, chat_id,
                    approval_reference, dispatch_count, receipt_execution_id,
                    last_error_class, last_error_message, created_at, updated_at,
                    schema_version, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    historical.intent_id,
                    historical.request_id,
                    historical.run_id,
                    historical.agent_id,
                    historical.capability_id,
                    historical.provider,
                    historical.request_hash,
                    historical.state.value,
                    historical.business_id,
                    historical.project_id,
                    historical.chat_id,
                    historical.approval_reference,
                    historical.dispatch_count,
                    historical.receipt_execution_id,
                    historical.last_error_class,
                    historical.last_error_message,
                    historical.created_at,
                    historical.updated_at,
                    historical.schema_version,
                    historical.record_hash,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        migrated = ExecutionReceiptRepository(database_path=historical_path)
        try:
            loaded = migrated.get_execution_intent("INTENT-HIST-V1")
            self.assertIsNotNone(loaded)
            self.assertEqual(1, loaded.schema_version)
            self.assertTrue(loaded.verify_integrity())
            self.assertIsNone(getattr(loaded, "action_intent_id", None))
            columns = {
                row[1]
                for row in migrated._conn.execute("PRAGMA table_info(execution_intents)").fetchall()
            }
            self.assertIn(
                "action_intent_id",
                columns,
                "STILL_PRESENT: opening a historical v1 DB does not migrate semantic provenance schema.",
            )
        finally:
            migrated.close()


if __name__ == "__main__":
    unittest.main()
