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
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class LateRealMeteredVideoAdapter(BaseCapabilityAdapter):
    """Contract-valid adapter that reports REAL only after dispatch."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def adapter_name(self) -> str:
        return "late_real_metered_video_adapter"

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
        return AdapterResult(
            success=True,
            data={"provider_job_id": f"remote-job-{self.calls}"},
            execution_mode=ExecutionMode.REAL,
        )


class ToolGatewayMeteredExecutionModePreflightAdversarialV1Tests(unittest.TestCase):
    CAPABILITY_ID = "late_real_metered_video_generation_test"

    def _build(self):
        registry = CapabilityRegistry()
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Late REAL Metered Video Generation Test",
                category=CapabilityCategory.CREATE,
                evidence_role=EvidenceRole.GENERATIVE,
                description="Adversarial metered adapter with no REAL preflight declaration.",
                required_permissions=[PermissionLevel.CREATE_LOCAL],
                risk_level=RiskLevel.MEDIUM,
                human_approval_required=False,
                supported_agents=["creative"],
                provider="late_real_metered_video_adapter",
                cost_policy=CostPolicy.PAID_METERED,
                timeout_policy=5.0,
                retry_policy={"max_retries": 0, "backoff_seconds": 0.0, "retryable_errors": []},
            )
        )
        adapter = LateRealMeteredVideoAdapter()
        gateway = ToolGateway(capability_registry=registry)
        gateway.register_adapter(adapter)
        return gateway, adapter

    @classmethod
    def _request(cls, *, run_id: str) -> ToolRequest:
        return ToolRequest(
            request_id=f"REQ-{run_id}",
            run_id=run_id,
            agent_id="creative",
            capability_id=cls.CAPABILITY_ID,
            parameters={
                "prompt": "cinematic product reveal",
                "connection_id": "video-provider-main",
                "idempotency_key": "idem-late-real-metered-0001",
            },
            business_id="biz-video",
            project_id="proj-video",
        )

    def test_real_result_cannot_bypass_metered_idempotency_preflight(self) -> None:
        gateway, adapter = self._build()

        first = gateway.execute(self._request(run_id="RUN-LATE-REAL-001"))
        second = gateway.execute(self._request(run_id="RUN-LATE-REAL-002"))

        self.assertEqual(ExecutionStatus.SUCCESS, first.status)
        self.assertEqual(ExecutionMode.REAL, first.execution_mode)
        self.assertEqual(ExecutionStatus.BLOCKED, second.status)
        self.assertEqual("IDEMPOTENCY_REPLAY_BLOCKED", second.error_class)
        self.assertEqual(
            1,
            adapter.calls,
            "a contract-valid adapter must not bypass metered duplicate protection by reporting REAL only after dispatch",
        )
        self.assertEqual(1, len(gateway.idempotency_ledger.list_records()))


if __name__ == "__main__":
    unittest.main()
