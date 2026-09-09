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
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class _NoopConfigService:
    def record_error(self, provider_id, error_code):
        return None


class _TrackedStream:
    def __init__(self):
        self.close_called = False
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self):
        self._index += 1
        if self._index == 1:
            return StreamDelta(content="partial-visible-output", finish_reason=None)
        if self._index == 2:
            return StreamDelta(content="provider-work-still-running", finish_reason=None)
        return StreamDelta(content="", finish_reason="stop")

    def close(self):
        self.close_called = True


class _TrackedStreamAdapter(BaseModelAdapter):
    def __init__(self):
        self.stream = None

    @property
    def provider_name(self):
        return "tracked"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="sync-not-used",
        )

    def generate_stream(self, request):
        self.stream = _TrackedStream()
        return self.stream


class ModelGatewayStreamConsumerCancelV1Tests(unittest.TestCase):
    def test_consumer_close_propagates_to_active_provider_stream(self):
        adapter = _TrackedStreamAdapter()
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="tracked", model_id="model-a"),
            fallback_chain=[],
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

        outer_stream = gateway.generate_stream(request)
        first = next(outer_stream)
        self.assertEqual(first.content, "partial-visible-output")
        self.assertIsNotNone(adapter.stream)
        self.assertFalse(adapter.stream.close_called)

        outer_stream.close()

        self.assertTrue(
            adapter.stream.close_called,
            "Closing/cancelling the gateway stream must close the active provider stream so provider I/O cannot continue.",
        )


if __name__ == "__main__":
    unittest.main()
