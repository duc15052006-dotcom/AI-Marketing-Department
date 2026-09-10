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


def _rate_limit_error(message):
    return ModelStreamError(
        code="RATE_LIMITED",
        category="RATE_LIMIT",
        safe_message=message,
        retryable=True,
        http_status=429,
    )


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
            error=_rate_limit_error("rate limit reached mid-stream"),
        )


class _FirstVisibleRateLimitAdapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "first-visible-429"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="sync-not-used",
        )

    def generate_stream(self, request):
        yield StreamDelta(
            content="visible-and-error",
            finish_reason="error",
            error=_rate_limit_error("rate limit arrived with first visible delta"),
        )


class ModelGatewayMidstreamErrorHealthV1Tests(unittest.TestCase):
    def _gateway_for(self, adapter):
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
        return gateway, config_service, request

    def test_later_midstream_rate_limit_records_error_and_marks_provider_rate_limited(self):
        adapter = _MidstreamRateLimitAdapter()
        gateway, config_service, request = self._gateway_for(adapter)

        deltas = list(gateway.generate_stream(request))

        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "partial visible output")
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "RATE_LIMITED")
        self.assertEqual(
            config_service.errors,
            [(adapter.provider_name, ProviderErrorCode.RATE_LIMIT_429)],
            "a terminal provider error after earlier visible output must feed provider error accounting",
        )
        self.assertEqual(
            gateway.get_provider_health(adapter.provider_name),
            ProviderHealth.RATE_LIMITED,
            "mid-stream 429 must affect future provider routing even though fallback is forbidden for this response",
        )

    def test_first_visible_delta_with_rate_limit_records_error_and_marks_provider_rate_limited(self):
        adapter = _FirstVisibleRateLimitAdapter()
        gateway, config_service, request = self._gateway_for(adapter)

        deltas = list(gateway.generate_stream(request))

        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "visible-and-error")
        self.assertIsNone(deltas[0].error)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "RATE_LIMITED")
        self.assertEqual(
            config_service.errors,
            [(adapter.provider_name, ProviderErrorCode.RATE_LIMIT_429)],
            "an error carried by the first visible delta must still feed provider error accounting",
        )
        self.assertEqual(
            gateway.get_provider_health(adapter.provider_name),
            ProviderHealth.RATE_LIMITED,
            "first-visible-delta 429 must affect future provider routing without enabling fallback",
        )


if __name__ == "__main__":
    unittest.main()
