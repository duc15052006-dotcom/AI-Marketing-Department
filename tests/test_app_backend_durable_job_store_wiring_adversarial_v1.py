"""Adversarial production-composition contract for durable queue persistence.

The lower-level RunManager/SQLiteJobRepository restart tests prove that queue
state is designed to survive process restarts. These tests guard the production
composition root itself: the backend used by API queue routes must actually
wire a disk-backed durable repository, and a fresh backend must recover the same
terminal queue history from the canonical per-user runtime directory.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app_api.server import APP_BACKEND, DepartmentAppBackend
from runtime.job_store import DurableJobRecord, SQLiteJobRepository
from runtime.queue import RunQueueStatus


class AppBackendDurableJobStoreWiringAdversarialV1Tests(unittest.TestCase):
    def test_production_backend_enables_durable_job_persistence(self) -> None:
        manager = APP_BACKEND.run_manager

        self.assertIsNotNone(
            manager.job_repository,
            "Production APP_BACKEND must wire a durable job repository; "
            "otherwise queued jobs exist only in process memory and cannot "
            "participate in RunManager startup recovery.",
        )
        self.assertIsInstance(
            manager.job_repository,
            SQLiteJobRepository,
            "Production APP_BACKEND must use the durable SQLite job repository.",
        )
        self.assertTrue(
            manager.get_queue_stats()["durability_enabled"],
            "Production APP_BACKEND must expose durability_enabled=True.",
        )

    def test_fresh_backend_recovers_terminal_job_from_same_runtime_directory(self) -> None:
        run_id = "RUN-PROD-DURABILITY-RESTART-V1"
        now = datetime.now(timezone.utc).isoformat()

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"APPDATA": tmpdir, "LOCALAPPDATA": tmpdir}
            with patch.dict(os.environ, env, clear=False):
                first = DepartmentAppBackend()
                first_repo = first.run_manager.job_repository
                self.assertIsInstance(
                    first_repo,
                    SQLiteJobRepository,
                    "A freshly constructed production backend must use disk-backed job storage.",
                )
                assert isinstance(first_repo, SQLiteJobRepository)

                runtime_root = Path(tmpdir).resolve()
                self.assertTrue(
                    first_repo.database_path.is_relative_to(runtime_root),
                    "The production job database must live under the configured per-user runtime root.",
                )

                first_repo.create_job(
                    DurableJobRecord(
                        run_id=run_id,
                        objective="prove production queue durability",
                        status=RunQueueStatus.COMPLETED.value,
                        created_at=now,
                        completed_at=now,
                    )
                )
                first.run_manager.shutdown(wait=True, cancel_pending=True)
                first_repo.close()

                second = DepartmentAppBackend()
                second_repo = second.run_manager.job_repository
                try:
                    self.assertIsInstance(second_repo, SQLiteJobRepository)
                    assert isinstance(second_repo, SQLiteJobRepository)
                    self.assertEqual(second_repo.database_path, first_repo.database_path)

                    restored = second.run_manager.get_run(run_id)
                    self.assertIsNotNone(
                        restored,
                        "Fresh production backend must restore durable terminal queue history.",
                    )
                    assert restored is not None
                    self.assertEqual(restored.status, RunQueueStatus.COMPLETED)
                    self.assertEqual(restored.objective, "prove production queue durability")
                finally:
                    second.run_manager.shutdown(wait=True, cancel_pending=True)
                    if isinstance(second_repo, SQLiteJobRepository):
                        second_repo.close()


if __name__ == "__main__":
    unittest.main()
