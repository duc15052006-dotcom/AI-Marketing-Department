"""Governed Google Ads and GA4 read-only marketing executors.

This provider module deliberately exposes reporting only. It does not accept raw
GAQL, arbitrary Google API paths, campaign mutations, budget changes, or write
operations. Credentials remain a single opaque SecretValue at the platform
boundary and are decoded here as a provider-specific JSON bundle.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence

from connections.secrets import SecretValue
from connectors.marketing import ExternalMarketingRequest, PreparedMarketingAction
from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from tools.dynamic_gateway.marketing_live import MarketingLiveExecutorResult


_GOOGLE_ADS_HOST = "googleads.googleapis.com"
_GA4_HOST = "analyticsdata.googleapis.com"
_GOOGLE_ADS_VERSION_RE = re.compile(r"^v[0-9]{1,3}$")
_NUMERIC_ID_RE = re.compile(r"^[0-9]{1,20}$")

_GA4_DIMENSIONS = frozenset(
    {
        "date",
        "sessionDefaultChannelGroup",
        "sourceMedium",
        "campaignName",
        "deviceCategory",
        "country",
        "pagePath",
        "eventName",
    }
)
_GA4_METRICS = frozenset(
    {
        "activeUsers",
        "newUsers",
        "sessions",
        "engagedSessions",
        "eventCount",
        "screenPageViews",
        "totalRevenue",
    }
)


class GoogleExecutorError(RuntimeError):
    """Base Google marketing executor error."""


class GoogleExecutorValidationError(GoogleExecutorError):
    """Definite local rejection before provider transport begins."""


class GoogleTransportError(GoogleExecutorError):
    """Provider transport or malformed-response failure."""


@dataclass(frozen=True)
class GoogleHttpResponse:
    status_code: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)


class GoogleHttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout_seconds: float,
    ) -> GoogleHttpResponse:
        ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UrllibGoogleHttpTransport:
    """Small stdlib transport that never follows redirects with credentials."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout_seconds: float,
    ) -> GoogleHttpResponse:
        request = urllib.request.Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method.upper(),
        )
        try:
            with self._opener.open(request, timeout=float(timeout_seconds)) as response:
                return GoogleHttpResponse(
                    status_code=int(response.status),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read()
            except Exception:
                payload = b""
            return GoogleHttpResponse(
                status_code=int(exc.code),
                body=payload,
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ConnectionError(
                "GOOGLE_TRANSPORT_UNCERTAIN: " + sanitize_sensitive_text(str(reason))
            ) from exc


def _decode_json(response: GoogleHttpResponse) -> Any:
    if not response.body:
        raise GoogleTransportError("GOOGLE_EMPTY_RESPONSE: provider returned no JSON body.")
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleTransportError(
            "GOOGLE_INVALID_JSON_RESPONSE: provider response was not valid UTF-8 JSON."
        ) from exc


def _scrub_text(text: Any, secrets: Sequence[str]) -> str:
    value = str(text or "")
    for secret in secrets:
        if secret:
            value = value.replace(secret, "***")
    return sanitize_sensitive_text(value)


def _scrub_payload(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, dict):
        value = {key: _scrub_payload(child, secrets) for key, child in value.items()}
    elif isinstance(value, list):
        value = [_scrub_payload(child, secrets) for child in value]
    elif isinstance(value, tuple):
        value = tuple(_scrub_payload(child, secrets) for child in value)
    elif isinstance(value, str):
        value = _scrub_text(value, secrets)
    return sanitize_sensitive_payload(value)


def _credential_bundle(credential: Optional[SecretValue], allowed_keys: frozenset[str]) -> Dict[str, str]:
    if credential is None:
        raise GoogleExecutorValidationError("GOOGLE_CREDENTIAL_BUNDLE_REQUIRED")
    raw = credential.reveal()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GoogleExecutorValidationError(
            "GOOGLE_CREDENTIAL_BUNDLE_INVALID: expected an opaque JSON object in SecretStore."
        ) from exc
    if not isinstance(decoded, dict):
        raise GoogleExecutorValidationError("GOOGLE_CREDENTIAL_BUNDLE_INVALID")
    unknown = sorted(set(decoded) - allowed_keys)
    if unknown:
        raise GoogleExecutorValidationError(
            "GOOGLE_CREDENTIAL_BUNDLE_UNSUPPORTED_FIELDS: " + ", ".join(unknown)
        )
    bundle: Dict[str, str] = {}
    for key, value in decoded.items():
        if not isinstance(value, str) or not value.strip():
            raise GoogleExecutorValidationError(
                f"GOOGLE_CREDENTIAL_BUNDLE_INVALID_FIELD: {key}"
            )
        bundle[key] = value.strip()
    return bundle


def _canonical_numeric_id(name: str, value: Any) -> str:
    raw = str(value or "").strip()
    if not _NUMERIC_ID_RE.fullmatch(raw):
        raise GoogleExecutorValidationError(f"{name} must be a canonical numeric identifier without hyphens.")
    return raw


def _date_range(payload: Mapping[str, Any]) -> tuple[str, str]:
    start_raw = str(payload.get("start_date") or "").strip()
    end_raw = str(payload.get("end_date") or "").strip()
    try:
        start = date.fromisoformat(start_raw)
        end = date.fromisoformat(end_raw)
    except ValueError as exc:
        raise GoogleExecutorValidationError("Google report dates must use YYYY-MM-DD.") from exc
    if end < start:
        raise GoogleExecutorValidationError("Google report end_date must not precede start_date.")
    if (end - start).days > 366:
        raise GoogleExecutorValidationError("Google report date range must not exceed 367 days.")
    return start.isoformat(), end.isoformat()


def _limit(payload: Mapping[str, Any], *, default: int = 100, maximum: int = 1000) -> int:
    value = payload.get("limit", default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        raise GoogleExecutorValidationError(f"limit must be an integer between 1 and {maximum}.")
    return value


class _GoogleExecutorBase:
    def __init__(self, *, transport: Optional[GoogleHttpTransport] = None) -> None:
        self.transport = transport or UrllibGoogleHttpTransport()

    @staticmethod
    def _definite_failure(code: str, message: str, *, data: Optional[Mapping[str, Any]] = None) -> MarketingLiveExecutorResult:
        return MarketingLiveExecutorResult(
            success=False,
            error_code=sanitize_sensitive_text(code),
            error_message=sanitize_sensitive_text(message),
            data=sanitize_sensitive_payload(dict(data or {})),
        )

    @staticmethod
    def _provider_error(response: GoogleHttpResponse, payload: Any, secrets: Sequence[str]) -> MarketingLiveExecutorResult:
        message = f"Google rejected the request with HTTP {response.status_code}."
        status = "UNKNOWN"
        if isinstance(payload, Mapping):
            err = payload.get("error")
            if isinstance(err, Mapping):
                message = _scrub_text(err.get("message") or message, secrets)
                status = re.sub(r"[^A-Za-z0-9_]+", "_", str(err.get("status") or "UNKNOWN")).upper()
        request_id = ""
        for key, value in response.headers.items():
            if str(key).lower() in {"request-id", "google-ads-request-id"}:
                request_id = sanitize_sensitive_text(str(value))
                break
        return MarketingLiveExecutorResult(
            success=False,
            error_code=f"GOOGLE_HTTP_{response.status_code}_{status}",
            error_message=message,
            data={"http_status": response.status_code, "request_id": request_id or None},
        )

    def _post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout_seconds: float,
    ) -> GoogleHttpResponse:
        return self.transport.request(
            method="POST",
            url=url,
            headers=headers,
            body=json.dumps(dict(body), ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            timeout_seconds=float(timeout_seconds),
        )


class GoogleAdsReadExecutor(_GoogleExecutorBase):
    """Read-only Google Ads reporting executor using a fixed GAQL builder."""

    executor_name = "google-ads-read-executor-v1"
    provider = "google_ads"

    def __init__(self, *, transport: Optional[GoogleHttpTransport] = None, api_version: str = "v25") -> None:
        super().__init__(transport=transport)
        version = str(api_version or "").strip().lower()
        if not _GOOGLE_ADS_VERSION_RE.fullmatch(version):
            raise GoogleExecutorValidationError("Google Ads api_version must look like v25.")
        self.api_version = version

    @staticmethod
    def _bundle(credential: Optional[SecretValue]) -> Dict[str, str]:
        bundle = _credential_bundle(
            credential,
            frozenset({"access_token", "developer_token", "customer_id", "login_customer_id"}),
        )
        for required in ("access_token", "developer_token", "customer_id"):
            if required not in bundle:
                raise GoogleExecutorValidationError(f"GOOGLE_ADS_CREDENTIAL_MISSING: {required}")
        bundle["customer_id"] = _canonical_numeric_id("customer_id", bundle["customer_id"])
        if "login_customer_id" in bundle:
            bundle["login_customer_id"] = _canonical_numeric_id(
                "login_customer_id", bundle["login_customer_id"]
            )
        return bundle

    @staticmethod
    def _campaign_query(payload: Mapping[str, Any]) -> str:
        allowed = {"start_date", "end_date", "limit"}
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise GoogleExecutorValidationError(
                "Unsupported Google Ads report fields: " + ", ".join(unexpected)
            )
        start, end = _date_range(payload)
        limit = _limit(payload)
        return (
            "SELECT segments.date, campaign.id, campaign.name, campaign.status, "
            "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, "
            "metrics.conversions_value "
            "FROM campaign "
            f"WHERE segments.date BETWEEN '{start}' AND '{end}' "
            "ORDER BY segments.date DESC, campaign.id "
            f"LIMIT {limit}"
        )

    def execute(
        self,
        *,
        prepared: PreparedMarketingAction,
        request: ExternalMarketingRequest,
        credential: Optional[SecretValue],
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        if prepared.provider != self.provider or request.connector_id != prepared.connector_id:
            return self._definite_failure(
                "GOOGLE_ADS_PROVIDER_BINDING_MISMATCH",
                "Google Ads executor received a request prepared for a different provider or connector.",
            )
        try:
            if request.capability_id != "analytics_retrieval" or request.action != "campaign_performance":
                return self._definite_failure(
                    "GOOGLE_ADS_UNSUPPORTED_ACTION",
                    "Google Ads executor v1 only supports analytics_retrieval/campaign_performance.",
                )
            if request.resource_type != "customer":
                raise GoogleExecutorValidationError("Google Ads report requires resource_type='customer'.")
            bundle = self._bundle(credential)
            customer_id = _canonical_numeric_id("resource_id", request.resource_id)
            if customer_id != bundle["customer_id"]:
                raise GoogleExecutorValidationError("GOOGLE_ADS_CUSTOMER_BINDING_MISMATCH")
            query = self._campaign_query(dict(request.payload))
        except GoogleExecutorValidationError as exc:
            return self._definite_failure("GOOGLE_ADS_VALIDATION_ERROR", str(exc))

        access_token = bundle["access_token"]
        developer_token = bundle["developer_token"]
        secrets = (access_token, developer_token)
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "developer-token": developer_token,
            "User-Agent": "AI-Marketing-Department/GoogleAdsReadExecutorV1",
        }
        if bundle.get("login_customer_id"):
            headers["login-customer-id"] = bundle["login_customer_id"]
        url = f"https://{_GOOGLE_ADS_HOST}/{self.api_version}/customers/{customer_id}/googleAds:search"
        response = self._post_json(
            url=url,
            headers=headers,
            body={"query": query},
            timeout_seconds=timeout_seconds,
        )
        try:
            payload = _decode_json(response)
        except GoogleTransportError:
            if 400 <= response.status_code < 500:
                payload = None
            else:
                raise
        if 400 <= response.status_code < 500:
            return self._provider_error(response, payload, secrets)
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise ConnectionError(f"GOOGLE_ADS_UPSTREAM_HTTP_{response.status_code}")
        if not isinstance(payload, Mapping):
            raise GoogleTransportError("GOOGLE_ADS_RESPONSE_INVALID")
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise GoogleTransportError("GOOGLE_ADS_RESULTS_INVALID")
        safe_results = _scrub_payload(results, secrets)
        next_page = sanitize_sensitive_text(str(payload.get("nextPageToken") or ""))
        return MarketingLiveExecutorResult(
            success=True,
            data={
                "provider": self.provider,
                "operation": "campaign_performance",
                "customer_id": customer_id,
                "api_version": self.api_version,
                "results": safe_results,
                "next_page_token": next_page or None,
                "provider_network_called": True,
                "read_only": True,
            },
        )


class GoogleAnalyticsReadExecutor(_GoogleExecutorBase):
    """Read-only GA4 Data API executor using runReport with allowlisted fields."""

    executor_name = "google-analytics-read-executor-v1"
    provider = "google_analytics"

    @staticmethod
    def _bundle(credential: Optional[SecretValue]) -> Dict[str, str]:
        bundle = _credential_bundle(
            credential,
            frozenset({"access_token", "property_id"}),
        )
        for required in ("access_token", "property_id"):
            if required not in bundle:
                raise GoogleExecutorValidationError(f"GA4_CREDENTIAL_MISSING: {required}")
        bundle["property_id"] = _canonical_numeric_id("property_id", bundle["property_id"])
        return bundle

    @staticmethod
    def _names(payload: Mapping[str, Any], key: str, allowed: frozenset[str], default: Sequence[str]) -> list[str]:
        raw = payload.get(key, list(default))
        if not isinstance(raw, (list, tuple)) or not raw:
            raise GoogleExecutorValidationError(f"GA4 {key} must be a non-empty list.")
        names: list[str] = []
        for item in raw:
            name = str(item or "").strip()
            if name not in allowed:
                raise GoogleExecutorValidationError(f"GA4_UNSUPPORTED_{key.upper()}: {name}")
            if name not in names:
                names.append(name)
        if len(names) > 8:
            raise GoogleExecutorValidationError(f"GA4 {key} may contain at most 8 entries.")
        return names

    @classmethod
    def _report_body(cls, payload: Mapping[str, Any]) -> Dict[str, Any]:
        allowed = {"start_date", "end_date", "dimensions", "metrics", "limit"}
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise GoogleExecutorValidationError(
                "Unsupported GA4 report fields: " + ", ".join(unexpected)
            )
        start, end = _date_range(payload)
        dimensions = cls._names(payload, "dimensions", _GA4_DIMENSIONS, ("date",))
        metrics = cls._names(payload, "metrics", _GA4_METRICS, ("sessions", "activeUsers"))
        limit = _limit(payload)
        return {
            "dateRanges": [{"startDate": start, "endDate": end}],
            "dimensions": [{"name": name} for name in dimensions],
            "metrics": [{"name": name} for name in metrics],
            "limit": str(limit),
        }

    def execute(
        self,
        *,
        prepared: PreparedMarketingAction,
        request: ExternalMarketingRequest,
        credential: Optional[SecretValue],
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        if prepared.provider != self.provider or request.connector_id != prepared.connector_id:
            return self._definite_failure(
                "GA4_PROVIDER_BINDING_MISMATCH",
                "GA4 executor received a request prepared for a different provider or connector.",
            )
        try:
            if request.capability_id != "analytics_retrieval" or request.action != "run_report":
                return self._definite_failure(
                    "GA4_UNSUPPORTED_ACTION",
                    "GA4 executor v1 only supports analytics_retrieval/run_report.",
                )
            if request.resource_type != "property":
                raise GoogleExecutorValidationError("GA4 report requires resource_type='property'.")
            bundle = self._bundle(credential)
            property_id = _canonical_numeric_id("resource_id", request.resource_id)
            if property_id != bundle["property_id"]:
                raise GoogleExecutorValidationError("GA4_PROPERTY_BINDING_MISMATCH")
            body = self._report_body(dict(request.payload))
        except GoogleExecutorValidationError as exc:
            return self._definite_failure("GA4_VALIDATION_ERROR", str(exc))

        access_token = bundle["access_token"]
        secrets = (access_token,)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "AI-Marketing-Department/GA4ReadExecutorV1",
        }
        url = f"https://{_GA4_HOST}/v1beta/properties/{property_id}:runReport"
        response = self._post_json(
            url=url,
            headers=headers,
            body=body,
            timeout_seconds=timeout_seconds,
        )
        try:
            payload = _decode_json(response)
        except GoogleTransportError:
            if 400 <= response.status_code < 500:
                payload = None
            else:
                raise
        if 400 <= response.status_code < 500:
            return self._provider_error(response, payload, secrets)
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise ConnectionError(f"GA4_UPSTREAM_HTTP_{response.status_code}")
        if not isinstance(payload, Mapping):
            raise GoogleTransportError("GA4_RESPONSE_INVALID")
        safe = _scrub_payload(dict(payload), secrets)
        return MarketingLiveExecutorResult(
            success=True,
            data={
                "provider": self.provider,
                "operation": "run_report",
                "property_id": property_id,
                "report": safe,
                "provider_network_called": True,
                "read_only": True,
            },
        )
