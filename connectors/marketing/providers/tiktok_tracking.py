"""Durable operation tracking wrapper for the governed TikTok executor.

The already-certified TikTok provider transport remains unchanged. This wrapper
adds restart-safe operation records around successful Direct Post initialization
and subsequent status polling.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from connectors.marketing import ExternalMarketingRequest, PreparedMarketingAction
from connectors.marketing.operations import (
    ProviderOperationError,
    ProviderOperationRepository,
    ProviderOperationState,
)
from connectors.marketing.providers.tiktok import (
    TikTokExecutorValidationError,
    TikTokMarketingExecutor,
    TikTokTransportError,
)
from tools.dynamic_gateway.marketing_live import MarketingLiveExecutorResult


_TIKTOK_STATE_MAP = {
    "PROCESSING_UPLOAD": ProviderOperationState.PROCESSING,
    "PROCESSING_DOWNLOAD": ProviderOperationState.PROCESSING,
    "SEND_TO_USER_INBOX": ProviderOperationState.PROCESSING,
    "PUBLISH_COMPLETE": ProviderOperationState.SUCCEEDED,
    "FAILED": ProviderOperationState.FAILED,
}


class TrackedTikTokMarketingExecutor(TikTokMarketingExecutor):
    """TikTok executor variant that requires durable tracking for async posts."""

    executor_name = "tiktok-content-posting-tracked-executor-v1"

    def __init__(self, *, operation_repository: ProviderOperationRepository, **kwargs: Any) -> None:
        if operation_repository is None:
            raise TikTokExecutorValidationError("TIKTOK_OPERATION_TRACKER_REQUIRED")
        super().__init__(**kwargs)
        self.operation_repository = operation_repository

    @staticmethod
    def _success_with_tracking(
        result: MarketingLiveExecutorResult,
        *,
        operation_id: str,
        state: ProviderOperationState,
    ) -> MarketingLiveExecutorResult:
        data: Dict[str, Any] = dict(result.data)
        data["operation_id"] = operation_id
        data["operation_state"] = state.value
        data["operation_durable"] = True
        return MarketingLiveExecutorResult(
            success=True,
            data=data,
            cost_or_tokens=dict(result.cost_or_tokens),
            artifact_refs=tuple(result.artifact_refs),
        )

    def _publish_video(
        self,
        *,
        prepared: PreparedMarketingAction,
        request: ExternalMarketingRequest,
        token: str,
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        result = super()._publish_video(
            prepared=prepared,
            request=request,
            token=token,
            timeout_seconds=timeout_seconds,
        )
        if not result.success:
            return result

        publish_id = str(result.data.get("publish_id") or "").strip()
        if not publish_id:
            # The underlying executor already treats this as uncertain; retain a
            # defensive guard so tracking can never create a synthetic operation.
            raise TikTokTransportError("TIKTOK_TRACKING_MISSING_PUBLISH_ID")
        try:
            record = self.operation_repository.create(
                provider="tiktok",
                connector_id=prepared.connector_id,
                connection_id=request.connection_id,
                capability_id=request.capability_id,
                action=request.action,
                external_operation_id=publish_id,
                business_id=request.business_id,
                project_id=request.project_id,
                brand_id=request.brand_id,
                provider_status="SUBMITTED",
                idempotency_key=request.idempotency_key,
                metadata={
                    "resource_type": request.resource_type,
                    "preflight_reference": result.data.get("preflight_reference"),
                    "status_source": "direct_post_init",
                },
            )
        except ProviderOperationError as exc:
            # Provider init may already have accepted the post. Escalate as
            # uncertain so ToolGateway keeps the durable idempotency reservation
            # blocked and never interprets tracking failure as permission to replay.
            raise TikTokTransportError(
                "TIKTOK_OPERATION_TRACKING_FAILED: " + str(exc)
            ) from exc
        return self._success_with_tracking(
            result,
            operation_id=record.operation_id,
            state=record.state,
        )

    @staticmethod
    def _provider_state(provider_status: str) -> ProviderOperationState:
        normalized = str(provider_status or "").strip().upper()
        return _TIKTOK_STATE_MAP.get(normalized, ProviderOperationState.UNKNOWN)

    def _tracked_record_for_status(self, request: ExternalMarketingRequest):
        payload = dict(request.payload)
        publish_id = self._publish_id(payload.get("publish_id"))
        try:
            return self.operation_repository.find_external(
                provider="tiktok",
                connection_id=request.connection_id,
                external_operation_id=publish_id,
                business_id=request.business_id,
                project_id=request.project_id,
                brand_id=request.brand_id,
            )
        except ProviderOperationError as exc:
            raise TikTokExecutorValidationError(
                "TIKTOK_OPERATION_TRACKING_REQUIRED: " + str(exc)
            ) from exc

    def _fetch_publish_status(
        self,
        *,
        request: ExternalMarketingRequest,
        token: str,
        timeout_seconds: float,
    ) -> MarketingLiveExecutorResult:
        record = self._tracked_record_for_status(request)
        result = super()._fetch_publish_status(
            request=request,
            token=token,
            timeout_seconds=timeout_seconds,
        )
        if not result.success:
            return result

        status_payload = result.data.get("status")
        if not isinstance(status_payload, dict):
            raise TikTokTransportError("TIKTOK_TRACKING_STATUS_PAYLOAD_INVALID")
        provider_status = str(status_payload.get("status") or "").strip().upper()
        if not provider_status:
            raise TikTokTransportError("TIKTOK_TRACKING_PROVIDER_STATUS_MISSING")
        state = self._provider_state(provider_status)
        try:
            updated = self.operation_repository.record_status(
                record.operation_id,
                state=state,
                provider_status=provider_status,
                metadata={
                    "last_status": status_payload,
                    "status_source": "post_status_fetch",
                },
                polled=True,
            )
        except ProviderOperationError as exc:
            # Status polling is read-only, so this is an internal tracking error,
            # not evidence that a new external side effect occurred.
            raise TikTokExecutorValidationError(
                "TIKTOK_OPERATION_STATUS_TRACKING_FAILED: " + str(exc)
            ) from exc
        return self._success_with_tracking(
            result,
            operation_id=updated.operation_id,
            state=updated.state,
        )
