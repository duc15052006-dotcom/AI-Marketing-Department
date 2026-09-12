from __future__ import annotations

import json
import unittest

from connections.secrets import SecretValue
from connectors.marketing import ExternalMarketingRequest, MarketingExecutionMode, PreparedMarketingAction
from connectors.marketing.providers.google import (
    GoogleAdsReadExecutor,
    GoogleAnalyticsReadExecutor,
    GoogleExecutorValidationError,
    GoogleHttpResponse,
)


class _FakeGoogleTransport:
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
            raise AssertionError("Unexpected Google transport call")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _response(status: int, payload, *, headers=None) -> GoogleHttpResponse:
    return GoogleHttpResponse(
        status_code=status,
        body=json.dumps(payload).encode("utf-8"),
        headers=headers or {},
    )


def _prepared(provider: str, connector_id: str) -> PreparedMarketingAction:
    return PreparedMarketingAction(
        request_fingerprint="b" * 64,
        request_id="REQ-GOOGLE-001",
        run_id="RUN-GOOGLE-001",
        connector_id=connector_id,
        provider=provider,
        connection_id=f"conn_{connector_id}",
        capability_id="analytics_retrieval",
        effect="READ",
        risk_level="LOW",
        approval_required=False,
        execution_mode=MarketingExecutionMode.LIVE,
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
    )


def _request(provider: str, connector_id: str, *, action: str, resource_type: str, resource_id: str, payload: dict):
    return ExternalMarketingRequest(
        request_id="REQ-GOOGLE-001",
        run_id="RUN-GOOGLE-001",
        connector_id=connector_id,
        connection_id=f"conn_{connector_id}",
        capability_id="analytics_retrieval",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        business_id="BUS-1",
        project_id="PROJ-1",
        brand_id="BRAND-1",
        payload=payload,
    )


def _ads_secret(*, customer_id="1234567890", login_customer_id="9999999999") -> SecretValue:
    return SecretValue(
        json.dumps(
            {
                "access_token": "oauth-access-secret",
                "developer_token": "developer-token-secret",
                "customer_id": customer_id,
                "login_customer_id": login_customer_id,
            }
        )
    )


def _ga4_secret(*, property_id="314159265") -> SecretValue:
    return SecretValue(json.dumps({"access_token": "ga4-access-secret", "property_id": property_id}))


class GoogleMarketingReadExecutorsV1Tests(unittest.TestCase):
    def test_google_ads_campaign_report_uses_v25_fixed_endpoint_and_headers(self):
        transport = _FakeGoogleTransport(
            _response(
                200,
                {
                    "results": [
                        {
                            "campaign": {"id": "1", "name": "Search"},
                            "metrics": {"impressions": "100", "clicks": "8"},
                            "segments": {"date": "2026-08-30"},
                        }
                    ],
                    "nextPageToken": "PAGE-NEXT-1",
                },
                headers={"request-id": "REQ-ID-1"},
            )
        )
        executor = GoogleAdsReadExecutor(transport=transport)
        result = executor.execute(
            prepared=_prepared("google_ads", "google_ads_main"),
            request=_request(
                "google_ads",
                "google_ads_main",
                action="campaign_performance",
                resource_type="customer",
                resource_id="1234567890",
                payload={"start_date": "2026-08-01", "end_date": "2026-08-30", "limit": 50},
            ),
            credential=_ads_secret(),
            timeout_seconds=12,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["api_version"], "v25")
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(
            call["url"],
            "https://googleads.googleapis.com/v25/customers/1234567890/googleAds:search",
        )
        self.assertEqual(call["headers"]["Authorization"], "Bearer oauth-access-secret")
        self.assertEqual(call["headers"]["developer-token"], "developer-token-secret")
        self.assertEqual(call["headers"]["login-customer-id"], "9999999999")
        body = json.loads(call["body"])
        query = body["query"]
        self.assertIn("FROM campaign", query)
        self.assertIn("BETWEEN '2026-08-01' AND '2026-08-30'", query)
        self.assertIn("LIMIT 50", query)
        serialized = json.dumps(dict(result.data))
        self.assertNotIn("oauth-access-secret", serialized)
        self.assertNotIn("developer-token-secret", serialized)
        self.assertNotIn("oauth-access-secret", call["url"])
        self.assertNotIn("developer-token-secret", call["url"])
        self.assertNotIn("oauth-access-secret", call["body"].decode("utf-8"))
        self.assertNotIn("developer-token-secret", call["body"].decode("utf-8"))

    def test_google_ads_customer_binding_mismatch_blocks_before_network(self):
        transport = _FakeGoogleTransport()
        executor = GoogleAdsReadExecutor(transport=transport)
        result = executor.execute(
            prepared=_prepared("google_ads", "google_ads_main"),
            request=_request(
                "google_ads",
                "google_ads_main",
                action="campaign_performance",
                resource_type="customer",
                resource_id="1111111111",
                payload={"start_date": "2026-08-01", "end_date": "2026-08-02"},
            ),
            credential=_ads_secret(customer_id="1234567890"),
            timeout_seconds=5,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "GOOGLE_ADS_VALIDATION_ERROR")
        self.assertIn("CUSTOMER_BINDING_MISMATCH", result.error_message)
        self.assertEqual(transport.calls, [])

    def test_google_ads_does_not_accept_raw_gaql_or_unknown_payload_fields(self):
        transport = _FakeGoogleTransport()
        executor = GoogleAdsReadExecutor(transport=transport)
        result = executor.execute(
            prepared=_prepared("google_ads", "google_ads_main"),
            request=_request(
                "google_ads",
                "google_ads_main",
                action="campaign_performance",
                resource_type="customer",
                resource_id="1234567890",
                payload={
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-02",
                    "query": "SELECT customer.id FROM customer",
                },
            ),
            credential=_ads_secret(),
            timeout_seconds=5,
        )
        self.assertFalse(result.success)
        self.assertEqual(transport.calls, [])
        self.assertIn("query", result.error_message)

    def test_google_ads_credential_bundle_rejects_unknown_fields_before_network(self):
        transport = _FakeGoogleTransport()
        executor = GoogleAdsReadExecutor(transport=transport)
        secret = SecretValue(
            json.dumps(
                {
                    "access_token": "access",
                    "developer_token": "developer",
                    "customer_id": "1234567890",
                    "client_secret": "forbidden-extra",
                }
            )
        )
        result = executor.execute(
            prepared=_prepared("google_ads", "google_ads_main"),
            request=_request(
                "google_ads",
                "google_ads_main",
                action="campaign_performance",
                resource_type="customer",
                resource_id="1234567890",
                payload={"start_date": "2026-08-01", "end_date": "2026-08-02"},
            ),
            credential=secret,
            timeout_seconds=5,
        )
        self.assertFalse(result.success)
        self.assertEqual(transport.calls, [])
        self.assertIn("UNSUPPORTED_FIELDS", result.error_message)
        self.assertNotIn("forbidden-extra", result.error_message)

    def test_google_ads_4xx_is_definite_rejection_and_5xx_is_uncertain(self):
        request = _request(
            "google_ads",
            "google_ads_main",
            action="campaign_performance",
            resource_type="customer",
            resource_id="1234567890",
            payload={"start_date": "2026-08-01", "end_date": "2026-08-02"},
        )
        four_xx = GoogleAdsReadExecutor(
            transport=_FakeGoogleTransport(
                _response(403, {"error": {"status": "PERMISSION_DENIED", "message": "denied"}})
            )
        )
        result = four_xx.execute(
            prepared=_prepared("google_ads", "google_ads_main"),
            request=request,
            credential=_ads_secret(),
            timeout_seconds=5,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "GOOGLE_HTTP_403_PERMISSION_DENIED")

        five_xx = GoogleAdsReadExecutor(
            transport=_FakeGoogleTransport(_response(503, {"error": {"status": "UNAVAILABLE"}}))
        )
        with self.assertRaises(ConnectionError):
            five_xx.execute(
                prepared=_prepared("google_ads", "google_ads_main"),
                request=request,
                credential=_ads_secret(),
                timeout_seconds=5,
            )

    def test_ga4_run_report_uses_fixed_property_endpoint_and_allowlisted_body(self):
        transport = _FakeGoogleTransport(
            _response(
                200,
                {
                    "dimensionHeaders": [{"name": "date"}],
                    "metricHeaders": [{"name": "sessions", "type": "TYPE_INTEGER"}],
                    "rows": [
                        {
                            "dimensionValues": [{"value": "20260830"}],
                            "metricValues": [{"value": "42"}],
                        }
                    ],
                    "rowCount": 1,
                },
            )
        )
        executor = GoogleAnalyticsReadExecutor(transport=transport)
        result = executor.execute(
            prepared=_prepared("google_analytics", "ga4_main"),
            request=_request(
                "google_analytics",
                "ga4_main",
                action="run_report",
                resource_type="property",
                resource_id="314159265",
                payload={
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-30",
                    "dimensions": ["date", "sessionDefaultChannelGroup"],
                    "metrics": ["sessions", "activeUsers"],
                    "limit": 200,
                },
            ),
            credential=_ga4_secret(),
            timeout_seconds=8,
        )
        self.assertTrue(result.success)
        call = transport.calls[0]
        self.assertEqual(
            call["url"],
            "https://analyticsdata.googleapis.com/v1beta/properties/314159265:runReport",
        )
        self.assertEqual(call["headers"]["Authorization"], "Bearer ga4-access-secret")
        body = json.loads(call["body"])
        self.assertEqual(body["dateRanges"], [{"startDate": "2026-08-01", "endDate": "2026-08-30"}])
        self.assertEqual(body["dimensions"], [{"name": "date"}, {"name": "sessionDefaultChannelGroup"}])
        self.assertEqual(body["metrics"], [{"name": "sessions"}, {"name": "activeUsers"}])
        self.assertEqual(body["limit"], "200")
        self.assertNotIn("ga4-access-secret", json.dumps(dict(result.data)))
        self.assertNotIn("ga4-access-secret", call["url"])
        self.assertNotIn("ga4-access-secret", call["body"].decode("utf-8"))

    def test_ga4_property_binding_and_unknown_metric_block_before_network(self):
        transport = _FakeGoogleTransport()
        executor = GoogleAnalyticsReadExecutor(transport=transport)
        mismatch = executor.execute(
            prepared=_prepared("google_analytics", "ga4_main"),
            request=_request(
                "google_analytics",
                "ga4_main",
                action="run_report",
                resource_type="property",
                resource_id="999999999",
                payload={"start_date": "2026-08-01", "end_date": "2026-08-02"},
            ),
            credential=_ga4_secret(property_id="314159265"),
            timeout_seconds=5,
        )
        self.assertFalse(mismatch.success)
        self.assertIn("PROPERTY_BINDING_MISMATCH", mismatch.error_message)
        self.assertEqual(transport.calls, [])

        unsupported = executor.execute(
            prepared=_prepared("google_analytics", "ga4_main"),
            request=_request(
                "google_analytics",
                "ga4_main",
                action="run_report",
                resource_type="property",
                resource_id="314159265",
                payload={
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-02",
                    "metrics": ["someArbitraryMetric"],
                },
            ),
            credential=_ga4_secret(),
            timeout_seconds=5,
        )
        self.assertFalse(unsupported.success)
        self.assertIn("UNSUPPORTED_METRICS", unsupported.error_message)
        self.assertEqual(transport.calls, [])

    def test_invalid_google_ads_api_version_is_rejected_locally(self):
        with self.assertRaises(GoogleExecutorValidationError):
            GoogleAdsReadExecutor(api_version="latest")


if __name__ == "__main__":
    unittest.main()
