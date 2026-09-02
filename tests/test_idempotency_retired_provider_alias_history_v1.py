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
from tools.idempotency import IdempotencyLedger
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class CountingCanonicalRealAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "canonical_retired_alias_publish_adapter"

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
        return AdapterResult(
            success=True,
            data={"external_side_effect": True, "call_count": self.call_count},
            execution_mode=ExecutionMode.REAL,
        )


class IdempotencyRetiredProviderAliasHistoryV1Tests(unittest.TestCase):
    CAPABILITY_ID = "retired_alias_history_publish"
    RETIRED_ALIAS = "retired_publish_provider_alias"
    PARAMS = {
        "idempotency_key": "idem-retired-alias-history-0001",
        "payload": {"caption": "same governed action after alias retirement"},
    }

    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.policy = PolicyEngine()
        self.receipts = ExecutionReceiptRepository()
        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=self.policy,
            receipt_repository=self.receipts,
        )
        self.adapter = CountingCanonicalRealAdapter()
        # The historical alias is intentionally NOT registered. This models an
        # alias that existed when the durable reservation was written but has
        # since been retired from the live adapter registry.
        self.gateway.register_adapter(self.adapter)
        self.registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Retired alias history publish",
                category=CapabilityCategory.PUBLISH,
                description="Regression capability for retired provider alias idempotency history.",
                provider=self.adapter.adapter_name,
                supported_agents=["cmo"],
                required_permissions=[
                    PermissionLevel.PUBLISH,
                    PermissionLevel.EXTERNAL_WRITE,
                ],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                retry_policy={
                    "max_retries": 0,
                    "backoff_seconds": 0.0,
                    "retryable_errors": [],
                },
            )
        )

    def _approved_execute(self, run_id: str):
        approval = self.policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=self.PARAMS,
            run_id=run_id,
            approved_by="retired provider alias history regression",
            risk_level=RiskLevel.CRITICAL,
        )
        return self.gateway.execute(
            ToolRequest(
                request_id=f"REQ-{run_id}",
                run_id=run_id,
                agent_id="cmo",
                capability_id=self.CAPABILITY_ID,
                parameters=self.PARAMS,
                approval_token=approval.approval_token,
            )
        )

    def test_retired_provider_alias_history_still_blocks_same_key_replay(self) -> None:
        # Simulate a completed consequential action written by a historical
        # implementation that used the provider alias as idempotency authority.
        legacy = self.gateway.idempotency_ledger.reserve(
            capability_id=self.CAPABILITY_ID,
            provider=self.RETIRED_ALIAS,
            idempotency_key=self.PARAMS["idempotency_key"],
            connection_id=None,
            parameters=self.PARAMS,
            business_id=None,
            project_id=None,
            brand_id=None,
        )
        self.gateway.idempotency_ledger.mark_dispatching(legacy.reservation_id)
        self.gateway.idempotency_ledger.settle(legacy.reservation_id)

        # The alias has been retired and is absent from the live adapter map.
        self.assertIsNone(self.gateway.get_adapter(self.RETIRED_ALIAS))

        replay = self._approved_execute("RUN-RETIRED-ALIAS-HISTORY-001")

        # Provider naming churn must not erase durable duplicate-execution
        # authority for the same consequential action/key.
        self.assertEqual(ExecutionStatus.BLOCKED, replay.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", replay.error_class)
        self.assertEqual(self.adapter.adapter_name, replay.provider)
        self.assertEqual(0, self.adapter.call_count)
        self.assertEqual(1, len(self.gateway.idempotency_ledger.list_records()))

    def test_pre_metadata_sqlite_history_remains_fail_closed_after_migration(self) -> None:
        # Build a database using the schema immediately before provider-neutral
        # authority metadata existed. The retired provider alias is intentionally
        # not recoverable from the live adapter registry after restart.
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "legacy-idempotency.sqlite3"
            reservation_id, namespace_hash, key_hash = IdempotencyLedger.reservation_identity(
                capability_id=self.CAPABILITY_ID,
                provider=self.RETIRED_ALIAS,
                idempotency_key=self.PARAMS["idempotency_key"],
                connection_id=None,
                business_id=None,
                project_id=None,
                brand_id=None,
            )
            request_fingerprint = IdempotencyLedger.semantic_fingerprint(
                capability_id=self.CAPABILITY_ID,
                provider=self.RETIRED_ALIAS,
                parameters=self.PARAMS,
                business_id=None,
                project_id=None,
                brand_id=None,
            )
            timestamp = "2026-08-01T00:00:00+00:00"
            with sqlite3.connect(str(database_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE idempotency_ledger (
                        reservation_id TEXT PRIMARY KEY,
                        namespace_hash TEXT NOT NULL,
                        key_hash TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL,
                        state TEXT NOT NULL,
                        retryable_pre_dispatch INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO idempotency_ledger(
                        reservation_id, namespace_hash, key_hash,
                        request_fingerprint, state, retryable_pre_dispatch,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        namespace_hash,
                        key_hash,
                        request_fingerprint,
                        "FINALIZED",
                        0,
                        timestamp,
                        timestamp,
                    ),
                )

            self.gateway.idempotency_ledger = IdempotencyLedger(
                database_path=database_path
            )
            replay = self._approved_execute("RUN-RETIRED-ALIAS-LEGACY-SQLITE-001")

            # Old rows cannot be given false provider lineage during migration.
            # Missing lineage must remain fail-closed instead of permitting a
            # potentially duplicate consequential external action.
            self.assertEqual(ExecutionStatus.BLOCKED, replay.status)
            self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", replay.error_class)
            self.assertEqual(0, self.adapter.call_count)
            self.assertEqual(1, len(self.gateway.idempotency_ledger.list_records()))


if __name__ == "__main__":
    unittest.main()
