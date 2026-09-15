"""Causal regression for delayed pre-content streaming fallback.

A provider may emit one or more non-visible deltas before surfacing a retryable
error. Because no assistant content has been exposed yet, the gateway is still
safe to try the next fallback candidate. It must not terminate the public
stream merely because the retryable error was not the provider's first delta.
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
    ModelStreamError,
    ModelUsage,
    StreamDelta,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderDefinition, ProviderRegistry


class _DelayedRetryableErrorAdapter(BaseModelAdapter):
    def __init__(self, provider_id: str) -> None:
        self._provider_id = provider_id
        self.stream_calls = 0

    @property
    def provider_name(self) -> str:
        return self._provider_id

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.FREE_TIER_ALLOWED

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            request_id=request.request_id,
            provider=self._provider_id,
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="RATE_LIMITED",
            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
        )

    def generate_stream(self, request: ModelRequest):
        self.stream_calls += 1
        # A non-visible protocol/metadata delta does not commit the public
        # response to this provider.
        yield StreamDelta(
            content="",
            finish_reason=None,
            provider=self._provider_id,
            model_name=request.model_name,
        )
        yield StreamDelta(
            content="",
            finish_reason="error",
            provider=self._provider_id,
            model_name=request.model_name,
            error=ModelStreamError(
                code="RATE_LIMITED",
                category="RATE_LIMIT",
                safe_message="provider temporarily rate limited",
                retryable=True,
                http_status=429,
            ),
        )


class _RecoveryAdapter(BaseModelAdapter):
    def __init__(self, provider_id: str) -> None:
        self._provider_id = provider_id
        self.stream_calls = 0

    @property
    def provider_name(self) -> str:
        return self._provider_id

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.FREE_TIER_ALLOWED

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            request_id=request.request_id,
            provider=self._provider_id,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="recovered",
            usage=ModelUsage(usage_source="NOT_AVAILABLE"),
        )

    def generate_stream(self, request: ModelRequest):
        self.stream_calls += 1
        yield StreamDelta(
            content="recovered",
            finish_reason=None,
            provider=self._provider_id,
            model_name=request.model_name,
        )
        yield StreamDelta(
            content="",
            finish_reason="stop",
            provider=self._provider_id,
            model_name=request.model_name,
        )


class TestDelayedPrecontentStreamErrorFallbackV1(unittest.TestCase):
    def test_retryable_error_after_empty_delta_falls_back_before_visible_content(self) -> None:
        first = _DelayedRetryableErrorAdapter("provider_a")
        second = _RecoveryAdapter("provider_b")

        registry = ProviderRegistry()
        for provider_id in ("provider_a", "provider_b"):
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
        registry._injected_adapters["provider_a"] = first
        registry._injected_adapters["provider_b"] = second

        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="provider_a", model_id="test-model"),
            fallback_chain=[
                ModelTarget(provider_id="provider_a", model_id="test-model"),
                ModelTarget(provider_id="provider_b", model_id="test-model"),
            ],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(
            provider_registry=registry,
            model_policy=policy,
            free_only_mode=False,
        )
        request = ModelRequest(
            request_id="REQ-DELAYED-PRECONTENT-ERROR",
            model_name="test-model",
            messages=[ModelMessage(role=ModelRole.USER, content="test")],
            temperature=0.0,
            max_tokens=32,
            timeout_seconds=10.0,
        )

        deltas = list(gateway.generate_stream(request, model_policy=policy))
        visible = "".join(delta.content for delta in deltas if delta.content)
        terminal_errors = [delta for delta in deltas if delta.finish_reason == "error"]

        self.assertEqual(first.stream_calls, 1)
        self.assertEqual(second.stream_calls, 1)
        self.assertEqual(visible, "recovered")
        self.assertFalse(terminal_errors)
        self.assertEqual(deltas[-1].finish_reason, "stop")
        self.assertEqual(deltas[-1].provider, "provider_b")


if __name__ == "__main__":
    unittest.main()
