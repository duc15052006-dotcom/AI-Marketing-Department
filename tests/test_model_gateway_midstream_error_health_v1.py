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


class _MidstreamRateLimitAdapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "midstream429"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="sync-not-used",
        )

    def generate_stream(self, request):
        yield StreamDelta(content="partial visible output")
        yield StreamDelta(
            content="",
            finish_reason="error",
            error=ModelStreamError(
                code="RATE_LIMITED",
                category="RATE_LIMIT",
                safe_message="rate limit reached mid-stream",
                retryable=True,
                http_status=429,
            ),
        )


class ModelGatewayMidstreamErrorHealthV1Tests(unittest.TestCase):
    def test_midstream_rate_limit_records_error_and_marks_provider_rate_limited(self):
        adapter = _MidstreamRateLimitAdapter()
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        config_service = _RecordingConfigService()
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="midstream429", model_id="model-a"),
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

        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "partial visible output")
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "RATE_LIMITED")
        self.assertEqual(
            config_service.errors,
            [("midstream429", ProviderErrorCode.RATE_LIMIT_429)],
            "a terminal provider error after visible output must still feed provider error accounting",
        )
        self.assertEqual(
            gateway.get_provider_health("midstream429"),
            ProviderHealth.RATE_LIMITED,
            "mid-stream 429 must affect future provider routing even though fallback is forbidden for this response",
        )


if __name__ == "__main__":
    unittest.main()
