from __future__ import annotations

import json
import unittest

from connections.secrets import SecretValue
from connectors.marketing import (
    ExternalMarketingRequest,
    MarketingExecutionMode,
    PreparedMarketingAction,
)
from connectors.marketing.preflight import ProviderPreflightRepository, ProviderPreflightState
from connectors.marketing.providers.tiktok import (
    TikTokHttpResponse,
    TikTokMarketingExecutor,
)


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
        request_id="REQ-TIKTOK-001",
        run_id="RUN-TIKTOK-001",
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
        request_id="REQ-TIKTOK-001",
        run_id="RUN-TIKTOK-001",
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


def _creator_snapshot(*, privacy_options=None, comment_disabled=False, duet_disabled=False, stitch_disabled=False):
    return {
        "creator_username": "creator_1",
        "creator_nickname": "Creator One",
        "privacy_level_options": privacy_options or ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
        "comment_disabled": comment_disabled,
        "duet_disabled": duet_disabled,
        "stitch_disabled": stitch_disabled,
        "max_video_post_duration_sec": 300,
    }


def _approved_payload(*, privacy="PUBLIC_TO_EVERYONE", disable_comment=False, disable_duet=False, disable_stitch=False):
    return {
        "post_info": {
            "title": "Governed TikTok post #demo",
            "privacy_level": privacy,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
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


def _preflight(repo: ProviderPreflightRepository, key: str, *, snapshot=None, approved=None):
    approved = approved or _approved_payload()
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
        provider_snapshot=snapshot or _creator_snapshot(),
        user_choices=_user_choices(approved),
        ttl_seconds=900,
    )


class TikTokMarketingExecutorV1Tests(unittest.TestCase):
    def test_query_creator_info_uses_fixed_endpoint_and_bearer_header(self):
        token = "tiktok-super-secret-token"
        transport = _FakeTikTokTransport(
            _response(
                200,
                {
                    "data": _creator_snapshot(),
                    "error": {"code": "ok", "message": "", "log_id": "LOG-1"},
                },
            )
        )
        executor = TikTokMarketingExecutor(transport=transport)
        result = executor.execute(
            prepared=_prepared("analytics_retrieval"),
            request=_request("analytics_retrieval", "query_creator_info", "creator", {}),
            credential=SecretValue(token),
            timeout_seconds=9,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["operation"], "query_creator_info")
        self.assertEqual(result.data["creator_info"]["privacy_level_options"], ["PUBLIC_TO_EVERYONE", "SELF_ONLY"])
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://open.tiktokapis.com/v2/post/publish/creator_info/query/")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {token}")
        self.assertEqual(json.loads(call["body"]), {})
        self.assertNotIn(token, json.dumps(dict(result.data)))
        self.assertNotIn(token, call["url"])
        self.assertNotIn(token, call["body"].decode("utf-8"))

    def test_publish_uses_only_claimed_preflight_payload_and_consumes_artifact(self):
        key = "idem-tiktok-video-001"
        repo = ProviderPreflightRepository()
        artifact = _preflight(repo, key)
        transport = _FakeTikTokTransport(
            _response(
                200,
                {
                    "data": {"publish_id": "v_pub_url~v2.123456789"},
                    "error": {"code": "ok", "message": "", "log_id": "LOG-2"},
                },
            )
        )
        executor = TikTokMarketingExecutor(transport=transport, preflight_repository=repo)
        request = _request(
            "social_publishing",
            "publish_video",
            "video",
            {"preflight_reference": artifact.preflight_id},
            idempotency_key=key,
        )
        result = executor.execute(
            prepared=_prepared("social_publishing", approval_required=True),
            request=request,
            credential=SecretValue("tiktok-secret"),
            timeout_seconds=12,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["publish_id"], "v_pub_url~v2.123456789")
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://open.tiktokapis.com/v2/post/publish/video/init/")
        sent = json.loads(call["body"])
        self.assertEqual(sent, _approved_payload())
        self.assertNotIn("preflight_reference", sent)
        self.assertEqual(repo.get(artifact.preflight_id).state, ProviderPreflightState.CONSUMED)

    def test_privacy_not_in_latest_creator_options_is_blocked_before_network(self):
        key = "idem-tiktok-video-002"
        repo = ProviderPreflightRepository()
        approved = _approved_payload(privacy="PUBLIC_TO_EVERYONE")
        artifact = _preflight(
            repo,
            key,
            snapshot=_creator_snapshot(privacy_options=["SELF_ONLY"]),
            approved=approved,
        )
        transport = _FakeTikTokTransport()
        executor = TikTokMarketingExecutor(transport=transport, preflight_repository=repo)
        result = executor.execute(
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
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TIKTOK_VALIDATION_ERROR")
        self.assertEqual(transport.calls, [])
        self.assertEqual(repo.get(artifact.preflight_id).state, ProviderPreflightState.CONSUMED)

    def test_provider_disabled_interaction_cannot_be_reenabled_by_preflight(self):
        key = "idem-tiktok-video-003"
        repo = ProviderPreflightRepository()
        approved = _approved_payload(disable_comment=False)
        artifact = _preflight(
            repo,
            key,
            snapshot=_creator_snapshot(comment_disabled=True),
            approved=approved,
        )
        transport = _FakeTikTokTransport()
        executor = TikTokMarketingExecutor(transport=transport, preflight_repository=repo)
        result = executor.execute(
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
        self.assertFalse(result.success)
        self.assertEqual(transport.calls, [])

    def test_consumed_preflight_cannot_be_replayed(self):
        key = "idem-tiktok-video-004"
        repo = ProviderPreflightRepository()
        artifact = _preflight(repo, key)
        transport = _FakeTikTokTransport(
            _response(200, {"data": {"publish_id": "v_pub_url~v2.1"}, "error": {"code": "ok"}})
        )
        executor = TikTokMarketingExecutor(transport=transport, preflight_repository=repo)
        request = _request(
            "social_publishing",
            "publish_video",
            "video",
            {"preflight_reference": artifact.preflight_id},
            idempotency_key=key,
        )
        first = executor.execute(
            prepared=_prepared("social_publishing", approval_required=True),
            request=request,
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        second = executor.execute(
            prepared=_prepared("social_publishing", approval_required=True),
            request=request,
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertEqual(len(transport.calls), 1)
        self.assertIn("NOT_ACTIVE", second.error_message)

    def test_transport_uncertainty_leaves_preflight_claimed(self):
        key = "idem-tiktok-video-005"
        repo = ProviderPreflightRepository()
        artifact = _preflight(repo, key)
        transport = _FakeTikTokTransport(ConnectionError("network uncertain"))
        executor = TikTokMarketingExecutor(transport=transport, preflight_repository=repo)
        with self.assertRaises(ConnectionError):
            executor.execute(
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
        self.assertEqual(repo.get(artifact.preflight_id).state, ProviderPreflightState.CLAIMED)

    def test_definite_4xx_rejection_consumes_preflight(self):
        key = "idem-tiktok-video-006"
        repo = ProviderPreflightRepository()
        artifact = _preflight(repo, key)
        transport = _FakeTikTokTransport(
            _response(
                403,
                {
                    "data": {},
                    "error": {
                        "code": "privacy_level_option_mismatch",
                        "message": "privacy mismatch",
                        "log_id": "LOG-403",
                    },
                },
            )
        )
        executor = TikTokMarketingExecutor(transport=transport, preflight_repository=repo)
        result = executor.execute(
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
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TIKTOK_ERROR_PRIVACY_LEVEL_OPTION_MISMATCH")
        self.assertEqual(repo.get(artifact.preflight_id).state, ProviderPreflightState.CONSUMED)

    def test_fetch_publish_status_is_read_only_and_allowlisted(self):
        transport = _FakeTikTokTransport(
            _response(
                200,
                {
                    "data": {"status": "PROCESSING_DOWNLOAD", "downloaded_bytes": 1234},
                    "error": {"code": "ok", "message": ""},
                },
            )
        )
        executor = TikTokMarketingExecutor(transport=transport)
        result = executor.execute(
            prepared=_prepared("analytics_retrieval"),
            request=_request(
                "analytics_retrieval",
                "fetch_publish_status",
                "post",
                {"publish_id": "v_pub_url~v2.123"},
            ),
            credential=SecretValue("token"),
            timeout_seconds=5,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["status"]["status"], "PROCESSING_DOWNLOAD")
        self.assertEqual(
            json.loads(transport.calls[0]["body"]),
            {"publish_id": "v_pub_url~v2.123"},
        )

    def test_query_parameters_on_pull_url_are_rejected_before_network(self):
        key = "idem-tiktok-video-007"
        repo = ProviderPreflightRepository()
        approved = _approved_payload()
        approved["source_info"]["video_url"] = "https://media.example.com/video.mp4?token=secret"
        artifact = _preflight(repo, key, approved=approved)
        transport = _FakeTikTokTransport()
        executor = TikTokMarketingExecutor(transport=transport, preflight_repository=repo)
        result = executor.execute(
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
        self.assertFalse(result.success)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
