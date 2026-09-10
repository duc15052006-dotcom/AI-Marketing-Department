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
from integrations.models.config_service import ProviderErrorCode
from integrations.models.gateway import ProviderHealth, UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class _RecordingConfigService:
    def __init__(self):
        self.errors = []

    def record_error(self, provider_id, error_code):
        self.errors.append((provider_id, error_code))


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


class _LateSyncAndFirstDeltaAdapter(BaseModelAdapter):
    def __init__(self):
        self.generate_calls = 0
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "late-timeout"

    def generate(self, request):
        self.generate_calls += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="late-success",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        yield StreamDelta(content="late-first-delta", finish_reason="stop")


class _MidstreamLateAdapter(BaseModelAdapter):
    def __init__(self):
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "midstream-timeout"

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
        yield StreamDelta(content="partial-visible", finish_reason=None)
        yield StreamDelta(content="late-terminal", finish_reason="stop")


class _LateDegradationAdapter(BaseModelAdapter):
    def __init__(self):
        self.generate_calls = 0
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "degradation-timeout"

    def generate(self, request):
        self.generate_calls += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="late-degraded-success",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        yield StreamDelta(content="", finish_reason="stream_unsupported")


def _request():
    return ModelRequest(
        model_name="default",
        messages=[ModelMessage(role=ModelRole.USER, content="hello")],
        timeout_seconds=1.0,
    )


def _gateway(adapter):
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
    return gateway, config_service


class ModelGatewayPostDispatchTimeoutHealthV2Tests(unittest.TestCase):
    def _assert_timeout_accounted(self, gateway, config_service, provider_id):
        self.assertEqual(
            config_service.errors,
            [(provider_id, ProviderErrorCode.TIMEOUT)],
            "a gateway timeout after provider dispatch must feed provider error accounting",
        )
        self.assertEqual(
            gateway.get_provider_health(provider_id),
            ProviderHealth.UNAVAILABLE,
            "a provider that missed the authoritative gateway deadline must not remain AVAILABLE",
        )

    def test_sync_late_result_records_timeout_and_marks_provider_unavailable(self):
        adapter = _LateSyncAndFirstDeltaAdapter()
        gateway, config_service = _gateway(adapter)
        clock = _ScriptedClock([0.0, 0.0, 2.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            response = gateway.generate(_request())
        self.assertEqual(adapter.generate_calls, 1)
        self.assertEqual(response.status, ModelResponseStatus.TIMEOUT)
        self._assert_timeout_accounted(gateway, config_service, adapter.provider_name)

    def test_stream_late_first_delta_records_timeout_and_marks_provider_unavailable(self):
        adapter = _LateSyncAndFirstDeltaAdapter()
        gateway, config_service = _gateway(adapter)
        clock = _ScriptedClock([0.0, 0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            deltas = list(gateway.generate_stream(_request()))
        self.assertEqual(adapter.stream_calls, 1)
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")
        self._assert_timeout_accounted(gateway, config_service, adapter.provider_name)

    def test_stream_late_midstream_delta_records_timeout_and_marks_provider_unavailable(self):
        adapter = _MidstreamLateAdapter()
        gateway, config_service = _gateway(adapter)
        clock = _ScriptedClock([0.0, 0.0, 0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            deltas = list(gateway.generate_stream(_request()))
        self.assertEqual(adapter.stream_calls, 1)
        self.assertTrue(any(delta.content == "partial-visible" for delta in deltas))
        self.assertFalse(any(delta.content == "late-terminal" for delta in deltas))
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")
        self._assert_timeout_accounted(gateway, config_service, adapter.provider_name)

    def test_stream_degradation_late_sync_result_records_timeout_and_marks_provider_unavailable(self):
        adapter = _LateDegradationAdapter()
        gateway, config_service = _gateway(adapter)
        clock = _ScriptedClock([0.0, 0.0, 0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            deltas = list(gateway.generate_stream(_request()))
        self.assertEqual(adapter.stream_calls, 1)
        self.assertEqual(adapter.generate_calls, 1)
        self.assertTrue(deltas)
        self.assertFalse(any(delta.content == "late-degraded-success" for delta in deltas))
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")
        self._assert_timeout_accounted(gateway, config_service, adapter.provider_name)


if __name__ == "__main__":
    unittest.main()
