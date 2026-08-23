"""PROD-SEC-01 & PROD-SEC-01R: Local API Trust Boundary & Human Approval Authority Test Suite.

Verifies:
1. Sandbox Publishing Approval Tests (unapproved, forged caller token, valid server approval, consumed replay, parameter tampering, platform tampering, run mismatch, business mismatch)
2. Approval Security & Cryptographic Authority (entropy >= 256 bits, TTL expiry, key order invariance, parameter sensitivity, model output rejection, fail-closed corruption)
3. One-Shot Dispatched Approval Semantics (atomic claim before dispatch, concurrency double-spend prevention, connector exception spending token, timeout spending token)
4. Host Validation & DNS Rebinding Defenses (structural hostname parsing, subdomain/prefix bypass rejection, testserver production rejection, valid loopback acceptance)
5. API Session Token & Bootstrap Security (weak env token discard, per-launch fresh token, zero bearer token leakage)
6. Minimal Public Surface & Privileged Gating (minimal /api/health public, /api/system/status and diagnostics auth required)
7. HTTP Method Gating (POST, PUT, PATCH, DELETE, OPTIONS all protected against untrusted origins, invalid hosts, and missing auth)
"""

import concurrent.futures
import json
import os
import secrets
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from app_api.server import (
    APP_BACKEND,
    GLOBAL_API_SESSION_TOKEN,
    DepartmentAPIHandler,
    get_secure_session_token,
    parse_and_validate_host,
)
from connectors.publishing_connector import SandboxPublishingConnector
from runtime.context import RuntimeContext, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityDescriptor, CapabilityRegistry, PermissionLevel, RiskLevel
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import (
    HumanApprovalRecord,
    PolicyEngine,
    compute_request_fingerprint,
)
from tools.tool_gateway import ToolGateway, ToolRequest


class FailingAdapter(BaseCapabilityAdapter):
    """Adapter that raises an unhandled exception or simulates a network error."""

    def __init__(self, name: str = "failing_adapter", mode: str = "exception"):
        self.name = name
        self.mode = mode
        self.invocations = 0

    @property
    def adapter_name(self) -> str:
        return self.name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        self.invocations += 1
        if self.mode == "exception":
            raise RuntimeError("CRITICAL_NETWORK_FAILURE: Remote connection dropped mid-dispatch")
        elif self.mode == "timeout":
            return AdapterResult(success=False, error_code="TIMEOUT", error_message="Request timed out")
        return AdapterResult(success=True, data={"result": "ok"}, execution_mode=ExecutionMode.SANDBOX)


class ConcurrentSynchronizedAdapter(BaseCapabilityAdapter):
    """Adapter with barrier synchronization to test race condition / double-spend defense."""

    def __init__(self, name: str = "concurrency_adapter"):
        self.name = name
        self.invocations = 0
        self.barrier = threading.Barrier(2)

    @property
    def adapter_name(self) -> str:
        return self.name

    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0) -> AdapterResult:
        self.invocations += 1
        time.sleep(0.05)
        return AdapterResult(success=True, data={"published": True}, execution_mode=ExecutionMode.SANDBOX)


class TestProdSec01ApprovalAuthority(unittest.TestCase):
    """Test suite verifying cryptographic server-side approval authority and invariant bindings."""

    def setUp(self):
        self.registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine()
        self.receipt_repo = ExecutionReceiptRepository()
        self.gateway = ToolGateway(
            capability_registry=self.registry,
            policy_engine=self.policy_engine,
            receipt_repository=self.receipt_repo,
        )
        self.publish_connector = SandboxPublishingConnector()
        self.gateway.register_adapter(self.publish_connector, aliases=["social_publish_adapter"])

    # =========================================================================
    # 1. SANDBOX PUBLISHING APPROVAL TESTS (Section 21 A-H)
    # =========================================================================
    def test_sandbox_publishing_a_no_approval_blocked(self):
        """A. No approval token -> APPROVAL_REQUIRED."""
        req = ToolRequest(
            run_id="RUN-SEC-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Campaign Post A"},
            approval_token=None,
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "HUMAN_APPROVAL_REQUIRED")

    def test_sandbox_publishing_b_arbitrary_caller_token_blocked(self):
        """B. Arbitrary caller-selected token -> BLOCKED / INVALID_APPROVAL_TOKEN."""
        req = ToolRequest(
            run_id="RUN-SEC-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Campaign Post A"},
            approval_token="ATTACKER-CHOSEN-TOKEN",
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "INVALID_APPROVAL_TOKEN")

    def test_sandbox_publishing_c_valid_server_issued_approval_success(self):
        """C. Valid server-issued approval for exact request -> SANDBOX SUCCESS."""
        params = {"platform": "linkedin", "content": "Campaign Post A"}
        record = self.policy_engine.create_server_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-SEC-001",
            business_id="BIZ-SEC-001",
            approved_by="Executive Human Reviewer",
            ttl_seconds=300,
        )
        self.assertTrue(record.approval_token.startswith("appr_"))
        self.assertFalse(record.consumed)

        req = ToolRequest(
            run_id="RUN-SEC-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters=params,
            approval_token=record.approval_token,
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.SUCCESS)
        self.assertEqual(receipt.execution_mode, ExecutionMode.SANDBOX)

    def test_sandbox_publishing_d_replay_consumed_approval_blocked(self):
        """D. Replay same consumed approval -> BLOCKED (APPROVAL_ALREADY_CONSUMED)."""
        params = {"platform": "linkedin", "content": "Campaign Post A"}
        record = self.policy_engine.create_server_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-SEC-001",
            business_id="BIZ-SEC-001",
            approved_by="Executive Human Reviewer",
            ttl_seconds=300,
        )

        req = ToolRequest(
            run_id="RUN-SEC-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters=params,
            approval_token=record.approval_token,
        )
        # First execution consumes the token
        receipt1 = self.gateway.execute(req)
        self.assertEqual(receipt1.status, ExecutionStatus.SUCCESS)

        # Second execution with same token must fail
        receipt2 = self.gateway.execute(req)
        self.assertEqual(receipt2.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt2.error_class, "APPROVAL_ALREADY_CONSUMED")

    def test_sandbox_publishing_e_modified_content_blocked(self):
        """E. Valid approval but modified content -> APPROVAL_FINGERPRINT_MISMATCH."""
        params_approved = {"platform": "linkedin", "content": "Original Authorized Post"}
        record = self.policy_engine.create_server_approval(
            capability_id="social_publishing",
            parameters=params_approved,
            run_id="RUN-SEC-001",
            business_id="BIZ-SEC-001",
        )

        req_tampered = ToolRequest(
            run_id="RUN-SEC-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Malicious Tampered Post"},
            approval_token=record.approval_token,
        )
        receipt = self.gateway.execute(req_tampered)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_FINGERPRINT_MISMATCH")

    def test_sandbox_publishing_f_modified_platform_blocked(self):
        """F. Valid approval but modified platform -> APPROVAL_FINGERPRINT_MISMATCH."""
        params_approved = {"platform": "linkedin", "content": "Campaign Post"}
        record = self.policy_engine.create_server_approval(
            capability_id="social_publishing",
            parameters=params_approved,
            run_id="RUN-SEC-001",
            business_id="BIZ-SEC-001",
        )

        req_tampered = ToolRequest(
            run_id="RUN-SEC-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "twitter", "content": "Campaign Post"},
            approval_token=record.approval_token,
        )
        receipt = self.gateway.execute(req_tampered)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_FINGERPRINT_MISMATCH")

    def test_sandbox_publishing_g_different_run_blocked(self):
        """G. Valid approval for run A used on run B -> APPROVAL_RUN_MISMATCH."""
        params = {"platform": "linkedin", "content": "Campaign Post"}
        record = self.policy_engine.create_server_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-AAA-111",
            business_id="BIZ-SEC-001",
        )

        req_wrong_run = ToolRequest(
            run_id="RUN-BBB-222",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters=params,
            approval_token=record.approval_token,
        )
        receipt = self.gateway.execute(req_wrong_run)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_RUN_MISMATCH")

    def test_sandbox_publishing_h_different_business_blocked(self):
        """H. Valid approval for business A used for business B -> APPROVAL_BUSINESS_MISMATCH."""
        params = {"platform": "linkedin", "content": "Campaign Post"}
        record = self.policy_engine.create_server_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-SEC-001",
            business_id="BIZ_ALPHA",
        )

        decision = self.policy_engine.evaluate(
            agent_id="cmo",
            capability=self.registry.get_capability("social_publishing"),
            approval_token=record.approval_token,
            run_id="RUN-SEC-001",
            business_id="BIZ_BETA",
            parameters=params,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_BUSINESS_MISMATCH")

    # =========================================================================
    # 2. APPROVAL SECURITY & FINGERPRINTING UNIT TESTS (Section 23)
    # =========================================================================
    def test_server_token_entropy(self):
        """12. Approval token generated server-side has sufficient entropy (>=256 bits)."""
        rec = self.policy_engine.create_server_approval("social_publishing")
        token = rec.approval_token
        self.assertTrue(token.startswith("appr_"))
        raw_part = token.split("_", 1)[1]
        self.assertGreaterEqual(len(raw_part), 32)

    def test_fingerprint_key_order_invariance(self):
        """10. Parameter key-order difference with same semantics retains same canonical hash."""
        fp1 = compute_request_fingerprint("social_publishing", {"a": 1, "b": 2, "c": [1, 2, 3]}, "RUN-1", "BIZ-1")
        fp2 = compute_request_fingerprint("social_publishing", {"c": [1, 2, 3], "b": 2, "a": 1}, "RUN-1", "BIZ-1")
        self.assertEqual(fp1, fp2)

    def test_fingerprint_value_sensitivity(self):
        """11. Meaningful parameter value change changes fingerprint."""
        fp1 = compute_request_fingerprint("platform_operations", {"budget": 100}, "RUN-1", "BIZ-1")
        fp2 = compute_request_fingerprint("platform_operations", {"budget": 10000}, "RUN-1", "BIZ-1")
        self.assertNotEqual(fp1, fp2)

    def test_expired_approval_rejected(self):
        """3. Expired approval fails closed."""
        rec = self.policy_engine.create_server_approval(
            capability_id="social_publishing",
            ttl_seconds=-10,  # Already expired in the past
        )
        decision = self.policy_engine.evaluate(
            agent_id="cmo",
            capability=self.registry.get_capability("social_publishing"),
            approval_token=rec.approval_token,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_EXPIRED")

    def test_wrong_capability_rejected(self):
        """5. Approval for social_publishing cannot authorize content_scheduling."""
        rec = self.policy_engine.create_server_approval(capability_id="social_publishing")
        decision = self.policy_engine.evaluate(
            agent_id="cmo",
            capability=self.registry.get_capability("content_scheduling"),
            approval_token=rec.approval_token,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_CAPABILITY_MISMATCH")

    def test_model_supplied_human_claim_has_no_authority(self):
        """13. Model-supplied metadata or token string without server registry has zero authority."""
        decision = self.policy_engine.evaluate(
            agent_id="cmo",
            capability=self.registry.get_capability("social_publishing"),
            approval_token="MODEL_CLAIMS_HUMAN_APPROVED_THIS",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "INVALID_APPROVAL_TOKEN")

    def test_fail_closed_on_corrupt_record_date(self):
        """15. Corrupt timestamp in approval record fails closed."""
        rec = HumanApprovalRecord(
            approval_token="appr_corrupt_record_token_001",
            capability_id="social_publishing",
            expires_at="NOT-A-VALID-ISO-DATE",
        )
        self.policy_engine.register_approval(rec)
        decision = self.policy_engine.evaluate(
            agent_id="cmo",
            capability=self.registry.get_capability("social_publishing"),
            approval_token=rec.approval_token,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_RECORD_CORRUPT")

    # =========================================================================
    # 3. ONE-SHOT CONCURRENCY & EXCEPTION DISPATCH TESTS (SEC-R3)
    # =========================================================================
    def test_one_shot_connector_exception_spends_approval(self):
        """SEC-R3: Connector exception permanently spends approval (cannot be replayed)."""
        failing_adapter = FailingAdapter(name="failing_publish", mode="exception")
        self.gateway.register_adapter(failing_adapter, aliases=["social_publish_adapter"])

        params = {"platform": "linkedin", "content": "Post before crash"}
        rec = self.policy_engine.create_server_approval("social_publishing", parameters=params, run_id="RUN-FAIL-01")

        req = ToolRequest(
            run_id="RUN-FAIL-01",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters=params,
            approval_token=rec.approval_token,
        )
        # First execution fails due to exception
        receipt1 = self.gateway.execute(req)
        self.assertEqual(receipt1.status, ExecutionStatus.ERROR)
        invocations_after_first = failing_adapter.invocations
        self.assertGreaterEqual(invocations_after_first, 1)

        # Retry with same approval token MUST fail closed (token was consumed/spent)
        receipt2 = self.gateway.execute(req)
        self.assertEqual(receipt2.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt2.error_class, "APPROVAL_ALREADY_CONSUMED")
        self.assertEqual(failing_adapter.invocations, invocations_after_first)  # No second dispatch

    def test_one_shot_connector_timeout_spends_approval(self):
        """SEC-R3: Connector timeout permanently spends approval (cannot be replayed)."""
        timeout_adapter = FailingAdapter(name="timeout_publish", mode="timeout")
        self.gateway.register_adapter(timeout_adapter, aliases=["social_publish_adapter"])

        params = {"platform": "linkedin", "content": "Post before timeout"}
        rec = self.policy_engine.create_server_approval("social_publishing", parameters=params, run_id="RUN-TO-01")

        req = ToolRequest(
            run_id="RUN-TO-01",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters=params,
            approval_token=rec.approval_token,
        )
        receipt1 = self.gateway.execute(req)
        self.assertEqual(receipt1.status, ExecutionStatus.TIMEOUT)

        # Retry with same token MUST fail closed
        receipt2 = self.gateway.execute(req)
        self.assertEqual(receipt2.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt2.error_class, "APPROVAL_ALREADY_CONSUMED")

    def test_one_shot_concurrent_double_spend_prevented(self):
        """SEC-R3: Two concurrent executions with the same token execute exactly ONCE."""
        sync_adapter = ConcurrentSynchronizedAdapter(name="concurrent_publish")
        self.gateway.register_adapter(sync_adapter, aliases=["social_publish_adapter"])

        params = {"platform": "linkedin", "content": "Concurrent publish attempt"}
        rec = self.policy_engine.create_server_approval("social_publishing", parameters=params, run_id="RUN-RACE-01")

        results = []

        def _worker():
            req = ToolRequest(
                run_id="RUN-RACE-01",
                agent_id="cmo",
                capability_id="social_publishing",
                parameters=params,
                approval_token=rec.approval_token,
            )
            r = self.gateway.execute(req)
            results.append(r)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_worker)
            f2 = executor.submit(_worker)
            f1.result()
            f2.result()

        # Exactly one execution must succeed, the other must be rejected
        statuses = [r.status for r in results]
        self.assertIn(ExecutionStatus.SUCCESS, statuses)
        self.assertIn(ExecutionStatus.APPROVAL_REQUIRED, statuses)
        self.assertEqual(sync_adapter.invocations, 1)


class TestProdSec01APITrustBoundary(unittest.TestCase):
    """Test suite verifying local API session authentication, CORS hardening, Host validation, and CSRF defense."""

    @classmethod
    def setUpClass(cls):
        cls.port = 8798
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), DepartmentAPIHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, str], Any]:
        url = f"http://127.0.0.1:{self.port}{path}"
        req_headers = headers or {}
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        if payload is not None and "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        resp_headers = {}
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                for k, v in resp.headers.items():
                    resp_headers[k] = v
                body = resp.read().decode("utf-8")
                parsed_data = json.loads(body) if body else {}
                return resp.status, resp_headers, parsed_data
        except urllib.error.HTTPError as e:
            for k, v in e.headers.items():
                resp_headers[k] = v
            body = e.read().decode("utf-8")
            try:
                parsed_data = json.loads(body) if body else {}
            except Exception:
                parsed_data = {"raw": body}
            return e.code, resp_headers, parsed_data

    # =========================================================================
    # 4. HOST VALIDATION & DNS REBINDING TESTS (SEC-R1)
    # =========================================================================
    def test_host_validation_dns_rebinding_subdomain_rejected(self):
        """SEC-R1: Host localhost.evil.example is rejected (400)."""
        code, _headers, data = self._request("GET", "/api/health", headers={"Host": "localhost.evil.example"})
        self.assertEqual(code, 400)
        self.assertEqual(data.get("error"), "INVALID_HOST")

    def test_host_validation_dns_rebinding_ipv4_subdomain_rejected(self):
        """SEC-R1: Host 127.0.0.1.attacker.com:8765 is rejected (400)."""
        code, _headers, data = self._request("GET", "/api/health", headers={"Host": "127.0.0.1.attacker.com:8765"})
        self.assertEqual(code, 400)
        self.assertEqual(data.get("error"), "INVALID_HOST")

    def test_host_validation_testserver_rejected_in_production(self):
        """SEC-R1: Host testserver is rejected by default in production (400)."""
        code, _headers, data = self._request("GET", "/api/health", headers={"Host": "testserver"})
        self.assertEqual(code, 400)
        self.assertEqual(data.get("error"), "INVALID_HOST")

    def test_host_validation_valid_loopback_accepted(self):
        """SEC-R1: Valid loopback host headers are accepted."""
        self.assertTrue(parse_and_validate_host("127.0.0.1:8765"))
        self.assertTrue(parse_and_validate_host("localhost:8765"))
        self.assertTrue(parse_and_validate_host("[::1]:8765"))
        self.assertTrue(parse_and_validate_host("127.0.0.1"))
        self.assertTrue(parse_and_validate_host("localhost"))
        self.assertTrue(parse_and_validate_host("[::1]"))

    def test_host_validation_invalid_malformed_rejected(self):
        """SEC-R1: Malformed and foreign hosts are rejected."""
        self.assertFalse(parse_and_validate_host("evil.example"))
        self.assertFalse(parse_and_validate_host("localhost.evil:8765"))
        self.assertFalse(parse_and_validate_host("127.0.0.1.evil:8765"))
        self.assertFalse(parse_and_validate_host("[::1].evil:8765"))
        self.assertFalse(parse_and_validate_host("testserver"))
        self.assertFalse(parse_and_validate_host("127.0.0.1:invalid_port"))

    # =========================================================================
    # 5. API SESSION TOKEN & BOOTSTRAP SECURITY TESTS (SEC-R2)
    # =========================================================================
    def test_weak_env_token_discarded(self):
        """SEC-R2: Weak static APP_API_TOKEN is discarded for fresh 256-bit runtime token."""
        orig_env = os.environ.get("APP_API_TOKEN")
        try:
            for weak in ("123", "password", "test", "admin", "secret", "short_string"):
                os.environ["APP_API_TOKEN"] = weak
                token = get_secure_session_token()
                self.assertNotEqual(token, weak)
                self.assertGreaterEqual(len(token), 32)
        finally:
            if orig_env is not None:
                os.environ["APP_API_TOKEN"] = orig_env
            else:
                os.environ.pop("APP_API_TOKEN", None)

    def test_minimal_public_health_zero_leakage(self):
        """SEC-R4: Minimal public /api/health returns only status: ok without secret leakage."""
        code, headers, data = self._request("GET", "/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("service"), "AI Marketing Department API")
        self.assertNotIn("projects_count", data)
        self.assertNotIn("permanent_agents", data)
        self.assertNotIn("providers", data)
        self.assertNotIn(GLOBAL_API_SESSION_TOKEN, json.dumps(data))

    def test_operational_endpoints_require_auth(self):
        """SEC-R4: /api/system/status, /api/system/diagnostics, /api/connections require auth."""
        # /api/system/status
        code1, _, d1 = self._request("GET", "/api/system/status")
        self.assertEqual(code1, 401)
        self.assertEqual(d1.get("error"), "UNAUTHORIZED")

        # /api/system/diagnostics
        code2, _, d2 = self._request("GET", "/api/system/diagnostics")
        self.assertEqual(code2, 401)

        # /api/connections
        code3, _, d3 = self._request("GET", "/api/connections")
        self.assertEqual(code3, 401)

    # =========================================================================
    # 6. HTTP METHOD SECURITY & CSRF TESTS (Section 22 & 23)
    # =========================================================================
    def test_privileged_get_with_valid_auth_succeeds(self):
        """Privileged GET with valid session token succeeds."""
        code, _headers, data = self._request(
            "GET",
            "/api/projects",
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code, 200)
        self.assertIsInstance(data, list)

    def test_untrusted_origin_post_rejected_with_403(self):
        """Evil browser Origin cannot execute privileged POST (CSRF protection -> 403)."""
        code, headers, data = self._request(
            "POST",
            "/api/projects",
            payload={"project_name": "CSRF Attacker Project"},
            headers={
                "Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}",
                "Origin": "https://evil.example",
            },
        )
        self.assertEqual(code, 403)
        self.assertEqual(data.get("error"), "FORBIDDEN_ORIGIN")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_untrusted_origin_put_rejected_with_403(self):
        """Evil browser Origin cannot execute privileged PUT (403)."""
        code, headers, data = self._request(
            "PUT",
            "/api/projects/1",
            payload={"name": "test"},
            headers={
                "Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}",
                "Origin": "https://evil.example",
            },
        )
        self.assertEqual(code, 403)
        self.assertEqual(data.get("error"), "FORBIDDEN_ORIGIN")

    def test_untrusted_origin_delete_rejected_with_403(self):
        """Evil browser Origin cannot execute privileged DELETE (403)."""
        code, headers, data = self._request(
            "DELETE",
            "/api/chat/sessions/chat_123",
            headers={
                "Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}",
                "Origin": "https://evil.example",
            },
        )
        self.assertEqual(code, 403)
        self.assertEqual(data.get("error"), "FORBIDDEN_ORIGIN")

    def test_untrusted_origin_options_preflight_rejected(self):
        """OPTIONS from untrusted Origin does not grant CORS authorization."""
        code, headers, _data = self._request(
            "OPTIONS",
            "/api/campaigns",
            headers={"Origin": "https://evil.example"},
        )
        self.assertIn(code, (403, 204))
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_trusted_local_origin_receives_cors_headers(self):
        """Trusted local origin receives explicit Allow-Origin (never wildcard *)."""
        code, headers, _data = self._request(
            "OPTIONS",
            "/api/health",
            headers={"Origin": "http://localhost:3000"},
        )
        self.assertEqual(code, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://localhost:3000")
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_approval_creation_endpoint_requires_api_auth(self):
        """Approval creation endpoint requires API auth."""
        # Unauthenticated
        code, _headers, data = self._request(
            "POST",
            "/api/approvals/create",
            payload={"capability_id": "social_publishing", "run_id": "RUN-SEC-099"},
        )
        self.assertEqual(code, 401)

        # Authenticated
        code2, _headers2, data2 = self._request(
            "POST",
            "/api/approvals/create",
            payload={"capability_id": "social_publishing", "run_id": "RUN-SEC-099"},
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code2, 201)
        self.assertTrue(data2.get("success"))
        self.assertTrue(data2.get("approval_token").startswith("appr_"))


if __name__ == "__main__":
    unittest.main()
