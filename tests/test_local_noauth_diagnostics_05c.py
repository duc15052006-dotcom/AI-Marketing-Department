"""Regression tests for local OpenAI-compatible no-auth diagnostics.

FIX-LOCAL-NOAUTH-DIAGNOSTICS-05C
"""

from __future__ import annotations

import http.server
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from app_api.server import APP_BACKEND, DepartmentAPIHandler, GLOBAL_API_SESSION_TOKEN
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ProviderRegistry
from integrations.models.secret_store import InMemorySecretStore
from integrations.models.settings_manager import ModelSettingsManager


class TestLocalNoAuthDiagnostics05C(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="local_noauth_diag_")
        self.old_manager = APP_BACKEND.settings_manager

        registry = ProviderRegistry()
        gateway = UniversalModelGateway(provider_registry=registry, free_only_mode=True)
        APP_BACKEND.settings_manager = ModelSettingsManager(
            settings_file_path=Path(self.tmp) / "model_settings.json",
            secret_store=InMemorySecretStore(),
            provider_registry=registry,
            gateway=gateway,
        )

        self.server = http.server.HTTPServer(("127.0.0.1", 0), DepartmentAPIHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        APP_BACKEND.settings_manager = self.old_manager
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1.0)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _upsert(self, provider_id: str, base_url: str) -> tuple[int, dict]:
        revision = APP_BACKEND.settings_manager.get_settings().settings_revision
        body = {
            "expected_revision": revision,
            "provider_id": provider_id,
            "display_name": provider_id,
            "adapter_type": "OPENAI_COMPATIBLE",
            "base_url": base_url,
            "default_model": "local-test-model",
            "cost_policy": "FREE_TIER_ALLOWED",
            "enabled": True,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/api/settings/providers/upsert",
            data=data,
            method="POST",
            headers={
                "Host": "127.0.0.1",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GLOBAL_API_SESSION_TOKEN}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_loopback_no_key_is_reported_configured(self) -> None:
        status, payload = self._upsert("local_noauth", "http://127.0.0.1:11434/v1")
        self.assertEqual(status, 200)
        self.assertFalse(payload["has_credential"])
        self.assertFalse(payload["requires_api_key"])
        self.assertTrue(payload["is_configured"])

    def test_remote_no_key_remains_unconfigured(self) -> None:
        status, payload = self._upsert("remote_noauth", "https://example.com/v1")
        self.assertEqual(status, 200)
        self.assertFalse(payload["has_credential"])
        self.assertTrue(payload["requires_api_key"])
        self.assertFalse(payload["is_configured"])


if __name__ == "__main__":
    unittest.main()
