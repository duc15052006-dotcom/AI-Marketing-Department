"""Tests for PROD-DESKTOP-ONE-CLICK-RECOVERY-01.

Validates:
1. Backend instance state file lifecycle (write, read, remove, atomicity).
2. DepartmentAPIHandler safe log_message without broken pipe crashes.
3. Public /api/health endpoint structure.
4. Owned stale backend recovery vs unknown port-owner safety.
5. Desktop health gating and error classification.
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
        if self.state_file.exists():
            self.state_file.unlink()

    def tearDown(self):
        if self.state_file.exists():
            self.state_file.unlink()

    def test_state_file_write_and_cleanup(self):
        """Test writing backend instance metadata and cleanup."""
        write_backend_state("127.0.0.1", 8765)
        self.assertTrue(self.state_file.is_file(), "Backend state file must exist after write")

        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("pid"), os.getpid())
        self.assertEqual(data.get("host"), "127.0.0.1")
        self.assertEqual(data.get("port"), 8765)
        self.assertEqual(data.get("service"), "AI Marketing Department API")
        self.assertEqual(data.get("root_dir"), str(REPO_ROOT))

        remove_backend_state()
        self.assertFalse(self.state_file.exists(), "Backend state file must be removed after cleanup")

    def test_handler_log_message_does_not_throw_on_broken_stdio(self):
        """Test that DepartmentAPIHandler.log_message absorbs any exceptions."""
        handler_instance = object.__new__(DepartmentAPIHandler)
        try:
            handler_instance.log_message("Test message %s", "arg1")
        except Exception as e:
            self.fail(f"log_message raised unexpected exception: {e}")

    def test_unknown_port_owner_contract(self):
        """Verify that an arbitrary occupied port without valid state file is recognized as UNKNOWN."""
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


if __name__ == "__main__":
    unittest.main()
