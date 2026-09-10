import unittest

from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import ProviderHealth, UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class _NoopConfigService:
    def record_error(self, provider_id, error_code):
        return None


class _Generic429Adapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "generic429"

    def generate(self, request):
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.ERROR,
            error="HTTP 429 RATE_LIMIT: quota exhausted",
        )


class ModelGatewaySyncRateLimitHealthV1Tests(unittest.TestCase):
    def test_generic_error_classified_as_429_marks_provider_rate_limited(self):
        registry = ProviderRegistry()
        registry.register_custom_adapter(_Generic429Adapter())
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="generic429", model_id="model-a"),
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
            timeout_seconds=30.0,
        )

        response = gateway.generate(request, strict_model_pin=True)

        self.assertEqual(response.status, ModelResponseStatus.ERROR)
        self.assertEqual(
            gateway.get_provider_health("generic429"),
            ProviderHealth.RATE_LIMITED,
            "A provider failure classified as RATE_LIMIT_429 must not be downgraded to generic UNAVAILABLE health.",
        )


if __name__ == "__main__":
    unittest.main()
