"""Production restart durability contract for non-secret connection metadata."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_api.server import DepartmentAppBackend
from connections.models import ConnectionProfile


class ProductionConnectionProfileRestartDurabilityAdversarialV1Tests(unittest.TestCase):
    def test_connection_profile_survives_backend_restart_without_resolving_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {"APPDATA": tmpdir, "LOCALAPPDATA": tmpdir},
                clear=False,
            ):
                first = DepartmentAppBackend()
                first.connection_manager.register(
                    ConnectionProfile(
                        connection_id="CONN-META-RESTART-V1",
                        provider="meta",
                        display_name="Meta restart-safe account",
                        secret_ref="ENV:META_RESTART_TOKEN_V1",
                        business_id="BIZ-META-RESTART-V1",
                        project_ids=("PROJ-META-RESTART-V1",),
                    )
                )
                database_path = first.connection_manager.database_path
                self.assertTrue(first.connection_manager.durable)
                self.assertIsNotNone(database_path)
                assert database_path is not None
                self.assertTrue(database_path.is_relative_to(Path(tmpdir).resolve()))
                first.close()

                second = DepartmentAppBackend()
                try:
                    restored = second.connection_manager.get("CONN-META-RESTART-V1")
                    self.assertEqual(restored.provider, "meta")
                    self.assertEqual(restored.secret_ref, "ENV:META_RESTART_TOKEN_V1")
                    self.assertEqual(restored.business_id, "BIZ-META-RESTART-V1")
                    self.assertEqual(restored.project_ids, ("PROJ-META-RESTART-V1",))
                finally:
                    second.close()


if __name__ == "__main__":
    unittest.main()
