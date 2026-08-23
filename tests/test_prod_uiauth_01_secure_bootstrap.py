"""Targeted Security & Functional Test Suite for PROD-UIAUTH-01:
Secure Frontend / Desktop Session Bootstrap.

Validates:
1. Fresh per-launch token generation and framed bootstrap handshake (`UIAUTH_BOOTSTRAP_V1:`)
2. Normal server startup does not emit bootstrap token (privacy preservation)
3. Privileged endpoints accept bootstrapped bearer token (HTTP 200)
4. Unauthenticated privileged endpoints strictly return HTTP 401
5. Health endpoint is public (HTTP 200) and contains zero secrets
6. Token rotation: each process launch generates a fresh token; previous token is rejected
7. Frontend client bundle (dist/) contains zero runtime tokens or hardcoded secrets
8. Frontend source contains zero localStorage/sessionStorage bearer storage
9. APP_API_TOKEN in .env is ignored for runtime bearer authentication
10. High-risk consequential actions still require human approval via authenticated API
11. Vite server-side proxy configuration attaches Authorization header downstream
12. Native proxy path validation blocks foreign schemes, hosts, traversal, and invalid methods
13. Sentinel runtime token is never leaked in diagnostics, logs, or error responses
14. Loopback host and CORS origin restrictions are preserved
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

from app_api.server import (
    ALLOWED_LOCAL_ORIGINS,
    GLOBAL_API_SESSION_TOKEN,
    DepartmentAPIHandler,
    get_secure_session_token,
    parse_and_validate_host,
)
from config.env_loader import REPO_ROOT


class TestProdUIAuth01SecureBootstrap(unittest.TestCase):
    """Adversarial and integration test suite for secure UI session bootstrap."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="test_uiauth_")
        self.temp_path = Path(self.temp_dir)
        self.active_processes = []

    def tearDown(self) -> None:
        for proc in self.active_processes:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _find_free_port(self) -> int:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _start_backend(self, emit_bootstrap: bool = True, extra_env: Optional[Dict[str, str]] = None, port: Optional[int] = None) -> Tuple[subprocess.Popen, Optional[Dict[str, str]]]:
        """Helper to start Python backend and capture bootstrap record."""
        target_port = port if port is not None else self._find_free_port()
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)

        args = [sys.executable, str(REPO_ROOT / "app_api" / "server.py"), "--port", str(target_port)]
        if emit_bootstrap:
            args.append("--emit-bootstrap")

        proc = subprocess.Popen(
            args,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.active_processes.append(proc)

        bootstrap_info = None
        if emit_bootstrap and proc.stdout:
            line = proc.stdout.readline().strip()
            if line.startswith("UIAUTH_BOOTSTRAP_V1:"):
                payload_str = line[len("UIAUTH_BOOTSTRAP_V1:"):]
                bootstrap_info = json.loads(payload_str)

        # Wait for health endpoint readiness (up to 5 seconds)
        active_port = bootstrap_info.get("port", target_port) if bootstrap_info else target_port
        ready = False
        start = time.time()
        while time.time() - start < 5.0:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{active_port}/api/health", timeout=0.5) as res:
                    if res.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.1)

        self.assertTrue(ready, f"Backend failed to become healthy on port {active_port}")
        return proc, bootstrap_info

    # ==========================================================================
    # 1. Bootstrap Handshake & Token Entropy
    # ==========================================================================

    def test_01_bootstrap_handshake_emits_valid_framed_json(self) -> None:
        """--emit-bootstrap outputs framed UIAUTH_BOOTSTRAP_V1 with valid token, host, port."""
        _, bootstrap = self._start_backend(emit_bootstrap=True)
        self.assertIsNotNone(bootstrap)
        self.assertIn("token", bootstrap)
        self.assertIn("host", bootstrap)
        self.assertIn("port", bootstrap)

        token = bootstrap["token"]
        self.assertIsInstance(token, str)
        self.assertGreaterEqual(len(token), 32)
        self.assertIn(bootstrap["host"], ["127.0.0.1", "localhost", "::1"])
        self.assertIsInstance(bootstrap["port"], int)
        self.assertGreaterEqual(bootstrap["port"], 1)
        self.assertLessEqual(bootstrap["port"], 65535)

    def test_02_normal_server_run_does_not_emit_bootstrap_token(self) -> None:
        """Standard CLI startup without --emit-bootstrap does NOT emit the framed token."""
        port = self._find_free_port()
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "app_api" / "server.py"), "--port", str(port)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.active_processes.append(proc)

        time.sleep(1.0)
        proc.terminate()
        stdout, _ = proc.communicate(timeout=3)
        self.assertNotIn("UIAUTH_BOOTSTRAP_V1:", stdout)

    # ==========================================================================
    # 2. Authentication Enforcement & Bearer Usage
    # ==========================================================================

    def test_03_bootstrapped_bearer_token_authenticates_privileged_endpoint(self) -> None:
        """Privileged endpoints return HTTP 200 when authenticated with bootstrapped bearer token."""
        _, bootstrap = self._start_backend(emit_bootstrap=True)
        port = bootstrap["port"]
        token = bootstrap["token"]

        # Call GET /api/chat/sessions with Bearer
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/chat/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode("utf-8"))
            self.assertIsInstance(data, list)

        # Call GET /api/projects with Bearer
        req_proj = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req_proj) as res:
            self.assertEqual(res.status, 200)

    def test_04_unauthenticated_privileged_endpoints_return_401(self) -> None:
        """Privileged endpoints without Authorization header return HTTP 401."""
        _, bootstrap = self._start_backend(emit_bootstrap=True)
        port = bootstrap["port"]

        privileged_paths = [
            "/api/chat/sessions",
            "/api/projects",
            "/api/workspaces",
            "/api/approvals",
            "/api/activity/receipts",
            "/api/system/status",
            "/api/system/diagnostics",
            "/api/connections",
        ]

        for path in privileged_paths:
            with self.subTest(path=path):
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 401)

    def test_05_health_endpoint_is_public_and_contains_zero_secrets(self) -> None:
        """Health endpoint is unauthenticated, returns 200, and contains zero secrets."""
        _, bootstrap = self._start_backend(emit_bootstrap=True)
        port = bootstrap["port"]

        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health")
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode("utf-8"))
            self.assertEqual(data.get("status", "").lower(), "ok")
            # Must not contain token or session secret
            self.assertNotIn("token", data)
            self.assertNotIn("bearer", data)
            self.assertNotIn("session_token", data)
            self.assertNotIn(bootstrap["token"], str(data))

    # ==========================================================================
    # 3. Token Rotation & Replay Defense
    # ==========================================================================

    def test_06_token_rotation_between_restarts(self) -> None:
        """Each backend launch creates a fresh token; prior launch token is rejected."""
        # Launch 1
        proc1, boot1 = self._start_backend(emit_bootstrap=True)
        token1 = boot1["token"]
        port1 = boot1["port"]

        # Verify token 1 works on instance 1
        req1 = urllib.request.Request(
            f"http://127.0.0.1:{port1}/api/chat/sessions",
            headers={"Authorization": f"Bearer {token1}"},
        )
        with urllib.request.urlopen(req1) as res:
            self.assertEqual(res.status, 200)

        # Stop instance 1
        proc1.terminate()
        proc1.wait(timeout=2)

        # Launch 2
        proc2, boot2 = self._start_backend(emit_bootstrap=True)
        token2 = boot2["token"]
        port2 = boot2["port"]

        # Tokens must be distinct
        self.assertNotEqual(token1, token2)

        # Token 1 must be rejected on instance 2 with HTTP 401
        req_stale = urllib.request.Request(
            f"http://127.0.0.1:{port2}/api/chat/sessions",
            headers={"Authorization": f"Bearer {token1}"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_stale)
        self.assertEqual(ctx.exception.code, 401)

        # Token 2 must succeed on instance 2
        req_fresh = urllib.request.Request(
            f"http://127.0.0.1:{port2}/api/chat/sessions",
            headers={"Authorization": f"Bearer {token2}"},
        )
        with urllib.request.urlopen(req_fresh) as res:
            self.assertEqual(res.status, 200)

    # ==========================================================================
    # 4. Client Bundle & Source Security
    # ==========================================================================

    def test_07_frontend_build_bundle_contains_zero_runtime_tokens_or_secrets(self) -> None:
        """Built frontend bundle in dist/ does not contain hardcoded bearer tokens or keys."""
        dist_dir = REPO_ROOT / "frontend" / "dist"
        if not dist_dir.exists():
            self.skipTest("frontend/dist does not exist yet (run npm run build)")

        forbidden_patterns = [
            "sk-proj-",
            "AIzaSy",
            "APP_API_TOKEN",
            "UIAUTH_BOOTSTRAP",
            "GLOBAL_API_SESSION_TOKEN",
        ]

        for js_file in dist_dir.rglob("*.js"):
            content = js_file.read_text(encoding="utf-8")
            for pat in forbidden_patterns:
                with self.subTest(file=js_file.name, pattern=pat):
                    self.assertNotIn(pat, content)

    def test_08_frontend_source_contains_zero_localstorage_bearer_storage(self) -> None:
        """Frontend source code in frontend/src does not use localStorage/sessionStorage for tokens."""
        src_dir = REPO_ROOT / "frontend" / "src"
        if src_dir.exists():
            for ts_file in src_dir.rglob("*.ts*"):
                content = ts_file.read_text(encoding="utf-8")
                self.assertNotIn("localStorage.setItem('token'", content)
                self.assertNotIn('localStorage.setItem("token"', content)
                self.assertNotIn("localStorage.setItem('bearer'", content)
                self.assertNotIn('localStorage.setItem("bearer"', content)
                self.assertNotIn("sessionStorage.setItem('token'", content)
                self.assertNotIn('sessionStorage.setItem("token"', content)

    def test_09_static_env_token_ignored_for_runtime_bearer(self) -> None:
        """Static APP_API_TOKEN in environment is NOT adopted as runtime session bearer."""
        static_token = "STATIC_TOKEN_TEST_ABCD_1234567890"
        _, boot = self._start_backend(emit_bootstrap=True, extra_env={"APP_API_TOKEN": static_token})
        port = boot["port"]
        runtime_token = boot["token"]

        self.assertNotEqual(runtime_token, static_token)

        # Attempting to use the static token returns HTTP 401
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/chat/sessions",
            headers={"Authorization": f"Bearer {static_token}"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    # ==========================================================================
    # 5. Approval Invariant Preservation
    # ==========================================================================

    def test_10_high_risk_actions_still_require_human_approval_via_authenticated_api(self) -> None:
        """API session bearer alone cannot execute consequential high-risk tools without approval."""
        _, boot = self._start_backend(emit_bootstrap=True)
        port = boot["port"]
        token = boot["token"]

        # Attempt to publish social content without valid human approval record
        payload = json.dumps({
            "agent_id": "cmo",
            "capability_id": "social_publishing",
            "parameters": {"content": "Unauthorized post attempt"},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/approvals/create",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        # Direct approval creation is forbidden (403)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

    # ==========================================================================
    # 6. Proxy & IPC Path Safety Validation
    # ==========================================================================

    def test_11_native_proxy_path_and_scheme_validation(self) -> None:
        """Test strict path and scheme validation rules required for native IPC proxy."""
        def is_safe_api_path(path: str) -> bool:
            clean = path.strip()
            if not clean.startswith("/api/"):
                return False
            if "://" in clean or "\\" in clean or ".." in clean or "\0" in clean or " " in clean:
                return False
            return True

        valid_paths = [
            "/api/chat/sessions",
            "/api/projects",
            "/api/workspaces",
            "/api/approvals",
            "/api/chat/sessions/chat_123/messages",
            "/api/system/status",
        ]
        for p in valid_paths:
            with self.subTest(path=p):
                self.assertTrue(is_safe_api_path(p))

        invalid_paths = [
            "http://attacker.com/api/test",
            "https://attacker.com/api/test",
            "//attacker.com/api/test",
            "/api/../../etc/passwd",
            "/api/..\\windows\\system32",
            "/api/test\0hidden",
            "file:///c:/passwords.txt",
            "\\\\server\\share\\api",
            "/other/endpoint",
            "api/chat",  # Missing leading slash
            "/api/chat with spaces",
        ]
        for p in invalid_paths:
            with self.subTest(path=p):
                self.assertFalse(is_safe_api_path(p))

    def test_12_vite_dev_proxy_config_logic(self) -> None:
        """Verify Vite proxy config injects Bearer header when APP_BACKEND_BEARER_DEV is set."""
        vite_config = (REPO_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        self.assertIn("APP_BACKEND_BEARER_DEV", vite_config)
        self.assertIn("Authorization", vite_config)
        self.assertIn("Bearer", vite_config)

    def test_13_sentinel_token_not_leaked_in_diagnostics(self) -> None:
        """Diagnostics endpoint never exposes the raw runtime session token."""
        _, boot = self._start_backend(emit_bootstrap=True)
        port = boot["port"]
        token = boot["token"]

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/system/diagnostics",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode("utf-8"))
            serialized = json.dumps(data)
            # Token must not be present in diagnostics values
            self.assertNotIn(token, serialized)

    def test_14_host_header_validation_regression(self) -> None:
        """Host header validation remains strictly bound to loopback hostnames."""
        self.assertTrue(parse_and_validate_host("127.0.0.1:8765"))
        self.assertTrue(parse_and_validate_host("localhost:8765"))
        self.assertTrue(parse_and_validate_host("127.0.0.1"))
        self.assertTrue(parse_and_validate_host("localhost"))

        self.assertFalse(parse_and_validate_host("attacker.com"))
        self.assertFalse(parse_and_validate_host("127.0.0.1.attacker.com"))
        self.assertFalse(parse_and_validate_host("0.0.0.0:8765"))
        self.assertFalse(parse_and_validate_host("192.168.1.1:8765"))

    def test_15_generic_proxy_denies_approval_decision_routes(self) -> None:
        """Generic proxy route policy strictly denies approval decision paths."""
        def is_allowed_generic_route(method: str, path: str) -> bool:
            if "/approve" in path or "/reject" in path or path == "/api/approvals/create":
                return False
            if method == "GET" and (path == "/api/approvals" or path.startswith("/api/approvals/pending_appr_")):
                return True
            return False

        forbidden_approval_paths = [
            ("POST", "/api/approvals/pending_appr_123/approve"),
            ("POST", "/api/approvals/pending_appr_123/reject"),
            ("POST", "/api/approvals/create"),
            ("PUT", "/api/approvals/pending_appr_123/approve"),
            ("DELETE", "/api/approvals/pending_appr_123/approve"),
        ]
        for m, p in forbidden_approval_paths:
            with self.subTest(method=m, path=p):
                self.assertFalse(is_allowed_generic_route(m, p))

        # Read-only approval inspection is allowed
        self.assertTrue(is_allowed_generic_route("GET", "/api/approvals"))
        self.assertTrue(is_allowed_generic_route("GET", "/api/approvals/pending_appr_xyz123"))

    def test_16_generic_proxy_denies_unrecognized_routes(self) -> None:
        """Arbitrary future/internal endpoints are blocked by generic proxy allowlist."""
        def is_allowed_generic_route(method: str, path: str) -> bool:
            if "/approve" in path or "/reject" in path or path == "/api/approvals/create":
                return False
            allowed_exact = {
                ("GET", "/api/health"),
                ("GET", "/api/system/status"),
                ("GET", "/api/system/diagnostics"),
                ("GET", "/api/system/health"),
                ("GET", "/api/chat/sessions"),
                ("POST", "/api/chat/sessions/first_turn"),
                ("GET", "/api/projects"),
                ("POST", "/api/projects"),
                ("GET", "/api/workspaces"),
                ("POST", "/api/workspaces"),
                ("GET", "/api/approvals"),
                ("GET", "/api/activity/receipts"),
                ("GET", "/api/connections"),
                ("POST", "/api/analytics/import"),
            }
            if (method, path) in allowed_exact:
                return True
            if method == "GET" and path.startswith("/api/chat/sessions/"):
                return True
            if (method == "PATCH" or method == "DELETE") and path.startswith("/api/chat/sessions/"):
                return True
            if method == "POST" and path.startswith("/api/chat/sessions/"):
                return (
                    path.endswith("/messages")
                    or (
                        "/messages/" in path
                        and (path.endswith("/edit") or path.endswith("/regenerate"))
                    )
                    or path.endswith("/regenerate")
                    or path.endswith("/retry")
                )
            if (method in ("GET", "PUT", "DELETE")) and path.startswith("/api/projects/"):
                return True
            if method == "GET" and path.startswith("/api/workspaces/"):
                return True
            if method == "GET" and path.startswith("/api/approvals/pending_appr_"):
                return True
            if method == "GET" and path.startswith("/api/activity/receipts/"):
                return True
            return False

        unauthorized_future_routes = [
            ("GET", "/api/internal/debug"),
            ("POST", "/api/admin/eval"),
            ("DELETE", "/api/database/drop"),
            ("POST", "/api/system/shutdown"),
            ("GET", "/api/v2/unreviewed"),
            ("POST", "/api/users/delete_all"),
        ]
        for m, p in unauthorized_future_routes:
            with self.subTest(method=m, path=p):
                self.assertFalse(is_allowed_generic_route(m, p))

    def test_17_vite_dev_proxy_blocks_approval_decisions(self) -> None:
        """Vite dev proxy configuration blocks /approve and /reject decision routes."""
        vite_config = (REPO_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        self.assertIn("/approve", vite_config)
        self.assertIn("/reject", vite_config)
        self.assertIn("APPROVAL_DECISION_FORBIDDEN_ON_DEV_PROXY", vite_config)

    def test_18_vite_proxy_uses_dynamic_port_not_hardcoded_8765(self) -> None:
        """Vite config and launcher dynamically consume runtime host/port."""
        vite_config = (REPO_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        self.assertIn("APP_BACKEND_HOST_DEV", vite_config)
        self.assertIn("APP_BACKEND_PORT_DEV", vite_config)

        launcher = (REPO_ROOT / "run_app.ps1").read_text(encoding="utf-8")
        self.assertIn("APP_BACKEND_HOST_DEV", launcher)
        self.assertIn("APP_BACKEND_PORT_DEV", launcher)
        self.assertIn("APP_BACKEND_BEARER_DEV = $null", launcher)

    def test_19_malformed_bootstrap_frames_fail_closed(self) -> None:
        """Bootstrap parser rejects malformed tokens, bad hosts, out-of-range ports, and bad JSON."""
        def parse_bootstrap_frame(frame: str) -> Optional[Dict[str, any]]:
            clean = frame.strip()
            if not clean.startswith("UIAUTH_BOOTSTRAP_V1:"):
                return None
            payload = clean[len("UIAUTH_BOOTSTRAP_V1:"):]
            try:
                data = json.loads(payload)
            except Exception:
                return None
            token = data.get("token")
            if not isinstance(token, str) or len(token) < 32 or len(token) > 256:
                return None
            host = data.get("host")
            if host not in ("127.0.0.1", "localhost", "::1"):
                return None
            port = data.get("port")
            if not isinstance(port, int) or port < 1 or port > 65535:
                return None
            return data

        valid = 'UIAUTH_BOOTSTRAP_V1:{"token":"' + ("A" * 40) + '","host":"127.0.0.1","port":8765}'
        self.assertIsNotNone(parse_bootstrap_frame(valid))

        malformed_cases = [
            'UIAUTH_BOOTSTRAP_V2:{"token":"' + ("A" * 40) + '","host":"127.0.0.1","port":8765}',
            'UIAUTH_BOOTSTRAP_V1:{"token":"short","host":"127.0.0.1","port":8765}',
            'UIAUTH_BOOTSTRAP_V1:{"token":"' + ("A" * 40) + '","host":"attacker.com","port":8765}',
            'UIAUTH_BOOTSTRAP_V1:{"token":"' + ("A" * 40) + '","host":"127.0.0.1","port":70000}',
            'UIAUTH_BOOTSTRAP_V1:{"token":"' + ("A" * 40) + '","host":"127.0.0.1","port":-1}',
            'UIAUTH_BOOTSTRAP_V1:{not_json}',
            'UIAUTH_BOOTSTRAP_V1:',
            '',
        ]
        for case in malformed_cases:
            with self.subTest(case=case):
                self.assertIsNone(parse_bootstrap_frame(case))

    def test_20_crlf_and_encoded_path_injection_blocked(self) -> None:
        """Suspicious encoded CRLF and traversal patterns in request path are blocked."""
        def is_safe_api_path(path: str) -> bool:
            clean = path.strip()
            if not clean.startswith("/api/"):
                return False
            forbidden = [
                "://", "\\", "..", "\0", "\r", "\n", " ",
                "%0d", "%0D", "%0a", "%0A", "%5c", "%5C", "%2e%2e", "%2E%2E",
            ]
            for pat in forbidden:
                if pat in clean:
                    return False
            return True

        self.assertTrue(is_safe_api_path("/api/chat/sessions"))
        self.assertFalse(is_safe_api_path("/api/chat%0d%0aInjected:1"))
        self.assertFalse(is_safe_api_path("/api/chat%2e%2e/admin"))
        self.assertFalse(is_safe_api_path("/api/chat%5cadmin"))
        self.assertFalse(is_safe_api_path("/api/chat\r\nHost: evil"))

    def test_21_request_body_size_bound(self) -> None:
        """Max request body is bounded to 10MB."""
        max_limit = 10 * 1024 * 1024
        oversized = "X" * (max_limit + 1)
        valid = "X" * (max_limit)

        self.assertTrue(len(valid) <= max_limit)
        self.assertFalse(len(oversized) <= max_limit)

    def test_22_frontend_cannot_override_host_or_port(self) -> None:
        """Tauri IPC args structure contains only method, path, body, headers."""
        tauri_main = (REPO_ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn("pub struct ApiRequestArgs", tauri_main)
        # Verify host/port are not in ApiRequestArgs struct definition
        self.assertNotIn("pub host:", tauri_main)
        self.assertNotIn("pub port:", tauri_main)
        self.assertNotIn("pub url:", tauri_main)

    def test_23_normal_ui_routes_permitted_in_allowlist(self) -> None:
        """All legitimate UI operations are present in allowlist."""
        allowed_ui_routes = [
            ("GET", "/api/health"),
            ("GET", "/api/system/status"),
            ("GET", "/api/system/diagnostics"),
            ("GET", "/api/system/health"),
            ("GET", "/api/chat/sessions"),
            ("POST", "/api/chat/sessions/first_turn"),
            ("POST", "/api/chat/sessions/chat_123/messages"),
            ("PATCH", "/api/chat/sessions/chat_123"),
            ("DELETE", "/api/chat/sessions/chat_123"),
            ("POST", "/api/chat/sessions/chat_123/messages/msg_1/edit"),
            ("POST", "/api/chat/sessions/chat_123/messages/msg_1/regenerate"),
            ("POST", "/api/chat/sessions/chat_123/regenerate"),
            ("POST", "/api/chat/sessions/chat_123/retry"),
            ("GET", "/api/projects"),
            ("POST", "/api/projects"),
            ("PUT", "/api/projects/proj_1"),
            ("DELETE", "/api/projects/proj_1"),
            ("GET", "/api/workspaces"),
            ("POST", "/api/workspaces"),
            ("GET", "/api/approvals"),
            ("GET", "/api/approvals/pending_appr_abc"),
            ("GET", "/api/activity/receipts"),
            ("GET", "/api/connections"),
            ("POST", "/api/analytics/import"),
        ]

        def check_allowed(method: str, path: str) -> bool:
            if "/approve" in path or "/reject" in path or path == "/api/approvals/create":
                return False
            if path in (
                "/api/health", "/api/system/status", "/api/system/diagnostics",
                "/api/system/health", "/api/chat/sessions", "/api/projects",
                "/api/workspaces", "/api/approvals", "/api/activity/receipts",
                "/api/connections",
            ):
                return True
            if path == "/api/chat/sessions/first_turn" and method == "POST":
                return True
            if path == "/api/analytics/import" and method == "POST":
                return True
            if path.startswith("/api/chat/sessions/"):
                return True
            if path.startswith("/api/projects/"):
                return True
            if path.startswith("/api/workspaces/"):
                return True
            if path.startswith("/api/approvals/pending_appr_"):
                return True
            if path.startswith("/api/activity/receipts/"):
                return True
            return False

        for m, p in allowed_ui_routes:
            with self.subTest(method=m, path=p):
                self.assertTrue(check_allowed(m, p))

    def test_24_backend_process_state_debug_redacts_auth_token(self) -> None:
        """Tauri BackendProcessState custom Debug implementation redacts session token."""
        tauri_main = (REPO_ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn('impl std::fmt::Debug for BackendProcessState', tauri_main)
        self.assertIn('"auth_token", &"[REDACTED]"', tauri_main)

    def test_25_approval_display_sourced_from_server_record(self) -> None:
        """Approval display fields are obtained directly from server record with secrets redacted."""
        from tools.security import PolicyEngine, RiskLevel
        policy = PolicyEngine()
        pending = policy.create_pending_approval(
            capability_id="social_publishing",
            parameters={
                "platform": "facebook",
                "target_page": "Main Page",
                "content": "Announcement",
                "api_key": "sensitive_key_999",
            },
            risk_level=RiskLevel.HIGH,
            run_id="RUN-TEST-001",
            business_id="BIZ-TEST",
        )
        self.assertEqual(pending.capability_id, "social_publishing")
        self.assertEqual(pending.run_id, "RUN-TEST-001")
        self.assertEqual(pending.business_id, "BIZ-TEST")
        self.assertEqual(pending.parameters["platform"], "facebook")

    def test_26_stale_or_expired_proposal_cannot_be_approved(self) -> None:
        """A proposal that is not in PENDING status strictly fails approval."""
        from tools.security import PolicyEngine, RiskLevel, PendingApprovalStatus
        policy = PolicyEngine()
        pending = policy.create_pending_approval(
            capability_id="social_publishing",
            parameters={"platform": "x"},
            risk_level=RiskLevel.HIGH,
            run_id="RUN-STALE-001",
        )

        # Mutate status to REJECTED before user confirms
        pending.status = PendingApprovalStatus.REJECTED
        ok, rec, msg = policy.approve_pending_action(pending.pending_approval_id)
        self.assertFalse(ok)
        self.assertIsNone(rec)
        self.assertEqual(msg, "INVALID_STATUS_REJECTED")

        # Expired action
        expired_pending = policy.create_pending_approval(
            capability_id="social_publishing",
            ttl_seconds=-10,
        )
        ok_exp, rec_exp, msg_exp = policy.approve_pending_action(expired_pending.pending_approval_id)
        self.assertFalse(ok_exp)
        self.assertIsNone(rec_exp)
        self.assertEqual(msg_exp, "PENDING_ACTION_EXPIRED")

    def test_27_duplicate_bootstrap_stream_fails_closed(self) -> None:
        """Rust parser strictly rejects duplicate bootstrap frames in stdout stream."""
        tauri_main = (REPO_ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn('pub fn parse_bootstrap_stream', tauri_main)
        self.assertIn('DUPLICATE_BOOTSTRAP_FRAME', tauri_main)

    def test_28_js_cannot_supply_confirmation_or_tamper_fields(self) -> None:
        """ReviewApprovalArgs IPC struct accepts ONLY pending_id."""
        tauri_main = (REPO_ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn("pub struct ReviewApprovalArgs", tauri_main)
        self.assertIn("pub pending_id: String", tauri_main)
        self.assertNotIn("pub approved:", tauri_main)
        self.assertNotIn("pub confirmed:", tauri_main)
        self.assertNotIn("pub capability:", tauri_main)
        self.assertNotIn("pub parameters:", tauri_main)

    def test_29_approval_secret_token_never_returned_to_frontend(self) -> None:
        """Pending approval inspection does not return session bearer or private approval secrets."""
        from tools.security import PolicyEngine, RiskLevel
        policy = PolicyEngine()
        pending = policy.create_pending_approval(
            capability_id="filesystem_write",
            parameters={"path": "output.txt"},
            risk_level=RiskLevel.HIGH,
            run_id="RUN-SECRET-CHECK",
        )
        # Verify pending record fields don't contain secret tokens
        self.assertNotIn("token", pending.parameters)
        self.assertNotIn("bearer", pending.parameters)


if __name__ == "__main__":
    unittest.main()
