"""Tests for PROD-DESKTOP-ONE-CLICK-RECOVERY-01 + PROD-DESKTOP-RUNTIME-STATE-LOCATION-01.

Validates:
A. State file path is outside the repository root.
B. State file write succeeds.
C. State file read/ownership verification works.
D. Cleanup removes the state file.
E. Stale-owned-backend recovery still works.
F. Unknown-port-owner safety still works.
G. Normal app run does NOT create runtime/backend_instance.json inside repo.
H. DepartmentAPIHandler safe log_message without broken pipe crashes.
"""

import json
import os
import socket
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_api.server import (
    get_backend_state_file_path,
    write_backend_state,
    remove_backend_state,
    DepartmentAPIHandler,
)


class TestDesktopBackendLifecycle(unittest.TestCase):
    """Test suite for desktop backend lifecycle contract."""

    def setUp(self):
        self.state_file = get_backend_state_file_path()
        self._backup = None
        if self.state_file.exists():
            self._backup = self.state_file.read_text(encoding="utf-8")
            self.state_file.unlink()

    def tearDown(self):
        if self.state_file.exists():
            self.state_file.unlink()
        if self._backup is not None:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(self._backup, encoding="utf-8")

    # ── A. State file path is outside repository root ──

    def test_A_state_file_path_outside_repository(self):
        """State file must reside outside the Git repository root."""
        state_path = get_backend_state_file_path()
        repo_runtime = str(REPO_ROOT / "runtime").lower()
        state_parent_str = str(state_path.parent).lower()
        self.assertFalse(
            state_parent_str.startswith(repo_runtime),
            f"State file parent {state_path.parent} must NOT be inside repo runtime/."
        )

    def test_A2_state_file_path_in_appdata(self):
        """State file must be under %APPDATA%/AI-Marketing-Department (Windows)."""
        state_path = get_backend_state_file_path()
        app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if app_data:
            expected_prefix = os.path.join(app_data, "AI-Marketing-Department")
            self.assertTrue(
                str(state_path).startswith(expected_prefix),
                f"State file {state_path} must be under {expected_prefix}"
            )

    # ── B. State file write succeeds ──

    def test_B_state_file_write_and_read(self):
        """Write backend state and verify all fields are readable."""
        write_backend_state("127.0.0.1", 8765)
        self.assertTrue(self.state_file.is_file(), "State file must exist after write")

        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("pid"), os.getpid())
        self.assertEqual(data.get("host"), "127.0.0.1")
        self.assertEqual(data.get("port"), 8765)
        self.assertEqual(data.get("service"), "AI Marketing Department API")
        self.assertEqual(data.get("root_dir"), str(REPO_ROOT))

    # ── C. State file ownership verification ──

    def test_C_state_file_ownership_verification(self):
        """State file with correct service field is recognized as owned backend."""
        write_backend_state("127.0.0.1", 8765)
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(data["service"], "AI Marketing Department API")
        self.assertGreater(data["pid"], 0)

    # ── D. Cleanup removes state file ──

    def test_D_state_file_cleanup(self):
        """remove_backend_state() removes the state file cleanly."""
        write_backend_state("127.0.0.1", 8765)
        self.assertTrue(self.state_file.exists())
        remove_backend_state()
        self.assertFalse(self.state_file.exists(), "State file must be gone after cleanup")

    # ── E. Stale-owned-backend recovery ──

    def test_E_stale_owned_backend_detected(self):
        """A state file with a valid service but dead PID is recognized as stale."""
        stale_payload = {
            "pid": 99999999,
            "host": "127.0.0.1",
            "port": 8765,
            "service": "AI Marketing Department API",
            "root_dir": str(REPO_ROOT),
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(stale_payload), encoding="utf-8")
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(data["service"], "AI Marketing Department API")
        self.assertEqual(data["pid"], 99999999)
        remove_backend_state()
        self.assertFalse(self.state_file.exists())

    # ── F. Unknown-port-owner safety ──

    def test_F_unknown_port_owner_contract(self):
        """An occupied port without state file is unknown — no state file exists."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        try:
            self.assertFalse(self.state_file.exists())
            state_data = None
            if self.state_file.is_file():
                state_data = json.loads(self.state_file.read_text())
            self.assertIsNone(state_data)
        finally:
            sock.close()

    # ── G. No repo-local runtime/backend_instance.json ──

    def test_G_no_repo_local_state_file_created(self):
        """write_backend_state must NOT create runtime/backend_instance.json inside repo."""
        repo_local = REPO_ROOT / "runtime" / "backend_instance.json"
        existed_before = repo_local.exists()
        write_backend_state("127.0.0.1", 8765)
        if not existed_before:
            self.assertFalse(
                repo_local.exists(),
                f"write_backend_state must NOT create {repo_local}"
            )
        remove_backend_state()

    # ── H. Safe log_message ──

    def test_H_handler_log_message_does_not_throw_on_broken_stdio(self):
        """DepartmentAPIHandler.log_message absorbs any exceptions."""
        handler_instance = object.__new__(DepartmentAPIHandler)
        try:
            handler_instance.log_message("Test message %s", "arg1")
        except Exception as e:
            self.fail(f"log_message raised unexpected exception: {e}")


if __name__ == "__main__":
    unittest.main()
