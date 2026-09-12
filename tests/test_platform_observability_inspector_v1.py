from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from integrations.mcp.models import McpServerConfig
from integrations.mcp.registry import McpServerRegistry
from observability.inspector import (
    InspectorScopeError,
    InspectorUnavailableError,
    PlatformInspector,
)
from plugins.models import PluginManifest, PluginToolDeclaration
from plugins.registry import PluginRegistry
from runtime.job_store import DurableJobRecord, SQLiteJobRepository
from tools.dynamic_gateway.gateway import DynamicToolGateway
from tools.receipts import (
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
)


class PlatformInspectorV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.jobs = SQLiteJobRepository(root / "jobs.sqlite3")
        self.receipts = ExecutionReceiptRepository(database_path=root / "receipts.sqlite3")

    def tearDown(self) -> None:
        self.receipts.close()
        self.jobs.close()
        self.tempdir.cleanup()

    def _create_job(self, run_id: str, business_id: str, *, objective: str = "Inspect campaign") -> DurableJobRecord:
        return self.jobs.create_job(
            DurableJobRecord(
                run_id=run_id,
                objective=objective,
                business_id=business_id,
                project_id="PROJECT-1",
                chat_id="CHAT-1",
                status="RUNNING",
                created_at="2026-08-31T09:00:00+00:00",
            )
        )

    def test_run_inspection_is_exact_business_scoped(self) -> None:
        self._create_job("RUN-SCOPE", "BUSINESS-A")
        inspector = PlatformInspector(job_repository=self.jobs, receipt_repository=self.receipts)

        with self.assertRaises(InspectorScopeError):
            inspector.inspect_run(run_id="RUN-SCOPE", business_id="BUSINESS-B")

        visible = inspector.list_runs(business_id="BUSINESS-A")
        hidden = inspector.list_runs(business_id="BUSINESS-B")
        self.assertEqual([row["run_id"] for row in visible], ["RUN-SCOPE"])
        self.assertEqual(hidden, [])

    def test_cross_business_receipt_aborts_instead_of_silent_filtering(self) -> None:
        self._create_job("RUN-MIXED", "BUSINESS-A")
        self.receipts.save_receipt(
            ExecutionReceipt(
                run_id="RUN-MIXED",
                agent_id="creative",
                capability_id="social_publishing",
                provider="test",
                request_hash="hash-mixed",
                status=ExecutionStatus.SUCCESS,
                execution_mode=ExecutionMode.REAL,
                business_id="BUSINESS-B",
            )
        )
        inspector = PlatformInspector(job_repository=self.jobs, receipt_repository=self.receipts)

        with self.assertRaises(InspectorScopeError):
            inspector.inspect_run(run_id="RUN-MIXED", business_id="BUSINESS-A")

    def test_timeline_combines_job_intent_and_receipt_without_payload_leakage(self) -> None:
        job = self._create_job(
            "RUN-TIMELINE",
            "BUSINESS-A",
            objective="Publish safely api_key=objective-secret-123456789",
        )
        self.jobs.save_job(
            replace(job, status="WAITING_APPROVAL", record_hash=""),
            event_type="WAITING_APPROVAL",
            message="Bearer event-secret-123456789",
        )

        intent = self.receipts.prepare_execution_intent(
            request_id="REQ-1",
            run_id="RUN-TIMELINE",
            agent_id="creative",
            capability_id="social_publishing",
            provider="test",
            request_hash="request-hash-1",
            business_id="BUSINESS-A",
            project_id="PROJECT-1",
            chat_id="CHAT-1",
            approval_reference="approval-super-secret-token-123456789",
        )
        self.receipts.mark_execution_intent_dispatching(intent.intent_id)
        receipt = ExecutionReceipt(
            run_id="RUN-TIMELINE",
            agent_id="creative",
            capability_id="social_publishing",
            provider="test",
            request_hash="request-hash-1",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            business_id="BUSINESS-A",
            project_id="PROJECT-1",
            chat_id="CHAT-1",
            approval_reference="approval-super-secret-token-123456789",
            data={"access_token": "tool-secret-123456789", "published": True},
        )
        self.receipts.finalize_execution_intent(intent.intent_id, receipt)

        inspector = PlatformInspector(job_repository=self.jobs, receipt_repository=self.receipts)
        snapshot = inspector.inspect_run(run_id="RUN-TIMELINE", business_id="BUSINESS-A")
        sources = {entry["source"] for entry in snapshot["timeline"]}
        self.assertIn("job_event", sources)
        self.assertIn("execution_intent", sources)
        self.assertIn("execution_receipt", sources)
        self.assertEqual(snapshot["execution_intents"][0]["reconciliation"]["outcome"], "CONFIRMED_FINALIZED")
        self.assertNotIn("data", snapshot["execution_receipts"][0])

        serialized = json.dumps(snapshot, sort_keys=True, default=str)
        for secret in (
            "objective-secret-123456789",
            "event-secret-123456789",
            "approval-super-secret-token-123456789",
            "tool-secret-123456789",
        ):
            self.assertNotIn(secret, serialized)

    def test_platform_snapshot_omits_mcp_secrets_and_never_probes_network(self) -> None:
        network_calls = []

        def forbidden_factory(config):
            network_calls.append(config.server_id)
            raise AssertionError("Inspector must not instantiate or probe an MCP client")

        plugins = PluginRegistry()
        plugins.register(
            PluginManifest(
                plugin_id="safe_plugin",
                name="Safe Plugin",
                version="1.0.0",
                metadata={"api_key": "plugin-metadata-secret-123456789"},
                tools=[
                    PluginToolDeclaration(
                        name="lookup",
                        description="Read-only lookup",
                        category="OBSERVE",
                        evidence_role="OBSERVATION",
                        required_permissions=["READ_ONLY"],
                        risk_level="LOW",
                        human_approval_required=False,
                    )
                ],
            ),
            enabled=True,
        )
        mcp = McpServerRegistry(client_factory=forbidden_factory)
        mcp.register_server(
            McpServerConfig(
                server_id="remote_mcp",
                endpoint="https://mcp.example.invalid/private-endpoint",
                headers={"Authorization": "Bearer mcp-header-secret-123456789"},
                enabled=True,
            )
        )
        gateway = DynamicToolGateway(plugin_registry=plugins, mcp_registry=mcp)
        gateway.sync_plugins()

        try:
            inspector = PlatformInspector(
                job_repository=self.jobs,
                receipt_repository=self.receipts,
                dynamic_gateway=gateway,
            )
            snapshot = inspector.platform_snapshot()
        finally:
            gateway.close()

        self.assertFalse(snapshot["network_probe_performed"])
        self.assertEqual(network_calls, [])
        self.assertEqual(snapshot["plugins"][0]["active_capability_count"], 1)
        self.assertEqual(snapshot["mcp_servers"][0]["discovered_capability_count"], 0)

        serialized = json.dumps(snapshot, sort_keys=True, default=str)
        self.assertNotIn("private-endpoint", serialized)
        self.assertNotIn("mcp-header-secret-123456789", serialized)
        self.assertNotIn("plugin-metadata-secret-123456789", serialized)
        self.assertNotIn("headers", serialized.lower())
        self.assertNotIn("input_schema", serialized)
        self.assertNotIn("output_schema", serialized)

    def test_run_inspection_requires_durable_job_authority(self) -> None:
        inspector = PlatformInspector(receipt_repository=self.receipts)
        with self.assertRaises(InspectorUnavailableError):
            inspector.inspect_run(run_id="RUN-UNKNOWN", business_id="BUSINESS-A")


if __name__ == "__main__":
    unittest.main()
