from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from connectors.marketing.preflight import (
    ProviderPreflightConflictError,
    ProviderPreflightRepository,
    ProviderPreflightState,
)


class ProviderPreflightRevokeRaceTests(unittest.TestCase):
    RAW_KEY = "idem-tiktok-revoke-race-0001"

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
            idempotency_key=ProviderPreflightRevokeRaceTests.RAW_KEY,
            provider_snapshot={"creator_username": "creator-1"},
            user_choices={"privacy_level": "SELF_ONLY", "consent_confirmed": True},
            approved_payload={"title": "User-approved caption"},
            ttl_seconds=900,
        )

    def test_two_sqlite_repositories_cannot_both_revoke_same_active_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "preflight-revoke-race.sqlite3"
            repo1 = ProviderPreflightRepository(db_path)
            record = self._create(repo1)
            repo2 = ProviderPreflightRepository(db_path)
            barrier = threading.Barrier(2)
            original_get1 = repo1.get
            original_get2 = repo2.get

            def synchronized_get(original_get, preflight_id: str):
                current = original_get(preflight_id)
                if current is not None and current.state is ProviderPreflightState.ACTIVE:
                    barrier.wait(timeout=5)
                return current

            def revoke_once(repo: ProviderPreflightRepository):
                try:
                    revoked = repo.revoke(record.preflight_id)
                    return ("revoked", revoked.state)
                except ProviderPreflightConflictError:
                    return ("conflict", None)

            try:
                with patch.object(repo1, "get", side_effect=lambda key: synchronized_get(original_get1, key)), patch.object(
                    repo2,
                    "get",
                    side_effect=lambda key: synchronized_get(original_get2, key),
                ):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        futures = [pool.submit(revoke_once, repo) for repo in (repo1, repo2)]
                        outcomes = [future.result(timeout=10) for future in futures]

                self.assertEqual(1, sum(kind == "revoked" for kind, _ in outcomes), outcomes)
                self.assertEqual(1, sum(kind == "conflict" for kind, _ in outcomes), outcomes)
                self.assertEqual(ProviderPreflightState.REVOKED, repo1.get(record.preflight_id).state)
            finally:
                repo2.close()
                repo1.close()


if __name__ == "__main__":
    unittest.main()
