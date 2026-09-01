"""Adversarial regression for canonical adapter idempotency authority.

RED requirements:
- provider aliases are configuration, not external-action identity;
- changing only an alias must not permit a second REAL dispatch;
- a durable reservation must remain authoritative after process restart even
  when the old alias is no longer registered and the adapter object is new;
- opaque pre-upgrade alias reservations must fail closed after that restart.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

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


class RealCountingAdapter(BaseCapabilityAdapter):
    def __init__(self) -> None:
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "canonical_real_publish_adapter"

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
            data={"external_side_effect_count": self.call_count},
            execution_mode=ExecutionMode.REAL,
        )


class IdempotencyCanonicalAdapterDurabilityV2Tests(unittest.TestCase):
    CAPABILITY_ID = "alias_bound_real_publish"
    ALIAS_A = "provider_alias_a"
    ALIAS_B = "provider_alias_b"
    BUSINESS_ID = "BIZ-ALIAS-IDEM"
    PROJECT_ID = "PROJ-ALIAS-IDEM"
    KEY = "idem-canonical-adapter-authority-001"

    @classmethod
    def _descriptor(cls, provider: str) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id=cls.CAPABILITY_ID,
            name="Alias-bound real publish",
            category=CapabilityCategory.PUBLISH,
            description="Regression fixture for canonical adapter idempotency authority.",
            required_permissions=[PermissionLevel.PUBLISH, PermissionLevel.EXTERNAL_WRITE],
            risk_level=RiskLevel.CRITICAL,
            human_approval_required=True,
            supported_agents=["cmo"],
            provider=provider,
            retry_policy={"max_retries": 0, "backoff_seconds": 0.0, "retryable_errors": []},
        )

    @classmethod
    def _parameters(cls) -> Dict[str, Any]:
        return {
            "idempotency_key": cls.KEY,
            "payload": {"caption": "same governed external action"},
        }

    def _build(
        self,
        database_path: Optional[Path],
        *,
        provider: str,
        aliases: Iterable[str],
    ):
        registry = CapabilityRegistry()
        registry.register_capability(self._descriptor(provider))
        policy = PolicyEngine()
        receipts = ExecutionReceiptRepository(database_path=database_path)
        gateway = ToolGateway(
            capability_registry=registry,
            policy_engine=policy,
            receipt_repository=receipts,
        )
        adapter = RealCountingAdapter()
        for alias in aliases:
            gateway.bind_adapter_alias(alias, adapter)
        return registry, policy, receipts, gateway, adapter

    def _approved_execute(
        self,
        gateway: ToolGateway,
        policy: PolicyEngine,
        *,
        run_id: str,
    ):
        parameters = self._parameters()
        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=parameters,
            run_id=run_id,
            business_id=self.BUSINESS_ID,
            project_id=self.PROJECT_ID,
            risk_level=RiskLevel.CRITICAL,
        )
        return gateway.execute(
            ToolRequest(
                request_id=f"REQ-{run_id}",
                run_id=run_id,
                agent_id="cmo",
                capability_id=self.CAPABILITY_ID,
                parameters=parameters,
                approval_token=approval.approval_token,
                business_id=self.BUSINESS_ID,
                project_id=self.PROJECT_ID,
            )
        )

    def test_same_adapter_cannot_replay_after_alias_change_in_process(self) -> None:
        for label, database_path in self._storage_variants():
            with self.subTest(storage=label):
                registry, policy, receipts, gateway, adapter = self._build(
                    database_path,
                    provider=self.ALIAS_A,
                    aliases=(self.ALIAS_A, self.ALIAS_B),
                )
                try:
                    first = self._approved_execute(gateway, policy, run_id=f"RUN-{label}-A")
                    self.assertEqual(ExecutionStatus.SUCCESS, first.status)
                    self.assertEqual(1, adapter.call_count)

                    registry.register_capability(self._descriptor(self.ALIAS_B))
                    second = self._approved_execute(gateway, policy, run_id=f"RUN-{label}-B")
                    self.assertEqual(ExecutionStatus.BLOCKED, second.status)
                    self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
                    self.assertEqual(1, adapter.call_count)
                    self.assertEqual(1, len(gateway.idempotency_ledger.list_records()))
                finally:
                    receipts.close()

    def test_durable_replay_is_blocked_after_restart_alias_removal_and_new_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "restart-alias-idempotency.sqlite3"

            _, policy_a, receipts_a, gateway_a, adapter_a = self._build(
                database_path,
                provider=self.ALIAS_A,
                aliases=(self.ALIAS_A,),
            )
            first = self._approved_execute(gateway_a, policy_a, run_id="RUN-RESTART-A")
            self.assertEqual(ExecutionStatus.SUCCESS, first.status)
            self.assertEqual(1, adapter_a.call_count)
            receipts_a.close()

            # Fresh process composition: alias A is gone and a new adapter object is
            # bound only to alias B. adapter_name remains the same external authority.
            _, policy_b, receipts_b, gateway_b, adapter_b = self._build(
                database_path,
                provider=self.ALIAS_B,
                aliases=(self.ALIAS_B,),
            )
            try:
                replay = self._approved_execute(gateway_b, policy_b, run_id="RUN-RESTART-B")
                self.assertEqual(ExecutionStatus.BLOCKED, replay.status)
                self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", replay.error_class)
                self.assertEqual(0, adapter_b.call_count)
                self.assertEqual(1, len(gateway_b.idempotency_ledger.list_records()))
            finally:
                receipts_b.close()

    def test_opaque_preupgrade_alias_reservation_fails_closed_after_alias_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "preupgrade-alias-idempotency.sqlite3"
            self._seed_opaque_legacy_reservation(database_path, provider=self.ALIAS_A)

            # Only alias B exists in the reconstructed runtime. There is deliberately
            # no registry evidence from which alias A can be rediscovered.
            _, policy, receipts, gateway, adapter = self._build(
                database_path,
                provider=self.ALIAS_B,
                aliases=(self.ALIAS_B,),
            )
            try:
                replay = self._approved_execute(gateway, policy, run_id="RUN-LEGACY-RESTART-B")
                self.assertEqual(ExecutionStatus.BLOCKED, replay.status)
                self.assertIn(
                    replay.error_class,
                    {"IDEMPOTENCY_REPLAY_BLOCKED", "IDEMPOTENCY_LEGACY_KEY_AMBIGUOUS"},
                )
                self.assertEqual(0, adapter.call_count)
                self.assertEqual(1, len(gateway.idempotency_ledger.list_records()))
            finally:
                receipts.close()

    def _seed_opaque_legacy_reservation(self, database_path: Path, *, provider: str) -> None:
        # Initialize the current table, then insert only the original seven-column
        # payload. Future migration columns must therefore use their legacy default.
        IdempotencyLedger(database_path=database_path)
        parameters = self._parameters()
        reservation_id, namespace_hash, key_hash = IdempotencyLedger.reservation_identity(
            capability_id=self.CAPABILITY_ID,
            provider=provider,
            idempotency_key=self.KEY,
            connection_id=None,
            business_id=self.BUSINESS_ID,
            project_id=self.PROJECT_ID,
            brand_id=None,
        )
        fingerprint = IdempotencyLedger.semantic_fingerprint(
            capability_id=self.CAPABILITY_ID,
            provider=provider,
            parameters=parameters,
            business_id=self.BUSINESS_ID,
            project_id=self.PROJECT_ID,
            brand_id=None,
        )
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(database_path)) as conn:
            conn.execute(
                """
                INSERT INTO idempotency_ledger(
                    reservation_id, namespace_hash, key_hash,
                    request_fingerprint, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reservation_id,
                    namespace_hash,
                    key_hash,
                    fingerprint,
                    "FINALIZED",
                    now,
                    now,
                ),
            )

    def _storage_variants(self):
        yield "memory", None
        with tempfile.TemporaryDirectory() as tmpdir:
            yield "sqlite", Path(tmpdir) / "same-process-alias-idempotency.sqlite3"


if __name__ == "__main__":
    unittest.main()
