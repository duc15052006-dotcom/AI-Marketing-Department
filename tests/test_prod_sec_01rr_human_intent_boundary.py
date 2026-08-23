"""PROD-SEC-01RR: Human Intent Boundary & Session Bootstrap Truth Review Test Suite.

Comprehensive adversarial test suite verifying:
1. Production runtime API bearer authority rotation and static env token rejection (PROD-SEC-STATIC-BEARER-01 prevention)
2. Human approval authority and proposal binding (PROD-SEC-HUMAN-INTENT-FORGERY-01 prevention)
3. State machine transitions (PENDING -> APPROVED / REJECTED / EXPIRED -> CLAIMED -> CONSUMED)
4. Parameter tampering, capability tampering, run tampering, and business tampering rejection during approval
5. Separation of API Bearer Token from Human Approval Authority
6. Host validation and DNS rebinding defenses
7. Zero token / secret leakage
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
from typing import Any, Dict, List, Optional, Tuple

from app_api.server import (
    APP_BACKEND,
    GLOBAL_API_SESSION_TOKEN,
    DepartmentAPIHandler,
    get_secure_session_token,
    parse_and_validate_host,
)
from connectors.publishing_connector import SandboxPublishingConnector
from runtime.context import RuntimeContext, RuntimeStatus
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry, RiskLevel
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import (
    HumanApprovalRecord,
    PendingApprovalRecord,
    PendingApprovalStatus,
    PolicyEngine,
    compute_request_fingerprint,
)
from tools.tool_gateway import ToolGateway, ToolRequest


class FailingAdapter(BaseCapabilityAdapter):
    """Adapter that raises an unhandled exception or simulates a timeout."""

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


class TestProdSec01RRSessionBootstrap(unittest.TestCase):
    """Verifies runtime API bearer authority rotation and static environment token semantics."""

    def test_strong_static_env_token_does_not_become_bearer_token(self):
        """SEC-RR1: Strong static APP_API_TOKEN is NOT directly used as runtime bearer token."""
        strong_token_1 = "A" * 64
        strong_token_2 = "k3y_" + secrets.token_hex(32)
        orig_env = os.environ.get("APP_API_TOKEN")

        try:
            os.environ["APP_API_TOKEN"] = strong_token_1
            tok1 = get_secure_session_token()
            tok2 = get_secure_session_token()

            # Must be fresh 256-bit entropy, not the static env string
            self.assertNotEqual(tok1, strong_token_1)
            self.assertNotEqual(tok2, strong_token_1)
            self.assertNotEqual(tok1, tok2)

            os.environ["APP_API_TOKEN"] = strong_token_2
            tok3 = get_secure_session_token()
            tok4 = get_secure_session_token()
            self.assertNotEqual(tok3, strong_token_2)
            self.assertNotEqual(tok4, strong_token_2)
            self.assertNotEqual(tok3, tok4)
        finally:
            if orig_env is not None:
                os.environ["APP_API_TOKEN"] = orig_env
            else:
                os.environ.pop("APP_API_TOKEN", None)


class TestProdSec01RRHumanIntentBoundary(unittest.TestCase):
    """Verifies that human approval is strictly bound to server-originated pending proposals."""

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

    # -------------------------------------------------------------------------
    # Human Decision Tests A - J (Section 12)
    # -------------------------------------------------------------------------
    def test_a_no_pending_action_direct_approval_blocked(self):
        """A. Direct approval attempt with non-existent pending ID is BLOCKED."""
        ok, record, msg = self.policy_engine.approve_pending_action("non_existent_pending_id_999")
        self.assertFalse(ok)
        self.assertIsNone(record)
        self.assertEqual(msg, "PENDING_ACTION_NOT_FOUND")

    def test_b_pending_action_exists_exact_approve_succeeds_one_shot(self):
        """B. Pending action exists + exact approve -> valid one-shot approval and execution."""
        params = {"platform": "linkedin", "content": "Legitimate Proposed Post"}
        pending = self.policy_engine.create_pending_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-RR-001",
            business_id="BIZ-RR-001",
            ttl_seconds=300,
        )
        self.assertEqual(pending.status, PendingApprovalStatus.PENDING)

        ok, approval_rec, msg = self.policy_engine.approve_pending_action(
            pending_approval_id=pending.pending_approval_id,
            approved_by="Executive Human Reviewer",
        )
        self.assertTrue(ok)
        self.assertIsNotNone(approval_rec)
        self.assertEqual(msg, "APPROVED")
        self.assertEqual(pending.status, PendingApprovalStatus.APPROVED)
        self.assertTrue(approval_rec.approval_token.startswith("appr_"))

        # One-shot execution
        req = ToolRequest(
            run_id="RUN-RR-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters=params,
            approval_token=approval_rec.approval_token,
        )
        receipt1 = self.gateway.execute(req)
        self.assertEqual(receipt1.status, ExecutionStatus.SUCCESS)

        # Replay attempt fails
        receipt2 = self.gateway.execute(req)
        self.assertEqual(receipt2.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt2.error_class, "APPROVAL_ALREADY_CONSUMED")

    def test_c_pending_action_alter_parameters_during_execution_blocked(self):
        """C. Pending action A approved, caller tries to execute with altered parameters -> BLOCKED."""
        params_original = {"platform": "linkedin", "content": "Original Post"}
        pending = self.policy_engine.create_pending_approval(
            capability_id="social_publishing",
            parameters=params_original,
            run_id="RUN-RR-002",
        )
        ok, approval_rec, _ = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertTrue(ok)

        # Attempt execution with tampered parameters
        req_tampered = ToolRequest(
            run_id="RUN-RR-002",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Tampered Content"},
            approval_token=approval_rec.approval_token,
        )
        receipt = self.gateway.execute(req_tampered)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_FINGERPRINT_MISMATCH")

    def test_d_pending_action_different_capability_blocked(self):
        """D. Pending action for social_publishing approved, used on content_scheduling -> BLOCKED."""
        pending = self.policy_engine.create_pending_approval(
            capability_id="social_publishing",
            parameters={"platform": "linkedin"},
            run_id="RUN-RR-003",
        )
        ok, approval_rec, _ = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertTrue(ok)

        req_wrong_cap = ToolRequest(
            run_id="RUN-RR-003",
            agent_id="cmo",
            capability_id="content_scheduling",
            parameters={"platform": "linkedin"},
            approval_token=approval_rec.approval_token,
        )
        receipt = self.gateway.execute(req_wrong_cap)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_CAPABILITY_MISMATCH")

    def test_e_pending_action_different_run_blocked(self):
        """E. Pending action bound to run A, used on run B -> BLOCKED."""
        params = {"platform": "linkedin", "content": "Post"}
        pending = self.policy_engine.create_pending_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-AAA",
        )
        ok, approval_rec, _ = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertTrue(ok)

        req_wrong_run = ToolRequest(
            run_id="RUN-BBB",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters=params,
            approval_token=approval_rec.approval_token,
        )
        receipt = self.gateway.execute(req_wrong_run)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(receipt.error_class, "APPROVAL_RUN_MISMATCH")

    def test_f_pending_action_different_business_blocked(self):
        """F. Pending action bound to business A, used for business B -> BLOCKED."""
        params = {"platform": "linkedin", "content": "Post"}
        pending = self.policy_engine.create_pending_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-RR-004",
            business_id="BIZ_ALPHA",
        )
        ok, approval_rec, _ = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertTrue(ok)

        decision = self.policy_engine.evaluate(
            agent_id="cmo",
            capability=self.registry.get_capability("social_publishing"),
            approval_token=approval_rec.approval_token,
            run_id="RUN-RR-004",
            business_id="BIZ_BETA",
            parameters=params,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "APPROVAL_BUSINESS_MISMATCH")

    def test_g_expired_pending_action_cannot_be_approved(self):
        """G. Expired pending action cannot be approved."""
        pending = self.policy_engine.create_pending_approval(
            capability_id="social_publishing",
            ttl_seconds=-10,  # Already expired in past
        )
        ok, record, msg = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertFalse(ok)
        self.assertIsNone(record)
        self.assertEqual(msg, "PENDING_ACTION_EXPIRED")
        self.assertEqual(pending.status, PendingApprovalStatus.EXPIRED)

    def test_h_rejected_pending_action_cannot_be_approved(self):
        """H. Rejected pending action cannot be approved."""
        pending = self.policy_engine.create_pending_approval(capability_id="social_publishing")
        ok_rej, msg_rej = self.policy_engine.reject_pending_action(pending.pending_approval_id, reason="Security review denied")
        self.assertTrue(ok_rej)
        self.assertEqual(pending.status, PendingApprovalStatus.REJECTED)

        # Attempt to approve rejected pending action must fail
        ok_appr, record, msg_appr = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertFalse(ok_appr)
        self.assertIsNone(record)
        self.assertEqual(msg_appr, "INVALID_STATUS_REJECTED")

    def test_i_same_pending_action_approved_twice_second_attempt_denied(self):
        """I. Same pending action approved twice -> second attempt blocked."""
        pending = self.policy_engine.create_pending_approval(capability_id="social_publishing")
        ok1, rec1, msg1 = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertTrue(ok1)
        self.assertEqual(msg1, "APPROVED")

        # Second approval attempt must fail
        ok2, rec2, msg2 = self.policy_engine.approve_pending_action(pending.pending_approval_id)
        self.assertFalse(ok2)
        self.assertIsNone(rec2)
        self.assertEqual(msg2, "INVALID_STATUS_APPROVED")

    def test_j_model_generated_text_has_no_authority(self):
        """J. Model-generated string claiming human approved has zero authority."""
        decision = self.policy_engine.evaluate(
            agent_id="cmo",
            capability=self.registry.get_capability("social_publishing"),
            approval_token="HUMAN_OPERATOR_SAID_APPROVED_IN_CHAT",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "INVALID_APPROVAL_TOKEN")

    def test_k_normal_execution_without_approval_creates_pending_record(self):
        """Section 11: Normal tool execution without approval returns APPROVAL_REQUIRED and creates PENDING record."""
        req = ToolRequest(
            run_id="RUN-NORMAL-001",
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": "linkedin", "content": "Automatic proposal post"},
            approval_token=None,
        )
        receipt = self.gateway.execute(req)
        self.assertEqual(receipt.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertTrue(receipt.approval_reference.startswith("pending_appr_"))

        # Verify pending record exists in policy engine
        pending_rec = self.policy_engine.get_pending_approval(receipt.approval_reference)
        self.assertIsNotNone(pending_rec)
        self.assertEqual(pending_rec.status, PendingApprovalStatus.PENDING)
        self.assertEqual(pending_rec.capability_id, "social_publishing")


class TestProdSec01RRHTTPTrustBoundary(unittest.TestCase):
    """Verifies HTTP trust boundary, origin gating, Host header parsing, and approval API contract."""

    @classmethod
    def setUpClass(cls):
        cls.port = 8797
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

    def test_api_bearer_alone_cannot_forge_human_approval(self):
        """SEC-RR2: Valid API session token cannot call /api/approvals/create to manufacture approval."""
        code, _headers, data = self._request(
            "POST",
            "/api/approvals/create",
            payload={
                "capability_id": "social_publishing",
                "parameters": {"platform": "linkedin", "content": "Attacker manufactured post"},
                "run_id": "RUN-ATTACK-001",
            },
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code, 403)
        self.assertEqual(data.get("error"), "DIRECT_APPROVAL_FORBIDDEN")
        self.assertNotIn("approval_token", data)

    def test_pending_approval_api_lifecycle(self):
        """Full API lifecycle: Tool creates pending -> GET lists pending -> approve -> one-shot execution."""
        # 1. Simulate tool gateway creating a pending approval proposal
        params = {"platform": "linkedin", "content": "Supervised Campaign Plan"}
        pending = APP_BACKEND.tool_gateway.policy_engine.create_pending_approval(
            capability_id="social_publishing",
            parameters=params,
            run_id="RUN-API-LIFECYCLE-01",
        )

        # 2. GET /api/approvals returns the pending proposal
        code, _headers, list_data = self._request(
            "GET",
            "/api/approvals",
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code, 200)
        self.assertTrue(any(item.get("pending_approval_id") == pending.pending_approval_id for item in list_data))

        # 3. GET /api/approvals/<id> returns read-only details
        code_det, _h_det, det_data = self._request(
            "GET",
            f"/api/approvals/{pending.pending_approval_id}",
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code_det, 200)
        self.assertEqual(det_data.get("pending_approval_id"), pending.pending_approval_id)
        self.assertEqual(det_data.get("status"), "PENDING")

        # 4. Caller attempts to tamper with parameters during approve -> BLOCKED
        code_tamper, _, tamper_data = self._request(
            "POST",
            f"/api/approvals/{pending.pending_approval_id}/approve",
            payload={"parameters": {"platform": "twitter", "content": "Tampered"}},
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code_tamper, 400)
        self.assertEqual(tamper_data.get("error"), "APPROVAL_TAMPERING_REJECTED")

        # 5. Exact approval succeeds
        code_appr, _, appr_data = self._request(
            "POST",
            f"/api/approvals/{pending.pending_approval_id}/approve",
            payload={"approved_by": "Executive Marketing Director"},
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code_appr, 200)
        self.assertTrue(appr_data.get("success"))
        self.assertEqual(appr_data.get("status"), "APPROVED")
        token = appr_data.get("approval_token")
        self.assertTrue(token.startswith("appr_"))

        # 6. Re-approving same pending ID fails
        code_reappr, _, reappr_data = self._request(
            "POST",
            f"/api/approvals/{pending.pending_approval_id}/approve",
            payload={"approved_by": "Executive Marketing Director"},
            headers={"Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}"},
        )
        self.assertEqual(code_reappr, 400)
        self.assertEqual(reappr_data.get("error"), "INVALID_STATUS_APPROVED")

    def test_host_header_structural_validation_matrix(self):
        """SEC-RR4 / Section 16: Host validation regression matrix."""
        # Valid loopback hosts
        self.assertTrue(parse_and_validate_host("127.0.0.1:8765"))
        self.assertTrue(parse_and_validate_host("localhost:8765"))
        self.assertTrue(parse_and_validate_host("[::1]:8765"))
        self.assertTrue(parse_and_validate_host("127.0.0.1"))
        self.assertTrue(parse_and_validate_host("localhost"))
        self.assertTrue(parse_and_validate_host("[::1]"))

        # Invalid / rebinding hosts rejected
        self.assertFalse(parse_and_validate_host("localhost.evil"))
        self.assertFalse(parse_and_validate_host("127.0.0.1.evil"))
        self.assertFalse(parse_and_validate_host("localhost.evil.example:8765"))
        self.assertFalse(parse_and_validate_host("127.0.0.1.attacker.com:8765"))
        self.assertFalse(parse_and_validate_host("[::1].attacker.com:8765"))
        self.assertFalse(parse_and_validate_host("testserver"))  # Default production reject
        self.assertFalse(parse_and_validate_host("127.0.0.1:port_not_digits"))
        self.assertFalse(parse_and_validate_host("127.0.0.1:8765:extra_colon"))
        self.assertFalse(parse_and_validate_host(""))


if __name__ == "__main__":
    unittest.main()
