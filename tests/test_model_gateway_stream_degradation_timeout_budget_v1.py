"""Causal regressions for stream->sync degradation timeout authority.

The gateway owns one total streaming request budget. If a provider reports
``stream_unsupported`` after spending part (or all) of that budget, the
synchronous degradation call must use only the remaining budget and must not
start at all once the total deadline has already expired.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
    StreamDelta,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderDefinition, ProviderRegistry


class _MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _UnsupportedThenSyncAdapter(BaseModelAdapter):
    def __init__(self, provider_id: str, clock: _MutableClock, probe_elapsed: float) -> None:
        self._provider_id = provider_id
        self._clock = clock
        self._probe_elapsed = probe_elapsed
        self.stream_calls = 0
        self.sync_calls = 0
        self.sync_timeouts: list[float | None] = []

    @property
    def provider_name(self) -> str:
        return self._provider_id

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.FREE_TIER_ALLOWED

    def generate_stream(self, request: ModelRequest):
        self.stream_calls += 1
        self._clock.value = self._probe_elapsed
        yield StreamDelta(
            content="",
            finish_reason="stream_unsupported",
            provider=self._provider_id,
            model_name=request.model_name,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.sync_calls += 1
        self.sync_timeouts.append(request.timeout_seconds)
        return ModelResponse(
            request_id=request.request_id,
            provider=self._provider_id,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="sync recovered",
            finish_reason="stop",
            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
        )


def _make_gateway(adapter: BaseModelAdapter) -> tuple[UniversalModelGateway, ModelPolicy]:
    provider_id = adapter.provider_name
    registry = ProviderRegistry()
    registry.register_provider(
        ProviderDefinition(
            provider_id=provider_id,
            adapter_type="OPENAI_COMPATIBLE",
            base_url=f"https://{provider_id}.invalid/v1",
            api_key_env="TEST_KEY",
            default_model="test-model",
            enabled=True,
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )
    )
    registry._injected_adapters[provider_id] = adapter
    policy = ModelPolicy(
        global_target=ModelTarget(provider_id=provider_id, model_id="test-model"),
        fallback_chain=[],
        free_only_mode=False,
    )
    return UniversalModelGateway(provider_registry=registry, model_policy=policy, free_only_mode=False), policy


def _make_request(timeout_seconds: float = 1.0) -> ModelRequest:
    return ModelRequest(
        request_id="REQ-STREAM-DEGRADATION-BUDGET",
        model_name="test-model",
        messages=[ModelMessage(role=ModelRole.USER, content="test")],
        temperature=0.0,
        max_tokens=32,
        timeout_seconds=timeout_seconds,
    )


class TestStreamDegradationTimeoutBudgetV1(unittest.TestCase):
    def test_sync_degradation_is_not_dispatched_after_total_budget_expires(self) -> None:
        clock = _MutableClock()
        adapter = _UnsupportedThenSyncAdapter("provider_a", clock, probe_elapsed=2.0)
        gateway, policy = _make_gateway(adapter)

        with patch("integrations.models.gateway.time.perf_counter", new=clock):
            deltas = list(gateway.generate_stream(_make_request(1.0), model_policy=policy))

        self.assertEqual(adapter.stream_calls, 1)
        self.assertEqual(adapter.sync_calls, 0)
        self.assertTrue(deltas)
        self.assertEqual(deltas[-1].finish_reason, "error")
        self.assertIsNotNone(deltas[-1].error)
        self.assertEqual(deltas[-1].error.code, "TIMEOUT")

    def test_sync_degradation_timeout_is_clamped_to_remaining_total_budget(self) -> None:
        clock = _MutableClock()
        adapter = _UnsupportedThenSyncAdapter("provider_a", clock, probe_elapsed=0.75)
        gateway, policy = _make_gateway(adapter)

        with patch("integrations.models.gateway.time.perf_counter", new=clock):
            deltas = list(gateway.generate_stream(_make_request(1.0), model_policy=policy))

        self.assertEqual(adapter.stream_calls, 1)
        self.assertEqual(adapter.sync_calls, 1)
        self.assertEqual(len(adapter.sync_timeouts), 1)
        self.assertIsNotNone(adapter.sync_timeouts[0])
        self.assertGreater(adapter.sync_timeouts[0], 0.0)
        self.assertLessEqual(adapter.sync_timeouts[0], 0.250001)
        self.assertEqual("".join(delta.content for delta in deltas if delta.content), "sync recovered")
        self.assertEqual(deltas[-1].finish_reason, "stop")


if __name__ == "__main__":
    unittest.main()
