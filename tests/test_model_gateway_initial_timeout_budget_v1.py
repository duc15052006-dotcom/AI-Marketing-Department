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
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class _NoopConfigService:
    def record_error(self, provider_id, error_code):
        return None


class _ScriptedClock:
    def __init__(self, perf_values):
        self._perf_values = iter(perf_values)
        self._last = 0.0

    def perf_counter(self):
        try:
            self._last = next(self._perf_values)
        except StopIteration:
            pass
        return self._last

    def time(self):
        return 1_000.0


class _CountingAdapter(BaseModelAdapter):
    def __init__(self):
        self.generate_calls = 0
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "first"

    def generate(self, request):
        self.generate_calls += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="must-not-dispatch",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        yield StreamDelta(content="must-not-dispatch", finish_reason="stop")


class ModelGatewayInitialTimeoutBudgetV1Tests(unittest.TestCase):
    def _gateway_and_request(self):
        adapter = _CountingAdapter()
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="first", model_id="model-a"),
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
            timeout_seconds=1.0,
        )
        return adapter, gateway, request

    def test_sync_does_not_dispatch_first_provider_after_total_timeout_is_exhausted(self):
        adapter, gateway, request = self._gateway_and_request()
        # t=0: gateway starts; t=2: candidate #1 would begin only after the
        # 1s total request budget has already expired.
        clock = _ScriptedClock([0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            response = gateway.generate(request)

        self.assertEqual(
            adapter.generate_calls,
            0,
            "first provider I/O must not start after the total gateway timeout budget is exhausted",
        )
        self.assertNotEqual(response.status, ModelResponseStatus.SUCCESS)
        self.assertIn("TIMEOUT", str(response.error).upper())

    def test_stream_does_not_dispatch_first_provider_after_total_timeout_is_exhausted(self):
        adapter, gateway, request = self._gateway_and_request()
        clock = _ScriptedClock([0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            deltas = list(gateway.generate_stream(request))

        self.assertEqual(
            adapter.stream_calls,
            0,
            "first streaming provider I/O must not start after the total gateway timeout budget is exhausted",
        )
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
