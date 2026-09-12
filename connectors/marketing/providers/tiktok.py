"""TikTok Content Posting API executor for governed LIVE marketing actions.

V1 deliberately supports a narrow, compliance-oriented surface:
- query creator info for the latest provider-side posting choices
- initialize Direct Post video using PULL_FROM_URL
- fetch asynchronous post status

Direct Post never trusts model-supplied privacy/caption/media settings. The request
carries only an opaque ``preflight_reference``; exact provider payload and human
choices are loaded from the short-lived ProviderPreflightRepository and claimed
one-shot before provider dispatch.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol

from connections.secrets import SecretValue
from connectors.marketing import ExternalMarketingRequest, PreparedMarketingAction
from connectors.marketing.preflight import (
    ProviderPreflightArtifact,
    ProviderPreflightConflictError,
    ProviderPreflightError,
    ProviderPreflightRepository,
)
from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from tools.dynamic_gateway.marketing_live import MarketingLiveExecutorResult


_TIKTOK_HOST = "open.tiktokapis.com"
_CREATOR_INFO_PATH = "/v2/post/publish/creator_info/query/"
_VIDEO_INIT_PATH = "/v2/post/publish/video/init/"
_STATUS_PATH = "/v2/post/publish/status/fetch/"
_PREFLIGHT_PURPOSE = "tiktok_direct_post_video"

_PRIVACY_LEVELS = frozenset(
    {
        "PUBLIC_TO_EVERYONE",
        "MUTUAL_FOLLOW_FRIENDS",
        "FOLLOWER_OF_CREATOR",
        "SELF_ONLY",
    }
)
_PUBLISH_ID_RE = re.compile(r"^[A-Za-z0-9_.:~-]{1,128}$")
_PREFLIGHT_ID_RE = re.compile(r"^PREF-[A-F0-9]{20}$")


class TikTokExecutorError(RuntimeError):
    """Base TikTok executor error."""


class TikTokExecutorValidationError(TikTokExecutorError):
    """Definite local rejection before provider transport begins."""


class TikTokTransportError(TikTokExecutorError):
    """Uncertain provider transport/result failure."""


@dataclass(frozen=True)
class TikTokHttpResponse:
    status_code: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)


class TikTokHttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout_seconds: float,
    ) -> TikTokHttpResponse:
        ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UrllibTikTokHttpTransport:
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
    ) -> TikTokHttpResponse:
        req = urllib.request.Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method.upper(),
        )
        try:
            with self._opener.open(req, timeout=float(timeout_seconds)) as response:
                return TikTokHttpResponse(
                    status_code=int(response.status),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read()
            except Exception:
                payload = b""
            return TikTokHttpResponse(
                status_code=int(exc.code),
                body=payload,
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ConnectionError(
                "TIKTOK_TRANSPORT_UNCERTAIN: " + sanitize_sensitive_text(str(reason))
            ) from exc


class TikTokMarketingExecutor:
    """Trusted TikTok executor with mandatory preflight for Direct Post writes."""

    executor_name = "tiktok-content-posting-executor-v1"
    provider = "tiktok"

    def __init__(
        self,
        *,
        transport: Optional[TikTokHttpTransport] = None,
        preflight_repository: Optional[ProviderPreflightRepository] = None,
    ) -> None:
        self.transport = transport or UrllibTikTokHttpTransport()
        self.preflight_repository = preflight_repository
        self.base_url = f"https://{_TIKTOK_HOST}"

    @staticmethod
    def _definite_failure(
        code: str,
        message: str,
        *,
        data: Optional[Mapping[str, Any]] = None,
    ) -> MarketingLiveExecutorResult:
        return MarketingLiveExecutorResult(
            success=False,
            error_code=sanitize_sensitive_text(code),
            error_message=sanitize_sensitive_text(message),
            data=sanitize_sensitive_payload(dict(data or {})),
        )

    @staticmethod
    def _reveal_credential(credential: Optional[SecretValue]) -> str:
        if credential is None:
            raise TikTokExecutorValidationError("TIKTOK_CREDENTIAL_REQUIRED")
        token = credential.reveal()
        if not isinstance(token, str) or not token.strip():
            raise TikTokExecutorValidationError("TIKTOK_CREDENTIAL_REQUIRED")
        return token.strip()

    @staticmethod
    def _decode_json(response: TikTokHttpResponse) -> Dict[str, Any]:
        if not response.body:
            raise TikTokTransportError("TIKTOK_EMPTY_RESPONSE: provider returned no JSON body.")
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TikTokTransportError(
                "TIKTOK_INVALID_JSON_RESPONSE: provider response was not valid UTF-8 JSON."
            ) from exc
        if not isinstance(decoded, dict):
            raise TikTokTransportError(
                "TIKTOK_INVALID_JSON_RESPONSE: provider response root must be an object."
            )
        return decoded

    @staticmethod
    def _safe_error_code(value: Any) -> str:
        raw = str(value or "unknown_error").strip().lower()
        normalized = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_") or "unknown_error"
        return "TIKTOK_ERROR_" + normalized.upper()

    @classmethod
    def _provider_failure(
        cls,
        *,
        payload: Optional[Mapping[str, Any]],
        status_code: int,
    ) -> MarketingLiveExecutorResult:
        error = payload.get("error") if isinstance(payload, Mapping) else None
        if isinstance(error, Mapping):
            code = str(error.get("code") or "").strip()
            message = sanitize_sensitive_text(
                str(error.get("message") or f"TikTok rejected the request with HTTP {status_code}.")
            )
            stable = cls._safe_error_code(code or f"http_{status_code}")
            log_id = str(error.get("log_id") or error.get("logid") or "").strip()
            return cls._definite_failure(
                stable,
                message,
                data={"http_status": status_code, "provider_log_id": log_id or None},
            )
        return cls._definite_failure(
            f"TIKTOK_HTTP_{status_code}",
            f"TikTok rejected the request with HTTP {status_code}.",
            data={"http_status": status_code},
        )

    @staticmethod
    def _error_code(payload: Mapping[str, Any]) -> str:
        error = payload.get("error")
        if not isinstance(error, Mapping):
            return ""
        return str(error.get("code") or "").strip().lower()

    def _request_json(
        self,
        *,
        path: str,
        token: str,
        timeout_seconds: float,
        body: Optional[Mapping[str, Any]] = None,
    ) -> TikTokHttpResponse:
        if path not in {_CREATOR_INFO_PATH, _VIDEO_INIT_PATH, _STATUS_PATH}:
            raise TikTokExecutorValidationError("TIKTOK_UNSAFE_PATH")
        payload = json.dumps(dict(body or {}), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "AI-Marketing-Department/TikTokExecutorV1",
        }
        return self.transport.request(
            method="POST",
            url=self.base_url + path,
            headers=headers,
            body=payload,
            timeout_seconds=float(timeout_seconds),
        )

    @staticmethod
    def _http_payload(response: TikTokHttpResponse) -> tuple[Optional[Dict[str, Any]], bool]:
        """Decode a response while preserving definite HTTP 4xx semantics.

        Invalid JSON on 4xx is still a definite rejection. Invalid JSON on 2xx/3xx/5xx
        is uncertain and therefore raised by the caller.
        """
        try:
            return TikTokMarketingExecutor._decode_json(response), True
        except TikTokTransportError:
            if 400 <= response.status_code < 500:
                return None, False
            raise

    @staticmethod
    def _creator_snapshot(data: Mapping[str, Any]) -> Dict[str, Any]:
        options_raw = data.get("privacy_level_options")
        if not isinstance(options_raw, list) or not options_raw:
            raise TikTokTransportError("TIKTOK_CREATOR_INFO_MISSING_PRIVACY_OPTIONS")
        options = []
        for item in options_raw:
            value = str(item or "").strip().upper()
            if value not in _PRIVACY_LEVELS:
                raise TikTokTransportError("TIKTOK_CREATOR_INFO_INVALID_PRIVACY_OPTION")
            if value not in options:
                options.append(value)

        def _bool_field(name: str) -> bool:
            value = data.get(name)
            if not isinstance(value, bool):
                raise TikTokTransportError(f"TIKTOK_CREATOR_INFO_INVALID_{name.upper()}")
            return value

        duration = data.get("max_video_post_duration_sec")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise TikTokTransportError("TIKTOK_CREATOR_INFO_INVALID_MAX_DURATION")

        return {
            "creator_username": sanitize_sensitive_text(str(data.get("creator_username") or "")),
            "creator_nickname": sanitize_sensitive_text(str(data.get("creator_nickname") or "")),
            "privacy_level_options": options,
            "comment_disabled": _bool_field("comment_disabled"),
            "duet_disabled": _bool_field("duet_disabled"),
            "stitch_disabled": _bool_field("stitch_disabled"),
            "max_video_post_duration_sec": duration,
        }

    def _query_creator_info(
        self,
        *,
        request: ExternalMarketingRequest,
        token: str,
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        if request.resource_type != "creator":
            raise TikTokExecutorValidationError(
                "query_creator_info requires resource_type='creator'."
            )
        if dict(request.payload):
            raise TikTokExecutorValidationError("query_creator_info does not accept payload fields.")
        response = self._request_json(
            path=_CREATOR_INFO_PATH,
            token=token,
            timeout_seconds=timeout_seconds,
            body={},
        )
        payload, _ = self._http_payload(response)
        if 400 <= response.status_code < 500:
            return self._provider_failure(payload=payload, status_code=response.status_code)
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise ConnectionError(f"TIKTOK_UPSTREAM_HTTP_{response.status_code}")
        if payload is None:
            raise TikTokTransportError("TIKTOK_CREATOR_INFO_MISSING_RESPONSE")
        code = self._error_code(payload)
        if code != "ok":
            return self._provider_failure(payload=payload, status_code=response.status_code)
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TikTokTransportError("TIKTOK_CREATOR_INFO_MISSING_DATA")
        snapshot = self._creator_snapshot(data)
        return MarketingLiveExecutorResult(
            success=True,
            data={
                "provider": "tiktok",
                "operation": "query_creator_info",
                "provider_network_called": True,
                "creator_info": snapshot,
            },
        )

    @staticmethod
    def _publish_id(value: Any) -> str:
        raw = str(value or "").strip()
        if not _PUBLISH_ID_RE.fullmatch(raw):
            raise TikTokExecutorValidationError("publish_id is invalid.")
        return raw

    def _fetch_publish_status(
        self,
        *,
        request: ExternalMarketingRequest,
        token: str,
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        if request.resource_type not in {"post", "video"}:
            raise TikTokExecutorValidationError(
                "fetch_publish_status requires resource_type='post' or 'video'."
            )
        payload_in = dict(request.payload)
        if set(payload_in) != {"publish_id"}:
            raise TikTokExecutorValidationError(
                "fetch_publish_status requires exactly payload.publish_id."
            )
        publish_id = self._publish_id(payload_in.get("publish_id"))
        response = self._request_json(
            path=_STATUS_PATH,
            token=token,
            timeout_seconds=timeout_seconds,
            body={"publish_id": publish_id},
        )
        payload, _ = self._http_payload(response)
        if 400 <= response.status_code < 500:
            return self._provider_failure(payload=payload, status_code=response.status_code)
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise ConnectionError(f"TIKTOK_UPSTREAM_HTTP_{response.status_code}")
        if payload is None:
            raise TikTokTransportError("TIKTOK_STATUS_MISSING_RESPONSE")
        code = self._error_code(payload)
        if code != "ok":
            return self._provider_failure(payload=payload, status_code=response.status_code)
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TikTokTransportError("TIKTOK_STATUS_MISSING_DATA")
        safe = sanitize_sensitive_payload(dict(data))
        if not isinstance(safe, dict):
            safe = {}
        safe["publish_id"] = publish_id
        return MarketingLiveExecutorResult(
            success=True,
            data={
                "provider": "tiktok",
                "operation": "fetch_publish_status",
                "provider_network_called": True,
                "status": safe,
            },
            artifact_refs=(f"tiktok://publish/{publish_id}",),
        )

    @staticmethod
    def _validate_video_url(value: Any) -> str:
        raw = str(value or "").strip()
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme != "https" or not parsed.netloc:
            raise TikTokExecutorValidationError(
                "TikTok PULL_FROM_URL video_url must be an absolute HTTPS URL."
            )
        if parsed.username or parsed.password:
            raise TikTokExecutorValidationError(
                "TikTok video_url must not contain embedded credentials."
            )
        if parsed.fragment:
            raise TikTokExecutorValidationError("TikTok video_url must not contain a fragment.")
        if parsed.query:
            raise TikTokExecutorValidationError(
                "TikTok executor v1 requires a stable public video_url without query parameters."
            )
        return raw

    @staticmethod
    def _title_units(value: str) -> int:
        return len(value.encode("utf-16-le")) // 2

    @classmethod
    def _validate_preflight_payload(
        cls,
        artifact: ProviderPreflightArtifact,
    ) -> Dict[str, Any]:
        approved = dict(artifact.approved_payload)
        if set(approved) != {"post_info", "source_info"}:
            raise TikTokExecutorValidationError(
                "TIKTOK_PREFLIGHT_PAYLOAD_INVALID: approved_payload requires post_info and source_info only."
            )
        post_info_raw = approved.get("post_info")
        source_info_raw = approved.get("source_info")
        if not isinstance(post_info_raw, Mapping) or not isinstance(source_info_raw, Mapping):
            raise TikTokExecutorValidationError("TIKTOK_PREFLIGHT_PAYLOAD_INVALID")
        post_info = dict(post_info_raw)
        source_info = dict(source_info_raw)

        allowed_post = {
            "title",
            "privacy_level",
            "disable_duet",
            "disable_comment",
            "disable_stitch",
            "video_cover_timestamp_ms",
            "brand_content_toggle",
            "brand_organic_toggle",
            "is_aigc",
        }
        unexpected = sorted(set(post_info) - allowed_post)
        if unexpected:
            raise TikTokExecutorValidationError(
                "Unsupported TikTok preflight post_info fields: " + ", ".join(unexpected)
            )
        required_choices = {
            "privacy_level",
            "disable_duet",
            "disable_comment",
            "disable_stitch",
            "brand_content_toggle",
            "brand_organic_toggle",
            "is_aigc",
        }
        missing = sorted(required_choices - set(post_info))
        if missing:
            raise TikTokExecutorValidationError(
                "TikTok preflight is missing explicit user choices: " + ", ".join(missing)
            )
        choices = dict(artifact.user_choices)
        for key in required_choices:
            if key not in choices or choices.get(key) != post_info.get(key):
                raise TikTokExecutorValidationError(
                    f"TIKTOK_PREFLIGHT_USER_CHOICE_MISMATCH: {key}"
                )

        privacy = str(post_info.get("privacy_level") or "").strip().upper()
        snapshot = dict(artifact.provider_snapshot)
        options_raw = snapshot.get("privacy_level_options")
        options = {
            str(item or "").strip().upper()
            for item in options_raw
        } if isinstance(options_raw, (list, tuple)) else set()
        if privacy not in _PRIVACY_LEVELS or privacy not in options:
            raise TikTokExecutorValidationError(
                "TIKTOK_PREFLIGHT_PRIVACY_OPTION_MISMATCH"
            )
        post_info["privacy_level"] = privacy

        for key in (
            "disable_duet",
            "disable_comment",
            "disable_stitch",
            "brand_content_toggle",
            "brand_organic_toggle",
            "is_aigc",
        ):
            if not isinstance(post_info.get(key), bool):
                raise TikTokExecutorValidationError(f"TikTok {key} must be boolean.")

        restrictions = {
            "disable_comment": "comment_disabled",
            "disable_duet": "duet_disabled",
            "disable_stitch": "stitch_disabled",
        }
        for post_key, snapshot_key in restrictions.items():
            provider_disabled = snapshot.get(snapshot_key)
            if not isinstance(provider_disabled, bool):
                raise TikTokExecutorValidationError(
                    f"TIKTOK_PREFLIGHT_SNAPSHOT_INVALID: {snapshot_key}"
                )
            if provider_disabled and post_info.get(post_key) is not True:
                raise TikTokExecutorValidationError(
                    f"TIKTOK_PREFLIGHT_PROVIDER_RESTRICTION_MISMATCH: {post_key}"
                )

        title = str(post_info.get("title") or "")
        if cls._title_units(title) > 2200:
            raise TikTokExecutorValidationError("TikTok title exceeds 2200 UTF-16 units.")
        if title:
            post_info["title"] = title
        elif "title" in post_info:
            post_info["title"] = ""

        if "video_cover_timestamp_ms" in post_info:
            cover = post_info.get("video_cover_timestamp_ms")
            if not isinstance(cover, int) or isinstance(cover, bool) or cover < 0:
                raise TikTokExecutorValidationError(
                    "video_cover_timestamp_ms must be a non-negative integer."
                )

        if set(source_info) != {"source", "video_url"}:
            raise TikTokExecutorValidationError(
                "TikTok executor v1 supports only source=PULL_FROM_URL with video_url."
            )
        if str(source_info.get("source") or "").strip().upper() != "PULL_FROM_URL":
            raise TikTokExecutorValidationError(
                "TikTok executor v1 supports only PULL_FROM_URL."
            )
        video_url = cls._validate_video_url(source_info.get("video_url"))
        source_info = {"source": "PULL_FROM_URL", "video_url": video_url}
        return {"post_info": post_info, "source_info": source_info}

    def _claim_preflight(
        self,
        *,
        prepared: PreparedMarketingAction,
        request: ExternalMarketingRequest,
    ) -> ProviderPreflightArtifact:
        if self.preflight_repository is None:
            raise TikTokExecutorValidationError("TIKTOK_PREFLIGHT_AUTHORITY_REQUIRED")
        payload = dict(request.payload)
        if set(payload) != {"preflight_reference"}:
            raise TikTokExecutorValidationError(
                "publish_video requires exactly payload.preflight_reference; provider choices must come from the trusted preflight artifact."
            )
        reference = str(payload.get("preflight_reference") or "").strip().upper()
        if not _PREFLIGHT_ID_RE.fullmatch(reference):
            raise TikTokExecutorValidationError("TIKTOK_PREFLIGHT_REFERENCE_INVALID")
        if not request.idempotency_key:
            raise TikTokExecutorValidationError("TIKTOK_IDEMPOTENCY_KEY_REQUIRED")
        try:
            return self.preflight_repository.claim(
                reference,
                provider="tiktok",
                connector_id=prepared.connector_id,
                connection_id=request.connection_id,
                business_id=request.business_id,
                project_id=request.project_id,
                brand_id=request.brand_id,
                purpose=_PREFLIGHT_PURPOSE,
                idempotency_key=request.idempotency_key,
            )
        except ProviderPreflightConflictError as exc:
            raise TikTokExecutorValidationError(str(exc)) from exc
        except ProviderPreflightError as exc:
            raise TikTokExecutorError(str(exc)) from exc

    def _consume_preflight(self, preflight_id: str) -> None:
        assert self.preflight_repository is not None
        try:
            self.preflight_repository.consume(preflight_id)
        except ProviderPreflightError as exc:
            # Provider dispatch may already have completed. Losing one-shot consent
            # settlement must be surfaced as uncertain so ToolGateway preserves the
            # idempotency reservation and never auto-replays the write.
            raise TikTokTransportError(
                "TIKTOK_PREFLIGHT_SETTLEMENT_FAILED: " + sanitize_sensitive_text(str(exc))
            ) from exc

    def _publish_video(
        self,
        *,
        prepared: PreparedMarketingAction,
        request: ExternalMarketingRequest,
        token: str,
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        if request.resource_type != "video":
            raise TikTokExecutorValidationError(
                "publish_video requires resource_type='video'."
            )
        artifact = self._claim_preflight(prepared=prepared, request=request)
        try:
            body = self._validate_preflight_payload(artifact)
        except TikTokExecutorValidationError:
            self._consume_preflight(artifact.preflight_id)
            raise

        response = self._request_json(
            path=_VIDEO_INIT_PATH,
            token=token,
            timeout_seconds=timeout_seconds,
            body=body,
        )
        payload, _ = self._http_payload(response)
        if 400 <= response.status_code < 500:
            result = self._provider_failure(payload=payload, status_code=response.status_code)
            self._consume_preflight(artifact.preflight_id)
            return result
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise ConnectionError(f"TIKTOK_UPSTREAM_HTTP_{response.status_code}")
        if payload is None:
            raise TikTokTransportError("TIKTOK_WRITE_MISSING_RESPONSE")
        code = self._error_code(payload)
        if code != "ok":
            result = self._provider_failure(payload=payload, status_code=response.status_code)
            self._consume_preflight(artifact.preflight_id)
            return result
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TikTokTransportError("TIKTOK_WRITE_MISSING_DATA")
        publish_id = str(data.get("publish_id") or "").strip()
        if not _PUBLISH_ID_RE.fullmatch(publish_id):
            raise TikTokTransportError(
                "TIKTOK_WRITE_RESPONSE_MISSING_PUBLISH_ID: provider returned success without a valid publish_id."
            )
        self._consume_preflight(artifact.preflight_id)
        return MarketingLiveExecutorResult(
            success=True,
            data={
                "provider": "tiktok",
                "operation": "direct_post_video_init",
                "publish_id": publish_id,
                "provider_network_called": True,
                "external_side_effect": True,
                "preflight_reference": artifact.preflight_id,
            },
            artifact_refs=(f"tiktok://publish/{publish_id}",),
        )

    def execute(
        self,
        *,
        prepared: PreparedMarketingAction,
        request: ExternalMarketingRequest,
        credential: Optional[SecretValue],
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        if prepared.provider != "tiktok" or request.connector_id != prepared.connector_id:
            return self._definite_failure(
                "TIKTOK_PROVIDER_BINDING_MISMATCH",
                "TikTok executor received a request prepared for a different provider or connector.",
            )
        token = self._reveal_credential(credential)
        try:
            if request.capability_id == "analytics_retrieval" and request.action == "query_creator_info":
                return self._query_creator_info(
                    request=request,
                    token=token,
                    timeout_seconds=timeout_seconds,
                )
            if request.capability_id == "analytics_retrieval" and request.action == "fetch_publish_status":
                return self._fetch_publish_status(
                    request=request,
                    token=token,
                    timeout_seconds=timeout_seconds,
                )
            if request.capability_id == "social_publishing" and request.action == "publish_video":
                return self._publish_video(
                    prepared=prepared,
                    request=request,
                    token=token,
                    timeout_seconds=timeout_seconds,
                )
            return self._definite_failure(
                "TIKTOK_UNSUPPORTED_ACTION",
                "TikTok executor v1 only supports query_creator_info, publish_video, and fetch_publish_status.",
            )
        except TikTokExecutorValidationError as exc:
            return self._definite_failure("TIKTOK_VALIDATION_ERROR", str(exc))
