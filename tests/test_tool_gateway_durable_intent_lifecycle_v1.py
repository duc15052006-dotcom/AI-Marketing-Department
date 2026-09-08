from __future__ import annotations

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
    ExecutionReceiptRepository,
    ExecutionStatus,
)
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class IntentProbeAdapter(BaseCapabilityAdapter):
    def __init__(
        self,
        *,
        repository: ExecutionReceiptRepository,
        name: str,
        raise_after_probe: bool = False,
    ) -> None:
        self._repository = repository
        self._name = name
        self._raise_after_probe = raise_after_probe
        self.call_count = 0
        self.intent_states_seen: list[list[ExecutionIntentState]] = []

    @property
    def adapter_name(self) -> str:
        return self._name

    def execution_mode_for(self, _capability_id: str) -> ExecutionMode:
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
        del capability_id, parameters, timeout_seconds, business_id, project_id
        self.call_count += 1
        intents = self._repository.list_execution_intents_for_run(run_id)
        self.intent_states_seen.append([intent.state for intent in intents])
        if self._raise_after_probe:
            raise ConnectionError("response lost after consequential dispatch")
        return AdapterResult(
            success=True,
            data={"dispatched": True},
            execution_mode=ExecutionMode.REAL,
        )


class ToolGatewayDurableIntentLifecycleV1Tests(unittest.TestCase):
    """Consequential dispatch must cross durable intent authority before adapter I/O."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.receipt_db = str(Path(self._tmp.name) / "receipts.sqlite3")
        self.registry = CapabilityRegistry()
        self.policy = PolicyEngine()
        self.receipts = ExecutionReceiptRepository(database_path=self.receipt_db)
        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=self.policy,
            receipt_repository=self.receipts,
        )

    def tearDown(self) -> None:
        self.receipts.close()
        self._tmp.cleanup()

    def _register_consequential(self, adapter: IntentProbeAdapter) -> None:
        self.gateway.register_adapter(adapter)
        self.registry.register_capability(
            CapabilityDescriptor(
                capability_id="durable_external_write",
                name="Durable External Write",
                category=CapabilityCategory.PUBLISH,
                description="Deterministic consequential dispatch contract probe.",
                provider=adapter.adapter_name,
                supported_agents=["cmo"],
                required_permissions=[PermissionLevel.EXTERNAL_WRITE],
                risk_level=RiskLevel.CRITICAL,
                human_approval_required=True,
                retry_policy={
                    "max_retries": 2,
                    "backoff_seconds": 0.0,
                    "retryable_errors": ["NETWORK_ERROR", "TIMEOUT"],
                },
            )
        )

    def _approved_request(self, *, run_id: str) -> ToolRequest:
        parameters = {"operation": "publish", "payload": "contract-probe"}
        approval = self.policy.create_server_approval(
            capability_id="durable_external_write",
            parameters=parameters,
            run_id=run_id,
            approved_by="durable intent lifecycle regression",
            risk_level=RiskLevel.CRITICAL,
        )
        return ToolRequest(
            request_id=f"REQ-{run_id}",
            run_id=run_id,
            agent_id="cmo",
            capability_id="durable_external_write",
            parameters=parameters,
            approval_token=approval.approval_token,
            business_id="BIZ-INTENT-1",
            project_id="PROJ-INTENT-1",
        )

    def test_adapter_observes_dispatching_intent_before_consequential_io(self) -> None:
        adapter = IntentProbeAdapter(
            repository=self.receipts,
            name="durable_intent_probe_adapter",
        )
        self._register_consequential(adapter)
        request = self._approved_request(run_id="RUN-INTENT-PREDISPATCH")

        receipt = self.gateway.execute(request)

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.call_count)
        self.assertEqual(
            [[ExecutionIntentState.DISPATCHING]],
            adapter.intent_states_seen,
            "adapter I/O began without one durable DISPATCHING intent",
        )

    def test_success_finalizes_same_intent_to_exact_receipt(self) -> None:
        adapter = IntentProbeAdapter(
            repository=self.receipts,
            name="durable_intent_success_adapter",
        )
        self._register_consequential(adapter)
        request = self._approved_request(run_id="RUN-INTENT-FINALIZE")

        receipt = self.gateway.execute(request)
        intents = self.receipts.list_execution_intents_for_run(request.run_id)

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, len(intents))
        self.assertEqual(ExecutionIntentState.FINALIZED, intents[0].state)
        self.assertEqual(receipt.execution_id, intents[0].receipt_execution_id)
        self.assertEqual(request.calculate_request_hash(), intents[0].request_hash)
        self.assertEqual(ExecutionMode.REAL, intents[0].execution_mode)

    def test_exception_after_dispatch_marks_intent_ambiguous_without_redispatch(self) -> None:
        adapter = IntentProbeAdapter(
            repository=self.receipts,
            name="durable_intent_ambiguous_adapter",
            raise_after_probe=True,
        )
        self._register_consequential(adapter)
        request = self._approved_request(run_id="RUN-INTENT-AMBIGUOUS")

        receipt = self.gateway.execute(request)
        intents = self.receipts.list_execution_intents_for_run(request.run_id)

        self.assertEqual(1, adapter.call_count)
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("AMBIGUOUS_EXTERNAL_ACTION_OUTCOME", receipt.error_class)
        self.assertEqual(1, len(intents))
        self.assertEqual(ExecutionIntentState.AMBIGUOUS, intents[0].state)
        self.assertEqual(receipt.execution_id, intents[0].receipt_execution_id)

    def test_read_only_control_does_not_require_consequential_intent(self) -> None:
        adapter = IntentProbeAdapter(
            repository=self.receipts,
            name="durable_intent_read_control_adapter",
        )
        self.gateway.register_adapter(adapter)
        self.registry.register_capability(
            CapabilityDescriptor(
                capability_id="durable_read_control",
                name="Durable Read Control",
                category=CapabilityCategory.OBSERVE,
                description="Read-only control for intent lifecycle regression.",
                provider=adapter.adapter_name,
                supported_agents=["intelligence"],
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                retry_policy={"max_retries": 0},
            )
        )
        request = ToolRequest(
            request_id="REQ-INTENT-READ-CONTROL",
            run_id="RUN-INTENT-READ-CONTROL",
            agent_id="intelligence",
            capability_id="durable_read_control",
            parameters={"query": "control"},
        )

        receipt = self.gateway.execute(request)

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.call_count)
        self.assertEqual([[]], adapter.intent_states_seen)
        self.assertEqual([], self.receipts.list_execution_intents_for_run(request.run_id))


if __name__ == "__main__":
    unittest.main()
