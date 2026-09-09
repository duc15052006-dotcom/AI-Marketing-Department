from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from integrations.models.base import (
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class TestModelGatewaySyncExceptionRedactionV1(unittest.TestCase):
    def test_sync_adapter_exception_does_not_expose_raw_exception_or_secret(self) -> None:
        secret = "sk-SYNC-EXCEPTION-SECRET-123456789"
        raw_marker = "INTERNAL_ADAPTER_DEBUG_MARKER_DO_NOT_EXPOSE"

        adapter = MagicMock()
        adapter.provider_name = "exploding_provider"
        adapter.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        adapter.generate.side_effect = RuntimeError(
            f"{raw_marker} Authorization: Bearer {secret} api_key={secret}"
        )

        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="exploding_provider", model_id="test-model"),
            fallback_chain=[],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(
            provider_registry=registry,
            model_policy=policy,
            free_only_mode=False,
        )

        response = gateway.generate(
            ModelRequest(
                model_name="default",
                messages=[ModelMessage(role=ModelRole.USER, content="trigger")],
            ),
            model_policy=policy,
            strict_model_pin=True,
        )

        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertIsNotNone(response.error)
        self.assertIn("ADAPTER_INVOCATION_EXCEPTION", response.error)
        self.assertNotIn(secret, response.error)
        self.assertNotIn("Bearer sk-", response.error)
        self.assertNotIn(raw_marker, response.error)


if __name__ == "__main__":
    unittest.main()
