import tempfile
import unittest
from pathlib import Path

from integrations.models.registry import ProviderRegistry
from integrations.models.secret_store import InMemorySecretStore
from integrations.models.settings_manager import ModelSettings, ModelSettingsManager


class ModelSettingsDefaultProviderAuthorityV1Tests(unittest.TestCase):
    def test_model_settings_schema_default_is_xkiro_without_hidden_fallback(self):
        settings = ModelSettings()
        self.assertEqual(settings.global_target.provider_id, "xkiro")
        self.assertEqual(
            settings.global_target.model_id,
            "mistralai/mistral-large-2512",
        )
        self.assertEqual(
            settings.fallback_chain,
            [],
            "schema defaults must not silently inject alternate providers",
        )

    def test_fresh_settings_manager_initializes_xkiro_without_hidden_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "model_settings.json"
            manager = ModelSettingsManager(
                settings_file_path=settings_path,
                secret_store=InMemorySecretStore(),
                provider_registry=ProviderRegistry(),
            )
            settings = manager.get_settings()

        self.assertEqual(settings.global_target.provider_id, "xkiro")
        self.assertEqual(
            settings.global_target.model_id,
            "mistralai/mistral-large-2512",
        )
        self.assertEqual(
            settings.fallback_chain,
            [],
            "fresh persisted Settings must leave fallback authority to explicit user configuration",
        )


if __name__ == "__main__":
    unittest.main()
