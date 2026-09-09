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
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class _NoopConfigService:
    def record_error(self, provider_id, error_code):
        return None


class _TrackedErrorStream:
    """Retained iterator so garbage collection cannot hide a missing close()."""

    def __init__(self):
        self._sent = False
        self.closed = False
        self.close_calls = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._sent:
            raise StopIteration
        self._sent = True
        return StreamDelta(
            content="",
            finish_reason="error",
            error=ModelStreamError(
                code="RATE_LIMITED",
                category="RATE_LIMIT",
                safe_message="first provider rate limited",
                retryable=True,
                http_status=429,
            ),
        )

    def close(self):
        self.close_calls += 1
        self.closed = True


class _FirstStreamAdapter(BaseModelAdapter):
    def __init__(self):
        self.stream_calls = 0
        self.stream = None

    @property
    def provider_name(self):
        return "first"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="RATE_LIMITED",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        self.stream = _TrackedErrorStream()
        return self.stream


class _FallbackStreamAdapter(BaseModelAdapter):
    def __init__(self, first_adapter):
        self.first_adapter = first_adapter
        self.stream_calls = 0
        self.saw_first_stream_closed = None

    @property
    def provider_name(self):
        return "second"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="fallback-ok",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        self.saw_first_stream_closed = bool(
            self.first_adapter.stream and self.first_adapter.stream.closed
        )
        yield StreamDelta(content="fallback-ok", finish_reason="stop")


class ModelGatewayFallbackStreamCloseV1Tests(unittest.TestCase):
    def test_abandoned_precontent_error_stream_is_closed_before_fallback_provider_runs(self):
        first = _FirstStreamAdapter()
        second = _FallbackStreamAdapter(first)
        registry = ProviderRegistry()
        registry.register_custom_adapter(first)
        registry.register_custom_adapter(second)

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="first", model_id="model-a"),
            fallback_chain=[ModelTarget(provider_id="second", model_id="model-b")],
            free_only_mode=True,
        )
        gateway = UniversalModelGateway(
            provider_registry=registry,
            config_service=_NoopConfigService(),
            model_policy=policy,
            free_only_mode=True,
        )
        request = ModelRequest(
            model_name="default",
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
            timeout_seconds=30.0,
        )

        deltas = list(gateway.generate_stream(request))

        self.assertEqual(first.stream_calls, 1)
        self.assertEqual(second.stream_calls, 1)
        self.assertIsNotNone(first.stream)
        self.assertEqual(
            first.stream.close_calls,
            1,
            "gateway must explicitly close an abandoned provider stream before switching candidates",
        )
        self.assertTrue(
            second.saw_first_stream_closed,
            "fallback provider must not begin while the abandoned provider stream is still open",
        )
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].content, "fallback-ok")
        self.assertEqual(deltas[-1].finish_reason, "stop")
        self.assertEqual(deltas[-1].provider, "second")


if __name__ == "__main__":
    unittest.main()
