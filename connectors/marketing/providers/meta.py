"""Meta Graph/Marketing API executor for governed LIVE marketing actions.

This provider implementation intentionally supports a narrow v1 surface:
- Facebook Page text/link publishing through ``/{page_id}/feed``
- Meta Ads Insights reads through ``/{object_id}/insights``

All permission, approval, idempotency, durable intent, scoped connection, and
secret-resolution controls live outside this module in the shared platform.
The executor receives a ``SecretValue`` only at the trusted transport boundary.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Mapping, Optional, Protocol

from connections.secrets import SecretValue
from connectors.marketing import ExternalMarketingRequest, PreparedMarketingAction
from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from tools.dynamic_gateway.marketing_live import MarketingLiveExecutorResult


_META_HOST = "graph.facebook.com"
_API_VERSION_RE = re.compile(r"^v[0-9]{1,3}\.[0-9]{1,3}$")
_NUMERIC_ID_RE = re.compile(r"^[0-9]{1,32}$")

_INSIGHT_RESOURCE_TYPES = frozenset({"ad_account", "campaign", "adset", "ad"})
_INSIGHT_FIELDS = frozenset(
    {
        "account_currency",
        "account_id",
        "account_name",
        "actions",
        "action_values",
        "ad_id",
        "ad_name",
        "adset_id",
        "adset_name",
        "campaign_id",
        "campaign_name",
        "clicks",
        "conversion_values",
        "conversions",
        "cpc",
        "cpm",
        "ctr",
        "date_start",
        "date_stop",
        "frequency",
        "impressions",
        "inline_link_clicks",
        "inline_post_engagement",
        "outbound_clicks",
        "reach",
        "spend",
        "unique_clicks",
        "unique_outbound_clicks",
        "video_play_actions",
    }
)
_DEFAULT_INSIGHT_FIELDS = (
    "date_start",
    "date_stop",
    "impressions",
    "clicks",
    "reach",
    "spend",
    "ctr",
    "cpc",
    "cpm",
)
_DATE_PRESETS = frozenset(
    {
        "today",
        "yesterday",
        "this_month",
        "last_month",
        "this_quarter",
        "maximum",
        "last_3d",
        "last_7d",
        "last_14d",
        "last_28d",
        "last_30d",
        "last_90d",
    }
)


class MetaExecutorError(RuntimeError):
    """Base error for Meta executor failures."""


class MetaExecutorValidationError(MetaExecutorError):
    """Definite local rejection before provider transport begins."""


class MetaTransportError(MetaExecutorError):
    """Uncertain provider-transport failure."""


@dataclass(frozen=True)
class MetaHttpResponse:
    status_code: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)


class MetaHttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout_seconds: float,
    ) -> MetaHttpResponse:
        ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UrllibMetaHttpTransport:
    """Minimal stdlib transport that never follows redirects with Authorization."""

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
    ) -> MetaHttpResponse:
        req = urllib.request.Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method.upper(),
        )
        try:
            with self._opener.open(req, timeout=float(timeout_seconds)) as response:
                return MetaHttpResponse(
                    status_code=int(response.status),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read()
            except Exception:
                payload = b""
            return MetaHttpResponse(
                status_code=int(exc.code),
                body=payload,
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ConnectionError(f"META_TRANSPORT_UNCERTAIN: {sanitize_sensitive_text(str(reason))}") from exc


class MetaMarketingExecutor:
    """Trusted Meta provider executor with a deliberately narrow allowlist."""

    executor_name = "meta-graph-marketing-executor-v1"
    provider = "meta"

    def __init__(
        self,
        *,
        transport: Optional[MetaHttpTransport] = None,
        api_version: str = "v26.0",
    ) -> None:
        normalized_version = str(api_version or "").strip()
        if not _API_VERSION_RE.fullmatch(normalized_version):
            raise ValueError("Meta api_version must look like 'v26.0'.")
        self.transport = transport or UrllibMetaHttpTransport()
        self.api_version = normalized_version
        self.base_url = f"https://{_META_HOST}/{self.api_version}"

    @staticmethod
    def _definite_failure(code: str, message: str, *, data: Optional[Mapping[str, Any]] = None) -> MarketingLiveExecutorResult:
        return MarketingLiveExecutorResult(
            success=False,
            error_code=sanitize_sensitive_text(code),
            error_message=sanitize_sensitive_text(message),
            data=sanitize_sensitive_payload(dict(data or {})),
        )

    @staticmethod
    def _numeric_id(value: Optional[str], *, field_name: str) -> str:
        raw = str(value or "").strip()
        if not _NUMERIC_ID_RE.fullmatch(raw):
            raise MetaExecutorValidationError(f"{field_name} must be a numeric Meta object id.")
        return raw

    @staticmethod
    def _decode_json(response: MetaHttpResponse) -> Dict[str, Any]:
        if not response.body:
            return {}
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MetaTransportError("META_INVALID_JSON_RESPONSE: provider response was not valid UTF-8 JSON.") from exc
        if not isinstance(decoded, dict):
            raise MetaTransportError("META_INVALID_JSON_RESPONSE: provider response root must be an object.")
        return decoded

    @staticmethod
    def _provider_error(payload: Mapping[str, Any], status_code: int) -> MarketingLiveExecutorResult:
        error = payload.get("error") if isinstance(payload, Mapping) else None
        if not isinstance(error, Mapping):
            return MetaMarketingExecutor._definite_failure(
                f"META_HTTP_{status_code}",
                f"Meta rejected the request with HTTP {status_code}.",
            )
        meta_code = str(error.get("code") or status_code)
        subcode = str(error.get("error_subcode") or "").strip()
        message = sanitize_sensitive_text(str(error.get("message") or "Meta rejected the request."))
        stable = f"META_ERROR_{meta_code}" + (f"_{subcode}" if subcode else "")
        return MetaMarketingExecutor._definite_failure(
            stable,
            message,
            data={"http_status": status_code, "meta_code": meta_code, "meta_subcode": subcode or None},
        )

    def _request(
        self,
        *,
        method: str,
        path: str,
        token: str,
        timeout_seconds: float,
        query: Optional[Mapping[str, Any]] = None,
        form: Optional[Mapping[str, Any]] = None,
    ) -> MetaHttpResponse:
        if not path.startswith("/") or ".." in path or "?" in path or "#" in path:
            raise MetaExecutorValidationError("META_UNSAFE_PATH: provider path was rejected.")
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(dict(query), doseq=True)
        body: Optional[bytes] = None
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "AI-Marketing-Department/MetaExecutorV1",
        }
        if form is not None:
            body = urllib.parse.urlencode(dict(form), doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        return self.transport.request(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout_seconds=float(timeout_seconds),
        )

    @staticmethod
    def _validate_link(value: Any) -> str:
        raw = str(value or "").strip()
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MetaExecutorValidationError("Meta Page link must be an absolute http(s) URL.")
        if parsed.username or parsed.password:
            raise MetaExecutorValidationError("Meta Page link must not contain embedded credentials.")
        return raw

    def _publish_page_post(
        self,
        *,
        request: ExternalMarketingRequest,
        token: str,
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        if request.resource_type != "page":
            raise MetaExecutorValidationError("publish_post only supports resource_type='page' in Meta executor v1.")
        page_id = self._numeric_id(request.resource_id, field_name="resource_id/page_id")
        payload = dict(request.payload)
        allowed = {"message", "link"}
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise MetaExecutorValidationError(
                "Unsupported Meta Page publish fields: " + ", ".join(unexpected)
            )
        message = str(payload.get("message") or "").strip()
        link_raw = payload.get("link")
        link = self._validate_link(link_raw) if link_raw else ""
        if not message and not link:
            raise MetaExecutorValidationError("Meta Page publish requires a non-empty message or link.")
        if len(message) > 63206:
            raise MetaExecutorValidationError("Meta Page message exceeds the supported v1 length limit.")

        form: Dict[str, str] = {}
        if message:
            form["message"] = message
        if link:
            form["link"] = link

        response = self._request(
            method="POST",
            path=f"/{page_id}/feed",
            token=token,
            timeout_seconds=timeout_seconds,
            form=form,
        )
        payload_json = self._decode_json(response)
        if 200 <= response.status_code < 300:
            post_id = str(payload_json.get("id") or "").strip()
            if not post_id:
                raise MetaTransportError("META_WRITE_RESPONSE_MISSING_ID: Meta returned 2xx without a post id.")
            return MarketingLiveExecutorResult(
                success=True,
                data={
                    "provider": "meta",
                    "operation": "page_publish_post",
                    "api_version": self.api_version,
                    "page_id": page_id,
                    "post_id": post_id,
                    "provider_network_called": True,
                    "external_side_effect": True,
                },
                artifact_refs=(f"meta://page/{page_id}/post/{post_id}",),
            )
        if 400 <= response.status_code < 500:
            return self._provider_error(payload_json, response.status_code)
        raise MetaTransportError(f"META_UPSTREAM_HTTP_{response.status_code}: provider outcome is uncertain.")

    @staticmethod
    def _parse_date(value: Any, *, field_name: str) -> str:
        raw = str(value or "").strip()
        try:
            date.fromisoformat(raw)
        except ValueError as exc:
            raise MetaExecutorValidationError(f"{field_name} must use YYYY-MM-DD.") from exc
        return raw

    def _insight_node(self, request: ExternalMarketingRequest) -> str:
        if request.resource_type not in _INSIGHT_RESOURCE_TYPES:
            raise MetaExecutorValidationError(
                "read_metrics supports ad_account, campaign, adset, or ad resources only."
            )
        raw = str(request.resource_id or "").strip()
        if request.resource_type == "ad_account" and raw.startswith("act_"):
            raw = raw[4:]
        object_id = self._numeric_id(raw, field_name="resource_id")
        return f"act_{object_id}" if request.resource_type == "ad_account" else object_id

    def _read_insights(
        self,
        *,
        request: ExternalMarketingRequest,
        token: str,
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        node_id = self._insight_node(request)
        payload = dict(request.payload)
        allowed_keys = {"fields", "date_preset", "time_range", "limit"}
        unexpected = sorted(set(payload) - allowed_keys)
        if unexpected:
            raise MetaExecutorValidationError(
                "Unsupported Meta Insights parameters: " + ", ".join(unexpected)
            )

        raw_fields = payload.get("fields", _DEFAULT_INSIGHT_FIELDS)
        if isinstance(raw_fields, str):
            fields = [part.strip() for part in raw_fields.split(",") if part.strip()]
        elif isinstance(raw_fields, (list, tuple)):
            fields = [str(item).strip() for item in raw_fields if str(item).strip()]
        else:
            raise MetaExecutorValidationError("Meta Insights fields must be a list or comma-separated string.")
        if not fields:
            raise MetaExecutorValidationError("Meta Insights fields must not be empty.")
        invalid_fields = sorted(set(fields) - _INSIGHT_FIELDS)
        if invalid_fields:
            raise MetaExecutorValidationError(
                "Unsupported Meta Insights fields: " + ", ".join(invalid_fields)
            )

        query: Dict[str, Any] = {"fields": ",".join(dict.fromkeys(fields))}
        if "date_preset" in payload and "time_range" in payload:
            raise MetaExecutorValidationError("Choose date_preset or time_range, not both.")
        if payload.get("date_preset") is not None:
            preset = str(payload.get("date_preset") or "").strip()
            if preset not in _DATE_PRESETS:
                raise MetaExecutorValidationError("Unsupported Meta Insights date_preset.")
            query["date_preset"] = preset
        if payload.get("time_range") is not None:
            time_range = payload.get("time_range")
            if not isinstance(time_range, Mapping):
                raise MetaExecutorValidationError("time_range must be an object with since/until.")
            if set(time_range) != {"since", "until"}:
                raise MetaExecutorValidationError("time_range must contain exactly since and until.")
            since = self._parse_date(time_range.get("since"), field_name="time_range.since")
            until = self._parse_date(time_range.get("until"), field_name="time_range.until")
            if since > until:
                raise MetaExecutorValidationError("time_range.since must not be after time_range.until.")
            query["time_range"] = json.dumps({"since": since, "until": until}, separators=(",", ":"))
        if payload.get("limit") is not None:
            limit = payload.get("limit")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
                raise MetaExecutorValidationError("Meta Insights limit must be an integer from 1 to 100.")
            query["limit"] = limit

        response = self._request(
            method="GET",
            path=f"/{node_id}/insights",
            token=token,
            timeout_seconds=timeout_seconds,
            query=query,
        )
        payload_json = self._decode_json(response)
        if 200 <= response.status_code < 300:
            return MarketingLiveExecutorResult(
                success=True,
                data={
                    "provider": "meta",
                    "operation": "ads_insights",
                    "api_version": self.api_version,
                    "resource_type": request.resource_type,
                    "resource_id": request.resource_id,
                    "provider_network_called": True,
                    "external_side_effect": False,
                    "response": sanitize_sensitive_payload(payload_json),
                },
            )
        if 400 <= response.status_code < 500:
            return self._provider_error(payload_json, response.status_code)
        raise MetaTransportError(f"META_UPSTREAM_HTTP_{response.status_code}: provider response is uncertain.")

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
                "META_EXECUTOR_BINDING_MISMATCH",
                "Prepared marketing action does not match the Meta executor binding.",
            )
        if credential is None:
            return self._definite_failure("META_CREDENTIAL_REQUIRED", "Meta LIVE execution requires a credential.")
        if not isinstance(credential, SecretValue):
            return self._definite_failure("META_INVALID_CREDENTIAL_WRAPPER", "Meta credential must be a SecretValue.")

        token = credential.reveal()
        if not token.strip():
            return self._definite_failure("META_EMPTY_CREDENTIAL", "Meta credential is empty.")

        try:
            if request.capability_id == "social_publishing" and request.action == "publish_post":
                return self._publish_page_post(
                    request=request,
                    token=token,
                    timeout_seconds=timeout_seconds,
                )
            if request.capability_id == "analytics_retrieval" and request.action == "read_metrics":
                return self._read_insights(
                    request=request,
                    token=token,
                    timeout_seconds=timeout_seconds,
                )
            return self._definite_failure(
                "META_OPERATION_NOT_SUPPORTED",
                "Meta executor v1 does not support the requested capability/action pair.",
            )
        except MetaExecutorValidationError as exc:
            return self._definite_failure("META_REQUEST_REJECTED", str(exc))
