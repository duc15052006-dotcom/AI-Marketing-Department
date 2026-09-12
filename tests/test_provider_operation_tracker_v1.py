from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from connections.secrets import SecretValue
from connectors.marketing import ExternalMarketingRequest, MarketingExecutionMode, PreparedMarketingAction
from connectors.marketing.operations import (
    ProviderOperationConflictError,
    ProviderOperationIntegrityError,
    ProviderOperationRepository,
    ProviderOperationScopeError,
    ProviderOperationState,
)
from connectors.marketing.preflight import ProviderPreflightRepository
from connectors.marketing.providers.tiktok import TikTokHttpResponse
from connectors.marketing.providers.tiktok_tracking import TrackedTikTokMarketingExecutor


class _FakeTikTokTransport:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.calls = []

    def request(self, *, method, url, headers, body, timeout_seconds):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not self.results:
            raise AssertionError("Unexpected TikTok transport call")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _response(status: int, payload: dict) -> TikTokHttpResponse:
    return TikTokHttpResponse(status_code=status, body=json.dumps(payload).encode("utf-8"))


def _prepared(capability: str, *, approval_required: bool = False) -> PreparedMarketingAction:
    return PreparedMarketingAction(
        request_fingerprint="a" * 64,
        request_id="REQ-TRACK-001",
        run_id="RUN-TRACK-001",
        connector_id="tiktok_main",
        provider="tiktok",
        connection_id="conn_tiktok_main",
        capability_id=capability,
        effect="PUBLISH" if approval_required else "READ",
        risk_level="CRITICAL" if approval_required else "LOW",
        approval_required=approval_required,
        execution_mode=MarketingExecutionMode.LIVE,
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
    )


def _request(
    capability: str,
    action: str,
    resource_type: str,
    payload: dict,
    *,
    idempotency_key: str | None = None,
) -> ExternalMarketingRequest:
    return ExternalMarketingRequest(
        request_id="REQ-TRACK-001",
        run_id="RUN-TRACK-001",
        connector_id="tiktok_main",
        connection_id="conn_tiktok_main",
        capability_id=capability,
        action=action,
        resource_type=resource_type,
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
        idempotency_key=idempotency_key,
        payload=payload,
    )


def _creator_snapshot() -> dict:
    return {
        "creator_username": "creator_1",
        "creator_nickname": "Creator One",
        "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
        "comment_disabled": False,
        "duet_disabled": False,
        "stitch_disabled": False,
        "max_video_post_duration_sec": 300,
    }


def _approved_payload() -> dict:
    return {
        "post_info": {
            "title": "Tracked TikTok post",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
            "brand_content_toggle": False,
            "brand_organic_toggle": True,
            "is_aigc": True,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": "https://media.example.com/exports/video-001.mp4",
        },
    }


def _user_choices(payload: dict) -> dict:
    post = payload["post_info"]
    return {
        key: post[key]
        for key in (
            "privacy_level",
            "disable_comment",
            "disable_duet",
            "disable_stitch",
            "brand_content_toggle",
            "brand_organic_toggle",
            "is_aigc",
        )
    }


def _preflight(repo: ProviderPreflightRepository, key: str):
    approved = _approved_payload()
    return repo.create(
        provider="tiktok",
        connector_id="tiktok_main",
        connection_id="conn_tiktok_main",
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
        purpose="tiktok_direct_post_video",
        idempotency_key=key,
        approved_payload=approved,
        provider_snapshot=_creator_snapshot(),
        user_choices=_user_choices(approved),
        ttl_seconds=900,
    )


class ProviderOperationRepositoryV1Tests(unittest.TestCase):
    def _create(self, repo: ProviderOperationRepository, **overrides):
        values = {
            "provider": "tiktok",
            "connector_id": "tiktok_main",
            "connection_id": "conn_tiktok_main",
            "capability_id": "social_publishing",
            "action": "publish_video",
            "external_operation_id": "v_pub_url~v2.123456",
            "business_id": "BUS-1",
            "project_id": "PROJ-1",
            "brand_id": "BRAND-1",
            "provider_status": "SUBMITTED",
            "idempotency_key": "idem-operation-tracker-001",
            "metadata": {"status_source": "direct_post_init"},
        }
        values.update(overrides)
        return repo.create(**values)

    def test_create_hashes_idempotency_and_returns_defensive_copy(self):
        repo = ProviderOperationRepository()
        raw_key = "idem-operation-tracker-001"
        record = self._create(repo, idempotency_key=raw_key)
        self.assertEqual(record.state, ProviderOperationState.SUBMITTED)
        self.assertEqual(len(record.idempotency_key_hash or ""), 64)
        self.assertNotEqual(record.idempotency_key_hash, raw_key)
        record.metadata["mutated"] = True
        stored = repo.get(record.operation_id)
        self.assertNotIn("mutated", stored.metadata)
        self.assertTrue(stored.record_hash)

    def test_scope_mismatch_fails_closed(self):
        repo = ProviderOperationRepository()
        record = self._create(repo)
        with self.assertRaises(ProviderOperationScopeError):
            repo.find_external(
                provider="tiktok",
                connection_id=record.connection_id,
                external_operation_id=record.external_operation_id,
                business_id="BUS-OTHER",
                project_id="PROJ-1",
                brand_id="BRAND-1",
            )

    def test_terminal_state_cannot_regress(self):
        repo = ProviderOperationRepository()
        record = self._create(repo)
        done = repo.record_status(
            record.operation_id,
            state=ProviderOperationState.SUCCEEDED,
            provider_status="PUBLISH_COMPLETE",
        )
        self.assertTrue(done.state.terminal)
        with self.assertRaises(ProviderOperationConflictError):
            repo.record_status(
                record.operation_id,
                state=ProviderOperationState.PROCESSING,
                provider_status="PROCESSING_DOWNLOAD",
            )

    def test_unknown_can_reconcile_to_success(self):
        repo = ProviderOperationRepository()
        record = self._create(repo)
        unknown = repo.record_status(
            record.operation_id,
            state=ProviderOperationState.UNKNOWN,
            provider_status="PROVIDER_NEW_STATE",
        )
        self.assertEqual(unknown.state, ProviderOperationState.UNKNOWN)
        done = repo.record_status(
            record.operation_id,
            state=ProviderOperationState.SUCCEEDED,
            provider_status="PUBLISH_COMPLETE",
        )
        self.assertEqual(done.state, ProviderOperationState.SUCCEEDED)

    def test_sqlite_restart_preserves_record_and_hides_raw_idempotency_key(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "provider_ops.sqlite3"
            raw_key = "idem-operation-tracker-secret-value"
            repo = ProviderOperationRepository(db)
            record = self._create(repo, idempotency_key=raw_key)
            repo.close()

            raw_bytes = db.read_bytes()
            self.assertNotIn(raw_key.encode("utf-8"), raw_bytes)

            reopened = ProviderOperationRepository(db)
            loaded = reopened.get(record.operation_id)
            self.assertEqual(loaded.external_operation_id, record.external_operation_id)
            self.assertEqual(loaded.business_id, "BUS-1")
            reopened.close()

    def test_sqlite_index_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "provider_ops.sqlite3"
            repo = ProviderOperationRepository(db)
            record = self._create(repo)
            repo.close()

            conn = sqlite3.connect(str(db))
            conn.execute(
                "UPDATE provider_operations SET business_id = ? WHERE operation_id = ?",
                ("BUS-TAMPER", record.operation_id),
            )
            conn.commit()
            conn.close()

            reopened = ProviderOperationRepository(db)
            with self.assertRaises(ProviderOperationIntegrityError):
                reopened.get(record.operation_id)
            reopened.close()

    def test_sensitive_metadata_is_rejected(self):
        repo = ProviderOperationRepository()
        with self.assertRaises(Exception):
            self._create(repo, metadata={"access_token": "should-never-store"})


class TrackedTikTokMarketingExecutorV1Tests(unittest.TestCase):
    def test_publish_creates_durable_operation_before_returning_success(self):
        key = "idem-tracked-tiktok-001"
        preflights = ProviderPreflightRepository()
        artifact = _preflight(preflights, key)
        operations = ProviderOperationRepository()
        transport = _FakeTikTokTransport(
            _response(
                200,
                {
                    "data": {"publish_id": "v_pub_url~v2.123456789"},
                    "error": {"code": "ok", "message": ""},
                },
            )
        )
        executor = TrackedTikTokMarketingExecutor(
            transport=transport,
            preflight_repository=preflights,
            operation_repository=operations,
        )
        result = executor.execute(
            prepared=_prepared("social_publishing", approval_required=True),
            request=_request(
                "social_publishing",
                "publish_video",
                "video",
                {"preflight_reference": artifact.preflight_id},
                idempotency_key=key,
            ),
            credential=SecretValue("tiktok-secret"),
            timeout_seconds=5,
        )
        self.assertTrue(result.success)
        self.assertTrue(result.data["operation_durable"])
        self.assertEqual(result.data["operation_state"], "SUBMITTED")
        stored = operations.get(result.data["operation_id"])
        self.assertEqual(stored.external_operation_id, "v_pub_url~v2.123456789")
        self.assertEqual(stored.state, ProviderOperationState.SUBMITTED)

    def test_status_poll_updates_same_operation(self):
        key = "idem-tracked-tiktok-002"
        preflights = ProviderPreflightRepository()
        artifact = _preflight(preflights, key)
        operations = ProviderOperationRepository()
        transport = _FakeTikTokTransport(
            _response(
                200,
                {
                    "data": {"publish_id": "v_pub_url~v2.222"},
                    "error": {"code": "ok", "message": ""},
                },
            ),
            _response(
                200,
                {
                    "data": {"status": "PROCESSING_DOWNLOAD", "downloaded_bytes": 123},
                    "error": {"code": "ok", "message": ""},
                },
            ),
        )
        executor = TrackedTikTokMarketingExecutor(
            transport=transport,
            preflight_repository=preflights,
            operation_repository=operations,
        )
        publish = executor.execute(
            prepared=_prepared("social_publishing", approval_required=True),
            request=_request(
                "social_publishing",
                "publish_video",
                "video",
                {"preflight_reference": artifact.preflight_id},
                idempotency_key=key,
            ),
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        status = executor.execute(
            prepared=_prepared("analytics_retrieval"),
            request=_request(
                "analytics_retrieval",
                "fetch_publish_status",
                "post",
                {"publish_id": "v_pub_url~v2.222"},
            ),
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        self.assertTrue(status.success)
        self.assertEqual(status.data["operation_id"], publish.data["operation_id"])
        self.assertEqual(status.data["operation_state"], "PROCESSING")
        stored = operations.get(publish.data["operation_id"])
        self.assertEqual(stored.state, ProviderOperationState.PROCESSING)
        self.assertEqual(stored.poll_count, 1)

    def test_unknown_provider_status_is_not_invented_as_success(self):
        key = "idem-tracked-tiktok-003"
        preflights = ProviderPreflightRepository()
        artifact = _preflight(preflights, key)
        operations = ProviderOperationRepository()
        transport = _FakeTikTokTransport(
            _response(200, {"data": {"publish_id": "v_pub_url~v2.333"}, "error": {"code": "ok"}}),
            _response(200, {"data": {"status": "NEW_PROVIDER_STATE"}, "error": {"code": "ok"}}),
        )
        executor = TrackedTikTokMarketingExecutor(
            transport=transport,
            preflight_repository=preflights,
            operation_repository=operations,
        )
        publish = executor.execute(
            prepared=_prepared("social_publishing", approval_required=True),
            request=_request(
                "social_publishing",
                "publish_video",
                "video",
                {"preflight_reference": artifact.preflight_id},
                idempotency_key=key,
            ),
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        status = executor.execute(
            prepared=_prepared("analytics_retrieval"),
            request=_request(
                "analytics_retrieval",
                "fetch_publish_status",
                "post",
                {"publish_id": "v_pub_url~v2.333"},
            ),
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        self.assertEqual(status.data["operation_state"], "UNKNOWN")
        self.assertEqual(operations.get(publish.data["operation_id"]).state, ProviderOperationState.UNKNOWN)

    def test_cross_scope_status_poll_is_blocked_before_provider_call(self):
        operations = ProviderOperationRepository()
        operations.create(
            provider="tiktok",
            connector_id="tiktok_main",
            connection_id="conn_tiktok_main",
            capability_id="social_publishing",
            action="publish_video",
            external_operation_id="v_pub_url~v2.scope",
            business_id="BUS-OTHER",
            project_id="PROJ-1",
            brand_id="BRAND-1",
        )
        transport = _FakeTikTokTransport()
        executor = TrackedTikTokMarketingExecutor(
            transport=transport,
            operation_repository=operations,
        )
        result = executor.execute(
            prepared=_prepared("analytics_retrieval"),
            request=_request(
                "analytics_retrieval",
                "fetch_publish_status",
                "post",
                {"publish_id": "v_pub_url~v2.scope"},
            ),
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        self.assertFalse(result.success)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
