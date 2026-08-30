"""Regression tests for authoritative fail-closed model cost governance.

FIX-FREE-ONLY-COST-AUTHORITY-02
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
    ModelMetadata,
    ModelRegistry,
    ProviderDefinition,
    ProviderRegistry,
)
from integrations.models.thespark_adapter import TheSparkProviderAdapter


class CountingAdapter(BaseModelAdapter):
    """Deterministic injected adapter that records actual model dispatches."""

    def __init__(self, provider_name: str, cost_policy: CostPolicy = CostPolicy.FREE_TIER_ALLOWED) -> None:
        self._provider_name = provider_name
        self._cost_policy = cost_policy
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def cost_policy(self) -> CostPolicy:
        return self._cost_policy

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="EXECUTED",
        )


class TestFreeOnlyCostAuthority02(unittest.TestCase):
    def test_provider_cost_policy_normalizes_canonical_strings(self) -> None:
        cases = {
            "paid": CostPolicy.PAID,
            " PAID ": CostPolicy.PAID,
            "unknown": CostPolicy.UNKNOWN,
            "FREE_TIER_ALLOWED": CostPolicy.FREE_TIER_ALLOWED,
            "disabled": CostPolicy.DISABLED,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                definition = ProviderDefinition(
                    provider_id="custom-provider",
                    cost_policy=raw,
                )
                self.assertIs(definition.cost_policy, expected)

    def test_provider_cost_policy_rejects_malformed_values_fail_closed(self) -> None:
        for raw in ("bogus", "paid_provider", "", None, 1, True, [], {}):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    ProviderDefinition(
                        provider_id="custom-provider",
                        cost_policy=raw,
                    )

    def test_model_metadata_cost_tier_uses_same_canonical_authority(self) -> None:
        metadata = ModelMetadata(
            provider_id="custom-provider",
            model_id="model-1",
            display_name="Model 1",
            cost_tier="unknown",
        )
        self.assertIs(metadata.cost_tier, CostPolicy.UNKNOWN)

        with self.assertRaises(ValueError):
            ModelMetadata(
                provider_id="custom-provider",
                model_id="model-2",
                display_name="Model 2",
                cost_tier="not-a-cost-tier",
            )

    def test_thespark_cost_authority_is_consistently_paid(self) -> None:
        provider_registry = ProviderRegistry()
        model_registry = ModelRegistry()

        provider = provider_registry.get_provider("thespark")
        model = model_registry.get_model("thespark", "spark-default")
        legacy_adapter = TheSparkProviderAdapter(
            api_key="not-used",
            base_url="https://example.com/v1",
            default_model="spark-default",
        )

        self.assertIsNotNone(provider)
        self.assertIsNotNone(model)
        self.assertIs(provider.cost_policy, CostPolicy.PAID)
        self.assertIs(model.cost_tier, CostPolicy.PAID)
        self.assertIs(legacy_adapter.cost_policy, CostPolicy.PAID)
        self.assertFalse(legacy_adapter.automatic_fallback_allowed)

    def test_thespark_is_not_reported_as_a_free_model(self) -> None:
        model_registry = ModelRegistry()
        free_keys = {
            (model.provider_id, model.model_id)
            for model in model_registry.list_free_models()
        }
        self.assertNotIn(("thespark", "spark-default"), free_keys)

    def test_universal_gateway_blocks_thespark_before_dispatch_in_free_only_mode(self) -> None:
        provider_registry = ProviderRegistry()
        injected = CountingAdapter("thespark", cost_policy=CostPolicy.FREE_TIER_ALLOWED)
        provider_registry.register_custom_adapter(injected)

        gateway = UniversalModelGateway(
            provider_registry=provider_registry,
            model_registry=ModelRegistry(),
            free_only_mode=True,
        )
        request = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Do not execute paid fallback")],
        )

        response = gateway.generate(
            request,
            provider_id="thespark",
            allow_paid=False,
        )

        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIn("FREE_ONLY_POLICY_VIOLATION", response.error or "")
        self.assertEqual(injected.call_count, 0)

    def test_explicit_allow_paid_can_dispatch_thespark(self) -> None:
        provider_registry = ProviderRegistry()
        injected = CountingAdapter("thespark", cost_policy=CostPolicy.FREE_TIER_ALLOWED)
        provider_registry.register_custom_adapter(injected)

        gateway = UniversalModelGateway(
            provider_registry=provider_registry,
            model_registry=ModelRegistry(),
            free_only_mode=True,
        )
        request = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Explicit paid approval")],
        )

        response = gateway.generate(
            request,
            provider_id="thespark",
            allow_paid=True,
        )

        self.assertEqual(response.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(response.content, "EXECUTED")
        self.assertEqual(injected.call_count, 1)


if __name__ == "__main__":
    unittest.main()
