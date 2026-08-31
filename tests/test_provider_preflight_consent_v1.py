from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from connectors.marketing.preflight import (
    ProviderPreflightConflictError,
    ProviderPreflightIntegrityError,
    ProviderPreflightRepository,
    ProviderPreflightState,
)


class ProviderPreflightConsentV1Tests(unittest.TestCase):
    RAW_KEY = "idem-tiktok-publish-do-not-store-0001"

    @staticmethod
    def _create(repo: ProviderPreflightRepository, **overrides):
        values = {
            "provider": "tiktok",
            "connector_id": "conn_tiktok_live",
            "connection_id": "tiktok-main",
            "business_id": "biz-1",
            "project_id": "proj-1",
            "brand_id": "brand-1",
            "purpose": "social_publishing",
            "idempotency_key": ProviderPreflightConsentV1Tests.RAW_KEY,
            "provider_snapshot": {
                "creator_username": "creator-1",
                "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
                "comment_disabled": False,
                "duet_disabled": False,
                "stitch_disabled": True,
                "max_video_post_duration_sec": 300,
            },
            "user_choices": {
                "privacy_level": "SELF_ONLY",
                "allow_comment": True,
                "allow_duet": False,
                "allow_stitch": False,
                "consent_confirmed": True,
            },
            "approved_payload": {
                "title": "User-approved caption",
                "source": "PULL_FROM_URL",
                "video_url": "https://media.example.com/video.mp4",
                "is_aigc": True,
            },
            "ttl_seconds": 900,
        }
        values.update(overrides)
        return repo.create(**values)

    @staticmethod
    def _claim(repo: ProviderPreflightRepository, preflight_id: str, **overrides):
        values = {
            "provider": "tiktok",
            "connector_id": "conn_tiktok_live",
            "connection_id": "tiktok-main",
            "business_id": "biz-1",
            "project_id": "proj-1",
            "brand_id": "brand-1",
            "purpose": "social_publishing",
            "idempotency_key": ProviderPreflightConsentV1Tests.RAW_KEY,
        }
        values.update(overrides)
        return repo.claim(preflight_id, **values)

    def test_create_is_secret_free_hashes_key_and_defensively_copies(self) -> None:
        repo = ProviderPreflightRepository()
        source = {"title": "User-approved caption", "nested": {"privacy": "SELF_ONLY"}}
        record = self._create(repo, approved_payload=source)
        source["title"] = "tampered"
        source["nested"]["privacy"] = "PUBLIC_TO_EVERYONE"

        stored = repo.get(record.preflight_id)
        self.assertIsNotNone(stored)
        self.assertEqual(ProviderPreflightState.ACTIVE, stored.state)
        self.assertEqual("User-approved caption", stored.approved_payload["title"])
        self.assertEqual("SELF_ONLY", stored.approved_payload["nested"]["privacy"])
        self.assertNotEqual(self.RAW_KEY, stored.idempotency_key_hash)
        self.assertEqual(64, len(stored.idempotency_key_hash))
        self.assertNotIn(self.RAW_KEY, repr(stored.to_safe_dict()))
        self.assertTrue(stored.verify_integrity())

    def test_sensitive_fields_and_credential_urls_are_rejected(self) -> None:
        repo = ProviderPreflightRepository()
        with self.assertRaises(ValueError):
            self._create(repo, user_choices={"access_token": "never-store-this"})
        with self.assertRaises(ValueError):
            self._create(
                repo,
                approved_payload={"video_url": "https://user:pass@media.example.com/video.mp4"},
            )

    def test_claim_requires_exact_scope_connection_purpose_and_key(self) -> None:
        repo = ProviderPreflightRepository()
        record = self._create(repo)
        for mutation in (
            {"business_id": "biz-2"},
            {"project_id": "proj-2"},
            {"brand_id": "brand-2"},
            {"connection_id": "tiktok-other"},
            {"connector_id": "conn_tiktok_other"},
            {"provider": "meta"},
            {"purpose": "analytics_retrieval"},
            {"idempotency_key": "idem-tiktok-different-0002"},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ProviderPreflightConflictError):
                    self._claim(repo, record.preflight_id, **mutation)
        self.assertEqual(ProviderPreflightState.ACTIVE, repo.get(record.preflight_id).state)

    def test_claim_and_consume_are_one_shot(self) -> None:
        repo = ProviderPreflightRepository()
        record = self._create(repo)
        claimed = self._claim(repo, record.preflight_id)
        self.assertEqual(ProviderPreflightState.CLAIMED, claimed.state)
        self.assertIsNotNone(claimed.claimed_at)
        with self.assertRaises(ProviderPreflightConflictError):
            self._claim(repo, record.preflight_id)

        consumed = repo.consume(record.preflight_id)
        self.assertEqual(ProviderPreflightState.CONSUMED, consumed.state)
        self.assertIsNotNone(consumed.consumed_at)
        with self.assertRaises(ProviderPreflightConflictError):
            repo.consume(record.preflight_id)
        with self.assertRaises(ProviderPreflightConflictError):
            repo.revoke(record.preflight_id)

    def test_active_artifact_can_be_revoked_but_not_claimed_afterward(self) -> None:
        repo = ProviderPreflightRepository()
        record = self._create(repo)
        revoked = repo.revoke(record.preflight_id)
        self.assertEqual(ProviderPreflightState.REVOKED, revoked.state)
        with self.assertRaises(ProviderPreflightConflictError):
            self._claim(repo, record.preflight_id)

    def test_expired_artifact_is_marked_expired_and_cannot_be_claimed(self) -> None:
        repo = ProviderPreflightRepository()
        record = self._create(repo)
        future = datetime.fromisoformat(record.expires_at) + timedelta(seconds=1)
        with patch("connectors.marketing.preflight._utc_now", return_value=future):
            with self.assertRaises(ProviderPreflightConflictError) as ctx:
                self._claim(repo, record.preflight_id)
        self.assertIn("EXPIRED", str(ctx.exception))
        self.assertEqual(ProviderPreflightState.EXPIRED, repo.get(record.preflight_id).state)

    def test_sqlite_restart_preserves_one_shot_authority_and_raw_key_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "platform-evidence.sqlite3"
            repo1 = ProviderPreflightRepository(db_path)
            record = self._create(repo1)
            claimed = self._claim(repo1, record.preflight_id)
            self.assertEqual(ProviderPreflightState.CLAIMED, claimed.state)
            repo1.close()

            raw_bytes = db_path.read_bytes()
            self.assertNotIn(self.RAW_KEY.encode("utf-8"), raw_bytes)

            repo2 = ProviderPreflightRepository(db_path)
            restored = repo2.get(record.preflight_id)
            self.assertEqual(ProviderPreflightState.CLAIMED, restored.state)
            with self.assertRaises(ProviderPreflightConflictError):
                self._claim(repo2, record.preflight_id)
            consumed = repo2.consume(record.preflight_id)
            self.assertEqual(ProviderPreflightState.CONSUMED, consumed.state)
            repo2.close()

            repo3 = ProviderPreflightRepository(db_path)
            self.assertEqual(
                ProviderPreflightState.CONSUMED,
                repo3.get(record.preflight_id).state,
            )
            repo3.close()

    def test_sqlite_payload_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "preflight.sqlite3"
            repo = ProviderPreflightRepository(db_path)
            record = self._create(repo)
            repo.close()

            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute(
                    "UPDATE provider_preflights SET payload_json=? WHERE preflight_id=?",
                    ('{"tampered":true}', record.preflight_id),
                )
            conn.close()

            reopened = ProviderPreflightRepository(db_path)
            with self.assertRaises(ProviderPreflightIntegrityError):
                reopened.get(record.preflight_id)
            reopened.close()

    def test_ttl_bounds_are_fail_closed(self) -> None:
        repo = ProviderPreflightRepository()
        with self.assertRaises(ValueError):
            self._create(repo, ttl_seconds=10)
        with self.assertRaises(ValueError):
            self._create(repo, ttl_seconds=7200)
        with self.assertRaises(ValueError):
            self._create(repo, ttl_seconds=True)


if __name__ == "__main__":
    unittest.main()
