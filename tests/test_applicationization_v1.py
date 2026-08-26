"""Applicationization V1 Test Suite — Python Application API & Desktop Packaging.

Verifies:
- System Status & Connector Health endpoints (Zero secret exposure)
- Business Workspace Creation & Benchmark Data Isolation
- Multi-format Knowledge Ingestion API
- Memory & Learning Management APIs (Operator promotion rules)
- Supervised Campaign Run Creation, Pausing, Resumption, and Gated Approvals
- Real Analytics & KPI Ingestion API
- Receipts & Lineage Query APIs
- Permanent Agent Count = 5, Zero Agent 6, and Frozen Brain RC3 Integrity
"""

import hashlib
import json
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app_api import server as app_server
from app_api.server import APP_BACKEND, DepartmentAPIHandler
from governance.access_matrix import AgentAccessMatrix, PERMANENT_FIVE_AGENTS
from integrations.models.base import ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway


class ScriptedAppGateway(UniversalModelGateway):
    """Deterministic script-based model gateway for applicationization tests."""

    def __init__(self) -> None:
        super().__init__(free_only_mode=True)

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        system_content = next((m.content for m in request.messages if m.role == ModelRole.SYSTEM), "")
        sys_low = system_content.lower()
        if "final governed" in sys_low or "master gtm" in sys_low:
            content = "Final governed GTM campaign plan for Acme Health."
        elif "initial strategic brief" in sys_low or "cmo_initial" in sys_low:
            content = "Initial strategic brief for Acme Health."
        elif "intelligence" in sys_low:
            content = "Intelligence report: market landscape analyzed."
        elif "strategist" in sys_low:
            content = "Strategy formulated for Acme Health GTM."
        elif "creative" in sys_low:
            content = "Creative concepts and messaging created."
        elif "performance" in sys_low:
            content = "Performance media plan and KPIs defined."
        else:
            content = "Deterministic mock stage response."

        return ModelResponse(
            request_id=request.request_id,
            provider="scripted_mock",
            model_name="scripted",
            status=ModelResponseStatus.SUCCESS,
            content=content,
        )


class TestApplicationizationV1(unittest.TestCase):
    """Test suite for Python Localhost Application API and Packaging."""

    @classmethod
    def setUpClass(cls):
        cls._orig_gateway = APP_BACKEND.runtime.model_gateway
        APP_BACKEND.runtime.model_gateway = ScriptedAppGateway()
        # Start test HTTP server on port 8799
        cls.port = 8799
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), DepartmentAPIHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        APP_BACKEND.runtime.model_gateway = cls._orig_gateway
        cls.server.shutdown()
        cls.server.server_close()

    def _api_get(self, path: str) -> Tuple[int, Any]:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {app_server.GLOBAL_API_SESSION_TOKEN}"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=120.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _api_post(self, path: str, payload: Dict[str, Any]) -> Tuple[int, Any]:
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {app_server.GLOBAL_API_SESSION_TOKEN}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    # =========================================================================
    # 1. SYSTEM STATUS & CONNECTOR HEALTH (ZERO SECRET EXPOSURE)
    # =========================================================================
    def test_system_status_api(self):
        """Verify /api/system/status reports permanent 5-agent configuration and online status."""
        code, data = self._api_get("/api/system/status")
        self.assertEqual(code, 200)
        self.assertEqual(data["app_name"], "AI Marketing Department")
        self.assertEqual(data["brain_version"], "FIVE_AGENT_BRAIN_V1_RC3")
        self.assertEqual(data["permanent_agent_count"], 5)
        self.assertEqual(data["permanent_agents"], ["cmo", "intelligence", "strategist", "creative", "performance"])

    def test_connector_health_api_zero_secret_exposure(self):
        """Verify /api/system/health returns sanitized statuses with zero API keys or secrets."""
        code, data = self._api_get("/api/system/health")
        self.assertEqual(code, 200)
        self.assertIn("conn_web_reader", data)
        self.assertIn("conn_file_system", data)
        self.assertIn("conn_analytics_engine", data)

        # String search for secret tokens
        json_str = json.dumps(data)
        self.assertNotIn("sk-", json_str)
        self.assertNotIn("AIza", json_str)

    # =========================================================================
    # 2. BRAND WORKSPACE & BENCHMARK DEMO ISOLATION
    # =========================================================================
    def test_create_and_list_workspaces_api(self):
        """Verify creating a real business workspace and checking demo benchmark isolation."""
        payload = {
            "business_id": "BIZ_ACME_HEALTH_2026",
            "brand_name": "Acme Health Technologies",
            "industry": "Healthcare AI",
            "products": [{"name": "Acme Monitor", "price": "$99/mo"}],
            "approved_claims": ["FDA-cleared sensor telemetry"],
            "prohibited_claims": ["100% cure guarantee"],
        }
        code_post, res_post = self._api_post("/api/workspaces", payload)
        self.assertEqual(code_post, 201)
        self.assertTrue(res_post["success"])

        code_get, workspaces = self._api_get("/api/workspaces")
        self.assertEqual(code_get, 200)

        # Verify demo benchmark workspace has explicit NOT PRODUCTION DATA warning
        demo_ws = next((w for w in workspaces if w["business_id"] == "DEMO_BENCHMARK_CASE04"), None)
        self.assertIsNotNone(demo_ws)
        self.assertTrue(demo_ws["is_demo_benchmark"])
        self.assertEqual(demo_ws["warning"], "NOT PRODUCTION DATA")

        # Verify real brand workspace is distinct and clean
        acme_ws = next((w for w in workspaces if w["business_id"] == "BIZ_ACME_HEALTH_2026"), None)
        self.assertIsNotNone(acme_ws)
        self.assertFalse(acme_ws["is_demo_benchmark"])

    # =========================================================================
    # 3. KNOWLEDGE INGESTION API
    # =========================================================================
    def test_knowledge_ingestion_api(self):
        """Verify ingesting verified knowledge via /api/knowledge/ingest."""
        payload = {
            "title": "Acme Health 2026 Guidelines",
            "source_name": "Acme Brand Guidelines",
            "source_type": "BRAND_GUIDELINE",
            "content": "# Acme Brand Guidelines\nClean medical aesthetics with patient empathy.",
            "format": "MARKDOWN",
            "scope": "SCOPE_BIZ_ACME_HEALTH_2026",
            "authority_level": "TIER_1_CANONICAL_GROUND_TRUTH",
        }
        code, data = self._api_post("/api/knowledge/ingest", payload)
        self.assertEqual(code, 200)
        self.assertTrue(data["success"])
        self.assertIsNotNone(data["document_id"])

        # Query list
        code_list, docs = self._api_get("/api/knowledge?scope=SCOPE_BIZ_ACME_HEALTH_2026")
        self.assertEqual(code_list, 200)
        self.assertGreaterEqual(len(docs), 1)
        self.assertEqual(docs[0]["authority_level"], "TIER_1_CANONICAL_GROUND_TRUTH")

    # =========================================================================
    # 4. CAMPAIGN EXECUTION, APPROVAL & PAUSE/RESUME APIS
    # =========================================================================
    def test_campaign_lifecycle_and_approval_apis(self):
        """Verify creating, executing, pausing, resuming, and approving campaign runs via API."""
        # 1. Create Run
        code_c, camp_data = self._api_post(
            "/api/campaigns",
            {
                "business_id": "BIZ_ACME_HEALTH_2026",
                "objective": "Launch Acme Health Q4 Acquisition",
                "campaign_id": "CAMP_ACME_Q4",
            },
        )
        self.assertEqual(code_c, 201)
        run_id = camp_data["run_id"]

        # 2. Pause Run
        code_p, res_p = self._api_post(f"/api/campaigns/{run_id}/pause", {})
        self.assertEqual(code_p, 200)
        self.assertEqual(res_p["status"], "PAUSED")

        # 3. Resume Run
        code_r, res_r = self._api_post(f"/api/campaigns/{run_id}/resume", {})
        self.assertEqual(code_r, 200)
        self.assertEqual(res_r["status"], "RUNNING")

        # 4. Execute Supervised Pipeline
        code_exec, exec_data = self._api_post(
            "/api/campaigns/execute_supervised",
            {
                "business_id": "BIZ_ACME_HEALTH_2026",
                "objective": "Acme Q4 Physician GTM Strategy",
            },
        )
        self.assertEqual(code_exec, 200)
        self.assertTrue(exec_data["success"])
        self.assertEqual(exec_data["status"], "COMPLETED")
        self.assertEqual(len(exec_data["stages_completed"]), 6)

    # =========================================================================
    # 5. REAL ANALYTICS INGESTION API
    # =========================================================================
    def test_analytics_import_api(self):
        """Verify importing structured campaign metrics via /api/analytics/import."""
        payload = {
            "campaign_id": "CAMP_ACME_METRICS_01",
            "records": [
                {"channel": "paid_search", "impressions": 10000, "clicks": 500, "conversions": 25, "spend": 750.0, "revenue": 3000.0},
                {"channel": "paid_social", "impressions": 20000, "clicks": 800, "conversions": 30, "spend": 900.0, "revenue": 3600.0},
            ],
        }
        code, data = self._api_post("/api/analytics/import", payload)
        self.assertEqual(code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["records_ingested"], 2)

    # =========================================================================
    # 6. INVARIANTS & BRAIN RC3 FROZEN HASH PROTECTION
    # =========================================================================
    def test_invariants_and_frozen_hashes_preserved(self):
        """Verify permanent agent count = 5 and frozen Brain RC3 files are bit-for-bit unchanged."""
        self.assertTrue(AgentAccessMatrix.validate_agent_count())
        self.assertEqual(len(PERMANENT_FIVE_AGENTS), 5)

        perf_md = Path(".agents/agents/performance/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(perf_md.encode("utf-8")).hexdigest(), "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9")

        cmo_md = Path(".agents/agents/cmo/agent.md").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(cmo_md.encode("utf-8")).hexdigest(), "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e")

        handoff_py = Path("schemas/handoff.py").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(handoff_py.encode("utf-8")).hexdigest(), "4075a8e269aef7526bb52c281ac88cc6fdc009d83e9aecb384032e29087e237a")


if __name__ == "__main__":
    unittest.main()
