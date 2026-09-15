"""Production composition contract for the governed marketing provider catalog."""

from __future__ import annotations

import unittest

from app_api.server import APP_BACKEND
from connectors.marketing.catalog import (
    GOOGLE_ADS_CONNECTOR_ID,
    GOOGLE_ANALYTICS_CONNECTOR_ID,
    META_CONNECTOR_ID,
    TIKTOK_CONNECTOR_ID,
)


class ProductionMarketingCatalogWiringAdversarialV1Tests(unittest.TestCase):
    def test_catalog_authorities_are_composed_but_live_execution_stays_disabled(self) -> None:
        expected = {
            GOOGLE_ADS_CONNECTOR_ID,
            GOOGLE_ANALYTICS_CONNECTOR_ID,
            META_CONNECTOR_ID,
            TIKTOK_CONNECTOR_ID,
        }

        self.assertIs(
            APP_BACKEND.marketing_registry,
            APP_BACKEND.dynamic_tool_gateway.marketing_registry,
        )
        self.assertIs(
            APP_BACKEND.marketing_executor_registry,
            APP_BACKEND.dynamic_tool_gateway.marketing_live_executor_registry,
        )
        self.assertIs(
            APP_BACKEND.conn_registry,
            APP_BACKEND.connector_control_plane.connector_registry,
        )
        self.assertEqual(
            {spec.connector_id for spec in APP_BACKEND.marketing_registry.list_specs()},
            expected,
        )
        self.assertEqual(
            set(APP_BACKEND.marketing_executor_registry.list_bindings()),
            expected,
        )

        self.assertFalse(APP_BACKEND.dynamic_tool_gateway.allow_live_marketing_execution)
        self.assertEqual(APP_BACKEND.connection_manager.list_profiles(), [])
        for connector_id in expected:
            self.assertIsNone(
                APP_BACKEND.cap_registry.get_capability(
                    f"marketing.{connector_id}.analytics_retrieval"
                )
            )

    def test_external_operation_authorities_are_restart_durable(self) -> None:
        self.assertTrue(APP_BACKEND.provider_preflight_repository.durable)
        self.assertIsNotNone(APP_BACKEND.provider_preflight_repository.database_path)
        self.assertIsNotNone(APP_BACKEND.provider_operation_repository.database_path)

    def test_backend_close_releases_all_durable_marketing_stores(self) -> None:
        from app_api.server import DepartmentAppBackend

        backend = DepartmentAppBackend()
        backend.close()
        backend.close()

        with self.assertRaisesRegex(Exception, "PROVIDER_PREFLIGHT_STORE_CLOSED"):
            backend.provider_preflight_repository.get("PREFLIGHT-CLOSED")
        with self.assertRaisesRegex(Exception, "PROVIDER_OPERATION_STORE_CLOSED"):
            backend.provider_operation_repository.list_scope(
                business_id="BIZ-CLOSED",
                project_id=None,
                brand_id=None,
            )


if __name__ == "__main__":
    unittest.main()
