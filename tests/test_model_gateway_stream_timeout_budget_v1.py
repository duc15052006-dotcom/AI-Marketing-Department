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
    ModelStreamError,
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


class _FailingStreamAdapter(BaseModelAdapter):
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
            status=ModelResponseStatus.ERROR,
            error="RATE_LIMITED",
        )

    def generate_stream(self, request):
        self.stream_calls += 1
        yield StreamDelta(
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


class _SuccessStreamAdapter(BaseModelAdapter):
    def __init__(self):
        self.stream_calls = 0

    @property
    def provider_name(self):
        return "second"

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


class ModelGatewayStreamTimeoutBudgetV1Tests(unittest.TestCase):
    def test_fallback_does_not_dispatch_after_total_timeout_budget_is_exhausted(self):
        first = _FailingStreamAdapter()
        second = _SuccessStreamAdapter()
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
            timeout_seconds=1.0,
        )

        # t=0: stream start; t=0: candidate #1 starts; t=2: candidate #2
        # would start only after the 1s total gateway budget is already exhausted.
        clock = _ScriptedClock([0.0, 0.0, 2.0])
        with patch.object(gateway_module, "time", clock):
            deltas = list(gateway.generate_stream(request))

        self.assertEqual(first.stream_calls, 1)
        self.assertEqual(
            second.stream_calls,
            0,
            "fallback provider I/O must not start after the total stream timeout budget is exhausted",
        )
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertEqual(deltas[-1].provider, "first")
        self.assertEqual(deltas[-1].error.code, "RATE_LIMITED")


if __name__ == "__main__":
    unittest.main()
