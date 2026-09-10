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


class _PermissionDeniedStreamAdapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "permission403"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="HTTP 403 FORBIDDEN: model access denied",
        )

    def generate_stream(self, request):
        yield StreamDelta(
            content="",
            finish_reason="error",
            error=ModelStreamError(
                code="AUTHORIZATION_ERROR",
                category="AUTHORIZATION",
                safe_message="provider denied access to this model",
                retryable=False,
                http_status=403,
            ),
        )


class ModelGatewayPermissionHealthV1Tests(unittest.TestCase):
    def _make_gateway(self):
        adapter = _PermissionDeniedStreamAdapter()
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        config_service = _RecordingConfigService()
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="permission403", model_id="model-a"),
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
        return gateway, config_service, request

    def test_structured_stream_403_records_permission_and_degrades_health(self):
        gateway, config_service, request = self._make_gateway()

        deltas = list(gateway.generate_stream(request))

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "AUTHORIZATION_ERROR")
        self.assertEqual(
            config_service.errors,
            [("permission403", ProviderErrorCode.PERMISSION_403)],
        )
        self.assertEqual(
            gateway.get_provider_health("permission403"),
            ProviderHealth.UNAVAILABLE,
            "stream 403 must not leave an access-denied provider marked AVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
