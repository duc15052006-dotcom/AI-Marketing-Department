from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from connectors.marketing.preflight import (
    ProviderPreflightConflictError,
    ProviderPreflightRepository,
    ProviderPreflightState,
)


class ProviderPreflightExpiryRaceTests(unittest.TestCase):
    RAW_KEY = "idem-preflight-expiry-race-0001"

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
            idempotency_key=ProviderPreflightExpiryRaceTests.RAW_KEY,
            provider_snapshot={"creator_username": "creator-1"},
            user_choices={"privacy_level": "SELF_ONLY", "consent_confirmed": True},
            approved_payload={"title": "Approved caption"},
            ttl_seconds=60,
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
            idempotency_key=ProviderPreflightExpiryRaceTests.RAW_KEY,
        )

    def test_stale_expiry_cannot_overwrite_successful_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "preflight.sqlite3"
            expirer = ProviderPreflightRepository(db_path)
            claimer = ProviderPreflightRepository(db_path)
            record = self._create(expirer)

            expires_at = datetime.fromisoformat(record.expires_at)
            before_expiry = expires_at - timedelta(seconds=1)
            after_expiry = expires_at + timedelta(seconds=1)

            read_barrier = threading.Barrier(2)
            claim_done = threading.Event()
            outcomes: dict[str, object] = {}

            original_expirer_get = expirer.get
            original_claimer_get = claimer.get
            original_expirer_store = expirer._store_replace

            def expirer_get(preflight_id: str):
                value = original_expirer_get(preflight_id)
                read_barrier.wait(timeout=5)
                return value

            def claimer_get(preflight_id: str):
                value = original_claimer_get(preflight_id)
                read_barrier.wait(timeout=5)
                return value

            def delayed_expiry_store(value):
                self.assertTrue(claim_done.wait(timeout=5), "claimer did not finish before stale expiry write")
                return original_expirer_store(value)

            def fake_now():
                return after_expiry if threading.current_thread().name == "expire-worker" else before_expiry

            def expire_worker() -> None:
                try:
                    self._claim(expirer, record.preflight_id)
                except ProviderPreflightConflictError as exc:
                    outcomes["expire_error"] = str(exc)
                except BaseException as exc:  # pragma: no cover - surfaced by assertions below
                    outcomes["expire_exception"] = exc

            def claim_worker() -> None:
                try:
                    outcomes["claimed"] = self._claim(claimer, record.preflight_id).state
                except BaseException as exc:  # pragma: no cover - surfaced by assertions below
                    outcomes["claim_exception"] = exc
                finally:
                    claim_done.set()

            with (
                patch.object(expirer, "get", side_effect=expirer_get),
                patch.object(claimer, "get", side_effect=claimer_get),
                patch.object(expirer, "_store_replace", side_effect=delayed_expiry_store),
                patch("connectors.marketing.preflight._utc_now", side_effect=fake_now),
            ):
                t_expire = threading.Thread(target=expire_worker, name="expire-worker")
                t_claim = threading.Thread(target=claim_worker, name="claim-worker")
                t_expire.start()
                t_claim.start()
                t_expire.join(timeout=10)
                t_claim.join(timeout=10)

            expire_alive = t_expire.is_alive()
            claim_alive = t_claim.is_alive()
            final = claimer.get(record.preflight_id)
            final_state = final.state if final is not None else None
            expirer.close()
            claimer.close()

            self.assertFalse(expire_alive, "expire worker deadlocked")
            self.assertFalse(claim_alive, "claim worker deadlocked")
            self.assertNotIn("expire_exception", outcomes, outcomes)
            self.assertNotIn("claim_exception", outcomes, outcomes)
            self.assertEqual(ProviderPreflightState.CLAIMED, outcomes.get("claimed"), outcomes)
            self.assertIn("expire_error", outcomes, outcomes)
            self.assertEqual(
                ProviderPreflightState.CLAIMED,
                final_state,
                "stale expiry must not overwrite a claim that already committed",
            )


if __name__ == "__main__":
    unittest.main()
