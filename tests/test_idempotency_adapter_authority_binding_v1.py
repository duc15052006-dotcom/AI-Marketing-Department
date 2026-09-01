"""Adversarial regression for idempotency authority across provider aliases."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    PermissionLevel,
    RiskLevel,
)
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


class IdempotencyAdapterAuthorityBindingV1Tests(unittest.TestCase):
    CAPABILITY_ID = "alias_bound_real_publish"
    ALIAS_A = "provider_alias_a"
    ALIAS_B = "provider_alias_b"

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

    @staticmethod
    def _parameters() -> Dict[str, Any]:
        return {
            "idempotency_key": "idem-canonical-adapter-authority-001",
            "payload": {"caption": "same governed external action"},
        }

    def _approved_execute(
        self,
        gateway: ToolGateway,
        policy: PolicyEngine,
        *,
        run_id: str,
        parameters: Dict[str, Any],
    ):
        approval = policy.create_server_approval(
            capability_id=self.CAPABILITY_ID,
            parameters=parameters,
            run_id=run_id,
            business_id="BIZ-ALIAS-IDEM",
            project_id="PROJ-ALIAS-IDEM",
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
                business_id="BIZ-ALIAS-IDEM",
                project_id="PROJ-ALIAS-IDEM",
            )
        )

    def _build(self, database_path: Optional[Path], *, provider: str):
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
        gateway.bind_adapter_alias(self.ALIAS_A, adapter)
        gateway.bind_adapter_alias(self.ALIAS_B, adapter)
        return registry, policy, receipts, gateway, adapter

    def _exercise(self, database_path: Optional[Path]) -> tuple[ExecutionStatus, Optional[str], int, int]:
        registry, policy, receipts, gateway, adapter = self._build(
            database_path,
            provider=self.ALIAS_A,
        )
        parameters = self._parameters()

        first = self._approved_execute(
            gateway,
            policy,
            run_id="RUN-ALIAS-IDEM-001",
            parameters=parameters,
        )
        self.assertEqual(ExecutionStatus.SUCCESS, first.status)
        self.assertEqual(1, adapter.call_count)
        self.assertEqual(adapter.adapter_name, first.provider)

        # Provider alias is configuration, not execution authority: both aliases
        # resolve to the exact same REAL adapter instance and adapter_name.
        registry.register_capability(self._descriptor(self.ALIAS_B))
        second = self._approved_execute(
            gateway,
            policy,
            run_id="RUN-ALIAS-IDEM-002",
            parameters=parameters,
        )
        record_count = len(gateway.idempotency_ledger.list_records())
        call_count = adapter.call_count
        receipts.close()
        return second.status, second.error_class, call_count, record_count

    def _exercise_legacy_alias_reservation(
        self,
        database_path: Optional[Path],
    ) -> tuple[ExecutionStatus, Optional[str], int, int]:
        _, policy, receipts, gateway, adapter = self._build(
            database_path,
            provider=self.ALIAS_B,
        )
        parameters = self._parameters()

        # Simulate a reservation persisted by the pre-fix implementation, which
        # used the configurable provider alias as its idempotency authority.
        legacy = gateway.idempotency_ledger.reserve(
            capability_id=self.CAPABILITY_ID,
            provider=self.ALIAS_A,
            idempotency_key=parameters["idempotency_key"],
            connection_id=None,
            parameters=parameters,
            business_id="BIZ-ALIAS-IDEM",
            project_id="PROJ-ALIAS-IDEM",
            brand_id=None,
        )
        gateway.idempotency_ledger.mark_dispatching(legacy.reservation_id)
        gateway.idempotency_ledger.settle(legacy.reservation_id)

        replay = self._approved_execute(
            gateway,
            policy,
            run_id="RUN-ALIAS-IDEM-LEGACY-002",
            parameters=parameters,
        )
        record_count = len(gateway.idempotency_ledger.list_records())
        call_count = adapter.call_count
        receipts.close()
        return replay.status, replay.error_class, call_count, record_count

    def test_same_real_adapter_cannot_replay_same_key_after_provider_alias_change(self) -> None:
        observations = []
        observations.append(("memory",) + self._exercise(None))
        with tempfile.TemporaryDirectory() as tmpdir:
            observations.append(
                ("sqlite",)
                + self._exercise(Path(tmpdir) / "alias-idempotency.sqlite3")
            )

        expected = [
            ("memory", ExecutionStatus.BLOCKED, "IDEMPOTENCY_REPLAY_BLOCKED", 1, 1),
            ("sqlite", ExecutionStatus.BLOCKED, "IDEMPOTENCY_REPLAY_BLOCKED", 1, 1),
        ]
        self.assertEqual(expected, observations)

    def test_legacy_alias_reservation_remains_authoritative_after_canonicalization(self) -> None:
        observations = []
        observations.append(("memory",) + self._exercise_legacy_alias_reservation(None))
        with tempfile.TemporaryDirectory() as tmpdir:
            observations.append(
                ("sqlite",)
                + self._exercise_legacy_alias_reservation(
                    Path(tmpdir) / "legacy-alias-idempotency.sqlite3"
                )
            )

        expected = [
            ("memory", ExecutionStatus.BLOCKED, "IDEMPOTENCY_REPLAY_BLOCKED", 0, 1),
            ("sqlite", ExecutionStatus.BLOCKED, "IDEMPOTENCY_REPLAY_BLOCKED", 0, 1),
        ]
        self.assertEqual(expected, observations)


if __name__ == "__main__":
    unittest.main()
