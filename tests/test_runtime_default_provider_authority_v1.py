import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.authority import ConfigurationAuthority, RuntimeConfigSnapshot


class RuntimeDefaultProviderAuthorityV1Tests(unittest.TestCase):
    def tearDown(self):
        ConfigurationAuthority.reset()

    def test_schema_and_clean_runtime_default_to_xkiro(self):
        self.assertEqual(
            RuntimeConfigSnapshot().default_provider,
            "xkiro",
            "the immutable runtime schema default must match the configured current provider authority",
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {}, clear=True):
            ConfigurationAuthority.reset()
            authority = ConfigurationAuthority(
                env_file_path=Path(tmpdir) / "missing.env",
            )
            snapshot = authority.get_snapshot()

        self.assertEqual(
            snapshot.default_provider,
            "xkiro",
            "a clean runtime must not silently select Gemini when no DEFAULT_PROVIDER is configured",
        )

    def test_explicit_default_provider_still_overrides_code_default(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {}, clear=True):
            ConfigurationAuthority.reset()
            authority = ConfigurationAuthority(
                env_file_path=Path(tmpdir) / "missing.env",
                explicit_overrides={"DEFAULT_PROVIDER": "acme-lab"},
            )
            snapshot = authority.get_snapshot()

        self.assertEqual(snapshot.default_provider, "acme-lab")


if __name__ == "__main__":
    unittest.main()
