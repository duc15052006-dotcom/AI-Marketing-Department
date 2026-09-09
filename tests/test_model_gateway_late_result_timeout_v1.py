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


class _LateSuccessAdapter(BaseModelAdapter):
    def __init__(self):
        self.generate_calls = 0
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "late"

    def generate(self, request):
        self.generate_calls += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="late-success-must-not-be-accepted",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        yield StreamDelta(content="late-delta-must-not-be-emitted", finish_reason="stop")


class ModelGatewayLateResultTimeoutV1Tests(unittest.TestCase):
    def _gateway_and_request(self):
        adapter = _LateSuccessAdapter()
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="late", model_id="model-a"),
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

    def test_sync_rejects_success_that_arrives_after_total_gateway_deadline(self):
        adapter, gateway, request = self._gateway_and_request()
        # start=0, pre-dispatch=0, post-provider=2: the adapter returns SUCCESS,
        # but only after the authoritative 1s gateway deadline has expired.
        clock = _ScriptedClock([0.0, 0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            response = gateway.generate(request)

        self.assertEqual(adapter.generate_calls, 1)
        self.assertEqual(response.status, ModelResponseStatus.TIMEOUT)
        self.assertIn("TIMEOUT", str(response.error).upper())
        self.assertNotEqual(response.content, "late-success-must-not-be-accepted")

    def test_stream_rejects_first_delta_that_arrives_after_total_gateway_deadline(self):
        adapter, gateway, request = self._gateway_and_request()
        # stream start=0, pre-dispatch=0, post-first-delta=2.
        clock = _ScriptedClock([0.0, 0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            deltas = list(gateway.generate_stream(request))

        self.assertEqual(adapter.stream_calls, 1)
        self.assertTrue(deltas)
        self.assertFalse(any(delta.content == "late-delta-must-not-be-emitted" for delta in deltas))
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
