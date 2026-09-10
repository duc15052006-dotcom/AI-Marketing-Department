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


class _TimeoutStreamAdapter(BaseModelAdapter):
    def __init__(self):
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "timeout-stream"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="sync-not-used",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        raise TimeoutError("provider stream read timed out")
        yield StreamDelta(content="unreachable", finish_reason="stop")


class ModelGatewayStreamExceptionHealthV1Tests(unittest.TestCase):
    def test_timeout_exception_records_error_and_marks_provider_unavailable(self):
        adapter = _TimeoutStreamAdapter()
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        config_service = _RecordingConfigService()

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="timeout-stream", model_id="model-a"),
            fallback_chain=[],
            free_only_mode=True,
        )
        gateway = UniversalModelGateway(
            provider_registry=registry,
            config_service=config_service,
            model_policy=policy,
            free_only_mode=True,
        )
        request = ModelRequest(
            model_name="default",
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
            timeout_seconds=10.0,
        )

        deltas = list(gateway.generate_stream(request))

        self.assertEqual(adapter.stream_calls, 1)
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")
        self.assertEqual(
            config_service.errors,
            [("timeout-stream", ProviderErrorCode.TIMEOUT)],
            "stream exceptions must feed the same provider error accounting as structured stream errors",
        )
        self.assertEqual(
            gateway.get_provider_health("timeout-stream"),
            ProviderHealth.UNAVAILABLE,
            "a timeout exception must not leave provider health at the default AVAILABLE state",
        )


if __name__ == "__main__":
    unittest.main()
