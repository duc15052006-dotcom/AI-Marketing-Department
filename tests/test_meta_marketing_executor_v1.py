from __future__ import annotations

import json
import urllib.parse
import unittest

from connections.secrets import SecretValue
from connectors.marketing import (
    ExternalMarketingRequest,
    MarketingExecutionMode,
    PreparedMarketingAction,
)
from connectors.marketing.providers.meta import (
    MetaHttpResponse,
    MetaMarketingExecutor,
    MetaTransportError,
)


class RecordingTransport:
    def __init__(self, responses=None, error=None) -> None:
        self.responses = list(responses or [])
        self.error = error
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
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("No fake Meta response configured.")
        return self.responses.pop(0)


class MetaMarketingExecutorV1Tests(unittest.TestCase):
    SECRET = "META-TEST-TOKEN-DO-NOT-LEAK"

    @staticmethod
    def _prepared(request: ExternalMarketingRequest) -> PreparedMarketingAction:
        return PreparedMarketingAction(
            request_fingerprint=request.fingerprint(),
            request_id=request.request_id,
            run_id=request.run_id,
            connector_id=request.connector_id,
            provider="meta",
            connection_id=request.connection_id,
            capability_id=request.capability_id,
            effect=request.policy.effect.value,
            risk_level=request.policy.risk_level.value,
            approval_required=request.policy.approval_required,
            execution_mode=MarketingExecutionMode.LIVE,
            business_id=request.business_id,
            project_id=request.project_id,
            brand_id=request.brand_id,
        )

    @classmethod
    def _publish_request(cls, *, payload=None, resource_id="123456789") -> ExternalMarketingRequest:
        return ExternalMarketingRequest(
            request_id="REQ-META-PUBLISH-001",
            run_id="RUN-META-PUBLISH-001",
            connector_id="conn_meta_live",
            connection_id="meta-live-main",
            capability_id="social_publishing",
            action="publish_post",
            resource_type="page",
            resource_id=resource_id,
            business_id="biz-meta",
            project_id="proj-meta",
            brand_id="brand-meta",
            idempotency_key="idem-meta-publish-0001",
            payload=payload or {"message": "Governed Meta post", "link": "https://example.com/item"},
        )

    @classmethod
    def _insights_request(cls, *, resource_type="ad_account", resource_id="987654321", payload=None):
        return ExternalMarketingRequest(
            request_id="REQ-META-READ-001",
            run_id="RUN-META-READ-001",
            connector_id="conn_meta_live",
            connection_id="meta-live-main",
            capability_id="analytics_retrieval",
            action="read_metrics",
            resource_type=resource_type,
            resource_id=resource_id,
            business_id="biz-meta",
            project_id="proj-meta",
            brand_id="brand-meta",
            payload=payload or {"fields": ["impressions", "clicks", "spend"], "date_preset": "last_7d", "limit": 25},
        )

    def test_page_publish_uses_fixed_v26_graph_endpoint_and_bearer_header(self) -> None:
        transport = RecordingTransport(
            [MetaHttpResponse(status_code=200, body=b'{"id":"123456789_777"}')]
        )
        executor = MetaMarketingExecutor(transport=transport)
        request = self._publish_request()
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=12.5,
        )

        self.assertTrue(result.success)
        self.assertEqual("123456789_777", result.data["post_id"])
        self.assertEqual("v26.0", result.data["api_version"])
        self.assertEqual(1, len(transport.calls))
        call = transport.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertEqual("https://graph.facebook.com/v26.0/123456789/feed", call["url"])
        self.assertEqual(f"Bearer {self.SECRET}", call["headers"]["Authorization"])
        form = urllib.parse.parse_qs(call["body"].decode("utf-8"))
        self.assertEqual(["Governed Meta post"], form["message"])
        self.assertEqual(["https://example.com/item"], form["link"])
        self.assertNotIn(self.SECRET, call["url"])
        self.assertNotIn(self.SECRET, call["body"].decode("utf-8"))
        self.assertNotIn(self.SECRET, repr(result))

    def test_api_version_is_injectable_but_validated(self) -> None:
        executor = MetaMarketingExecutor(transport=RecordingTransport(), api_version="v25.0")
        self.assertEqual("https://graph.facebook.com/v25.0", executor.base_url)
        with self.assertRaises(ValueError):
            MetaMarketingExecutor(transport=RecordingTransport(), api_version="latest")
        with self.assertRaises(ValueError):
            MetaMarketingExecutor(transport=RecordingTransport(), api_version="v26.0/../../me")

    def test_page_publish_rejects_unallowlisted_payload_without_network_call(self) -> None:
        transport = RecordingTransport()
        executor = MetaMarketingExecutor(transport=transport)
        request = self._publish_request(payload={"message": "safe", "published": False})
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=10,
        )
        self.assertFalse(result.success)
        self.assertEqual("META_REQUEST_REJECTED", result.error_code)
        self.assertEqual([], transport.calls)

    def test_page_publish_rejects_embedded_credentials_in_link(self) -> None:
        transport = RecordingTransport()
        executor = MetaMarketingExecutor(transport=transport)
        request = self._publish_request(payload={"link": "https://user:pass@example.com/private"})
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=10,
        )
        self.assertFalse(result.success)
        self.assertEqual("META_REQUEST_REJECTED", result.error_code)
        self.assertEqual([], transport.calls)

    def test_ads_insights_builds_allowlisted_account_endpoint_and_query(self) -> None:
        response_payload = {"data": [{"impressions": "123", "clicks": "7", "spend": "12.50"}], "paging": {}}
        transport = RecordingTransport(
            [MetaHttpResponse(status_code=200, body=json.dumps(response_payload).encode("utf-8"))]
        )
        executor = MetaMarketingExecutor(transport=transport)
        request = self._insights_request()
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=8,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.data["external_side_effect"])
        call = transport.calls[0]
        self.assertEqual("GET", call["method"])
        parsed = urllib.parse.urlsplit(call["url"])
        self.assertEqual("graph.facebook.com", parsed.hostname)
        self.assertEqual("/v26.0/act_987654321/insights", parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(["impressions,clicks,spend"], query["fields"])
        self.assertEqual(["last_7d"], query["date_preset"])
        self.assertEqual(["25"], query["limit"])
        self.assertEqual(f"Bearer {self.SECRET}", call["headers"]["Authorization"])
        self.assertNotIn(self.SECRET, call["url"])

    def test_ads_insights_accepts_explicit_time_range_only(self) -> None:
        transport = RecordingTransport(
            [MetaHttpResponse(status_code=200, body=b'{"data":[]}')]
        )
        executor = MetaMarketingExecutor(transport=transport)
        request = self._insights_request(
            resource_type="campaign",
            resource_id="55555",
            payload={
                "fields": "campaign_id,impressions,spend",
                "time_range": {"since": "2026-08-01", "until": "2026-08-31"},
            },
        )
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=8,
        )
        self.assertTrue(result.success)
        parsed = urllib.parse.urlsplit(transport.calls[0]["url"])
        self.assertEqual("/v26.0/55555/insights", parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(["campaign_id,impressions,spend"], query["fields"])
        self.assertEqual(
            [{"since": "2026-08-01", "until": "2026-08-31"}],
            [json.loads(query["time_range"][0])],
        )

    def test_ads_insights_rejects_unknown_field_without_network_call(self) -> None:
        transport = RecordingTransport()
        executor = MetaMarketingExecutor(transport=transport)
        request = self._insights_request(payload={"fields": ["impressions", "raw_private_metric"]})
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=8,
        )
        self.assertFalse(result.success)
        self.assertEqual("META_REQUEST_REJECTED", result.error_code)
        self.assertEqual([], transport.calls)

    def test_4xx_is_a_definite_provider_rejection(self) -> None:
        body = json.dumps(
            {"error": {"message": "Unsupported post request", "type": "GraphMethodException", "code": 100, "error_subcode": 33}}
        ).encode("utf-8")
        transport = RecordingTransport([MetaHttpResponse(status_code=400, body=body)])
        executor = MetaMarketingExecutor(transport=transport)
        request = self._publish_request()
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=8,
        )
        self.assertFalse(result.success)
        self.assertEqual("META_ERROR_100_33", result.error_code)
        self.assertNotIn(self.SECRET, repr(result))

    def test_5xx_write_is_uncertain_and_raises_for_gateway_ambiguity(self) -> None:
        transport = RecordingTransport(
            [MetaHttpResponse(status_code=503, body=b'{"error":{"message":"temporary"}}')]
        )
        executor = MetaMarketingExecutor(transport=transport)
        request = self._publish_request()
        with self.assertRaises(MetaTransportError):
            executor.execute(
                prepared=self._prepared(request),
                request=request,
                credential=SecretValue(self.SECRET),
                timeout_seconds=8,
            )

    def test_2xx_publish_without_id_is_uncertain(self) -> None:
        transport = RecordingTransport([MetaHttpResponse(status_code=200, body=b'{"success":true}')])
        executor = MetaMarketingExecutor(transport=transport)
        request = self._publish_request()
        with self.assertRaises(MetaTransportError):
            executor.execute(
                prepared=self._prepared(request),
                request=request,
                credential=SecretValue(self.SECRET),
                timeout_seconds=8,
            )

    def test_transport_exception_propagates_as_uncertain(self) -> None:
        transport = RecordingTransport(error=ConnectionError("network disappeared"))
        executor = MetaMarketingExecutor(transport=transport)
        request = self._publish_request()
        with self.assertRaises(ConnectionError):
            executor.execute(
                prepared=self._prepared(request),
                request=request,
                credential=SecretValue(self.SECRET),
                timeout_seconds=8,
            )

    def test_unsupported_operation_never_calls_network(self) -> None:
        transport = RecordingTransport()
        executor = MetaMarketingExecutor(transport=transport)
        request = ExternalMarketingRequest(
            request_id="REQ-META-UNSUPPORTED-001",
            run_id="RUN-META-UNSUPPORTED-001",
            connector_id="conn_meta_live",
            connection_id="meta-live-main",
            capability_id="platform_operations",
            action="change_budget",
            resource_type="campaign",
            resource_id="123",
            business_id="biz-meta",
            project_id="proj-meta",
            idempotency_key="idem-meta-budget-0001",
            payload={"daily_budget": 9999},
        )
        result = executor.execute(
            prepared=self._prepared(request),
            request=request,
            credential=SecretValue(self.SECRET),
            timeout_seconds=8,
        )
        self.assertFalse(result.success)
        self.assertEqual("META_OPERATION_NOT_SUPPORTED", result.error_code)
        self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
