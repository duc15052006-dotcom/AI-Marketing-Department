import json
import tempfile
import unittest
from pathlib import Path

from integrations.models.settings_manager import (
    ModelSettings,
    ModelSettingsManager,
    ModelSettingsValidationError,
    PersistedSettingsCorruptionError,
)


class GovernanceBoolHardening10Tests(unittest.TestCase):
    def test_model_settings_accepts_real_booleans(self):
        self.assertIs(ModelSettings(free_only_mode=True).free_only_mode, True)
        self.assertIs(ModelSettings(free_only_mode=False).free_only_mode, False)

    def test_model_settings_rejects_non_boolean_free_only_values(self):
        for bad in (None, "", "false", "true", 0, 1, [], {}):
            with self.subTest(value=bad):
                with self.assertRaises(ModelSettingsValidationError):
                    ModelSettings(free_only_mode=bad)

    def test_persisted_non_boolean_free_only_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model_settings.json"
            path.write_text(json.dumps({"free_only_mode": None}), encoding="utf-8")
            with self.assertRaises(PersistedSettingsCorruptionError):
                ModelSettingsManager(settings_file_path=path)

    def test_update_non_boolean_cannot_disable_free_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model_settings.json"
            mgr = ModelSettingsManager(settings_file_path=path)
            before = mgr.get_settings()
            self.assertIs(before.free_only_mode, True)

            for bad in (None, "", "false", "true", 0, 1):
                with self.subTest(value=bad):
                    with self.assertRaises(ModelSettingsValidationError):
                        mgr.update_settings(
                            {"free_only_mode": bad},
                            expected_revision=before.settings_revision,
                        )
                    after = mgr.get_settings()
                    self.assertIs(after.free_only_mode, True)
                    self.assertEqual(after.settings_revision, before.settings_revision)

    def test_update_real_false_is_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model_settings.json"
            mgr = ModelSettingsManager(settings_file_path=path)
            before = mgr.get_settings()
            after = mgr.update_settings(
                {"free_only_mode": False},
                expected_revision=before.settings_revision,
            )
            self.assertIs(after.free_only_mode, False)
            self.assertEqual(after.settings_revision, before.settings_revision + 1)


if __name__ == "__main__":
    unittest.main()
