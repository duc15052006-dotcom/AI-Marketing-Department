from __future__ import annotations

import json
import unittest

from connections.secrets import SecretValue
from connectors.marketing import ExternalMarketingRequest, MarketingExecutionMode, PreparedMarketingAction
from connectors.marketing.operations import (
    ProviderOperationRepository,
    ProviderOperationState,
    ProviderOperationStoreError,
)
from connectors.marketing.preflight import ProviderPreflightRepository
from connectors.marketing.providers.tiktok import TikTokHttpResponse, TikTokTransportError
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


class _FailingCreateOperationRepository(ProviderOperationRepository):
    def create(self, **kwargs):
        raise ProviderOperationStoreError("forced provider-operation persistence failure")


def _response(status: int, payload: dict) -> TikTokHttpResponse:
    return TikTokHttpResponse(status_code=status, body=json.dumps(payload).encode("utf-8"))


def _create_operation(repo: ProviderOperationRepository, *, suffix: str):
    return repo.create(
        provider="tiktok",
        connector_id="tiktok_main",
        connection_id="conn_tiktok_main",
        capability_id="social_publishing",
        action="publish_video",
        external_operation_id=f"v_pub_url~v2.{suffix}",
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
        provider_status="SUBMITTED",
        idempotency_key=f"idem-operation-{suffix}",
    )


def _prepared() -> PreparedMarketingAction:
    return PreparedMarketingAction(
        request_fingerprint="a" * 64,
        request_id="REQ-TRACK-FAIL-001",
        run_id="RUN-TRACK-FAIL-001",
        connector_id="tiktok_main",
        provider="tiktok",
        connection_id="conn_tiktok_main",
        capability_id="social_publishing",
        effect="PUBLISH",
        risk_level="CRITICAL",
        approval_required=True,
        execution_mode=MarketingExecutionMode.LIVE,
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
    )


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


def _preflight(repo: ProviderPreflightRepository, key: str):
    approved = _approved_payload()
    post = approved["post_info"]
    user_choices = {
        name: post[name]
        for name in (
            "privacy_level",
            "disable_comment",
            "disable_duet",
            "disable_stitch",
            "brand_content_toggle",
            "brand_organic_toggle",
            "is_aigc",
        )
    }
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
        user_choices=user_choices,
        ttl_seconds=900,
    )


def _publish_request(preflight_id: str, key: str) -> ExternalMarketingRequest:
    return ExternalMarketingRequest(
        request_id="REQ-TRACK-FAIL-001",
        run_id="RUN-TRACK-FAIL-001",
        connector_id="tiktok_main",
        connection_id="conn_tiktok_main",
        capability_id="social_publishing",
        action="publish_video",
        resource_type="video",
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
        idempotency_key=key,
        payload={"preflight_reference": preflight_id},
    )


class ProviderOperationTrackerAdversarialV1Tests(unittest.TestCase):
    def test_processing_can_finalize_as_succeeded(self) -> None:
        repo = ProviderOperationRepository()
        record = _create_operation(repo, suffix="success")
        processing = repo.record_status(
            record.operation_id,
            state=ProviderOperationState.PROCESSING,
            provider_status="PROCESSING_DOWNLOAD",
        )
        self.assertEqual(processing.state, ProviderOperationState.PROCESSING)

        done = repo.record_status(
            record.operation_id,
            state=ProviderOperationState.SUCCEEDED,
            provider_status="PUBLISH_COMPLETE",
        )
        self.assertEqual(done.state, ProviderOperationState.SUCCEEDED)
        self.assertTrue(done.state.terminal)

    def test_processing_can_finalize_as_failed(self) -> None:
        repo = ProviderOperationRepository()
        record = _create_operation(repo, suffix="failure")
        processing = repo.record_status(
            record.operation_id,
            state=ProviderOperationState.PROCESSING,
            provider_status="PROCESSING_UPLOAD",
        )
        self.assertEqual(processing.state, ProviderOperationState.PROCESSING)

        failed = repo.record_status(
            record.operation_id,
            state=ProviderOperationState.FAILED,
            provider_status="FAILED",
        )
        self.assertEqual(failed.state, ProviderOperationState.FAILED)
        self.assertTrue(failed.state.terminal)

    def test_tracking_store_failure_after_publish_is_uncertain_and_preflight_blocks_replay(self) -> None:
        key = "idem-tracked-tiktok-store-failure-001"
        preflights = ProviderPreflightRepository()
        artifact = _preflight(preflights, key)
        transport = _FakeTikTokTransport(
            _response(
                200,
                {
                    "data": {"publish_id": "v_pub_url~v2.storefail"},
                    "error": {"code": "ok", "message": ""},
                },
            )
        )
        executor = TrackedTikTokMarketingExecutor(
            transport=transport,
            preflight_repository=preflights,
            operation_repository=_FailingCreateOperationRepository(),
        )
        request = _publish_request(artifact.preflight_id, key)

        with self.assertRaises(TikTokTransportError) as raised:
            executor.execute(
                prepared=_prepared(),
                request=request,
                credential=SecretValue("tiktok-secret"),
                timeout_seconds=5,
            )
        self.assertIn("TIKTOK_OPERATION_TRACKING_FAILED", str(raised.exception))
        self.assertEqual(len(transport.calls), 1)

        replay = executor.execute(
            prepared=_prepared(),
            request=request,
            credential=SecretValue("tiktok-secret"),
            timeout_seconds=5,
        )
        self.assertFalse(replay.success)
        self.assertEqual(replay.error_code, "TIKTOK_VALIDATION_ERROR")
        self.assertEqual(len(transport.calls), 1, "consumed preflight must block provider replay")


if __name__ == "__main__":
    unittest.main()
