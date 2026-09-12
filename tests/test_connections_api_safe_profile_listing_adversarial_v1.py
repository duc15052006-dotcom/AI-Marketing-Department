"""Safe API listing contract for durable connection profiles."""

from __future__ import annotations

import json
import unittest

from app_api.server import APP_BACKEND, DepartmentAPIHandler
from connections.models import ConnectionProfile


class ConnectionsApiSafeProfileListingAdversarialV1Tests(unittest.TestCase):
    def test_profile_listing_is_visible_but_never_exposes_secret_locator(self) -> None:
        connection_id = "CONN-SAFE-API-LIST-V1"
        APP_BACKEND.connection_manager.register(
            ConnectionProfile(
                connection_id=connection_id,
                provider="meta",
                display_name="Safe API profile",
                secret_ref="ENV:CONNECTION_API_SECRET_PLACEHOLDER_V1",
                endpoint="https://graph.example.invalid",
                business_id="BIZ-SAFE-API-V1",
                project_ids=("PROJ-SAFE-API-V1",),
                brand_ids=("BRAND-SAFE-API-V1",),
            )
        )
        try:
            report = DepartmentAPIHandler._connection_profiles_report()
            selected = next(item for item in report if item["connection_id"] == connection_id)
            self.assertEqual(selected["provider"], "meta")
            self.assertTrue(selected["enabled"])
            serialized = json.dumps(selected, sort_keys=True)
            self.assertNotIn("secret_ref", serialized.lower())
            self.assertNotIn("credential", serialized.lower())
            self.assertNotIn("CONNECTION_API_SECRET_PLACEHOLDER_V1", serialized)
        finally:
            APP_BACKEND.connection_manager.remove(connection_id)


if __name__ == "__main__":
    unittest.main()
