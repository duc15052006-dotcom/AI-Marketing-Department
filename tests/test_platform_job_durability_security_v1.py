"""Security regressions for Platform Batch #8 durable job storage."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.job_store import DurableJobRecord, JobStoreError, SQLiteJobRepository


class TestPlatformJobDurabilitySecurityV1(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "jobs.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _record(objective: str) -> DurableJobRecord:
        return DurableJobRecord(
            run_id="RUN-DURABILITY-SECURITY-001",
            objective=objective,
            business_id="BIZ-SECURITY",
            status="QUEUED",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def test_objective_secrets_are_redacted_before_hash_and_persistence(self) -> None:
        bearer = "objective-bearer-secret-123456"
        api_key = "objective-api-key-654321"
        repo = SQLiteJobRepository(self.db_path)
        saved = repo.create_job(
            self._record(f"Audit Authorization: Bearer {bearer} api_key={api_key}")
        )

        self.assertNotIn(bearer, saved.objective)
        self.assertNotIn(api_key, saved.objective)
        self.assertTrue(saved.verify_integrity())
        repo.close()

        raw = sqlite3.connect(str(self.db_path))
        objective = raw.execute(
            "SELECT objective FROM jobs WHERE run_id=?",
            ("RUN-DURABILITY-SECURITY-001",),
        ).fetchone()[0]
        raw.close()
        self.assertNotIn(bearer, objective)
        self.assertNotIn(api_key, objective)

    def test_closed_database_write_is_translated_to_job_store_error(self) -> None:
        repo = SQLiteJobRepository(self.db_path)
        saved = repo.create_job(self._record("safe objective"))
        repo.close()

        with self.assertRaisesRegex(JobStoreError, "JOB_STORE_SAVE_FAILED"):
            repo.save_job(saved)


if __name__ == "__main__":
    unittest.main()
