from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from connectors.marketing.preflight import (
    ProviderPreflightConflictError,
    ProviderPreflightRepository,
    ProviderPreflightState,
)


class ProviderPreflightExpiryStaleWriteTests(unittest.TestCase):
    RAW_KEY = "idem-tiktok-expiry-race-0001"

    @staticmethod
    def _create(repo: ProviderPreflightRepository):
        return repo.create(
            provider="tiktok",
            connector_id="conn_tiktok_live",
            connection_id="tiktok-main",
            business_id="biz-1",
            project_id="proj-1",
            brand_id="brand-1",
            purpose="social_publishing",
            idempotency_key=ProviderPreflightExpiryStaleWriteTests.RAW_KEY,
            provider_snapshot={"creator_username": "creator-1"},
            user_choices={"privacy_level": "SELF_ONLY", "consent_confirmed": True},
            approved_payload={"title": "User-approved caption"},
            ttl_seconds=900,
        )

    @staticmethod
    def _claim(repo: ProviderPreflightRepository, preflight_id: str):
        return repo.claim(
            preflight_id,
            provider="tiktok",
            connector_id="conn_tiktok_live",
            connection_id="tiktok-main",
            business_id="biz-1",
            project_id="proj-1",
            brand_id="brand-1",
            purpose="social_publishing",
            idempotency_key=ProviderPreflightExpiryStaleWriteTests.RAW_KEY,
        )

    def test_stale_expiry_writer_cannot_overwrite_committed_revoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "preflight-expiry-stale-write.sqlite3"
            repo1 = ProviderPreflightRepository(db_path)
            record = self._create(repo1)
            repo2 = ProviderPreflightRepository(db_path)
            read_active = threading.Event()
            release_stale_reader = threading.Event()
            original_get = repo1.get
            future = datetime.fromisoformat(record.expires_at) + timedelta(seconds=1)

            def stale_get(preflight_id: str):
                current = original_get(preflight_id)
                if current is not None and current.state is ProviderPreflightState.ACTIVE:
                    read_active.set()
                    if not release_stale_reader.wait(timeout=5):
                        raise TimeoutError("stale expiry reader was not released")
                return current

            def expire_from_stale_read() -> None:
                with patch("connectors.marketing.preflight._utc_now", return_value=future):
                    with self.assertRaises(ProviderPreflightConflictError):
                        self._claim(repo1, record.preflight_id)

            try:
                with patch.object(repo1, "get", side_effect=stale_get):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        stale_future = pool.submit(expire_from_stale_read)
                        self.assertTrue(read_active.wait(timeout=5), "expiry claimant did not read ACTIVE")
                        revoked = repo2.revoke(record.preflight_id)
                        self.assertEqual(ProviderPreflightState.REVOKED, revoked.state)
                        release_stale_reader.set()
                        stale_future.result(timeout=10)

                self.assertEqual(
                    ProviderPreflightState.REVOKED,
                    repo2.get(record.preflight_id).state,
                    "a stale expiry transition must not overwrite a committed state change",
                )
            finally:
                release_stale_reader.set()
                repo2.close()
                repo1.close()


if __name__ == "__main__":
    unittest.main()
