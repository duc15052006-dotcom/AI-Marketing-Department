import unittest

from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelStreamError,
    StreamDelta,
)
from integrations.models.config_service import ProviderErrorCode
from integrations.models.gateway import ProviderHealth, UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class _RecordingConfigService:
    def __init__(self):
        self.errors = []

    def record_error(self, provider_id, error_code):
        self.errors.append((provider_id, error_code))


def _permission_error():
    return ModelStreamError(
        code="AUTHORIZATION_ERROR",
        category="AUTHORIZATION",
        safe_message="provider denied access to this model",
        retryable=False,
        http_status=403,
    )


class _BasePermissionAdapter(BaseModelAdapter):
    provider_id = "permission403"

    @property
    def provider_name(self):
        return self.provider_id

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="HTTP 403 FORBIDDEN: model access denied",
            metadata={
                "error_code": "AUTHORIZATION_ERROR",
                "error_category": "AUTHORIZATION",
                "safe_message": "provider denied access to this model",
                "retryable": False,
                "http_status": 403,
            },
        )


class _PrecontentPermissionAdapter(_BasePermissionAdapter):
    provider_id = "permission403-precontent"

    def generate_stream(self, request):
        yield StreamDelta(content="", finish_reason="error", error=_permission_error())


class _FirstVisiblePermissionAdapter(_BasePermissionAdapter):
    provider_id = "permission403-first-visible"

    def generate_stream(self, request):
        yield StreamDelta(content="partial", finish_reason="error", error=_permission_error())


class _MidstreamPermissionAdapter(_BasePermissionAdapter):
    provider_id = "permission403-midstream"

    def generate_stream(self, request):
        yield StreamDelta(content="partial")
        yield StreamDelta(content="", finish_reason="error", error=_permission_error())


class _SyncDegradationPermissionAdapter(_BasePermissionAdapter):
    provider_id = "permission403-sync-degradation"

    def generate_stream(self, request):
        yield StreamDelta(content="", finish_reason="stream_unsupported")


class ModelGatewayPermissionHealthV1Tests(unittest.TestCase):
    def _run_adapter(self, adapter):
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        config_service = _RecordingConfigService()
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id=adapter.provider_name, model_id="model-a"),
            fallback_chain=[],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(
            provider_registry=registry,
            config_service=config_service,
            model_policy=policy,
            free_only_mode=False,
        )
        request = ModelRequest(
            model_name="default",
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
            timeout_seconds=10.0,
        )

        deltas = list(gateway.generate_stream(request))
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "AUTHORIZATION_ERROR")
        self.assertEqual(
            config_service.errors,
            [(adapter.provider_name, ProviderErrorCode.PERMISSION_403)],
        )
        self.assertEqual(
            gateway.get_provider_health(adapter.provider_name),
            ProviderHealth.UNAVAILABLE,
            "stream 403 must not leave an access-denied provider marked AVAILABLE",
        )

    def test_precontent_structured_403_degrades_health(self):
        self._run_adapter(_PrecontentPermissionAdapter())

    def test_first_visible_structured_403_degrades_health(self):
        self._run_adapter(_FirstVisiblePermissionAdapter())

    def test_midstream_structured_403_degrades_health(self):
        self._run_adapter(_MidstreamPermissionAdapter())

    def test_sync_degradation_structured_403_degrades_health(self):
        self._run_adapter(_SyncDegradationPermissionAdapter())


if __name__ == "__main__":
    unittest.main()
