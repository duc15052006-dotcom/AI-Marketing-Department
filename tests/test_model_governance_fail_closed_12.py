"""Regression tests for strict fail-closed model governance.

FIX-MODEL-GOVERNANCE-FAIL-CLOSED-12

Covers boolean governance boundaries and CostPolicy.DISABLED at both
synchronous and streaming execution boundaries.
"""

from __future__ import annotations

import unittest
from typing import Generator

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    StreamDelta,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ModelPolicy, ProviderDefinition, ProviderRegistry


class CountingAdapter(BaseModelAdapter):
    def __init__(self, provider_name: str, cost_policy: CostPolicy) -> None:
        self._provider_name = provider_name
        self._cost_policy = cost_policy
        self.call_count = 0
        self.stream_call_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def cost_policy(self) -> CostPolicy:
        return self._cost_policy

    @property
    def default_model(self) -> str:
        return "test-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="EXECUTED",
        )

    def generate_stream(self, request: ModelRequest) -> Generator[StreamDelta, None, None]:
        self.stream_call_count += 1
        yield StreamDelta(content="EXECUTED", provider=self.provider_name, model_name=request.model_name)
        yield StreamDelta(content="", finish_reason="stop", provider=self.provider_name, model_name=request.model_name)


def _request() -> ModelRequest:
    return ModelRequest(
        model_name="test-model",
        messages=[ModelMessage(role=ModelRole.USER, content="governance test")],
    )


def _gateway(provider_name: str, cost_policy: CostPolicy, *, free_only_mode: bool) -> tuple[UniversalModelGateway, CountingAdapter, ProviderRegistry]:
    registry = ProviderRegistry()
    adapter = CountingAdapter(provider_name, cost_policy)
    registry.register_custom_adapter(adapter)
    gateway = UniversalModelGateway(provider_registry=registry, free_only_mode=free_only_mode)
    return gateway, adapter, registry


class TestStrictBooleanGovernance(unittest.TestCase):
    def test_provider_definition_rejects_string_false_enabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "INVALID_BOOLEAN"):
            ProviderDefinition(provider_id="strict-enabled", enabled="false")  # type: ignore[arg-type]

    def test_provider_definition_rejects_numeric_enabled(self) -> None:
        for raw in (0, 1, None):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "INVALID_BOOLEAN"):
                    ProviderDefinition(provider_id="strict-enabled", enabled=raw)  # type: ignore[arg-type]

    def test_model_policy_rejects_string_free_only_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "INVALID_BOOLEAN"):
            ModelPolicy(free_only_mode="false")  # type: ignore[arg-type]

    def test_gateway_constructor_rejects_string_free_only_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "INVALID_BOOLEAN"):
            UniversalModelGateway(free_only_mode="false")  # type: ignore[arg-type]

    def test_gateway_setter_rejects_string_free_only_mode(self) -> None:
        gateway = UniversalModelGateway(free_only_mode=True)
        with self.assertRaisesRegex(ValueError, "INVALID_BOOLEAN"):
            gateway.set_free_only_mode("false")  # type: ignore[arg-type]
        self.assertTrue(gateway.free_only_mode)

    def test_sync_rejects_string_false_allow_paid_before_dispatch(self) -> None:
        gateway, adapter, _ = _gateway("paid-sync", CostPolicy.PAID, free_only_mode=True)
        response = gateway.generate(
            _request(),
            provider_id="paid-sync",
            allow_paid="false",  # type: ignore[arg-type]
        )
        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("INVALID_GOVERNANCE_BOOLEAN", response.error or "")
        self.assertEqual(adapter.call_count, 0)

    def test_stream_rejects_string_false_allow_paid_before_dispatch(self) -> None:
        gateway, adapter, _ = _gateway("paid-stream", CostPolicy.PAID, free_only_mode=True)
        deltas = list(
            gateway.generate_stream(
                _request(),
                provider_id="paid-stream",
                allow_paid="false",  # type: ignore[arg-type]
            )
        )
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "INVALID_REQUEST")
        self.assertIn("allow_paid", deltas[0].error.safe_message)
        self.assertEqual(adapter.stream_call_count, 0)
        self.assertEqual(adapter.call_count, 0)

    def test_mutated_string_false_enabled_is_blocked_sync_and_stream(self) -> None:
        gateway, adapter, registry = _gateway("mutated-enabled", CostPolicy.FREE_TIER_ALLOWED, free_only_mode=False)
        definition = registry.get_provider("mutated-enabled")
        self.assertIsNotNone(definition)
        definition.enabled = "false"  # type: ignore[assignment]

        response = gateway.generate(_request(), provider_id="mutated-enabled")
        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("PROVIDER_DISABLED", response.error or "")
        self.assertEqual(adapter.call_count, 0)

        deltas = list(gateway.generate_stream(_request(), provider_id="mutated-enabled"))
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertEqual(deltas[0].error.code, "PROVIDER_DISABLED")
        self.assertEqual(adapter.stream_call_count, 0)
        self.assertEqual(adapter.call_count, 0)


class TestDisabledCostPolicy(unittest.TestCase):
    def test_sync_disabled_cost_policy_cannot_be_overridden_by_allow_paid(self) -> None:
        gateway, adapter, _ = _gateway("disabled-sync", CostPolicy.DISABLED, free_only_mode=False)
        response = gateway.generate(
            _request(),
            provider_id="disabled-sync",
            allow_paid=True,
        )
        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("PROVIDER_DISABLED", response.error or "")
        self.assertEqual(adapter.call_count, 0)

    def test_stream_disabled_cost_policy_cannot_be_overridden_by_allow_paid(self) -> None:
        gateway, adapter, _ = _gateway("disabled-stream", CostPolicy.DISABLED, free_only_mode=False)
        deltas = list(
            gateway.generate_stream(
                _request(),
                provider_id="disabled-stream",
                allow_paid=True,
            )
        )
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "PROVIDER_DISABLED")
        self.assertEqual(adapter.stream_call_count, 0)
        self.assertEqual(adapter.call_count, 0)

    def test_real_boolean_allow_paid_true_still_allows_paid_provider(self) -> None:
        gateway, adapter, _ = _gateway("paid-explicit", CostPolicy.PAID, free_only_mode=True)
        response = gateway.generate(
            _request(),
            provider_id="paid-explicit",
            allow_paid=True,
        )
        self.assertEqual(response.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(adapter.call_count, 1)


if __name__ == "__main__":
    unittest.main()
