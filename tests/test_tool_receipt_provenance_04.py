"""Regression tests for truthful ToolGateway execution-mode provenance.

FIX-TOOL-RECEIPT-PROVENANCE-04
"""

from __future__ import annotations

import unittest
from typing import Any, Dict

from connectors.analytics_connector import RealAnalyticsConnector
from connectors.file_connector import RealFileConnector
from connectors.publishing_connector import SandboxPublishingConnector
from connectors.web_connector import RealWebConnector
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


class ProvenanceAdapter(BaseCapabilityAdapter):
    def __init__(self, name: str, declared_mode: ExecutionMode, outcome: Any) -> None:
        self._name = name
        self._declared_mode = declared_mode
        self._outcome = outcome
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return self._name

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        return self._declared_mode

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
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class LegacyResultModeAdapter(BaseCapabilityAdapter):
    """Legacy adapter without capability-level provenance resolver."""

    @property
    def adapter_name(self) -> str:
        return "legacy_sandbox_adapter"

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
        return AdapterResult(
            success=False,
            error_code="SANDBOX_FAILURE",
            error_message="sandbox failure",
            execution_mode=ExecutionMode.SANDBOX,
        )


class TestToolReceiptProvenance04(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.policy = PolicyEngine()
        self.receipts = ExecutionReceiptRepository()
        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=self.policy,
            receipt_repository=self.receipts,
        )

    def _register_safe_capability(self, capability_id: str, adapter: BaseCapabilityAdapter) -> None:
        self.gateway.register_adapter(adapter)
        self.registry.register_capability(
            CapabilityDescriptor(
                capability_id=capability_id,
                name="Provenance Test Capability",
                category=CapabilityCategory.OBSERVE,
                description="Read-only provenance regression test.",
                provider=adapter.adapter_name,
                supported_agents=["intelligence"],
                required_permissions=[PermissionLevel.READ_ONLY],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                retry_policy={
                    "max_retries": 0,
                    "backoff_seconds": 0.0,
                    "retryable_errors": [],
                },
            )
        )

    def _request(self, capability_id: str) -> ToolRequest:
        return ToolRequest(
            run_id="RUN-PROVENANCE-04",
            agent_id="intelligence",
            capability_id=capability_id,
            parameters={"query": "provenance"},
        )

    def test_structured_failure_uses_declared_real_mode_not_result_default_mock(self) -> None:
        adapter = ProvenanceAdapter(
            "declared_real_adapter",
            ExecutionMode.REAL,
            AdapterResult(
                success=False,
                error_code="NETWORK_ERROR",
                error_message="real backend failed",
                execution_mode=ExecutionMode.MOCK,
            ),
        )
        self._register_safe_capability("provenance_structured_failure", adapter)

        receipt = self.gateway.execute(self._request("provenance_structured_failure"))

        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertEqual(adapter.call_count, 1)

    def test_thrown_exception_preserves_declared_real_mode(self) -> None:
        adapter = ProvenanceAdapter(
            "declared_real_exception_adapter",
            ExecutionMode.REAL,
            RuntimeError("real backend exploded"),
        )
        self._register_safe_capability("provenance_exception_failure", adapter)

        receipt = self.gateway.execute(self._request("provenance_exception_failure"))

        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertEqual(adapter.call_count, 1)

    def test_legacy_adapter_explicit_result_mode_is_preserved(self) -> None:
        adapter = LegacyResultModeAdapter()
        self._register_safe_capability("provenance_legacy_result", adapter)

        receipt = self.gateway.execute(self._request("provenance_legacy_result"))

        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.execution_mode, ExecutionMode.SANDBOX)

    def test_real_web_connector_declares_real_only_for_live_http_capabilities(self) -> None:
        connector = RealWebConnector()
        self.assertEqual(connector.execution_mode_for("read_page"), ExecutionMode.REAL)
        self.assertEqual(connector.execution_mode_for("analyze_url"), ExecutionMode.REAL)
        self.assertEqual(connector.execution_mode_for("web_search"), ExecutionMode.MOCK)

    def test_real_file_connector_declares_real_for_filesystem_operations(self) -> None:
        connector = RealFileConnector()
        for capability_id in (
            "file_read",
            "read_file",
            "file_write",
            "write_file",
            "data_export",
            "structured_storage_query",
        ):
            with self.subTest(capability_id=capability_id):
                self.assertEqual(connector.execution_mode_for(capability_id), ExecutionMode.REAL)
        self.assertEqual(connector.execution_mode_for("unsupported"), ExecutionMode.MOCK)

    def test_analytics_and_publishing_connector_modes_are_truthful(self) -> None:
        analytics = RealAnalyticsConnector()
        publisher = SandboxPublishingConnector()

        self.assertEqual(analytics.execution_mode_for("analytics_retrieval"), ExecutionMode.REAL)
        self.assertEqual(analytics.execution_mode_for("kpi_calculation"), ExecutionMode.MOCK)
        self.assertEqual(publisher.execution_mode_for("social_publishing"), ExecutionMode.SANDBOX)
        self.assertEqual(publisher.execution_mode_for("content_scheduling"), ExecutionMode.SANDBOX)


if __name__ == "__main__":
    unittest.main()
