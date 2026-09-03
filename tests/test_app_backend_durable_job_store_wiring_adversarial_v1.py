"""Adversarial production-composition contract for durable queue persistence.

The lower-level RunManager/SQLiteJobRepository restart tests prove that queue
state is designed to survive process restarts. This test guards the production
composition root itself: the backend used by API queue routes must actually
wire a durable repository into its RunManager.
"""

import unittest

from app_api.server import APP_BACKEND


class AppBackendDurableJobStoreWiringAdversarialV1Tests(unittest.TestCase):
    def test_production_backend_enables_durable_job_persistence(self) -> None:
        manager = APP_BACKEND.run_manager

        self.assertIsNotNone(
            manager.job_repository,
            "Production APP_BACKEND must wire a durable job repository; "
            "otherwise queued jobs exist only in process memory and cannot "
            "participate in RunManager startup recovery.",
        )
        self.assertTrue(
            manager.get_queue_stats()["durability_enabled"],
            "Production APP_BACKEND must expose durability_enabled=True.",
        )


if __name__ == "__main__":
    unittest.main()
