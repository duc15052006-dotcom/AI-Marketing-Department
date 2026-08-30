"""Test Suite for PROD-TRUTH-01: ToolGateway Execution Truthfulness & Active Connector Wiring.

Verifies:
- Legacy adapters never emit ExecutionMode.REAL
- SandboxPublishingConnector emits ExecutionMode.SANDBOX
- RealFileConnector emits ExecutionMode.REAL for genuine filesystem I/O
- RealWebConnector emits ExecutionMode.REAL for live read_page and ExecutionMode.MOCK for search
- RealAnalyticsConnector fails closed with NO_DATA when unpopulated and requires explicit KPI inputs
- ContextCompiler deserializes receipt.data (not string "None"), maps epistemic tiers accurately, and attaches rich metadata
- DepartmentAppBackend properly binds active connector provider aliases
- Five-Agent and six-stage collaboration invariants remain intact
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app_api.server import DepartmentAppBackend
from connectors.analytics_connector import RealAnalyticsConnector
from connectors.file_connector import RealFileConnector
from connectors.publishing_connector import SandboxPublishingConnector
from connectors.web_connector import RealWebConnector
from runtime.context import EpistemicTier, RuntimeContext
from runtime.context_compiler import ContextCompiler
from tools.adapters import (
    AnalyticsAdapter,
    CreativeTextAdapter,
    FileStorageAdapter,
    HttpAdapter,
    MediaCreationAdapter,
    MockToolAdapter,
    PublishingAdapter,
    SearchAdapter,
)
from tools.capabilities import CapabilityRegistry, EvidenceRole, RiskLevel
from tools.receipts import (
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
)
from tools.security import HumanApprovalRecord, PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class TestProdTruth01ExecutionTruthfulness(unittest.TestCase):
    """Exhaustive tests for ToolGateway truthfulness and active connector wiring."""

    def setUp(self):
        self.cap_registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine()
        self.receipt_repo = ExecutionReceiptRepository()
        self.tool_gateway = ToolGateway(
            capability_registry=self.cap_registry,
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )
        self.compiler = ContextCompiler()

    # -------------------------------------------------------------------------
    # 1. LEGACY ADAPTER EXECUTION MODE INVARIANTS
    # -------------------------------------------------------------------------
    def test_01_legacy_search_adapter_never_produces_real_receipt(self):
        """1. Legacy SearchAdapter success never produces REAL receipt."""
        req = ToolRequest(
            agent_id="intelligence",
            capability_id="web_search",
            parameters={"query": "electric vehicles market"},
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertNotEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertEqual(receipt.execution_mode, ExecutionMode.MOCK)

    def test_02_legacy_analytics_adapter_never_produces_real_receipt(self):
        """2. Legacy AnalyticsAdapter success never produces REAL receipt."""
        req = ToolRequest(
            agent_id="performance",
            capability_id="analytics_retrieval",
            parameters={"campaign_id": "CAMP_MOCK_01"},
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertNotEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertEqual(receipt.execution_mode, ExecutionMode.MOCK)

    def test_03_legacy_publishing_adapter_never_produces_real_receipt(self):
        """3. Legacy PublishingAdapter success never produces REAL receipt."""
        self.policy_engine.register_approval(
            HumanApprovalRecord(
                approval_token="AUTH-PUB-MOCK",
                action_type="social_publishing",
                approved_by="Auditor",
                approved_at=datetime.now(timezone.utc).isoformat(),
                scope="GLOBAL",
                risk_level=RiskLevel.CRITICAL,
            )
        )
        req = ToolRequest(
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Sample post"},
            approval_token="AUTH-PUB-MOCK",
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertNotEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertEqual(receipt.execution_mode, ExecutionMode.MOCK)

    def test_03b_all_legacy_adapters_default_non_real(self):
        """3b. All legacy default adapters execute with MOCK or SANDBOX provenance."""
        adapters = [
            SearchAdapter(),
            HttpAdapter(),
            CreativeTextAdapter(),
            MediaCreationAdapter(),
            AnalyticsAdapter(),
            FileStorageAdapter(),
            MockToolAdapter(),
        ]
        for adp in adapters:
            res = adp.execute("test_cap", {"query": "q", "url": "http://example.com", "path": "p.txt"})
            self.assertIn(res.execution_mode, (ExecutionMode.MOCK, ExecutionMode.SANDBOX))
            self.assertNotEqual(res.execution_mode, ExecutionMode.REAL)

    # -------------------------------------------------------------------------
    # 2. ACTIVE CONNECTOR EXECUTION MODES & TRUTHFULNESS
    # -------------------------------------------------------------------------
    def test_04_sandbox_publishing_connector_produces_sandbox_receipt(self):
        """4. SandboxPublishingConnector active application binding produces SANDBOX receipt."""
        pub_conn = SandboxPublishingConnector()
        self.tool_gateway.register_adapter(pub_conn, aliases=["social_publish_adapter"])

        self.policy_engine.register_approval(
            HumanApprovalRecord(
                approval_token="AUTH-SANDBOX-01",
                action_type="social_publishing",
                approved_by="Auditor",
                approved_at=datetime.now(timezone.utc).isoformat(),
                scope="GLOBAL",
                risk_level=RiskLevel.CRITICAL,
            )
        )
        req = ToolRequest(
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "twitter", "content": "Launch promo"},
            approval_token="AUTH-SANDBOX-01",
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.SANDBOX)
        self.assertEqual(receipt.data.get("status"), "SANDBOX_PUBLISHED")

    def test_05_real_file_connector_produces_real_receipt_for_actual_io(self):
        """5. RealFileConnector successful actual file operation can produce REAL receipt."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_conn = RealFileConnector(base_dir=Path(tmp_dir))
            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])

            # Write actual file
            req_write = ToolRequest(
                agent_id="cmo",
                capability_id="file_write",
                parameters={"path": "report.txt", "content": "Actual report content on disk."},
            )
            rec_write = self.tool_gateway.execute(req_write)
            self.assertEqual(rec_write.status, ExecutionStatus.SUCCESS)
            self.assertEqual(rec_write.execution_mode, ExecutionMode.REAL)

            # Read actual file
            req_read = ToolRequest(
                agent_id="intelligence",
                capability_id="file_read",
                parameters={"path": "report.txt"},
            )
            rec_read = self.tool_gateway.execute(req_read)
            self.assertEqual(rec_read.status, ExecutionStatus.SUCCESS)
            self.assertEqual(rec_read.execution_mode, ExecutionMode.REAL)
            self.assertEqual(rec_read.data.get("content"), "Actual report content on disk.")

    def test_06_real_web_connector_simulated_search_cannot_produce_real_evidence(self):
        """6. RealWebConnector simulated web_search cannot produce REAL evidence."""
        web_conn = RealWebConnector()
        self.tool_gateway.register_adapter(web_conn, aliases=["search_adapter"])

        req = ToolRequest(
            agent_id="intelligence",
            capability_id="web_search",
            parameters={"query": "AI market size"},
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.MOCK)
        self.assertNotEqual(receipt.execution_mode, ExecutionMode.REAL)

    def test_07_real_analytics_connector_no_ingested_metrics_fails_closed(self):
        """7. RealAnalyticsConnector with no ingested metrics does NOT invent baseline analytics."""
        analytics_conn = RealAnalyticsConnector()
        self.tool_gateway.register_adapter(analytics_conn, aliases=["analytics_adapter"])

        req = ToolRequest(
            agent_id="performance",
            capability_id="analytics_retrieval",
            parameters={"campaign_id": "CAMP_UNPOPULATED_999"},
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt.error_class, "NO_DATA")
        self.assertIsNone(receipt.data)

    def test_08_real_analytics_connector_calculates_only_from_ingested_metrics(self):
        """8. RealAnalyticsConnector with actual ingested metrics calculates only from those metrics."""
        analytics_conn = RealAnalyticsConnector()
        self.tool_gateway.register_adapter(analytics_conn, aliases=["analytics_adapter"])

        records = [
            {"channel": "meta_ads", "impressions": 10000, "clicks": 500, "conversions": 50, "spend": 1000.0, "revenue": 4000.0},
            {"channel": "google_ads", "impressions": 20000, "clicks": 800, "conversions": 70, "spend": 1500.0, "revenue": 6000.0},
        ]
        analytics_conn.ingest_campaign_metrics("CAMP_TEST_REAL", records)

        req = ToolRequest(
            agent_id="performance",
            capability_id="analytics_retrieval",
            parameters={"campaign_id": "CAMP_TEST_REAL"},
        )
        receipt = self.tool_gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.REAL)
        self.assertEqual(receipt.data["impressions"], 30000)
        self.assertEqual(receipt.data["clicks"], 1300)
        self.assertEqual(receipt.data["conversions"], 120)
        self.assertEqual(receipt.data["spend"], 2500.0)
        self.assertEqual(receipt.data["revenue"], 10000.0)
        self.assertEqual(receipt.data["roas"], 4.0)

    def test_09_kpi_calculation_without_explicit_inputs_fails_closed(self):
        """9. kpi_calculation without explicit required inputs does NOT invent default values."""
        analytics_conn = RealAnalyticsConnector()
        self.tool_gateway.register_adapter(analytics_conn, aliases=["kpi_calc_adapter"])

        # Missing spend & revenue
        req_empty = ToolRequest(
            agent_id="performance",
            capability_id="kpi_calculation",
            parameters={"metric_name": "roas"},
        )
        receipt_empty = self.tool_gateway.execute(req_empty)
        self.assertEqual(receipt_empty.status, ExecutionStatus.ERROR)
        self.assertEqual(receipt_empty.error_class, "MISSING_INPUTS")

        # Explicit inputs provided
        req_valid = ToolRequest(
            agent_id="performance",
            capability_id="kpi_calculation",
            parameters={"metric_name": "roas", "spend": 2000.0, "revenue": 8000.0},
        )
        receipt_valid = self.tool_gateway.execute(req_valid)
        self.assertEqual(receipt_valid.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt_valid.data["roas"], 4.0)
        self.assertEqual(receipt_valid.execution_mode, ExecutionMode.REAL)

    def test_10_hardcoded_attribution_sample_is_not_real_evidence(self):
        """10. Hardcoded attribution/experiment sample data does not become REAL empirical evidence."""
        analytics_conn = RealAnalyticsConnector()
        self.tool_gateway.register_adapter(analytics_conn, aliases=["attribution_adapter", "stats_analysis_adapter"])

        req_attr = ToolRequest(agent_id="performance", capability_id="attribution_data_access", parameters={})
        rec_attr = self.tool_gateway.execute(req_attr)
        self.assertEqual(rec_attr.status, ExecutionStatus.ERROR)
        self.assertNotEqual(rec_attr.execution_mode, ExecutionMode.REAL)
        self.assertIsNone(rec_attr.data)

        req_stat = ToolRequest(agent_id="performance", capability_id="experiment_result_analysis", parameters={})
        rec_stat = self.tool_gateway.execute(req_stat)
        self.assertEqual(rec_stat.status, ExecutionStatus.ERROR)
        self.assertNotEqual(rec_stat.execution_mode, ExecutionMode.REAL)
        self.assertIsNone(rec_stat.data)

    # -------------------------------------------------------------------------
    # 3. CONTEXT COMPILER DESERIALIZATION & EPISTEMIC TIER COMPILATION
    # -------------------------------------------------------------------------
    def test_11_context_compiler_consumes_receipt_data_when_output_is_none(self):
        """11. ContextCompiler consumes receipt.data when receipt.output is None."""
        receipt = ExecutionReceipt(
            execution_id="EXEC-DATA-01",
            run_id="RUN-TEST-11",
            agent_id="intelligence",
            capability_id="web_search",
            provider="search_adapter",
            request_hash="req_h",
            execution_mode=ExecutionMode.MOCK,
            status=ExecutionStatus.SUCCESS,
            data={"query": "battery tech", "findings": "Solid state advancement"},
            output=None,
        )
        ctx = RuntimeContext(run_id="RUN-TEST-11", objective="Battery research", business_id="BIZ_TECH")
        pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[receipt])

        tool_ev = [ev for ev in pkg.evidence_items if ev.source_type == "TOOL_RECEIPT"]
        self.assertEqual(len(tool_ev), 1)
        self.assertIn("Solid state advancement", tool_ev[0].content)
        self.assertNotIn("None", tool_ev[0].content)

    def test_12_context_compiler_never_produces_none_string_for_successful_data(self):
        """12. ContextCompiler never produces content 'None' for a successful receipt with non-empty data."""
        receipt = ExecutionReceipt(
            execution_id="EXEC-DATA-02",
            run_id="RUN-TEST-12",
            agent_id="performance",
            capability_id="analytics_retrieval",
            provider="local_analytics",
            request_hash="req_h2",
            execution_mode=ExecutionMode.REAL,
            status=ExecutionStatus.SUCCESS,
            data={"roas": 3.8, "conversions": 150},
            output=None,
        )
        ctx = RuntimeContext(run_id="RUN-TEST-12", objective="Performance review")
        pkg = self.compiler.compile_grounded_package("performance", ctx, tool_receipts=[receipt])

        tool_ev = next(ev for ev in pkg.evidence_items if ev.source_type == "TOOL_RECEIPT")
        self.assertNotEqual(tool_ev.content.strip(), "None")
        self.assertIn("3.8", tool_ev.content)

    def test_13_mock_receipt_compiles_as_mock_or_sandbox(self):
        """13. MOCK receipt compiles as MOCK_OR_SANDBOX."""
        receipt = ExecutionReceipt(
            execution_id="EXEC-MOCK-13",
            run_id="RUN-TEST-13",
            agent_id="intelligence",
            capability_id="web_search",
            provider="mock_p",
            request_hash="req_h",
            execution_mode=ExecutionMode.MOCK,
            status=ExecutionStatus.SUCCESS,
            data={"result": "Simulated intelligence"},
        )
        ctx = RuntimeContext(run_id="RUN-TEST-13", objective="Market study")
        pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[receipt])

        tool_ev = next(ev for ev in pkg.evidence_items if ev.source_type == "TOOL_RECEIPT")
        self.assertEqual(tool_ev.epistemic_tier, EpistemicTier.MOCK_OR_SANDBOX)
        self.assertNotEqual(tool_ev.epistemic_tier, EpistemicTier.SOURCE_BACKED_OBSERVATION)

    def test_14_sandbox_receipt_compiles_as_mock_or_sandbox(self):
        """14. SANDBOX receipt compiles as MOCK_OR_SANDBOX."""
        receipt = ExecutionReceipt(
            execution_id="EXEC-SANDBOX-14",
            run_id="RUN-TEST-14",
            agent_id="intelligence",
            capability_id="read_page",
            provider="sandbox_http_reader",
            request_hash="req_h",
            execution_mode=ExecutionMode.SANDBOX,
            status=ExecutionStatus.SUCCESS,
            data={"url": "https://example.com", "extracted_text": "Sandbox web content."},
        )
        ctx = RuntimeContext(run_id="RUN-TEST-14", objective="Sandbox test")
        pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[receipt])

        tool_ev = next(ev for ev in pkg.evidence_items if ev.source_type == "TOOL_RECEIPT")
        self.assertEqual(tool_ev.epistemic_tier, EpistemicTier.MOCK_OR_SANDBOX)
        self.assertNotEqual(tool_ev.epistemic_tier, EpistemicTier.SOURCE_BACKED_OBSERVATION)

    def test_15_real_successful_receipt_compiles_as_source_backed_observation(self):
        """15. REAL successful receipt compiles as SOURCE_BACKED_OBSERVATION."""
        receipt = ExecutionReceipt(
            execution_id="EXEC-REAL-15",
            run_id="RUN-TEST-15",
            agent_id="intelligence",
            capability_id="read_page",
            provider="system_http_reader",
            request_hash="req_h",
            execution_mode=ExecutionMode.REAL,
            status=ExecutionStatus.SUCCESS,
            data={"url": "https://example.com", "extracted_text": "Live verified webpage content."},
        )
        ctx = RuntimeContext(run_id="RUN-TEST-15", objective="Web observation")
        pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[receipt])

        tool_ev = next(ev for ev in pkg.evidence_items if ev.source_type == "TOOL_RECEIPT")
        self.assertEqual(tool_ev.epistemic_tier, EpistemicTier.SOURCE_BACKED_OBSERVATION)

    def test_16_failed_blocked_timeout_receipt_produces_no_factual_evidence(self):
        """16. ERROR/BLOCKED/TIMEOUT receipt produces no factual EvidenceItem."""
        receipts = [
            ExecutionReceipt(
                execution_id="EXEC-ERR",
                run_id="RUN-TEST-16",
                agent_id="intelligence",
                capability_id="web_search",
                provider="p",
                request_hash="h1",
                execution_mode=ExecutionMode.REAL,
                status=ExecutionStatus.ERROR,
            ),
            ExecutionReceipt(
                execution_id="EXEC-BLOCKED",
                run_id="RUN-TEST-16",
                agent_id="intelligence",
                capability_id="social_publishing",
                provider="p",
                request_hash="h2",
                execution_mode=ExecutionMode.REAL,
                status=ExecutionStatus.BLOCKED,
            ),
            ExecutionReceipt(
                execution_id="EXEC-TIMEOUT",
                run_id="RUN-TEST-16",
                agent_id="intelligence",
                capability_id="read_page",
                provider="p",
                request_hash="h3",
                execution_mode=ExecutionMode.REAL,
                status=ExecutionStatus.TIMEOUT,
            ),
        ]
        ctx = RuntimeContext(run_id="RUN-TEST-16", objective="Error test")
        pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=receipts)

        tool_ev = [ev for ev in pkg.evidence_items if ev.source_type == "TOOL_RECEIPT"]
        self.assertEqual(len(tool_ev), 0)

    def test_17_compiled_evidence_metadata_contains_provenance_attributes(self):
        """17. Compiled evidence metadata contains required bounded authoritative metadata."""
        receipt = ExecutionReceipt(
            execution_id="EXEC-META-17",
            run_id="RUN-TEST-17",
            agent_id="intelligence",
            capability_id="read_page",
            provider="system_http_reader",
            request_hash="h_meta",
            execution_mode=ExecutionMode.REAL,
            status=ExecutionStatus.SUCCESS,
            data={"content": "Verified payload"},
        )
        ctx = RuntimeContext(run_id="RUN-TEST-17", objective="Metadata test", business_id="BIZ_META")
        pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[receipt])

        tool_ev = next(ev for ev in pkg.evidence_items if ev.source_type == "TOOL_RECEIPT")
        meta = tool_ev.metadata

        self.assertEqual(meta.get("receipt_id"), "EXEC-META-17")
        self.assertEqual(meta.get("run_id"), "RUN-TEST-17")
        self.assertEqual(meta.get("capability_id"), "read_page")
        self.assertEqual(meta.get("provider"), "system_http_reader")
        self.assertEqual(meta.get("execution_mode"), "REAL")
        self.assertEqual(meta.get("status"), "SUCCESS")
        self.assertTrue(len(meta.get("result_hash", "")) == 64)

    # -------------------------------------------------------------------------
    # 4. APPLICATION BACKEND ACTIVE WIRING AUDIT
    # -------------------------------------------------------------------------
    def test_18_direct_application_backend_provider_resolution(self):
        """18. Verify DepartmentAppBackend resolves all standard capabilities to truthful connectors."""
        backend = DepartmentAppBackend()

        from tools.adapters import ObservationSearchAdapter
        mapping = {
            "web_search": ObservationSearchAdapter,
            "read_page": RealWebConnector,
            "file_read": RealFileConnector,
            "file_write": RealFileConnector,
            "structured_storage_query": RealFileConnector,
            "analytics_retrieval": RealAnalyticsConnector,
            "kpi_calculation": RealAnalyticsConnector,
            "attribution_data_access": RealAnalyticsConnector,
            "experiment_result_analysis": RealAnalyticsConnector,
            "social_publishing": SandboxPublishingConnector,
            "content_scheduling": SandboxPublishingConnector,
            "platform_operations": SandboxPublishingConnector,
        }

        for cap_id, expected_cls in mapping.items():
            descriptor = backend.cap_registry.get_capability(cap_id)
            self.assertIsNotNone(descriptor, f"Missing descriptor for capability '{cap_id}'")
            adapter = backend.tool_gateway.get_adapter(descriptor.provider)
            self.assertIsNotNone(adapter, f"Missing adapter for provider '{descriptor.provider}' (cap: {cap_id})")
            self.assertIsInstance(
                adapter,
                expected_cls,
                f"Capability '{cap_id}' (provider '{descriptor.provider}') resolved to {type(adapter).__name__}, expected {expected_cls.__name__}",
            )

    # -------------------------------------------------------------------------
    # 5. EVIDENCE ELIGIBILITY & ROLE DISCRIMINATION (PROD-TRUTH-01R)
    # -------------------------------------------------------------------------
    def test_19_capability_evidence_role_classification_table(self):
        """19. Verify all 19 standard capabilities have explicit, truthful EvidenceRole assignments."""
        expected_roles = {
            "web_search": EvidenceRole.OBSERVATION,
            "read_page": EvidenceRole.OBSERVATION,
            "structured_data_retrieval": EvidenceRole.OBSERVATION,
            "text_generation_support": EvidenceRole.GENERATIVE,
            "image_generation": EvidenceRole.GENERATIVE,
            "image_editing": EvidenceRole.GENERATIVE,
            "video_generation": EvidenceRole.GENERATIVE,
            "video_editing_rendering": EvidenceRole.GENERATIVE,
            "social_publishing": EvidenceRole.ACTION,
            "content_scheduling": EvidenceRole.ACTION,
            "platform_operations": EvidenceRole.ACTION,
            "analytics_retrieval": EvidenceRole.OBSERVATION,
            "kpi_calculation": EvidenceRole.COMPUTATION,
            "attribution_data_access": EvidenceRole.OBSERVATION,
            "experiment_result_analysis": EvidenceRole.COMPUTATION,
            "file_read": EvidenceRole.OBSERVATION,
            "file_write": EvidenceRole.ACTION,
            "structured_storage_query": EvidenceRole.OBSERVATION,
            "data_export": EvidenceRole.ACTION,
        }

        for cap_id, expected_role in expected_roles.items():
            cap = self.cap_registry.get_capability(cap_id)
            self.assertIsNotNone(cap, f"Capability '{cap_id}' not found in registry")
            self.assertEqual(
                cap.evidence_role,
                expected_role,
                f"Capability '{cap_id}' has evidence_role {cap.evidence_role}, expected {expected_role}",
            )

    def test_20_real_file_read_creates_observation_evidence(self):
        """20. REAL file_read execution creates factual SOURCE_BACKED_OBSERVATION."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_conn = RealFileConnector(base_dir=Path(tmp_dir))
            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])

            # Setup file on disk
            req_write = ToolRequest(
                agent_id="cmo",
                capability_id="file_write",
                parameters={"path": "market_notes.txt", "content": "Organic search traffic grew 35% MoM."},
            )
            self.tool_gateway.execute(req_write)

            # Read file via ToolGateway
            req_read = ToolRequest(
                agent_id="intelligence",
                capability_id="file_read",
                parameters={"path": "market_notes.txt"},
            )
            rec_read = self.tool_gateway.execute(req_read)
            self.assertEqual(rec_read.status, ExecutionStatus.SUCCESS)
            self.assertEqual(rec_read.execution_mode, ExecutionMode.REAL)

            # Compile into GroundedContextPackage
            ctx = RuntimeContext(run_id="RUN-FILE-READ", objective="File observation")
            pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[rec_read])

            tool_items = [it for it in pkg.evidence_items if it.source_type == "TOOL_RECEIPT"]
            self.assertEqual(len(tool_items), 1)
            self.assertEqual(tool_items[0].epistemic_tier, EpistemicTier.SOURCE_BACKED_OBSERVATION)
            self.assertIn("Organic search traffic grew 35%", tool_items[0].content)

    def test_21_real_structured_storage_query_creates_observation_evidence(self):
        """21. REAL structured_storage_query creates factual SOURCE_BACKED_OBSERVATION."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_conn = RealFileConnector(base_dir=Path(tmp_dir))
            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter", "db_storage_adapter"])

            # Seed a JSON record
            req_write = ToolRequest(
                agent_id="cmo",
                capability_id="file_write",
                parameters={"path": "metrics.json", "content": '{"customer_retention_rate": 0.88}'},
            )
            self.tool_gateway.execute(req_write)

            # Query structured storage
            req_query = ToolRequest(
                agent_id="performance",
                capability_id="structured_storage_query",
                parameters={"path": "metrics.json"},
            )
            rec_query = self.tool_gateway.execute(req_query)
            self.assertEqual(rec_query.status, ExecutionStatus.SUCCESS)
            self.assertEqual(rec_query.execution_mode, ExecutionMode.REAL)

            ctx = RuntimeContext(run_id="RUN-DB-QUERY", objective="Storage query")
            pkg = self.compiler.compile_grounded_package("performance", ctx, tool_receipts=[rec_query])

            tool_items = [it for it in pkg.evidence_items if it.source_type == "TOOL_RECEIPT"]
            self.assertEqual(len(tool_items), 1)
            self.assertEqual(tool_items[0].epistemic_tier, EpistemicTier.SOURCE_BACKED_OBSERVATION)
            self.assertIn("customer_retention_rate", tool_items[0].content)

    def test_22_real_file_write_creates_no_factual_observation_evidence(self):
        """22. REAL file_write is an ACTION receipt and must NOT enter EvidenceItems."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_conn = RealFileConnector(base_dir=Path(tmp_dir))
            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])

            req_write = ToolRequest(
                agent_id="cmo",
                capability_id="file_write",
                parameters={"path": "output.txt", "content": "Generated campaign draft."},
            )
            rec_write = self.tool_gateway.execute(req_write)
            self.assertEqual(rec_write.status, ExecutionStatus.SUCCESS)
            self.assertEqual(rec_write.execution_mode, ExecutionMode.REAL)

            # Compile through ContextCompiler
            ctx = RuntimeContext(run_id="RUN-WRITE-01", objective="Write test")
            pkg = self.compiler.compile_grounded_package("cmo", ctx, tool_receipts=[rec_write])

            # Action receipt must NOT compile into EvidenceItems
            tool_items = [it for it in pkg.evidence_items if it.source_type == "TOOL_RECEIPT"]
            self.assertEqual(len(tool_items), 0, "REAL file_write must not emit EvidenceItem")

    def test_23_hypothetical_real_action_receipts_create_no_factual_evidence(self):
        """23. Hypothetical REAL social_publishing, scheduling, and platform operations create NO EvidenceItems."""
        actions = ["social_publishing", "content_scheduling", "platform_operations"]
        for cap_id in actions:
            receipt = ExecutionReceipt(
                execution_id=f"EXEC-REAL-{cap_id.upper()}",
                run_id="RUN-ACTION-REAL",
                agent_id="cmo",
                capability_id=cap_id,
                provider="real_platform_provider",
                request_hash="req_hash_act",
                status=ExecutionStatus.SUCCESS,
                execution_mode=ExecutionMode.REAL,
                data={"status": "ACTION_COMPLETED", "target_id": "PUB-999"},
            )
            ctx = RuntimeContext(run_id="RUN-ACTION-REAL", objective="Action test")
            pkg = self.compiler.compile_grounded_package("cmo", ctx, tool_receipts=[receipt])

            tool_items = [it for it in pkg.evidence_items if it.source_type == "TOOL_RECEIPT"]
            self.assertEqual(len(tool_items), 0, f"REAL {cap_id} must not emit EvidenceItem")

    def test_24_real_generative_receipts_create_no_factual_evidence(self):
        """24. REAL image/video generation receipts create NO EvidenceItems."""
        gen_caps = ["image_generation", "image_editing", "video_generation", "video_editing_rendering", "text_generation_support"]
        for cap_id in gen_caps:
            receipt = ExecutionReceipt(
                execution_id=f"EXEC-REAL-{cap_id.upper()}",
                run_id="RUN-GEN-REAL",
                agent_id="creative",
                capability_id=cap_id,
                provider="real_media_provider",
                request_hash="req_hash_gen",
                status=ExecutionStatus.SUCCESS,
                execution_mode=ExecutionMode.REAL,
                data={"asset_id": "art-real-001", "status": "RENDERED"},
            )
            ctx = RuntimeContext(run_id="RUN-GEN-REAL", objective="Gen test")
            pkg = self.compiler.compile_grounded_package("creative", ctx, tool_receipts=[receipt])

            tool_items = [it for it in pkg.evidence_items if it.source_type == "TOOL_RECEIPT"]
            self.assertEqual(len(tool_items), 0, f"REAL {cap_id} must not emit EvidenceItem")

    def test_25_kpi_calculation_cannot_become_empirical_observation(self):
        """25. Deterministic KPI calculation and experiment analysis create NO EvidenceItems."""
        calc_caps = ["kpi_calculation", "experiment_result_analysis"]
        for cap_id in calc_caps:
            receipt = ExecutionReceipt(
                execution_id=f"EXEC-CALC-{cap_id.upper()}",
                run_id="RUN-CALC-REAL",
                agent_id="performance",
                capability_id=cap_id,
                provider="kpi_calc_adapter",
                request_hash="req_hash_calc",
                status=ExecutionStatus.SUCCESS,
                execution_mode=ExecutionMode.REAL,
                data={"metric": "roas", "calculated_value": 4.5},
            )
            ctx = RuntimeContext(run_id="RUN-CALC-REAL", objective="Calc test")
            pkg = self.compiler.compile_grounded_package("performance", ctx, tool_receipts=[receipt])

            tool_items = [it for it in pkg.evidence_items if it.source_type == "TOOL_RECEIPT"]
            self.assertEqual(len(tool_items), 0, f"Computation capability '{cap_id}' must not emit EvidenceItem")

    def test_26_action_receipts_remain_auditable_in_runtime_and_repo(self):
        """26. Action receipts remain preserved in ExecutionReceiptRepository and RuntimeContext."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_conn = RealFileConnector(base_dir=Path(tmp_dir))
            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])

            req_write = ToolRequest(
                agent_id="cmo",
                capability_id="file_write",
                parameters={"path": "audit.log", "content": "Action event log."},
            )
            rec_write = self.tool_gateway.execute(req_write)

            # Receipt is saved in repository
            saved = self.receipt_repo.get_receipt(rec_write.execution_id)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.execution_mode, ExecutionMode.REAL)
            self.assertEqual(saved.status, ExecutionStatus.SUCCESS)

    def test_27_material_claim_referencing_real_file_write_is_blocked(self):
        """27. Material claim whose only referenced receipt is REAL file_write cannot qualify as deployable evidence."""
        from runtime.claim_verification import MockClaimVerifier
        from runtime.engine import FiveAgentDepartmentRuntime

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_conn = RealFileConnector(base_dir=Path(tmp_dir))
            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])

            req_write = ToolRequest(
                run_id="RUN-CLAIM-TEST",
                agent_id="cmo",
                capability_id="file_write",
                parameters={"path": "spec.txt", "content": "Hardware test spec: Device features 5000mAh battery."},
            )
            rec_write = self.tool_gateway.execute(req_write)
            self.assertEqual(rec_write.status, ExecutionStatus.SUCCESS)
            self.assertEqual(rec_write.execution_mode, ExecutionMode.REAL)

            rt = FiveAgentDepartmentRuntime(
                tool_gateway=self.tool_gateway,
                context_compiler=self.compiler,
                claim_verifier=MockClaimVerifier(),
            )
            ctx = rt.start_run(objective="Product launch", business_id="BIZ_TEST", run_id="RUN-CLAIM-TEST")

            # Compile context with write receipt (emits 0 evidence items because file_write is ACTION)
            pkg = self.compiler.compile_grounded_package("cmo", ctx, tool_receipts=[rec_write])
            ctx.working_state["provenance_index"] = {it.source_id: it.model_dump() for it in pkg.evidence_items}

            # Final CMO text attempts to cite file_write receipt for a material claim
            claim_text = f"# FINAL CMO PLAN\nDevice features 5000mAh battery (Source: {rec_write.execution_id})."
            audit_res = rt._evaluate_final_authorization(
                context=ctx,
                perf_out={},
                crtv_out={},
                final_text=claim_text,
            )
            self.assertEqual(audit_res.authorization_status, "BLOCKED")
            self.assertGreater(audit_res.blocked_claims, 0)
            self.assertEqual(audit_res.supported_claims, 0)

    def test_28_material_claim_referencing_real_publishing_action_is_blocked(self):
        """28. Material claim referencing REAL publishing action receipt remains unsupported."""
        from runtime.claim_verification import MockClaimVerifier
        from runtime.engine import FiveAgentDepartmentRuntime

        pub_receipt = ExecutionReceipt(
            execution_id="EXEC-PUB-REAL-99",
            run_id="RUN-PUB-CLAIM-TEST",
            agent_id="cmo",
            capability_id="social_publishing",
            provider="live_social_adapter",
            request_hash="req_h_pub",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            data={"post_id": "POST-12345", "status": "LIVE"},
        )
        self.receipt_repo.save_receipt(pub_receipt)

        rt = FiveAgentDepartmentRuntime(
            tool_gateway=self.tool_gateway,
            context_compiler=self.compiler,
            claim_verifier=MockClaimVerifier(),
        )
        ctx = rt.start_run(objective="Publishing verification", business_id="BIZ_TEST", run_id="RUN-PUB-CLAIM-TEST")

        pkg = self.compiler.compile_grounded_package("cmo", ctx, tool_receipts=[pub_receipt])
        ctx.working_state["provenance_index"] = {it.source_id: it.model_dump() for it in pkg.evidence_items}

        claim_text = f"# FINAL CMO PLAN\nDevice features 5000mAh battery (Source: {pub_receipt.execution_id})."
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text=claim_text,
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertGreater(audit_res.blocked_claims, 0)

    def test_29_gov02_real_action_cannot_prove_observed_performance_result(self):
        """29. GOV-02: REAL action receipt cannot prove performance result (CTR/ROAS) without empirical evaluation."""
        from runtime.claim_verification import MockClaimVerifier
        from runtime.engine import FiveAgentDepartmentRuntime

        rt = FiveAgentDepartmentRuntime(
            tool_gateway=self.tool_gateway,
            context_compiler=self.compiler,
            claim_verifier=MockClaimVerifier(),
        )
        ctx = rt.start_run(objective="Ad optimization", business_id="BIZ_TEST", run_id="RUN-GOV02-TEST")

        # Performance handoff has experiment proposed (not real observed result)
        ctx.working_state.setdefault("stage_handoffs", {})["performance"] = {
            "experiment_execution_state": "EXPERIMENT_PROPOSED",
            "evaluation_status": "NOT_EVALUATED",
            "evaluation_data_origin": "NO_DATA",
        }

        # Prose asserts winning performance based on an action receipt
        phantom_prose = "# FINAL CMO PLAN\nCampaign won the test and ROAS improved by 40%."
        audit_res = rt._evaluate_final_authorization(
            context=ctx,
            perf_out={},
            crtv_out={},
            final_text=phantom_prose,
        )
        self.assertEqual(audit_res.authorization_status, "BLOCKED")
        self.assertTrue(
            any("PHANTOM_WINNER" in r or "UNSUPPORTED" in r for r in audit_res.blocking_reasons),
            f"Expected phantom performance claim block, got: {audit_res.blocking_reasons}",
        )


if __name__ == "__main__":
    unittest.main()
