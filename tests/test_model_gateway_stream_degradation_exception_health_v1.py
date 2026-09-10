import unittest

from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
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


class _DegradationTimeoutAdapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "degradation-timeout-exception"

    def generate_stream(self, request):
        yield StreamDelta(content="", finish_reason="stream_unsupported")

    def generate(self, request):
        raise TimeoutError("synchronous degradation timed out")


class ModelGatewayStreamDegradationExceptionHealthV1Tests(unittest.TestCase):
    def test_degradation_timeout_exception_preserves_timeout_accounting_and_health(self):
        adapter = _DegradationTimeoutAdapter()
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

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(
            deltas[0].error.code,
            "TIMEOUT",
            "a TimeoutError raised by sync degradation must not be collapsed into STREAM_INTERNAL_ERROR",
        )
        self.assertEqual(
            config_service.errors,
            [(adapter.provider_name, ProviderErrorCode.TIMEOUT)],
            "degradation timeout exceptions must feed provider error accounting",
        )
        self.assertEqual(
            gateway.get_provider_health(adapter.provider_name),
            ProviderHealth.UNAVAILABLE,
            "a provider timing out during sync degradation must not remain AVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
