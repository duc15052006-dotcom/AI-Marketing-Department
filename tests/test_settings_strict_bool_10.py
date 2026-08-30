"""Regression coverage for strict boolean model-settings governance."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from integrations.models.registry import ProviderRegistry
from integrations.models.secret_store import InMemorySecretStore
from integrations.models.settings_manager import (
    ModelSettings,
    ModelSettingsManager,
    PersistedSettingsCorruptionError,
)


class TestSettingsStrictBool10(unittest.TestCase):
    def _new_manager(self, settings_path: Path) -> ModelSettingsManager:
        secret_store = InMemorySecretStore()
        registry = ProviderRegistry()
        return ModelSettingsManager(
            settings_file_path=settings_path,
            secret_store=secret_store,
            provider_registry=registry,
            gateway=None,
        )

    def test_01_model_settings_rejects_non_boolean_free_only_mode(self) -> None:
        for invalid in ("false", "true", "0", "1", 0, 1, None, [], {}):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "INVALID_BOOLEAN"):
                    ModelSettings(free_only_mode=invalid)

    def test_02_update_rejects_non_boolean_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings_path = Path(td) / "model_settings.json"
            manager = self._new_manager(settings_path)
            initial = manager.get_settings()
            initial_file = settings_path.read_text(encoding="utf-8")

            for invalid in ("false", "true", 0, 1):
                with self.subTest(invalid=invalid):
                    with self.assertRaisesRegex(ValueError, "INVALID_BOOLEAN"):
                        manager.update_settings({"free_only_mode": invalid})
                    current = manager.get_settings()
                    self.assertEqual(current.settings_revision, initial.settings_revision)
                    self.assertIs(current.free_only_mode, initial.free_only_mode)
                    self.assertEqual(settings_path.read_text(encoding="utf-8"), initial_file)

    def test_03_real_booleans_update_and_persist_normally(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings_path = Path(td) / "model_settings.json"
            manager = self._new_manager(settings_path)
            rev = manager.get_settings().settings_revision

            updated = manager.update_settings({"free_only_mode": False})
            self.assertIs(updated.free_only_mode, False)
            self.assertEqual(updated.settings_revision, rev + 1)
            persisted = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIs(persisted["free_only_mode"], False)

            updated = manager.update_settings({"free_only_mode": True})
            self.assertIs(updated.free_only_mode, True)
            self.assertEqual(updated.settings_revision, rev + 2)
            persisted = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIs(persisted["free_only_mode"], True)

    def test_04_persisted_non_boolean_fails_closed_and_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings_path = Path(td) / "model_settings.json"
            manager = self._new_manager(settings_path)
            payload = manager.get_settings().model_dump()
            payload["free_only_mode"] = "false"
            malformed_text = json.dumps(payload, indent=2)
            settings_path.write_text(malformed_text, encoding="utf-8")

            with self.assertRaisesRegex(PersistedSettingsCorruptionError, "CORRUPT_MODEL_SETTINGS_FILE"):
                self._new_manager(settings_path)

            self.assertEqual(settings_path.read_text(encoding="utf-8"), malformed_text)


if __name__ == "__main__":
    unittest.main()
