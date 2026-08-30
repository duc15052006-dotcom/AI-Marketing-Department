"""Regression tests for strict provider governance state.

FIX-PROVIDER-GOVERNANCE-STATE-15
"""

from __future__ import annotations

import unittest

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import (
    ModelPolicy,
    ProviderDefinition,
    ProviderRegistry,
)
from integrations.models.settings_manager import ModelSettings


class CountingAdapter(BaseModelAdapter):
    def __init__(self, provider_name: str) -> None:
        self._provider_name = provider_name
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="EXECUTED",
        )


def request() -> ModelRequest:
    return ModelRequest(
        model_name="default",
        messages=[ModelMessage(role=ModelRole.USER, content="governance test")],
    )


def injected_gateway(cost_policy: CostPolicy) -> tuple[UniversalModelGateway, CountingAdapter, ProviderRegistry]:
    registry = ProviderRegistry()
    adapter = CountingAdapter("govtest")
    registry.register_custom_adapter(adapter)
    registry.update_provider("govtest", {"cost_policy": cost_policy})
    gateway = UniversalModelGateway(
        provider_registry=registry,
        free_only_mode=True,
    )
    return gateway, adapter, registry


class TestProviderGovernanceState15(unittest.TestCase):
    def test_provider_enabled_requires_strict_bool(self) -> None:
        for bad in ("false", "true", 0, 1, None, [], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ProviderDefinition(provider_id="strict-bool", enabled=bad)

    def test_registry_update_rejects_string_false_and_preserves_old_state(self) -> None:
        registry = ProviderRegistry()
        registry.register_provider(
            ProviderDefinition(
                provider_id="strict-update",
                adapter_type="OPENAI_COMPATIBLE",
                base_url="https://example.com/v1",
                default_model="m1",
                enabled=True,
            )
        )
        with self.assertRaises(ValueError):
            registry.update_provider("strict-update", {"enabled": "false"})
        self.assertIs(registry.get_provider("strict-update").enabled, True)

    def test_model_policy_free_only_requires_strict_bool(self) -> None:
        for bad in ("false", "true", 0, 1, None, [], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ModelPolicy(free_only_mode=bad)

    def test_persisted_model_settings_free_only_requires_strict_bool(self) -> None:
        for bad in ("false", "true", 0, 1, None, [], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ModelSettings(free_only_mode=bad)

    def test_allow_paid_string_false_cannot_bypass_free_only_sync(self) -> None:
        gateway, adapter, _ = injected_gateway(CostPolicy.PAID)
        response = gateway.generate(
            request(),
            provider_id="govtest",
            allow_paid="false",  # type: ignore[arg-type]
        )
        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("REQUEST_SCHEMA_ERROR", response.error or "")
        self.assertEqual(adapter.call_count, 0)

    def test_real_bool_allow_paid_true_still_allows_explicit_paid_dispatch(self) -> None:
        gateway, adapter, _ = injected_gateway(CostPolicy.PAID)
        response = gateway.generate(
            request(),
            provider_id="govtest",
            allow_paid=True,
        )
        self.assertEqual(response.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(adapter.call_count, 1)

    def test_allow_paid_string_false_cannot_bypass_free_only_stream(self) -> None:
        gateway, adapter, _ = injected_gateway(CostPolicy.PAID)
        deltas = list(
            gateway.generate_stream(
                request(),
                provider_id="govtest",
                allow_paid="false",  # type: ignore[arg-type]
            )
        )
        self.assertEqual(adapter.call_count, 0)
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "REQUEST_SCHEMA_ERROR")

    def test_cost_policy_disabled_never_dispatches_sync_even_with_allow_paid(self) -> None:
        gateway, adapter, _ = injected_gateway(CostPolicy.DISABLED)
        response = gateway.generate(
            request(),
            provider_id="govtest",
            allow_paid=True,
        )
        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("PROVIDER_DISABLED", response.error or "")
        self.assertEqual(adapter.call_count, 0)

    def test_cost_policy_disabled_never_dispatches_stream_even_with_allow_paid(self) -> None:
        gateway, adapter, _ = injected_gateway(CostPolicy.DISABLED)
        deltas = list(
            gateway.generate_stream(
                request(),
                provider_id="govtest",
                allow_paid=True,
            )
        )
        self.assertEqual(adapter.call_count, 0)
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "PROVIDER_DISABLED")


if __name__ == "__main__":
    unittest.main()
