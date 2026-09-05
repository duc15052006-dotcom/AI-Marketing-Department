from __future__ import annotations

import unittest
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    CostPolicy,
    EvidenceRole,
    PermissionLevel,
    RiskLevel,
)
from tools.idempotency import IdempotencyState
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class MeteredRealVideoAdapter(BaseCapabilityAdapter):
    def __init__(self, *, timeout_after_submit: bool = False) -> None:
        self.calls = 0
        self.timeout_after_submit = timeout_after_submit

    @property
    def adapter_name(self) -> str:
        return "metered_real_video_adapter"

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
        self.calls += 1
        if self.timeout_after_submit:
            # Adversarial provider behavior: the remote job was accepted and quota
            # was consumed, but the response was lost before the client received it.
            raise TimeoutError("remote video job accepted before response timeout")
        return AdapterResult(
            success=True,
            data={"provider_job_id": "remote-video-job-001"},
            execution_mode=ExecutionMode.REAL,
        )


class ToolGatewayMeteredRealIdempotencyGateAdversarialV1Tests(unittest.TestCase):
    CAPABILITY_ID = "metered_real_video_generation_test"

    def _build(self, *, timeout_after_submit: bool = False):
        registry = CapabilityRegistry()
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Metered REAL Video Generation Test",
                category=CapabilityCategory.CREATE,
                evidence_role=EvidenceRole.GENERATIVE,
                description="Adversarial REAL metered create operation.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.MEDIUM,
                human_approval_required=False,
                supported_agents=["creative"],
                provider="metered_real_video_adapter",
                cost_policy=CostPolicy.PAID_METERED,
                timeout_policy=5.0,
                retry_policy={
                    "max_retries": 1,
                    "backoff_seconds": 0.0,
                    "retryable_errors": ["TIMEOUT", "NETWORK_ERROR"],
                },
            )
        )
        adapter = MeteredRealVideoAdapter(timeout_after_submit=timeout_after_submit)
        gateway = ToolGateway(capability_registry=registry)
        gateway.register_adapter(adapter)
        return gateway, adapter

    @staticmethod
    def _request(*, run_id: str) -> ToolRequest:
        return ToolRequest(
            request_id=f"REQ-{run_id}",
            run_id=run_id,
            agent_id="creative",
            capability_id=ToolGatewayMeteredRealIdempotencyGateAdversarialV1Tests.CAPABILITY_ID,
            parameters={
                "prompt": "cinematic product reveal",
                "connection_id": "video-provider-main",
                "idempotency_key": "idem-metered-video-0001",
            },
            business_id="biz-video",
            project_id="proj-video",
        )

    def test_timeout_after_remote_submit_is_not_automatically_dispatched_twice(self) -> None:
        gateway, adapter = self._build(timeout_after_submit=True)

        receipt = gateway.execute(self._request(run_id="RUN-METERED-TIMEOUT-001"))

        self.assertEqual(1, adapter.calls, "ambiguous REAL metered submit must never auto-retry")
        self.assertEqual(ExecutionStatus.ERROR, receipt.status)
        self.assertEqual("AMBIGUOUS_EXTERNAL_ACTION_OUTCOME", receipt.error_class)
        records = gateway.idempotency_ledger.list_records()
        self.assertEqual(1, len(records))
        self.assertEqual(IdempotencyState.AMBIGUOUS, records[0].state)

    def test_same_metered_real_key_is_blocked_across_new_run(self) -> None:
        gateway, adapter = self._build(timeout_after_submit=False)

        first = gateway.execute(self._request(run_id="RUN-METERED-REPLAY-001"))
        second = gateway.execute(self._request(run_id="RUN-METERED-REPLAY-002"))

        self.assertEqual(ExecutionStatus.SUCCESS, first.status)
        self.assertEqual(ExecutionStatus.BLOCKED, second.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
        self.assertEqual(1, adapter.calls, "same logical metered action must not submit twice")
        records = gateway.idempotency_ledger.list_records()
        self.assertEqual(1, len(records))
        self.assertEqual(IdempotencyState.FINALIZED, records[0].state)


if __name__ == "__main__":
    unittest.main()
