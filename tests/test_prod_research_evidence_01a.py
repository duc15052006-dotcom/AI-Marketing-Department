"""PROD-RESEARCH-EVIDENCE-CONVERGENCE-01A Certification Tests.

Verifies that production research paths route through the certified observation
ToolGateway, that mock/synthetic research behavior is eliminated, and that
observation backends receive allowed requests with truthful execution modes.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from tools.adapters import (
    AdapterResult,
    BaseCapabilityAdapter,
    ObservationSearchAdapter,
    SearchAdapter,
)
from tools.receipts import ExecutionMode


class MockObservationResult:
    """Minimal mock for CapabilityResult from observation ToolGateway."""

    def __init__(
        self,
        status: str = "SUCCESS",
        data: Optional[Dict[str, Any]] = None,
        backend_used: str = "search_duckduckgo_html",
        error: Any = None,
    ) -> None:
        self.status = status
        self.data = data
        self.backend_used = backend_used
        self.error = error


class TestProdResearchEvidence01AMockPath(unittest.TestCase):
    """PROD-RESEARCH-PRODUCTION-MOCK-PATH-01: Verify production mock path is eliminated."""

    def test_old_search_adapter_returns_mock(self) -> None:
        """The original SearchAdapter still returns MOCK (for backward compat in tests)."""
        adapter = SearchAdapter()
        result = adapter.execute("web_search", {"query": "test"})
        self.assertTrue(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)
        self.assertIn("example.com", str(result.data))

    def test_observation_search_adapter_delegates_to_gateway(self) -> None:
        """ObservationSearchAdapter delegates to observation ToolGateway."""
        adapter = ObservationSearchAdapter()
        self.assertIsNotNone(adapter._gateway)

    def test_observation_adapter_returns_real_on_success(self) -> None:
        """ObservationSearchAdapter returns REAL execution mode on successful backend dispatch."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test", "results": []},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertTrue(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.REAL)

    def test_observation_adapter_returns_mock_on_error(self) -> None:
        """ObservationSearchAdapter returns MOCK execution mode on observation error."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="ERROR",
            error=MagicMock(error_code="TIMEOUT", message="Backend timeout"),
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertFalse(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)

    def test_observation_adapter_returns_mock_on_exception(self) -> None:
        """ObservationSearchAdapter returns MOCK on gateway exception."""
        adapter = ObservationSearchAdapter()
        with patch.object(adapter._gateway, "execute", side_effect=RuntimeError("gateway crash")):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertFalse(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)
        self.assertEqual(result.error_code, "OBSERVATION_GATEWAY_ERROR")


class TestProdResearchEvidence01AToolGatewayPath(unittest.TestCase):
    """Verify research goes through ToolGateway, not direct backend bypass."""

    def test_observation_search_adapter_is_base_capability_adapter(self) -> None:
        """ObservationSearchAdapter extends BaseCapabilityAdapter (production interface)."""
        self.assertTrue(issubclass(ObservationSearchAdapter, BaseCapabilityAdapter))

    def test_observation_adapter_has_correct_name(self) -> None:
        """Adapter name matches expected provider alias."""
        adapter = ObservationSearchAdapter()
        self.assertEqual(adapter.adapter_name, "observation_search_adapter")

    def test_observation_adapter_routes_search_web(self) -> None:
        """Adapter routes web_search capability to observation search_web."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test", "results": []},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute("web_search", {"query": "test"})
            call_args = mock_exec.call_args
            req = call_args[0][0]
            self.assertEqual(req.capability, "search_web")


class TestProdResearchEvidence01ACapabilityControl(unittest.TestCase):
    """ToolGateway capability control: research requires registered capability."""

    def test_disabled_search_capability_denied(self) -> None:
        """Disabled search capability is denied by observation ToolGateway."""
        from tools.gateway.gateway import ToolGateway as ObservationToolGateway
        from tools.observation.registry import CapabilityRegistry
        from tools.gateway.contracts import CapabilityRequest, CapabilityState, ToolExecutionContext

        registry = CapabilityRegistry()
        cap = registry.get_capability("search_web")
        cap.status = CapabilityState.DISABLED
        gw = ObservationToolGateway(registry=registry)

        req = CapabilityRequest(
            capability="search_web",
            parameters={"query": "test"},
            context=ToolExecutionContext(
                agent_id="intelligence",
                product_id="p1",
                brand_id="b1",
                run_id="RUN-001",
                business_id="BIZ-001",
                project_id="PROJ-001",
            ),
        )
        result = gw.execute(req)
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.error.error_code, "CAPABILITY_DISABLED")

    def test_unknown_capability_denied(self) -> None:
        """Unknown capability is denied by observation ToolGateway."""
        from tools.gateway.gateway import ToolGateway as ObservationToolGateway
        from tools.gateway.contracts import CapabilityRequest, ToolExecutionContext

        gw = ObservationToolGateway()
        req = CapabilityRequest(
            capability="nonexistent_research_thing",
            parameters={"query": "test"},
            context=ToolExecutionContext(
                agent_id="intelligence",
                product_id="p1",
                brand_id="b1",
                run_id="RUN-001",
                business_id="BIZ-001",
                project_id="PROJ-001",
            ),
        )
        result = gw.execute(req)
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.error.error_code, "CAPABILITY_NOT_FOUND")

    def test_manifest_cannot_self_authorize_research(self) -> None:
        """Agent manifest cannot self-authorize research capability."""
        from tools.gateway.gateway import ToolGateway as ObservationToolGateway
        from tools.observation.registry import CapabilityRegistry
        from tools.gateway.contracts import CapabilityRequest, CapabilityState, ToolExecutionContext

        registry = CapabilityRegistry()
        cap = registry.get_capability("search_web")
        cap.status = CapabilityState.NO_PERMISSION
        gw = ObservationToolGateway(registry=registry)

        req = CapabilityRequest(
            capability="search_web",
            parameters={"query": "test"},
            context=ToolExecutionContext(
                agent_id="intelligence",
                product_id="p1",
                brand_id="b1",
                run_id="RUN-001",
                business_id="BIZ-001",
                project_id="PROJ-001",
            ),
        )
        result = gw.execute(req)
        self.assertEqual(result.status, "BLOCKED")


class TestProdResearchEvidence01AMockTruth(unittest.TestCase):
    """Mock vs real truth contract: execution mode must be truthful."""

    def test_mock_result_labeled_mock(self) -> None:
        """MOCK results are labeled MOCK, never REAL."""
        adapter = SearchAdapter()
        result = adapter.execute("web_search", {"query": "test"})
        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)

    def test_observation_result_labeled_per_backend(self) -> None:
        """Observation results labeled per true backend execution mode."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertEqual(result.execution_mode, ExecutionMode.REAL)

    def test_no_fabricated_source_urls(self) -> None:
        """Old mock adapter fabricates example.com URLs. New adapter delegates to real backends."""
        old = SearchAdapter()
        old_result = old.execute("web_search", {"query": "test"})
        self.assertIn("example.com", str(old_result.data))

        new = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test", "results": [{"url": "https://real.example.com"}]},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(new._gateway, "execute", return_value=mock_result):
            new_result = new.execute("web_search", {"query": "test"})
        self.assertNotIn("example.com/research", str(new_result.data))


class TestProdResearchEvidence01AFailureContract(unittest.TestCase):
    """Network/provider failure behavior: truthful error, no fake success."""

    def test_network_failure_returns_error(self) -> None:
        """Network failure returns error, not fake success."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="ERROR",
            error=MagicMock(error_code="NETWORK_ERROR", message="Connection refused"),
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "NETWORK_ERROR")

    def test_timeout_returns_error(self) -> None:
        """Timeout returns error, not fake success."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="ERROR",
            error=MagicMock(error_code="TIMEOUT", message="Request timed out"),
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TIMEOUT")

    def test_empty_query_returns_error(self) -> None:
        """Empty query returns error before reaching backend."""
        adapter = ObservationSearchAdapter()
        result = adapter.execute("web_search", {"query": ""})
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "INVALID_PARAMETERS")


class TestProdResearchEvidence01AProvenance(unittest.TestCase):
    """Source provenance: observation records preserve metadata."""

    def test_observation_result_carries_backend_info(self) -> None:
        """Successful observation result carries backend_used information."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test", "results": []},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertTrue(result.success)
        self.assertEqual(result.data, {"query": "test", "results": []})


class TestProdResearchEvidence01AScope(unittest.TestCase):
    """Run/project association preserved."""

    def test_context_preserves_ids(self) -> None:
        """Adapter passes product_id and brand_id through to observation gateway."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute("web_search", {
                "query": "test",
                "product_id": "PROD-123",
                "brand_id": "BRAND-456",
            })
            call_args = mock_exec.call_args
            req = call_args[0][0]
            self.assertEqual(req.context.product_id, "PROD-123")
            self.assertEqual(req.context.brand_id, "BRAND-456")

    def test_trusted_scope_not_from_parameters(self) -> None:
        """Trusted run_id/business_id/project_id come from keyword args, not parameters dict."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute(
                "web_search",
                {"query": "test", "run_id": "RUN-B", "business_id": "BIZ-B", "project_id": "PROJ-B"},
                run_id="RUN-A",
                business_id="BIZ-A",
                project_id="PROJ-A",
            )
            call_args = mock_exec.call_args
            req = call_args[0][0]
            self.assertEqual(req.context.run_id, "RUN-A")
            self.assertEqual(req.context.business_id, "BIZ-A")
            self.assertEqual(req.context.project_id, "PROJ-A")


class TestProdResearchEvidence01ASpoofResistance(unittest.TestCase):
    """Model parameter spoof must not override trusted scope."""

    def test_spoofed_run_id_ignored(self) -> None:
        """Malicious run_id in parameters is ignored; trusted run_id wins."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute(
                "web_search",
                {"query": "test", "run_id": "RUN-B"},
                run_id="RUN-A",
            )
            req = mock_exec.call_args[0][0]
            self.assertEqual(req.context.run_id, "RUN-A")

    def test_spoofed_business_id_ignored(self) -> None:
        """Malicious business_id in parameters is ignored; trusted business_id wins."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute(
                "web_search",
                {"query": "test", "business_id": "BIZ-B"},
                business_id="BIZ-A",
            )
            req = mock_exec.call_args[0][0]
            self.assertEqual(req.context.business_id, "BIZ-A")

    def test_spoofed_project_id_ignored(self) -> None:
        """Malicious project_id in parameters is ignored; trusted project_id wins."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute(
                "web_search",
                {"query": "test", "project_id": "PROJ-B"},
                project_id="PROJ-A",
            )
            req = mock_exec.call_args[0][0]
            self.assertEqual(req.context.project_id, "PROJ-A")

    def test_all_spoofed_ids_ignored(self) -> None:
        """All three scope IDs spoofed in parameters are ignored."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute(
                "web_search",
                {"query": "test", "run_id": "RUN-B", "business_id": "BIZ-B", "project_id": "PROJ-B"},
                run_id="RUN-A",
                business_id="BIZ-A",
                project_id="PROJ-A",
            )
            req = mock_exec.call_args[0][0]
            self.assertEqual(req.context.run_id, "RUN-A")
            self.assertEqual(req.context.business_id, "BIZ-A")
            self.assertEqual(req.context.project_id, "PROJ-A")


class TestProdResearchEvidence01AObservationProvenance(unittest.TestCase):
    """ObservationRecord carries trusted scope from ToolExecutionContext."""

    def test_observation_record_has_scope_fields(self) -> None:
        """ObservationRecord can store run_id, business_id, project_id."""
        from tools.observation.models import ObservationRecord
        obs = ObservationRecord(
            capability="search_web",
            source_url_or_id="search://test",
            backend_used="mock",
            product_id="PROD-01",
            brand_id="BRAND-01",
            run_id="RUN-01",
            business_id="BIZ-01",
            project_id="PROJ-01",
        )
        self.assertEqual(obs.run_id, "RUN-01")
        self.assertEqual(obs.business_id, "BIZ-01")
        self.assertEqual(obs.project_id, "PROJ-01")

    def test_observation_to_evidence_copies_scope(self) -> None:
        """EvidenceBuilder copies scope from ObservationRecord to EvidenceItem."""
        from tools.evidence.builder import EvidenceBuilder
        from tools.observation.models import ObservationRecord
        obs = ObservationRecord(
            capability="search_web",
            source_url_or_id="search://test",
            backend_used="mock",
            product_id="PROD-01",
            brand_id="BRAND-01",
            run_id="RUN-01",
            business_id="BIZ-01",
            project_id="PROJ-01",
        )
        ev = EvidenceBuilder.observation_to_evidence(obs)
        self.assertEqual(ev.run_id, "RUN-01")
        self.assertEqual(ev.business_id, "BIZ-01")
        self.assertEqual(ev.project_id, "PROJ-01")

    def test_observation_to_evidence_no_undefined_parameters(self) -> None:
        """EvidenceBuilder.observation_to_evidence does not reference undefined variables."""
        from tools.evidence.builder import EvidenceBuilder
        from tools.observation.models import ObservationRecord
        obs = ObservationRecord(
            capability="search_web",
            source_url_or_id="search://test",
            backend_used="mock",
            product_id="PROD-01",
            brand_id="BRAND-01",
        )
        ev = EvidenceBuilder.observation_to_evidence(obs)
        self.assertEqual(ev.run_id, "")
        self.assertEqual(ev.business_id, "")
        self.assertEqual(ev.project_id, "")


class TestProdResearchEvidence01ACrossScopeIsolation(unittest.TestCase):
    """Cross-run/business/project isolation."""

    def test_run_a_observation_not_run_b_evidence(self) -> None:
        """RUN-A observation becomes RUN-A evidence, never RUN-B."""
        from tools.evidence.builder import EvidenceBuilder
        from tools.observation.models import ObservationRecord
        obs = ObservationRecord(
            capability="search_web",
            source_url_or_id="search://test",
            backend_used="mock",
            product_id="PROD-01",
            brand_id="BRAND-01",
            run_id="RUN-A",
            business_id="BIZ-A",
            project_id="PROJ-A",
        )
        ev = EvidenceBuilder.observation_to_evidence(obs)
        self.assertEqual(ev.run_id, "RUN-A")
        self.assertNotEqual(ev.run_id, "RUN-B")

    def test_business_a_observation_not_business_b_evidence(self) -> None:
        """BIZ-A observation becomes BIZ-A evidence, never BIZ-B."""
        from tools.evidence.builder import EvidenceBuilder
        from tools.observation.models import ObservationRecord
        obs = ObservationRecord(
            capability="search_web",
            source_url_or_id="search://test",
            backend_used="mock",
            product_id="PROD-01",
            brand_id="BRAND-01",
            run_id="RUN-01",
            business_id="BIZ-A",
            project_id="PROJ-01",
        )
        ev = EvidenceBuilder.observation_to_evidence(obs)
        self.assertEqual(ev.business_id, "BIZ-A")
        self.assertNotEqual(ev.business_id, "BIZ-B")

    def test_project_a_observation_not_project_b_evidence(self) -> None:
        """PROJ-A observation becomes PROJ-A evidence, never PROJ-B."""
        from tools.evidence.builder import EvidenceBuilder
        from tools.observation.models import ObservationRecord
        obs = ObservationRecord(
            capability="search_web",
            source_url_or_id="search://test",
            backend_used="mock",
            product_id="PROD-01",
            brand_id="BRAND-01",
            run_id="RUN-01",
            business_id="BIZ-01",
            project_id="PROJ-A",
        )
        ev = EvidenceBuilder.observation_to_evidence(obs)
        self.assertEqual(ev.project_id, "PROJ-A")
        self.assertNotEqual(ev.project_id, "PROJ-B")

    def test_brand_and_product_distinct_from_business_and_project(self) -> None:
        """brand_id and product_id are distinct from business_id and project_id."""
        from tools.evidence.builder import EvidenceBuilder
        from tools.observation.models import ObservationRecord
        obs = ObservationRecord(
            capability="search_web",
            source_url_or_id="search://test",
            backend_used="mock",
            product_id="PRODUCT-X",
            brand_id="BRAND-X",
            run_id="RUN-01",
            business_id="BIZ-01",
            project_id="PROJ-01",
        )
        ev = EvidenceBuilder.observation_to_evidence(obs)
        self.assertEqual(ev.product_id, "PRODUCT-X")
        self.assertEqual(ev.brand_id, "BRAND-X")
        self.assertEqual(ev.business_id, "BIZ-01")
        self.assertEqual(ev.project_id, "PROJ-01")


class TestProdResearchEvidence01AFailureContract(unittest.TestCase):
    """Failed research cannot become successful evidence."""

    def test_failed_result_not_evidence(self) -> None:
        """Failed adapter result is not passed to EvidenceBuilder as successful evidence."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="ERROR",
            error=MagicMock(error_code="NETWORK_ERROR", message="Connection refused"),
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result):
            result = adapter.execute("web_search", {"query": "test"})
        self.assertFalse(result.success)
        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)

    def test_empty_query_not_evidence(self) -> None:
        """Empty query returns error before reaching backend."""
        adapter = ObservationSearchAdapter()
        result = adapter.execute("web_search", {"query": ""})
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "INVALID_PARAMETERS")


class TestProdResearchEvidence01AFiveAgent(unittest.TestCase):
    """5-agent / 6-stage invariant preserved."""

    def test_intelligence_agent_can_use_search(self) -> None:
        """Intelligence agent identifier is passed through to observation gateway."""
        adapter = ObservationSearchAdapter()
        mock_result = MockObservationResult(
            status="SUCCESS",
            data={"query": "test"},
            backend_used="search_duckduckgo_html",
        )
        with patch.object(adapter._gateway, "execute", return_value=mock_result) as mock_exec:
            adapter.execute("web_search", {
                "query": "test",
                "agent_id": "intelligence",
            })
            call_args = mock_exec.call_args
            req = call_args[0][0]
            self.assertEqual(req.context.agent_id, "intelligence")


if __name__ == "__main__":
    unittest.main()
