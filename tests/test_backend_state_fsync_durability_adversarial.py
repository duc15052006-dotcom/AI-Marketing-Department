"""Adversarial RED for durable publication of the desktop backend state file.

A successful write_backend_state() is coordination evidence used across process
lifecycle boundaries. Atomic rename prevents torn names, but does not prove the
new bytes left Python/userspace buffers before the state file becomes visible.
The required ordering is explicit write -> flush -> fsync -> atomic replace.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_api.server import (
    get_backend_state_file_path,
    remove_backend_state,
    write_backend_state,
)


class _TrackedFile:
    def __init__(self, handle, events):
        self._handle = handle
        self._events = events

    def write(self, data):
        self._events.append("write")
        return self._handle.write(data)

    def flush(self):
        self._events.append("flush")
        return self._handle.flush()

    def fileno(self):
        return self._handle.fileno()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._handle.__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self._handle, name)


class BackendStateFsyncDurabilityAdversarialTests(unittest.TestCase):
    def test_backend_state_flushes_and_fsyncs_before_atomic_replace(self) -> None:
        events: list[str] = []
        real_path_open = Path.open
        real_replace = os.replace

        def tracked_open(path_obj, *args, **kwargs):
            return _TrackedFile(real_path_open(path_obj, *args, **kwargs), events)

        def tracked_fsync(fd):
            events.append("fsync")
            return None

        def tracked_replace(src, dst):
            events.append("replace")
            return real_replace(src, dst)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"APPDATA": tmpdir}, clear=False):
                with (
                    patch.object(Path, "open", tracked_open),
                    patch("app_api.server.os.fsync", side_effect=tracked_fsync),
                    patch("app_api.server.os.replace", side_effect=tracked_replace),
                ):
                    write_backend_state("127.0.0.1", 8765)

                state_path = get_backend_state_file_path()
                self.assertTrue(state_path.is_file())

                self.assertIn("write", events)
                self.assertIn(
                    "flush",
                    events,
                    "backend state must explicitly flush buffered bytes before publication",
                )
                self.assertIn(
                    "fsync",
                    events,
                    "backend state must fsync the temp file before atomic publication",
                )
                self.assertIn("replace", events)
                self.assertLess(events.index("write"), events.index("flush"))
                self.assertLess(events.index("flush"), events.index("fsync"))
                self.assertLess(events.index("fsync"), events.index("replace"))

                remove_backend_state()


if __name__ == "__main__":
    unittest.main()
