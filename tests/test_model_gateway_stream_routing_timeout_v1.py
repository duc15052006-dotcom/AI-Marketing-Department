import unittest
from unittest.mock import patch

import integrations.models.gateway as gateway_module
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
from integrations.models.registry import ProviderRegistry


class _NoopConfigService:
    def record_error(self, provider_id, error_code):
        return None


class _MutableClock:
    def __init__(self):
        self.now = 0.0

    def perf_counter(self):
        return self.now

    def time(self):
        return 1_000.0


class _SuccessStreamAdapter(BaseModelAdapter):
    def __init__(self):
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "first"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="should-not-dispatch",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        yield StreamDelta(content="should-not-dispatch", finish_reason="stop")


class ModelGatewayStreamRoutingTimeoutV1Tests(unittest.TestCase):
    def test_stream_routing_time_consumes_total_gateway_timeout_budget(self):
        adapter = _SuccessStreamAdapter()
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)

        gateway = UniversalModelGateway(
            provider_registry=registry,
            config_service=_NoopConfigService(),
            free_only_mode=False,
        )
        request = ModelRequest(
            model_name="default",
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
            timeout_seconds=1.0,
        )

        clock = _MutableClock()

        # Simulate 2s spent in routing/model-policy resolution before candidate #1.
        # A 1s *total gateway* budget must already be exhausted at that point.
        def slow_resolve_candidate_chain(**kwargs):
            clock.now = 2.0
            return [("first", "model-a")]

        gateway.resolve_candidate_chain = slow_resolve_candidate_chain

        with patch.object(gateway_module, "time", clock):
            deltas = list(gateway.generate_stream(request))

        self.assertEqual(
            adapter.stream_calls,
            0,
            "stream provider I/O must not start when routing already exhausted the total gateway timeout budget",
        )
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
